import { api } from "../api.js";
import { getState, queueOperation } from "../store.js";
import {
  badge,
  closeModal,
  confirmDialog,
  dateTimeLocalValue,
  dayParam,
  debounce,
  emptyState,
  escapeHtml,
  formatDate,
  formatDateTime,
  hydrateIcons,
  icon,
  money,
  num,
  openModal,
  paginationHtml,
  setBusy,
  startOfMonthParam,
  statusLabel,
  toast,
  uid,
} from "../ui.js";

const PAGE_SIZE = 50;

function isOffline() {
  const state = getState();
  return state.online === false || state.serverReachable === false;
}

const STOCK_CATEGORY = "inventory_purchase";
const FALLBACK_CATEGORIES = [STOCK_CATEGORY, "travel", "food", "packaging", "personal_other", "miscellaneous"];

function configuredCategories() {
  const settings = getState().settings;
  return settings.expense_categories?.length ? settings.expense_categories : FALLBACK_CATEGORIES;
}

function defaultOrdinaryCategory() {
  const ordinary = configuredCategories().filter((category) => category !== STOCK_CATEGORY);
  if (ordinary.includes("miscellaneous")) return "miscellaneous";
  return ordinary[0] || "miscellaneous";
}

function categoryOptions(selected, { includeStock = false } = {}) {
  const categories = configuredCategories().filter((category) => includeStock || category !== STOCK_CATEGORY);
  const list = categories.length ? categories : ["miscellaneous"];
  return list
    .map((category) => `<option value="${escapeHtml(category)}" ${category === selected ? "selected" : ""}>${escapeHtml(statusLabel(category))}</option>`)
    .join("");
}

function methodOptions(selected) {
  const methods = getState().settings.payment_methods?.length ? getState().settings.payment_methods : ["cash", "upi"];
  return methods
    .map((method) => `<option value="${escapeHtml(method)}" ${method === selected ? "selected" : ""}>${escapeHtml(statusLabel(method))}</option>`)
    .join("");
}

function categoryBars(rows) {
  const totals = new Map();
  rows.forEach((expense) => {
    totals.set(expense.category, (totals.get(expense.category) || 0) + Number(expense.amount || 0));
  });
  const list = Array.from(totals.entries()).sort((a, b) => b[1] - a[1]);
  if (!list.length) return `<div class="empty-state" style="padding:24px 16px"><span class="empty-icon">${icon("chart")}</span><strong>No category data</strong><p>Record an expense to see how spending is distributed.</p></div>`;
  const max = list[0][1] || 1;
  return `<div class="stack" style="gap:12px">${list
    .map(
      ([category, amount]) => `<div>
        <div class="row-between small"><span>${escapeHtml(statusLabel(category))}</span><span class="strong">${money(amount)}</span></div>
        <div class="stock-bar" style="margin-top:5px"><span style="width:${Math.max(3, (amount / max) * 100)}%;background:var(--accent)"></span></div>
      </div>`
    )
    .join("")}</div>`;
}

function expenseRows(items, focusId) {
  return `<div class="table-wrap"><table class="data expense-table">
    <thead><tr><th>Date</th><th>Expense</th><th>Kind</th><th>Category</th><th>Method</th><th class="num">Amount</th><th></th></tr></thead>
    <tbody>${items
      .map(
        (expense) => {
          const stock = expense.kind === "stock_purchase";
          const focused = Number(focusId) === Number(expense.id);
          const receiptLink = stock && expense.linked_receipt_id
            ? `<a class="row-link" href="/inventory?tab=receipts">Receipt #${expense.linked_receipt_id}</a> · `
            : "";
          return `<tr class="${expense.is_void ? "muted" : ""} ${focused ? "row-focus" : ""}">
        <td class="cell-date nowrap">${formatDate(expense.occurred_at)}<span class="tiny muted block">${formatDateTime(expense.occurred_at).split(", ").slice(-1)[0]}</span></td>
        <td class="cell-desc"><div class="cell-title">
          <span class="row-link">${escapeHtml(expense.description)}</span>
          <span>${receiptLink}${expense.paid_to ? `Paid to ${escapeHtml(expense.paid_to)}` : escapeHtml(statusLabel(expense.category))}${expense.reference ? ` · ${escapeHtml(expense.reference)}` : ""}${expense.void_reason ? ` · voided: ${escapeHtml(expense.void_reason)}` : ""}</span>
        </div></td>
        <td class="cell-kind">${stock ? `<span class="badge badge-imported">Stock purchase</span>` : `<span class="badge no-dot">Ordinary</span>`}</td>
        <td class="cell-category">${escapeHtml(statusLabel(expense.category))}</td>
        <td class="cell-method">${badge(expense.method)}</td>
        <td class="cell-amount num strong-cell ${expense.is_void ? "" : "negative"}">${expense.is_void ? `<s>${money(expense.amount)}</s>` : `−${money(expense.amount)}`}</td>
        <td class="cell-actions text-right"><div class="row">${
          expense.is_void
            ? `<span class="badge badge-voided">Voided</span>`
            : stock
              ? `<a class="btn btn-ghost btn-xs" href="/inventory?tab=receipts">${icon("package")} Receipt</a>`
              : `<button class="btn btn-ghost btn-xs" type="button" data-edit="${expense.id}">${icon("edit")} Edit</button>
                 <button class="btn btn-ghost btn-xs" type="button" data-void="${expense.id}">${icon("xCircle")} Void</button>`
        }</div></td>
      </tr>`;
        }
      )
      .join("")}</tbody>
  </table></div>`;
}

export default {
  title: "Expenses",
  subtitle: "Ordinary operating costs and stock purchases, kept separate in Money History.",
  async render(view, ctx) {
    let offset = Number(ctx.query.get("offset") || 0) || 0;
    let disposed = false;
    let latestRequest = 0;
    let cachedItems = [];
    const focusId = Number(ctx.query.get("focus") || 0) || 0;
    const openNew = ctx.query.get("new") === "1";
    const filters = {
      search: ctx.query.get("q") || "",
      date_from: ctx.query.get("date_from") || "",
      date_to: ctx.query.get("date_to") || "",
      category: ctx.query.get("category") || "",
      method: ctx.query.get("method") || "",
      include_void: ctx.query.get("include_void") === "1",
    };

    view.innerHTML = `
      <div class="stack">
        <div class="toolbar">
          <button class="btn btn-primary" type="button" id="add-expense">${icon("plus")} Add expense</button>
          <a class="btn btn-secondary" id="export-expenses" href="#" download>${icon("download")} Export CSV</a>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-ghost btn-sm" type="button" id="refresh-expenses">${icon("refresh")} Refresh</button>
        </div>
        <div id="expense-summary"></div>
        <div class="money-range-bar" style="padding:0">
          <div class="segmented" id="expense-ranges">
            <button type="button" data-range="today">Today</button>
            <button type="button" data-range="yesterday">Yesterday</button>
            <button type="button" data-range="7d">7 days</button>
            <button type="button" data-range="month">This month</button>
            <button type="button" data-range="all">All time</button>
          </div>
          <span class="small muted">Quick date range</span>
        </div>
        <div class="filter-bar">
          <div class="filter-field filter-search wide"><label for="expense-search">Search</label><div class="filter-search">${icon("search")}<input id="expense-search" type="search" placeholder="Description, reference or notes" value="${escapeHtml(filters.search)}" /></div></div>
          <div class="filter-field"><label for="expense-from">From</label><input id="expense-from" type="date" value="${escapeHtml(filters.date_from)}" /></div>
          <div class="filter-field"><label for="expense-to">To</label><input id="expense-to" type="date" value="${escapeHtml(filters.date_to)}" /></div>
          <div class="filter-field"><label for="expense-category">Category</label><select id="expense-category"><option value="">All categories</option>${categoryOptions(filters.category, { includeStock: true })}</select></div>
          <div class="filter-field"><label for="expense-method">Method</label><select id="expense-method"><option value="">All methods</option>${methodOptions(filters.method)}</select></div>
          <div class="filter-field"><label>Status</label><label class="checkbox-row small"><input type="checkbox" id="expense-void" ${filters.include_void ? "checked" : ""} /> Show voided</label></div>
        </div>
        <div class="grid-main-side">
          <section class="card" id="expense-table-card"></section>
          <section class="card"><div class="card-header"><div><h2>Category mix</h2><p>Spending for the current filters.</p></div></div><div class="card-body" id="expense-breakdown"></div></section>
        </div>
        <div class="inline-note">${icon("info")}Stock purchases are created automatically by inventory receipts and stay linked to them. Ordinary expenses and stock purchases both appear in Money History as money out, so they are never entered twice.</div>
      </div>`;

    const summarySlot = view.querySelector("#expense-summary");
    const tableCard = view.querySelector("#expense-table-card");
    const breakdown = view.querySelector("#expense-breakdown");

    function params(limit, offsetValue) {
      return {
        search: filters.search || undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        category: filters.category || undefined,
        method: filters.method || undefined,
        include_void: filters.include_void || undefined,
        limit,
        offset: offsetValue,
      };
    }

    function updateExportLink() {
      const search = new URLSearchParams({ type: "expenses" });
      if (filters.date_from) search.set("date_from", filters.date_from);
      if (filters.date_to) search.set("date_to", filters.date_to);
      view.querySelector("#export-expenses").href = `/api/reports/export?${search.toString()}`;
    }

    function renderSummary(totals, allItems) {
      const active = allItems.filter((expense) => !expense.is_void);
      const ordinary = active.filter((expense) => expense.kind !== "stock_purchase").reduce((sum, expense) => sum + Number(expense.amount), 0);
      const stock = active.filter((expense) => expense.kind === "stock_purchase").reduce((sum, expense) => sum + Number(expense.amount), 0);
      summarySlot.innerHTML = `<div class="metric-strip">
        <div><span>Filtered expense total</span><strong class="negative">${money(totals.amount)}</strong></div>
        <div><span>Ordinary expenses</span><strong>${money(ordinary)}</strong></div>
        <div><span>Stock purchases</span><strong>${money(stock)}</strong></div>
        <div><span>Records</span><strong>${num(totals.count)}</strong></div>
      </div>`;
    }

    async function load() {
      const requestId = ++latestRequest;
      tableCard.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading expenses…</span></div>`;
      try {
        const [page, all] = await Promise.all([
          api.expenses.list(params(PAGE_SIZE, offset)),
          api.expenses.list(params(500, 0)),
        ]);
        if (disposed || requestId !== latestRequest) return;
        cachedItems = page.items || [];
        renderSummary(page.totals || { amount: 0, count: 0 }, all.items || []);
        breakdown.innerHTML = categoryBars(all.items || []);
        tableCard.innerHTML = page.items.length
          ? `<div class="card-header"><div><h2>Expense records</h2><p>${num(page.total)} matching record${Number(page.total) === 1 ? "" : "s"}.</p></div></div>
             ${expenseRows(page.items, focusId)}
             <div class="card-footer">${paginationHtml({ total: page.total, limit: page.limit, offset: page.offset, idPrefix: "expense-page" })}</div>`
          : `<div class="card-header"><div><h2>Expense records</h2><p>No matching expenses.</p></div></div>${emptyState({
              iconName: "banknote",
              title: "No expenses match these filters",
              text: "Record delivery fuel, packaging, rent or any other cost. Stock purchases are recorded from Inventory → Receive stock.",
              action: `<button class="btn btn-primary btn-sm" type="button" data-add-expense>${icon("plus")} Add expense</button>`,
            })}`;
        hydrateIcons(tableCard);
        attachTableEvents();
        updateExportLink();
      } catch (error) {
        if (disposed || requestId !== latestRequest) return;
        tableCard.innerHTML = `<div class="empty-state">
          <span class="empty-icon">${icon("cloudOff")}</span>
          <strong>Expenses are unavailable</strong>
          <p>${escapeHtml(error.message)}</p>
          <p class="small">New expenses can still be saved locally and synchronized later.</p>
          <div class="row"><button class="btn btn-secondary" type="button" id="retry-expenses">${icon("refresh")} Try again</button><button class="btn btn-primary" type="button" data-add-expense>${icon("plus")} Add expense</button></div>
        </div>`;
        breakdown.innerHTML = `<div class="inline-note warn">${icon("cloudOff")}Category mix needs server data.</div>`;
        tableCard.querySelector("#retry-expenses")?.addEventListener("click", load);
        tableCard.querySelector("[data-add-expense]")?.addEventListener("click", () => openExpenseModal(null));
      }
    }

    function attachTableEvents() {
      view.querySelectorAll("[data-add-expense]").forEach((button) =>
        button.addEventListener("click", () => openExpenseModal(null))
      );
      tableCard.querySelectorAll("[data-edit]").forEach((button) =>
        button.addEventListener("click", () => {
          const expense = cachedItems.find((item) => Number(item.id) === Number(button.dataset.edit));
          if (expense) openExpenseModal(expense);
        })
      );
      tableCard.querySelectorAll("[data-void]").forEach((button) =>
        button.addEventListener("click", () => voidExpense(Number(button.dataset.void)))
      );
      tableCard.querySelector("[data-expense-page-prev]")?.addEventListener("click", () => {
        offset = Math.max(0, offset - PAGE_SIZE);
        load();
      });
      tableCard.querySelector("[data-expense-page-next]")?.addEventListener("click", () => {
        offset += PAGE_SIZE;
        load();
      });
    }

    function readFilters() {
      filters.search = view.querySelector("#expense-search").value;
      filters.date_from = view.querySelector("#expense-from").value;
      filters.date_to = view.querySelector("#expense-to").value;
      filters.category = view.querySelector("#expense-category").value;
      filters.method = view.querySelector("#expense-method").value;
      filters.include_void = view.querySelector("#expense-void").checked;
      if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
        [filters.date_from, filters.date_to] = [filters.date_to, filters.date_from];
        view.querySelector("#expense-from").value = filters.date_from;
        view.querySelector("#expense-to").value = filters.date_to;
      }
      offset = 0;
      const query = new URLSearchParams();
      if (filters.search) query.set("q", filters.search);
      if (filters.date_from) query.set("date_from", filters.date_from);
      if (filters.date_to) query.set("date_to", filters.date_to);
      if (filters.category) query.set("category", filters.category);
      if (filters.method) query.set("method", filters.method);
      if (filters.include_void) query.set("include_void", "1");
      const text = query.toString();
      history.replaceState(null, "", `/expenses${text ? `?${text}` : ""}`);
      load();
    }

    function openExpenseModal(expense) {
      if (expense && isOffline()) {
        toast("Editing an expense needs the local server.", { type: "warn" });
        return;
      }
      const { root } = openModal({
        title: expense ? "Edit expense" : "Add expense",
        subtitle: expense ? "Changes are version-checked and audited." : "Record a business cost. It is saved locally if the server is offline.",
        body: `<form id="expense-form" autocomplete="off">
          <div class="form-grid">
            <div class="field"><label for="e-when">Date and time</label><input id="e-when" name="occurred_at" type="datetime-local" value="${dateTimeLocalValue(expense ? new Date(expense.occurred_at) : new Date())}" required /></div>
            <div class="field"><label for="e-amount">Amount (₹)</label><input id="e-amount" name="amount" type="number" min="0.01" step="0.01" value="${expense ? Number(expense.amount).toFixed(2) : ""}" required placeholder="0.00" /></div>
            <div class="field"><label for="e-category">Category</label><select id="e-category" name="category">${categoryOptions(expense?.category || defaultOrdinaryCategory(), { includeStock: expense?.kind === "stock_purchase" })}</select></div>
            <div class="field"><label for="e-method">Paid with</label><select id="e-method" name="method">${methodOptions(expense?.method || "cash")}</select></div>
            <div class="field span-2"><label for="e-description">Description</label><input id="e-description" name="description" maxlength="200" required value="${escapeHtml(expense?.description || "")}" placeholder="e.g. Auto fare for hostel deliveries" /></div>
            <div class="field"><label for="e-paid-to">Paid to <span class="muted">(optional)</span></label><input id="e-paid-to" name="paid_to" maxlength="120" value="${escapeHtml(expense?.paid_to || "")}" placeholder="Person or shop" /></div>
            <div class="field"><label for="e-reference">Reference <span class="muted">(optional)</span></label><input id="e-reference" name="reference" maxlength="120" value="${escapeHtml(expense?.reference || "")}" placeholder="Bill or receipt number" /></div>
            <div class="field span-2"><label for="e-notes">Notes <span class="muted">(optional)</span></label><input id="e-notes" name="notes" value="${escapeHtml(expense?.notes || "")}" /></div>
          </div>
          ${expense ? "" : `<div class="inline-note">${icon("package")}Buying stock? Record it from Inventory → Receive stock so the purchase stays linked to the receipt. This form is for ordinary operating costs.</div>`}
          ${expense ? "" : `<div class="inline-note">${icon("cloudOff")}If the server is unreachable, this expense is stored on this device and synchronized later.</div>`}
          <div id="expense-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="expense-form" id="save-expense">${icon("save")} ${expense ? "Save changes" : isOffline() ? "Save locally" : "Add expense"}</button>`,
      });
      const form = root.querySelector("#expense-form");
      const errorBox = root.querySelector("#expense-error");

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const button = root.querySelector("#save-expense");
        const data = new FormData(form);
        const amount = Number(data.get("amount"));
        const description = String(data.get("description") || "").trim();
        if (!Number.isFinite(amount) || amount <= 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Enter an amount greater than zero.</div>`;
          return;
        }
        if (description.length < 1) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}A description is required.</div>`;
          return;
        }
        const when = data.get("occurred_at");
        const payload = {
          occurred_at: when ? new Date(when).toISOString() : new Date().toISOString(),
          category: data.get("category"),
          description,
          amount: amount.toFixed(2),
          method: data.get("method"),
          paid_to: String(data.get("paid_to") || "").trim() || null,
          reference: String(data.get("reference") || "").trim() || null,
          notes: String(data.get("notes") || "").trim() || null,
        };
        setBusy(button, true, "Saving…");
        try {
          if (expense) {
            payload.version = expense.version;
            await api.expenses.update(expense.id, payload);
            toast("Expense updated.", { title: "Saved" });
          } else if (isOffline()) {
            await queueOperation({
              kind: "expense",
              payload,
              label: `${description} · ${money(amount)}`,
              amount,
            });
            toast("Expense saved on this device. It will synchronize automatically.", { title: "Saved locally", type: "warn" });
          } else {
            await api.expenses.create({ ...payload, idempotency_key: uid() });
            toast("Expense recorded.", { title: "Saved" });
          }
          closeModal();
          await load();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    async function voidExpense(id) {
      if (isOffline()) {
        toast("Voiding an expense needs the local server.", { type: "warn" });
        return;
      }
      const expense = cachedItems.find((item) => Number(item.id) === Number(id));
      if (!expense) return;
      const proceed = await confirmDialog({
        title: "Void this expense?",
        message: `<strong>${escapeHtml(expense.description)}</strong> for ${money(expense.amount)} will be excluded from totals but kept in the audit trail. This cannot be undone.`,
        confirmLabel: "Void expense",
        danger: true,
      });
      if (!proceed) return;
      let reason = null;
      const { promptDialog } = await import("../ui.js");
      reason = await promptDialog({
        title: "Reason for voiding",
        label: "Reason",
        placeholder: "e.g. Entered twice by mistake",
        confirmLabel: "Void expense",
        danger: true,
      });
      if (!reason) return;
      try {
        await api.expenses.void(expense.id, { version: expense.version, reason });
        toast("Expense voided. The record remains in history.", { title: "Voided" });
        await load();
      } catch (error) {
        toast(error.message, { type: "error", title: "Could not void expense" });
      }
    }

    view.querySelector("#add-expense")?.addEventListener("click", () => openExpenseModal(null));
    view.querySelector("#refresh-expenses")?.addEventListener("click", load);
    view.querySelector("#expense-search")?.addEventListener("input", debounce(readFilters, 320));
    ["#expense-from", "#expense-to", "#expense-category", "#expense-method", "#expense-void"].forEach((selector) => {
      view.querySelector(selector)?.addEventListener("change", readFilters);
    });
    view.querySelector("#expense-ranges")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-range]");
      if (!button) return;
      view.querySelectorAll("#expense-ranges [data-range]").forEach((item) => item.classList.toggle("active", item === button));
      const today = new Date();
      let from = "";
      let to = dayParam(today);
      if (button.dataset.range === "today") {
        from = to;
      } else if (button.dataset.range === "yesterday") {
        const yesterday = new Date(today.getTime() - 86400000);
        from = dayParam(yesterday);
        to = from;
      } else if (button.dataset.range === "7d") {
        from = dayParam(new Date(today.getTime() - 6 * 86400000));
      } else if (button.dataset.range === "month") {
        from = startOfMonthParam(today);
      } else {
        from = "";
        to = "";
      }
      view.querySelector("#expense-from").value = from;
      view.querySelector("#expense-to").value = to;
      readFilters();
    });

    updateExportLink();
    await load();
    if (focusId) {
      tableCard.querySelector("tr.row-focus")?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
    if (openNew) openExpenseModal(null);
    return () => {
      disposed = true;
    };
  },
};
