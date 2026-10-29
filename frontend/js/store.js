import { api } from "./api.js";
import { countOutbox, deleteOutbox, getMeta, listOutbox, setMeta, updateOutbox } from "./db.js";

const DEFAULT_SETTINGS = {
  business_name: "College Cart",
  payment_methods: ["cash", "upi"],
  expense_categories: ["inventory_purchase", "travel", "food", "packaging", "personal_other", "miscellaneous"],
  money_in_categories: ["customer_payment", "money_from_owner", "repayment_received", "other_money_received"],
  money_out_categories: ["money_to_owner", "stock_purchase", "expense_payment", "cash_handover", "repayment_given", "other_money_given"],
  default_low_stock_threshold: 5,
  opening_cash_balance: null,
  opening_upi_balance: null,
  opening_balance_date: null,
  currency: "INR",
  business_timezone: "Asia/Kolkata",
  inventory_category: "inventory_purchase",
};

const state = {
  online: typeof navigator !== "undefined" ? navigator.onLine : true,
  serverReachable: null,
  syncing: false,
  booted: false,
  settings: { ...DEFAULT_SETTINGS },
  products: [],
  categories: [],
  productsCachedAt: null,
  pendingCount: 0,
  lastSyncAt: null,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit() {
  for (const listener of listeners) {
    try {
      listener(state);
    } catch (error) {
      console.error("Store listener failed", error);
    }
  }
  window.dispatchEvent(new CustomEvent("store:change", { detail: state }));
}

export function setOnline(online) {
  if (state.online === online) return;
  state.online = online;
  if (!online) state.serverReachable = false;
  emit();
}

export function setSyncing(syncing) {
  state.syncing = syncing;
  emit();
}

export function setServerReachable(reachable) {
  state.serverReachable = reachable;
  if (reachable) state.online = true;
  emit();
}

export async function initStore() {
  const [cachedSettings, cachedProducts, cachedCategories, cachedAt] = await Promise.all([
    getMeta("settings"),
    getMeta("products"),
    getMeta("categories"),
    getMeta("products_cached_at"),
  ]);
  if (cachedSettings && Array.isArray(cachedSettings.payment_methods)) {
    state.settings = { ...DEFAULT_SETTINGS, ...cachedSettings };
  }
  if (Array.isArray(cachedProducts)) {
    state.products = cachedProducts;
    state.productsCachedAt = cachedAt || null;
  }
  if (Array.isArray(cachedCategories)) state.categories = cachedCategories;
  await refreshPendingCount();
  state.booted = true;
  emit();

  if (state.online) {
    try {
      await Promise.all([refreshSettings(), refreshProducts()]);
      state.serverReachable = true;
    } catch (error) {
      if (error?.offline) {
        state.serverReachable = false;
      }
      console.warn("Initial data refresh failed; using cached data.", error);
    }
    emit();
  }
  return state;
}

export async function refreshSettings() {
  const settings = await api.settings.get();
  state.settings = { ...DEFAULT_SETTINGS, ...settings };
  await setMeta("settings", state.settings);
  emit();
  return state.settings;
}

export async function refreshProducts() {
  const result = await api.products.list({ limit: 500 });
  state.products = result.items || [];
  state.categories = result.categories || [];
  state.productsCachedAt = new Date().toISOString();
  await Promise.all([
    setMeta("products", state.products),
    setMeta("categories", state.categories),
    setMeta("products_cached_at", state.productsCachedAt),
  ]);
  emit();
  return state.products;
}

export function productById(id) {
  return state.products.find((product) => product.id === Number(id)) || null;
}

export function activeProducts() {
  return state.products.filter((product) => product.is_active);
}

export function adjustCachedStock(productId, delta) {
  const product = productById(productId);
  if (!product) return;
  product.stock_quantity = Number(product.stock_quantity || 0) + delta;
  product.stock_value = Number(product.stock_value || 0) + delta * Number(product.purchase_cost || 0);
  product.retail_value = Number(product.retail_value || 0) + delta * Number(product.selling_price || 0);
  product.is_low_stock = product.stock_quantity <= product.low_stock_threshold;
  setMeta("products", state.products);
  emit();
}

export async function refreshPendingCount() {
  try {
    state.pendingCount = await countOutbox();
  } catch {
    state.pendingCount = 0;
  }
  emit();
  return state.pendingCount;
}

export async function pendingOperations() {
  return listOutbox();
}

export async function queueOperation({ kind, payload, label, amount = 0, id = null, status = "pending" }) {
  const { addOutbox } = await import("./db.js");
  const operation = {
    id: id || payload.client_uuid || payload.idempotency_key || crypto.randomUUID(),
    kind,
    payload,
    label,
    amount,
    createdAt: new Date().toISOString(),
    attempts: 0,
    status,
    lastError: null,
  };
  await addOutbox(operation);
  await refreshPendingCount();
  return operation;
}

export async function markOperationAttempt(operation, error = null) {
  return updateOutbox(operation.id, {
    attempts: Number(operation.attempts || 0) + 1,
    status: error ? "failed" : "pending",
    lastError: error || null,
  });
}

export async function removeOperation(operation) {
  await deleteOutbox(operation.id);
  await refreshPendingCount();
}

export function methodLabel(method) {
  if (!method) return "—";
  if (method === "upi") return "UPI";
  return method.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function expenseCategoryLabel(category) {
  const labels = {
    inventory_purchase: "Stock purchase",
    travel: "Travel",
    food: "Food & refreshments",
    packaging: "Packaging",
    personal_other: "Personal / other",
    miscellaneous: "Miscellaneous",
    delivery: "Delivery / transport",
    other: "Other",
  };
  return labels[category] || methodLabel(category);
}

export const MONEY_CATEGORY_LABELS = {
  cash_upi_transfer: "Transfer between cash & UPI",
  customer_payment: "Customer payment",
  money_from_owner: "Money received from owner",
  repayment_received: "Repayment received",
  other_money_received: "Other money received",
  money_to_owner: "Money given to owner",
  stock_purchase: "Stock purchase",
  expense_payment: "Expense payment",
  cash_handover: "Cash handover",
  repayment_given: "Repayment given",
  other_money_given: "Other money given",
  adjustment: "Cash / UPI adjustment",
  refund: "Sale refund",
};

export function moneyCategoryLabel(category) {
  return MONEY_CATEGORY_LABELS[category] || methodLabel(category);
}

export function isOffline() {
  return state.online === false || state.serverReachable === false;
}

export function moneyCategories(direction) {
  const fallback =
    direction === "in" ? DEFAULT_SETTINGS.money_in_categories : DEFAULT_SETTINGS.money_out_categories;
  const values = direction === "in" ? state.settings.money_in_categories : state.settings.money_out_categories;
  return values?.length ? values : fallback;
}

export function paymentMethods() {
  return state.settings.payment_methods?.length ? state.settings.payment_methods : ["cash", "upi"];
}
