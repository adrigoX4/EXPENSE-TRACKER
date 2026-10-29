export class ApiError extends Error {
  constructor(message, { status = 0, code = "request_failed", details = null, offline = false } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.offline = offline;
  }
}

function buildQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function request(path, { method = "GET", body, headers = {}, timeout = 20000, signal } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const mergedHeaders = { Accept: "application/json", ...headers };
  let payload;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    mergedHeaders["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const onAbort = () => controller.abort();
  if (signal) signal.addEventListener("abort", onAbort, { once: true });

  try {
    const response = await fetch(path, {
      method,
      headers: mergedHeaders,
      body: payload,
      signal: controller.signal,
      credentials: "same-origin",
    });
    if (!response.ok) {
      let data = null;
      try {
        data = await response.json();
      } catch {
        /* non-JSON error */
      }
      const error = data?.error || data?.detail;
      const message =
        typeof error === "string"
          ? error
          : error?.message || `The server responded with ${response.status}.`;
      if (response.status === 401 && !path.startsWith("/api/auth/")) {
        const next = `${window.location.pathname}${window.location.search}`;
        window.location.replace(`/login?next=${encodeURIComponent(next)}`);
      }
      throw new ApiError(message, {
        status: response.status,
        code: error?.code || "http_error",
        details: error?.details || null,
      });
    }
    if (response.status === 204) return null;
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) return response;
    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error.name === "AbortError") {
      throw new ApiError("The request timed out. Check that the local server is running.", {
        code: "timeout",
        offline: true,
      });
    }
    throw new ApiError("Cannot reach the College Cart server. Your work can still be saved locally.", {
      code: "network_error",
      offline: true,
    });
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", onAbort);
  }
}

const get = (path, params, options = {}) => request(`${path}${buildQuery(params)}`, options);
const post = (path, body, options = {}) => request(path, { method: "POST", body, ...options });
const patch = (path, body, options = {}) => request(path, { method: "PATCH", body, ...options });
const put = (path, body, options = {}) => request(path, { method: "PUT", body, ...options });

export const api = {
  health: () => get("/api/health"),

  products: {
    list: (params) => get("/api/products", params),
    get: (id) => get(`/api/products/${id}`),
    create: (body) => post("/api/products", body),
    update: (id, body) => patch(`/api/products/${id}`, body),
    categories: () => get("/api/products/categories"),
    movements: (id, params) => get(`/api/products/${id}/movements`, params),
  },

  inventory: {
    summary: () => get("/api/inventory/summary"),
    movements: (params) => get("/api/inventory/movements", params),
    createMovement: (body) => post("/api/inventory/movements", body),
    receipts: (params) => get("/api/inventory/receipts", params),
    createReceipt: (body) => post("/api/inventory/receipts", body),
  },

  sales: {
    list: (params) => get("/api/sales", params),
    get: (id) => get(`/api/sales/${id}`),
    create: (body, idempotencyKey) =>
      post("/api/sales", body, idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    update: (id, body) => patch(`/api/sales/${id}`, body),
    void: (id, body) => post(`/api/sales/${id}/void`, body),
    payments: (id) => get(`/api/sales/${id}/payments`),
    addPayment: (id, body, idempotencyKey) =>
      post(`/api/sales/${id}/payments`, body, idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    addReturn: (id, body) => post(`/api/sales/${id}/returns`, body),
    audit: (id) => get(`/api/sales/${id}/audit`),
    checkExternal: (externalOrderId) => get("/api/sales/check-external", { external_order_id: externalOrderId }),
  },

  expenses: {
    list: (params) => get("/api/expenses", params),
    get: (id) => get(`/api/expenses/${id}`),
    create: (body) => post("/api/expenses", body),
    update: (id, body) => patch(`/api/expenses/${id}`, body),
    void: (id, body) => post(`/api/expenses/${id}/void`, body),
  },

  money: {
    ledger: (params) => get("/api/money/ledger", params),
    summary: (params) => get("/api/money/summary", params),
    monthly: (params) => get("/api/money/monthly", params),
    get: (id) => get(`/api/money/transactions/${id}`),
    create: (body, idempotencyKey) =>
      post("/api/money/transactions", body, idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    update: (id, body) => patch(`/api/money/transactions/${id}`, body),
    void: (id, body) => post(`/api/money/transactions/${id}/void`, body),
  },

  cash: {
    createHandover: (body) => post("/api/handovers", body),
  },

  deliveries: {
    create: (body) => post("/api/deliveries", body),
    update: (id, body) => patch(`/api/deliveries/${id}`, body),
  },

  reconciliation: {
    updateSale: (saleId, body) => patch(`/api/reconciliation/sales/${saleId}`, body),
    link: (body) => post("/api/reconciliation/link", body),
  },

  reports: {
    summary: (params) => get("/api/reports/summary", params),
    monthly: (params) => get("/api/reports/monthly", params),
    dashboard: (params) => get("/api/dashboard", params),
  },

  settings: {
    get: () => get("/api/settings"),
    update: (body) => put("/api/settings", body),
    audit: (params) => get("/api/audit", params),
    syncOperations: (params) => get("/api/sync/operations", params),
  },

  backup: {
    info: () => get("/api/backup/info"),
    create: () => post("/api/backup/create", {}),
    validate: (file) => {
      const data = new FormData();
      data.append("upload", file);
      return post("/api/backup/validate", data);
    },
    restore: (file, confirm) => {
      const data = new FormData();
      data.append("upload", file);
      return post(`/api/backup/restore?confirm=${encodeURIComponent(confirm)}`, data);
    },
  },
};

export const moneyString = (value) => {
  const amount = Number(value || 0);
  return (Number.isFinite(amount) ? amount : 0).toFixed(2);
};
