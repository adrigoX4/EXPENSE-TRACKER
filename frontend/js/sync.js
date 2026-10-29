import { api } from "./api.js";
import { deleteOutbox, listOutbox, updateOutbox } from "./db.js";
import {
  getState,
  refreshPendingCount,
  refreshProducts,
  refreshSettings,
  setServerReachable,
  setSyncing,
} from "./store.js";
import { toast } from "./ui.js";

let inFlight = false;

async function sendOperation(operation) {
  const payload = operation.payload || {};
  switch (operation.kind) {
    case "sale":
      return api.sales.create({ ...payload, client_uuid: operation.id }, operation.id);
    case "expense":
      return api.expenses.create({ ...payload, idempotency_key: operation.id });
    case "payment":
      return api.sales.addPayment(payload.sale_id, { ...payload.body, idempotency_key: operation.id }, operation.id);
    case "return":
      return api.sales.addReturn(payload.sale_id, { ...payload.body, idempotency_key: operation.id });
    case "movement":
      return api.inventory.createMovement({ ...payload, idempotency_key: operation.id });
    case "handover":
      return api.cash.createHandover({ ...payload, idempotency_key: operation.id });
    case "money":
      return api.money.create({ ...payload, idempotency_key: operation.id }, operation.id);
    default:
      throw new Error(`Unknown offline operation: ${operation.kind}`);
  }
}

export async function syncOutbox({ manual = false, silent = false } = {}) {
  if (inFlight) return { skipped: true };
  if (!navigator.onLine) {
    if (manual) toast("You are offline. Pending records will sync when the connection returns.", { type: "warn" });
    return { offline: true };
  }
  const operations = await listOutbox();
  if (!operations.length) {
    if (manual) toast("Everything is already synchronized.", { type: "info" });
    return { success: 0, failed: 0 };
  }

  inFlight = true;
  setSyncing(true);
  let success = 0;
  let failed = 0;
  let wentOffline = false;
  const errors = [];

  try {
    for (const operation of operations) {
      try {
        await sendOperation(operation);
        await deleteOutbox(operation.id);
        success += 1;
      } catch (error) {
        if (error?.offline) {
          wentOffline = true;
          setServerReachable(false);
          break;
        }
        if (error?.status === 401) {
          break;
        }
        failed += 1;
        errors.push(error);
        await updateOutbox(operation.id, {
          status: "failed",
          attempts: Number(operation.attempts || 0) + 1,
          lastError: error?.message || "Synchronization failed",
          lastAttemptAt: new Date().toISOString(),
        });
      }
    }

    if (success > 0) {
      try {
        await Promise.all([refreshProducts(), refreshSettings()]);
      } catch {
        /* cached data remains usable */
      }
    }
    await refreshPendingCount();

    if (!silent) {
      if (success > 0 && failed === 0) {
        toast(`${success} local record${success === 1 ? "" : "s"} synchronized with the server.`, {
          title: "Synchronization complete",
        });
      } else if (failed > 0) {
        toast(
          `${failed} record${failed === 1 ? "" : "s"} could not sync. Open Settings → Offline queue to review the error.`,
          { type: "error", title: "Some changes need attention" }
        );
      } else if (wentOffline && manual) {
        toast("The server is unreachable. Pending records remain saved on this device.", { type: "warn" });
      }
    }
    if (!wentOffline) setServerReachable(true);
    return { success, failed, offline: wentOffline, errors };
  } finally {
    inFlight = false;
    setSyncing(false);
    getState().lastSyncAt = new Date().toISOString();
    await refreshPendingCount();
  }
}

export function startAutoSync() {
  window.addEventListener("online", () => {
    syncOutbox({ silent: true });
  });
  setInterval(() => {
    if (document.visibilityState === "visible" && navigator.onLine && getState().pendingCount > 0) {
      syncOutbox({ silent: true });
    }
  }, 60000);
}
