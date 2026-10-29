const BASE_DB_NAME = "college-cart-offline";
const DB_VERSION = 1;
const META_STORE = "meta";
const OUTBOX_STORE = "outbox";

let dbName = `${BASE_DB_NAME}-shared`;
let fallbackKey = "cartflow_outbox_v1";
let fallbackMetaKey = "cartflow_meta_v1";

let dbPromise = null;

export function setOfflineUser(userId) {
  const suffix = String(userId || "shared").replace(/[^a-z0-9]/gi, "").slice(0, 32) || "shared";
  dbName = `${BASE_DB_NAME}-${suffix}`;
  fallbackKey = `cartflow_outbox_v1_${suffix}`;
  fallbackMetaKey = `cartflow_meta_v1_${suffix}`;
  if (dbPromise) {
    dbPromise.then((database) => database.close()).catch(() => undefined);
  }
  dbPromise = null;
}

function hasIndexedDb() {
  return typeof indexedDB !== "undefined";
}

function openDb() {
  if (!hasIndexedDb()) return Promise.reject(new Error("IndexedDB unavailable"));
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(dbName, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(META_STORE)) {
        database.createObjectStore(META_STORE, { keyPath: "key" });
      }
      if (!database.objectStoreNames.contains(OUTBOX_STORE)) {
        const store = database.createObjectStore(OUTBOX_STORE, { keyPath: "id" });
        store.createIndex("status", "status");
        store.createIndex("createdAt", "createdAt");
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Could not open offline database"));
  });
  return dbPromise;
}

function runTransaction(storeName, mode, action) {
  return openDb().then(
    (database) =>
      new Promise((resolve, reject) => {
        const transaction = database.transaction(storeName, mode);
        const store = transaction.objectStore(storeName);
        let result;
        try {
          result = action(store);
        } catch (error) {
          reject(error);
          return;
        }
        transaction.oncomplete = () => resolve(result);
        transaction.onerror = () => reject(transaction.error || new Error("Offline database transaction failed"));
        transaction.onabort = () => reject(transaction.error || new Error("Offline database transaction aborted"));
      })
  );
}

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function readFallback() {
  try {
    const raw = localStorage.getItem(fallbackKey);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeFallback(items) {
  try {
    localStorage.setItem(fallbackKey, JSON.stringify(items));
  } catch {
    /* storage full or disabled */
  }
}

export async function getMeta(key) {
  try {
    const database = await openDb();
    const transaction = database.transaction(META_STORE, "readonly");
    const row = await requestResult(transaction.objectStore(META_STORE).get(key));
    return row ? row.value : null;
  } catch {
    try {
      const raw = localStorage.getItem(fallbackMetaKey);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed[key] ?? null;
    } catch {
      return null;
    }
  }
}

export async function setMeta(key, value) {
  try {
    await runTransaction(META_STORE, "readwrite", (store) => {
      store.put({ key, value, updatedAt: new Date().toISOString() });
    });
    return;
  } catch {
    try {
      const raw = localStorage.getItem(fallbackMetaKey);
      const parsed = raw ? JSON.parse(raw) : {};
      parsed[key] = value;
      localStorage.setItem(fallbackMetaKey, JSON.stringify(parsed));
    } catch {
      /* ignore */
    }
  }
}

export async function listOutbox() {
  try {
    const database = await openDb();
    const transaction = database.transaction(OUTBOX_STORE, "readonly");
    const rows = await requestResult(transaction.objectStore(OUTBOX_STORE).getAll());
    return (rows || []).sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
  } catch {
    return readFallback().sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
  }
}

export async function getOutbox(id) {
  try {
    const database = await openDb();
    const transaction = database.transaction(OUTBOX_STORE, "readonly");
    return (await requestResult(transaction.objectStore(OUTBOX_STORE).get(id))) || null;
  } catch {
    return readFallback().find((row) => row.id === id) || null;
  }
}

export async function addOutbox(operation) {
  try {
    await runTransaction(OUTBOX_STORE, "readwrite", (store) => store.put(operation));
  } catch {
    const rows = readFallback();
    rows.push(operation);
    writeFallback(rows);
  }
  return operation;
}

export async function updateOutbox(id, changes) {
  try {
    const existing = await getOutbox(id);
    if (!existing) return null;
    const next = { ...existing, ...changes };
    await runTransaction(OUTBOX_STORE, "readwrite", (store) => store.put(next));
    return next;
  } catch {
    const rows = readFallback();
    const index = rows.findIndex((row) => row.id === id);
    if (index === -1) return null;
    rows[index] = { ...rows[index], ...changes };
    writeFallback(rows);
    return rows[index];
  }
}

export async function deleteOutbox(id) {
  try {
    await runTransaction(OUTBOX_STORE, "readwrite", (store) => store.delete(id));
  } catch {
    writeFallback(readFallback().filter((row) => row.id !== id));
  }
}

export async function countOutbox() {
  const rows = await listOutbox();
  return rows.length;
}

export async function clearOutbox() {
  try {
    await runTransaction(OUTBOX_STORE, "readwrite", (store) => store.clear());
  } catch {
    writeFallback([]);
  }
}
