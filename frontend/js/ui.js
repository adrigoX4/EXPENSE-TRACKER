const ICONS = {
  dashboard:
    '<rect x="3" y="3" width="7" height="9" rx="1.4"/><rect x="14" y="3" width="7" height="5" rx="1.4"/><rect x="14" y="12" width="7" height="9" rx="1.4"/><rect x="3" y="16" width="7" height="5" rx="1.4"/>',
  cart: '<circle cx="8" cy="21" r="1.2"/><circle cx="19" cy="21" r="1.2"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
  receipt:
    '<path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z"/><path d="M8 7h8"/><path d="M8 11h8"/><path d="M8 15h5"/>',
  package:
    '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  truck:
    '<path d="M14 18V6a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h2"/><path d="M14 9h4l4 4v4a1 1 0 0 1-1 1h-1"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/><path d="M9 18h6"/>',
  wallet:
    '<rect x="2" y="5" width="20" height="15" rx="2.5"/><path d="M2 10h20"/><path d="M16 15h3"/>',
  banknote:
    '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="2"/><path d="M6 12h.01M18 12h.01"/>',
  compare:
    '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>',
  chart:
    '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  settings:
    '<line x1="21" y1="4" x2="14" y2="4"/><line x1="10" y1="4" x2="3" y2="4"/><line x1="21" y1="12" x2="12" y2="12"/><line x1="8" y1="12" x2="3" y2="12"/><line x1="21" y1="20" x2="16" y2="20"/><line x1="12" y1="20" x2="3" y2="20"/><line x1="14" y1="2" x2="14" y2="6"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="16" y1="18" x2="16" y2="22"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
  check: '<path d="m20 6-11 11-5-5"/>',
  alert:
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-5M12 8h.01"/>',
  trash:
    '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M10 11v6M14 11v6"/>',
  edit: '<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
  download:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  upload:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
  database:
    '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  cloudOff:
    '<path d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A7 7 0 0 0 5.3 7.3"/><path d="M5 19h12.5"/><path d="m2 2 20 20"/>',
  cloud:
    '<path d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A7 7 0 0 0 5.3 7.3 4.5 4.5 0 0 0 6 19Z"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  arrowLeft: '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
  arrowUpRight: '<path d="M7 17 17 7"/><path d="M7 7h10v10"/>',
  arrowDownLeft: '<path d="M17 7 7 17"/><path d="M17 17H7V7"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  chevronLeft: '<path d="m15 18-6-6 6-6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  creditCard:
    '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  filter: '<path d="M22 3H2l8 9.46V19l4 2v-8.54Z"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  minus: '<path d="M5 12h14"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  mapPin:
    '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
  tag: '<path d="M12.6 2.6A2 2 0 0 0 11.2 2H4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 .6 1.4l8.7 8.7a2.4 2.4 0 0 0 3.4 0l6.6-6.6a2.4 2.4 0 0 0 0-3.4z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  layers:
    '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  logout:
    '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  externalLink:
    '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
  rotate: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  calculator:
    '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8"/><path d="M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01"/>',
  checkCircle:
    '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
  xCircle:
    '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
  phone:
    '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.34 1.79.66 2.64a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.44-1.23a2 2 0 0 1 2.11-.45c.85.32 1.74.54 2.64.66A2 2 0 0 1 22 16.92Z"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>',
};

export function icon(name, extra = "") {
  const body = ICONS[name] || ICONS.info;
  return `<svg class="icon ${extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((node) => {
    node.innerHTML = icon(node.dataset.icon);
  });
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("en-IN");

export function money(value, fallback = "₹0.00") {
  if (value === null || value === undefined || value === "") return fallback;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return fallback;
  return currencyFormatter.format(amount);
}

export function moneySigned(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount === 0) return money(0);
  return `${amount > 0 ? "+" : "−"}${money(Math.abs(amount))}`;
}

export function num(value) {
  const amount = Number(value || 0);
  return numberFormatter.format(Number.isFinite(amount) ? amount : 0);
}

export function decimal(value, digits = 2) {
  const amount = Number(value || 0);
  return Number.isFinite(amount) ? amount.toFixed(digits) : "0.00";
}

export function cents(value) {
  const amount = Number(value || 0);
  return Number.isFinite(amount) ? Math.round(amount * 100) : 0;
}

export function formatDate(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function formatTime(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
}

export function relativeTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diff = Date.now() - date.getTime();
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatDate(date);
}

export function dayParam(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

export function dateTimeLocalValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function startOfMonthParam(date = new Date()) {
  return dayParam(new Date(date.getFullYear(), date.getMonth(), 1));
}

export function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

const STATUS_LABELS = {
  unpaid: "Unpaid",
  partial: "Partially paid",
  paid: "Paid",
  voided: "Voided",
  recorded: "Recorded",
  verified: "Verified",
  not_found: "Not found",
  needs_review: "Needs review",
  potential_duplicate: "Potential duplicate",
  pending: "Pending",
  out_for_delivery: "Out for delivery",
  delivered: "Delivered",
  cancelled: "Cancelled",
  completed: "Completed",
  website: "Website",
  manual: "Manual",
  imported: "Imported",
  opening: "Opening",
  in_stock: "In Stock",
  low_stock: "Low Stock",
  out_of_stock: "Out of Stock",
  receipt: "Received",
  sale: "Sale",
  return: "Return",
  damage: "Damaged",
  correction: "Correction",
  cash: "Cash",
  upi: "UPI",
  card: "Card",
  bank: "Bank transfer",
  inventory_purchase: "Inventory purchase",
  delivery: "Delivery / transport",
  travel: "Travel",
  food: "Food & refreshments",
  personal_other: "Personal / other",
  packaging: "Packaging",
  miscellaneous: "Miscellaneous",
  other: "Other",
  ordinary: "Ordinary expense",
  stock_purchase: "Stock purchase",
  customer_payment: "Customer payment",
  money_from_owner: "Money received from owner",
  repayment_received: "Repayment received",
  other_money_received: "Other money received",
  money_to_owner: "Money given to owner",
  expense_payment: "Expense payment",
  cash_handover: "Cash handover",
  repayment_given: "Repayment given",
  other_money_given: "Other money given",
  cash_upi_transfer: "Transfer between cash & UPI",
  payment: "Sale payment",
  expense: "Expense",
  handover: "Handover",
  money: "Manual entry",
  in: "Money in",
  out: "Money out",
  synced: "Synced",
  failed: "Failed",
  conflict: "Conflict",
  dismissed: "Dismissed",
  confirmed_duplicate: "Confirmed duplicate",
  adjustment: "Adjustment",
  refund: "Refund",
  sale_payment: "Sale payment",
};

export function statusLabel(value) {
  if (value === null || value === undefined || value === "") return "—";
  return STATUS_LABELS[value] || String(value).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function capitalize(value) {
  return String(value || "").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function badge(value, extraClass = "") {
  if (value === null || value === undefined) return "";
  return `<span class="badge badge-${escapeHtml(value)} ${extraClass}">${escapeHtml(statusLabel(value))}</span>`;
}

export function methodBadge(method) {
  return `<span class="badge no-dot">${escapeHtml(statusLabel(method))}</span>`;
}

export function emptyState({ iconName = "box", title, text = "", action = "" }) {
  return `<div class="empty-state">
    <span class="empty-icon">${icon(iconName)}</span>
    <strong>${escapeHtml(title)}</strong>
    ${text ? `<p>${escapeHtml(text)}</p>` : ""}
    ${action}
  </div>`;
}

export function errorBlock(message, retryId = "retry-load") {
  return `<div class="card"><div class="empty-state">
    <span class="empty-icon">${icon("alert")}</span>
    <strong>Could not load this page</strong>
    <p>${escapeHtml(message)}</p>
    <button class="btn btn-secondary" type="button" id="${retryId}">${icon("refresh")} Try again</button>
  </div></div>`;
}

export function toast(message, { type = "success", title = "" } = {}) {
  const root = document.getElementById("toast-root");
  if (!root) return;
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.setAttribute("role", type === "error" ? "alert" : "status");
  node.innerHTML = `<span class="toast-icon"></span><div class="grow">${title ? `<strong>${escapeHtml(title)}</strong>` : ""}<p>${escapeHtml(message)}</p></div><button class="toast-close" type="button" aria-label="Dismiss">${icon("x")}</button>`;
  node.querySelector(".toast-close").addEventListener("click", () => node.remove());
  root.appendChild(node);
  while (root.children.length > 4) root.firstElementChild.remove();
  setTimeout(() => node.remove(), type === "error" ? 7000 : 4200);
}

let activeModal = null;

export function closeModal() {
  if (!activeModal) return;
  const { root, onClose, previousFocus, keyHandler } = activeModal;
  document.removeEventListener("keydown", keyHandler);
  root.innerHTML = "";
  root.classList.remove("open");
  activeModal = null;
  if (previousFocus instanceof HTMLElement) {
    try {
      previousFocus.focus({ preventScroll: true });
    } catch {
      /* noop */
    }
  }
  if (onClose) onClose();
}

export function openModal({
  title,
  subtitle = "",
  body = "",
  footer = "",
  size = "",
  onMount,
  onClose,
  dismissible = true,
}) {
  closeModal();
  const root = document.getElementById("modal-root");
  const previousFocus = document.activeElement;
  root.classList.add("open");
  root.innerHTML = `<div class="modal-backdrop">
    <div class="modal ${size}" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div class="modal-header">
        <div><h2 id="modal-title">${escapeHtml(title)}</h2>${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}</div>
        ${dismissible ? `<button class="icon-btn" type="button" data-modal-close aria-label="Close dialog">${icon("x")}</button>` : ""}
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-footer">${footer}</div>` : ""}
    </div>
  </div>`;

  const backdrop = root.querySelector(".modal-backdrop");
  const keyHandler = (event) => {
    if (event.key === "Escape" && dismissible) {
      event.preventDefault();
      closeModal();
    }
    if (event.key === "Tab") {
      const focusables = root.querySelectorAll(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };

  activeModal = { root, previousFocus, keyHandler, onClose };
  document.addEventListener("keydown", keyHandler);
  root.querySelectorAll("[data-modal-close]").forEach((btn) => btn.addEventListener("click", closeModal));
  if (dismissible) {
    backdrop.addEventListener("mousedown", (event) => {
      if (event.target === backdrop) closeModal();
    });
  }

  const bodyNode = root.querySelector(".modal-body");
  const footerNode = root.querySelector(".modal-footer");
  if (onMount) onMount({ root, body: bodyNode, footer: footerNode, close: closeModal });
  hydrateIcons(root);
  requestAnimationFrame(() => {
    const target = bodyNode.querySelector("input:not([type=hidden]), select, textarea, button");
    if (target) target.focus({ preventScroll: false });
  });
  return { root, body: bodyNode, footer: footerNode, close: closeModal };
}

export function confirmDialog({
  title = "Are you sure?",
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  details = "",
}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    const { root } = openModal({
      title,
      body: `<div class="confirm-copy">${message}${details ? `<div style="margin-top:12px">${details}</div>` : ""}</div>`,
      footer: `<button class="btn btn-secondary" type="button" data-cancel>${escapeHtml(cancelLabel)}</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" type="button" data-confirm>${escapeHtml(confirmLabel)}</button>`,
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(false);
        }
      },
    });
    root.querySelector("[data-cancel]").addEventListener("click", () => finish(false));
    root.querySelector("[data-confirm]").addEventListener("click", () => finish(true));
  });
}

export function promptDialog({
  title,
  subtitle = "",
  label = "Reason",
  placeholder = "",
  confirmLabel = "Save",
  danger = false,
  required = true,
  rows = 3,
}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    const { root } = openModal({
      title,
      subtitle,
      body: `<div class="field">
        <label for="prompt-input">${escapeHtml(label)}</label>
        <textarea id="prompt-input" rows="${rows}" placeholder="${escapeHtml(placeholder)}"></textarea>
        <span class="error-text" id="prompt-error" hidden>This field is required.</span>
      </div>`,
      footer: `<button class="btn btn-secondary" type="button" data-cancel>Cancel</button>
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" type="button" data-confirm>${escapeHtml(confirmLabel)}</button>`,
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(null);
        }
      },
    });
    const input = root.querySelector("#prompt-input");
    const error = root.querySelector("#prompt-error");
    root.querySelector("[data-cancel]").addEventListener("click", () => finish(null));
    root.querySelector("[data-confirm]").addEventListener("click", () => {
      const value = input.value.trim();
      if (required && !value) {
        error.hidden = false;
        input.focus();
        return;
      }
      finish(value);
    });
    setTimeout(() => input.focus(), 40);
  });
}

export function formDataObject(form) {
  const data = {};
  new FormData(form).forEach((value, key) => {
    if (typeof value === "string") {
      data[key] = value.trim();
    } else {
      data[key] = value;
    }
  });
  form.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    data[checkbox.name] = checkbox.checked;
  });
  return data;
}

export function setBusy(button, busy, label = "Saving…") {
  if (!button) return;
  if (busy) {
    if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
    button.innerHTML = `<span class="spinner-sm"></span>${escapeHtml(label)}`;
  } else {
    button.removeAttribute("aria-busy");
    button.disabled = false;
    if (button.dataset.originalHtml) {
      button.innerHTML = button.dataset.originalHtml;
      delete button.dataset.originalHtml;
      hydrateIcons(button);
    }
  }
}

export function debounce(fn, delay = 250) {
  let handle = null;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), delay);
  };
}

export function uid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function statusBadgeList(...values) {
  return values.filter(Boolean).map((value) => badge(value)).join(" ");
}

export function paginationHtml({ total, limit, offset, idPrefix = "page" }) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return `<div class="pagination">
    <span>${num(total)} record${total === 1 ? "" : "s"} · page ${page} of ${pages}</span>
    <div class="row">
      <button class="btn btn-secondary btn-sm" type="button" data-${idPrefix}-prev ${offset <= 0 ? "disabled" : ""}>${icon("chevronLeft")} Previous</button>
      <button class="btn btn-secondary btn-sm" type="button" data-${idPrefix}-next ${offset + limit >= total ? "disabled" : ""}>Next ${icon("chevronRight")}</button>
    </div>
  </div>`;
}

export function readFormNumber(form, name) {
  const raw = form.elements[name]?.value;
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) ? value : 0;
}
