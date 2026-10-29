import { api } from "../api.js";
import {
  getState,
  isOffline,
  moneyCategories,
  moneyCategoryLabel,
  paymentMethods,
  pendingOperations,
  queueOperation,
} from "../store.js";
import {
  badge,
  closeModal,
  confirmDialog,
  debounce,
  emptyState,
  escapeHtml,
  formatDate,
  formatDateTime,
  formatTime,
  hydrateIcons,
  icon,
  methodBadge,
  money,
  num,
  openModal,
  paginationHtml,
  promptDialog,
  setBusy,
  statusLabel,
  toast,
  uid,
  dateTimeLocalValue,
} from "../ui.js";

const PAGE_SIZE = 50;

const RANGES = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "7 days" },
  { key: "month", label: "This month" },
  { key: "previous_month", label: "Last month" },
  { key: "all", label: "All time" },
  { key: "custom", label: "Custom" },
];

const SOURCE_LABELS = {
  payment: "Sale payment",
  expense: "Expense",
  stock_purchase: "Stock purchase",
  handover: "Handover",
  money: "Manual entry",
};

function sourceLabel(source) {
  return SOURCE_LABELS[source] || statusLabel(source);
}

function optionsHtml(options, selected) {
  return options
    .map(([value, label]) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(label)}</option>`)
    .join("");
}

function directionOptions(selected) {
  return optionsHtml(
    [
      ["", "All directions"],
      ["in", "Money in"],
      ["out", "Money out"],
    ],
    selected
  );
}

function categoryOptions(selected) {
  const state = getState();
  const values = [
    ...new Set([
      ...(state.settings.money_in_categories || []),
      ...(state.settings.money_out_categories || []),
      "customer_payment",
      "refund",
      "adjustment",
      "stock_purchase",
      "expense_payment",
      "cash_handover",
      "cash_upi_transfer",
    ]),
  ].sort((a, b) => moneyCategoryLabel(a).localeCompare(moneyCategoryLabel(b)));
  return `<option value="">All categories</option>${values
    .map((value) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(moneyCategoryLabel(value))}</option>`)
    .join("")}`;
}

function methodOptions(selected, includeAll = false) {
  const methods = [...new Set([...paymentMethods(), "cash", "upi"])];
  return `${includeAll ? `<option value="">All methods</option>` : ""}${methods
    .map((method) => `<option value="${escapeHtml(method)}" ${method === selected ? "selected" : ""}>${escapeHtml(statusLabel(method))}</option>`)
    .join("")}`;
}

function pendingTransactionTotal(operation) {
  return Number(operation.payload?.amount || 0);
}

function pendingPanel(operations) {
  if (!operations.length) return "";
  return `<section class="card">
    <div class="card-header">
      <div><h2>Saved on this device</h2><p>These money entries are waiting to synchronize. They will receive permanent IDs once the server accepts them.</p></div>
      <span class="badge badge-pending">${operations.length} pending</span>
    </div>
    <div class="table-wrap"><table class="data compact">
      <thead><tr><th>Saved</th><th>Money entry</th><th>Direction</th><th class="num">Amount</th><th>Status</th></tr></thead>
      <tbody>${operations
        .map((operation) => {
          const payload = operation.payload || {};
          const failed = operation.status === "failed";
          const transfer = payload.category === "cash_upi_transfer";
          return `<tr>
            <td class="nowrap">${formatDateTime(operation.createdAt)}</td>
            <td><div class="cell-title"><span class="row-link">${escapeHtml(payload.description || "Money entry")}</span><span>${escapeHtml(payload.person || "No person")} · ${escapeHtml(moneyCategoryLabel(payload.category))}</span></div></td>
            <td>${transfer ? `<span class="badge badge-local">Transfer</span>` : badge(payload.direction === "in" ? "in" : "out")}</td>
            <td class="num strong-cell ${transfer ? "" : payload.direction === "in" ? "positive" : "negative"}">${transfer ? money(pendingTransactionTotal(operation)) : `${payload.direction === "in" ? "+" : "−"}${money(pendingTransactionTotal(operation))}`}</td>
            <td>${failed ? `<span class="badge badge-failed" title="${escapeHtml(operation.lastError || "")}">Sync failed</span>` : `<span class="badge badge-local">Pending sync</span>`}</td>
          </tr>`;
        })
        .join("")}</tbody>
    </table></div>
    <div class="card-footer row-between">
      <span class="small muted">${operations.some((item) => item.status === "failed") ? "Some entries failed to sync. Review them in Settings &amp; Backup → Offline queue." : "Use Sync now when the connection is available."}</span>
      <a class="btn btn-secondary btn-sm" href="/settings">Open offline queue ${icon("arrowRight")}</a>
    </div>
  </section>`;
}

function summaryView(summary) {
  const complete = summary.balance_complete;
  const openingLine = complete
    ? `Opening cash ${money(summary.opening_cash)} · opening UPI ${money(summary.opening_upi)}${summary.opening_effective_date ? ` from ${formatDate(summary.opening_effective_date)}` : ""}`
    : "Opening balances are not set, so running balances may be incomplete.";
  return `<div class="metric-strip money-strip">
      <div><span>Money in</span><strong class="positive">+${money(summary.money_in)}</strong><small>${money(summary.sale_payments_in)} sale payments · ${money(summary.other_money_in)} other</small></div>
      <div><span>Money out</span><strong class="negative">−${money(summary.money_out)}</strong><small>${money(summary.ordinary_expenses)} ordinary · ${money(summary.stock_purchases)} stock</small></div>
      <div><span>Cash available</span><strong>${money(summary.current_cash)}</strong><small>Cash in ${money(summary.cash_in)} · cash out ${money(summary.cash_out)}</small></div>
      <div><span>UPI available</span><strong>${money(summary.current_upi)}</strong><small>UPI in ${money(summary.upi_in)} · UPI out ${money(summary.upi_out)}</small></div>
    </div>
    <div class="money-opening ${complete ? "" : "incomplete"}">
      <span>${icon(complete ? "checkCircle" : "alert")} ${escapeHtml(openingLine)}</span>
      <a href="/settings">${complete ? "Edit opening balances" : "Set opening balances"}</a>
    </div>
    <div class="money-range-line"><span>${escapeHtml(summary.label)}</span><span>${num(summary.count)} entries</span></div>`;
}

function relatedCell(row) {
  const links = [];
  if (row.sale_id) {
    links.push(`<a class="row-link" href="/sales/${row.sale_id}">Sale #${row.sale_id}</a>${row.sale_external_order_id ? `<span class="tiny muted block">Order ${escapeHtml(row.sale_external_order_id)}</span>` : ""}`);
  }
  if (row.expense_id) {
    links.push(`<a class="row-link" href="/expenses?focus=${row.expense_id}">Expense #${row.expense_id}</a>`);
  }
  if (row.receipt_id) {
    links.push(`<a class="row-link" href="/inventory?tab=receipts">Stock receipt #${row.receipt_id}</a>`);
  }
  if (row.handover_id) {
    links.push(`<span class="small muted">Handover #${row.handover_id}</span>`);
  }
  return links.length ? `<div class="cell-title">${links.join("")}</div>` : `<span class="muted">—</span>`;
}

function ledgerRow(row, focusedKey) {
  const isTransfer = row.category === "cash_upi_transfer";
  const incoming = row.direction === "in";
  const transferLabel = row.method === "cash" ? "Cash → UPI" : "UPI → Cash";
  const amount = `${incoming ? "+" : "−"}${money(row.amount)}`;
  const balance = [
    row.cash_balance_after !== null && row.cash_balance_after !== undefined ? `Cash ${money(row.cash_balance_after)}` : "",
    row.upi_balance_after !== null && row.upi_balance_after !== undefined ? `UPI ${money(row.upi_balance_after)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const actions = row.money_id
    ? row.is_void
      ? `<span class="badge badge-voided">Voided</span>`
      : `<button class="btn btn-ghost btn-xs" type="button" data-edit="${row.record_id}" data-key="${escapeHtml(row.key)}">${icon("edit")} Edit</button>
         <button class="btn btn-ghost btn-xs" type="button" data-void="${row.record_id}" data-key="${escapeHtml(row.key)}">${icon("xCircle")} Void</button>`
    : `<span class="tiny muted">Linked</span>`;
  return `<tr class="${row.is_void ? "muted" : ""} ${focusedKey === row.key ? "row-focus" : ""}" data-row-key="${escapeHtml(row.key)}">
    <td class="cell-date nowrap">${formatDate(row.occurred_at)}<span class="tiny muted block">${formatTime(row.occurred_at)}</span></td>
    <td class="cell-desc"><div class="cell-title">
      <span class="row-link">${escapeHtml(row.person || row.category_label)}</span>
      <span>${escapeHtml(row.category_label)} · ${escapeHtml(sourceLabel(row.source))}${row.reference ? ` · ${escapeHtml(row.reference)}` : ""}</span>
      <span class="tiny muted">${escapeHtml(row.description)}${row.notes ? ` · ${escapeHtml(row.notes)}` : ""}</span>
      ${row.is_void ? `<span class="tiny negative">Voided${row.void_reason ? `: ${escapeHtml(row.void_reason)}` : ""}</span>` : ""}
    </div></td>
    <td>${isTransfer ? `<span class="badge badge-local">Transfer</span>` : badge(row.direction)}</td>
    <td>${methodBadge(row.method)}</td>
    <td class="num strong-cell ${isTransfer ? "" : incoming ? "positive" : "negative"}">${isTransfer ? `<span class="row">${icon("arrowRight")} ${money(row.amount)}</span><span class="tiny muted block">${transferLabel}</span>` : row.is_void ? `<s>${amount}</s>` : amount}</td>
    <td class="cell-balance tiny muted">${balance || "—"}</td>
    <td class="cell-linked">${relatedCell(row)}</td>
    <td class="cell-actions text-right"><div class="row">${actions}</div></td>
  </tr>`;
}

function ledgerTable(data, focusId) {
  const focusedKey = focusId ? `money:${focusId}` : "";
  return `<div class="table-wrap"><table class="data money-table">
    <thead><tr>
      <th>Date</th><th>Person &amp; reason</th><th>Direction</th><th>Method</th><th class="num">Amount</th><th>Balance after</th><th>Related</th><th></th>
    </tr></thead>
    <tbody>${data.items.map((row) => ledgerRow(row, focusedKey)).join("")}</tbody>
  </table></div>`;
}

function dailyTable(daily) {
  if (!daily.length) return `<p class="muted small">No daily activity in this range.</p>`;
  const rows = [...daily].reverse().slice(0, 40);
  return `<div class="table-wrap" style="max-height:360px;overflow-y:auto"><table class="data compact">
    <thead><tr><th>Date</th><th class="num">In</th><th class="num">Out</th><th class="num">Cash in</th><th class="num">Cash out</th><th class="num">UPI in</th><th class="num">UPI out</th><th class="num">Entries</th></tr></thead>
    <tbody>${rows
      .map(
        (row) => `<tr>
        <td class="nowrap">${formatDate(row.date)}</td>
        <td class="num positive">${money(row.money_in)}</td>
        <td class="num negative">${money(row.money_out)}</td>
        <td class="num">${money(row.cash_in)}</td>
        <td class="num">${money(row.cash_out)}</td>
        <td class="num">${money(row.upi_in)}</td>
        <td class="num">${money(row.upi_out)}</td>
        <td class="num">${num(row.count)}</td>
      </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function monthlyTable(months) {
  if (!months.length) return `<p class="muted small">No monthly activity yet.</p>`;
  return `<div class="table-wrap"><table class="data compact">
    <thead><tr><th>Month</th><th class="num">In</th><th class="num">Out</th><th class="num">Cash in</th><th class="num">Cash out</th><th class="num">UPI in</th><th class="num">UPI out</th><th class="num">Entries</th></tr></thead>
    <tbody>${months
      .map(
        (row) => `<tr>
        <td>${escapeHtml(row.label)}</td>
        <td class="num positive">${money(row.money_in)}</td>
        <td class="num negative">${money(row.money_out)}</td>
        <td class="num">${money(row.cash_in)}</td>
        <td class="num">${money(row.cash_out)}</td>
        <td class="num">${money(row.upi_in)}</td>
        <td class="num">${money(row.upi_out)}</td>
        <td class="num">${num(row.count)}</td>
      </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

export default {
  title: "Money History",
  subtitle: "A permanent ledger of money received and given, including sale payments, expenses and owner handovers.",
  async render(view, ctx) {
    let disposed = false;
    let latestRequest = 0;
    let offset = Number(ctx.query.get("offset") || 0) || 0;
    let focusId = Number(ctx.query.get("focus") || 0) || 0;
    let currentItems = [];
    const filters = {
      range: ctx.query.get("range") || "month",
      date_from: ctx.query.get("date_from") || "",
      date_to: ctx.query.get("date_to") || "",
      search: ctx.query.get("q") || "",
      direction: ctx.query.get("direction") || "",
      category: ctx.query.get("category") || "",
      method: ctx.query.get("method") || "",
      include_void: ctx.query.get("include_void") === "1",
    };
    if (filters.range === "custom" && (!filters.date_from || !filters.date_to)) {
      const today = new Date();
      const first = new Date(today.getFullYear(), today.getMonth(), 1);
      filters.date_from = filters.date_from || first.toISOString().slice(0, 10);
      filters.date_to = filters.date_to || today.toISOString().slice(0, 10);
    }

    view.innerHTML = `
      <div class="stack">
        <div class="toolbar">
          <button class="btn btn-primary" type="button" id="add-money">${icon("plus")} Add transaction</button>
          <button class="btn btn-secondary" type="button" id="record-transfer">${icon("arrowRight")} Cash / UPI transfer</button>
          <button class="btn btn-secondary" type="button" id="record-handover">${icon("wallet")} Owner handover</button>
          <a class="btn btn-secondary" id="export-money" href="/api/reports/export?type=money">${icon("download")} Export CSV</a>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-ghost btn-sm" type="button" id="refresh-money">${icon("refresh")} Refresh</button>
        </div>

        <div class="alert alert-info">${icon("info")}<div><strong>Money in is not automatically income</strong>It can be a customer payment, money received from the owner or a repayment. Likewise, money out is not automatically an expense. Use the category and person fields so the history stays meaningful.</div></div>

        <div id="money-pending"></div>
        <div id="money-summary"></div>

        <section class="card">
          <div class="card-header">
            <div><h2>Transaction ledger</h2><p>Every recorded money movement, newest first. Sale payments, expenses and handovers stay linked to their source records.</p></div>
            <div class="row-wrap"><button class="btn btn-secondary btn-sm" type="button" data-add-money>${icon("plus")} Add</button></div>
          </div>
          <div class="filter-bar money-filters">
            <div class="filter-field filter-search wide">
              <label for="money-search">Search</label>
              <div class="filter-search">${icon("search")}<input id="money-search" type="search" placeholder="Person, amount, description or reference" value="${escapeHtml(filters.search)}" /></div>
            </div>
            <div class="filter-field"><label for="money-direction">Direction</label><select id="money-direction">${directionOptions(filters.direction)}</select></div>
            <div class="filter-field"><label for="money-category">Category</label><select id="money-category">${categoryOptions(filters.category)}</select></div>
            <div class="filter-field"><label for="money-method">Method</label><select id="money-method">${methodOptions(filters.method, true)}</select></div>
            <div class="filter-field"><label>Status</label><label class="checkbox-row small"><input type="checkbox" id="money-void" ${filters.include_void ? "checked" : ""} /> Show voided</label></div>
            <div class="filter-field"><label>&nbsp;</label><button class="btn btn-secondary" type="button" id="money-clear">${icon("x")} Clear</button></div>
          </div>
          <div class="money-range-bar">
            <div class="segmented" id="money-ranges">
              ${RANGES.map((item) => `<button type="button" data-range="${item.key}" class="${filters.range === item.key ? "active" : ""}">${item.label}</button>`).join("")}
            </div>
            <div class="row" id="money-custom" ${filters.range === "custom" ? "" : "hidden"}>
              <input type="date" id="money-from" value="${escapeHtml(filters.date_from)}" aria-label="From date" style="width:150px" />
              <span class="muted small">to</span>
              <input type="date" id="money-to" value="${escapeHtml(filters.date_to)}" aria-label="To date" style="width:150px" />
              <button class="btn btn-secondary btn-sm" type="button" id="apply-money-range">Apply</button>
            </div>
          </div>
          <div id="money-results"><div class="app-loading"><span class="spinner"></span><span>Loading money history…</span></div></div>
        </section>

        <div class="grid-main-side">
          <section class="card">
            <div class="card-header"><div><h2>Daily totals</h2><p>Money in and out by day for the current filters. Outstanding balances are not money received.</p></div></div>
            <div class="card-body" id="money-daily"><div class="app-loading"><span class="spinner"></span><span>Loading…</span></div></div>
          </section>
          <section class="card">
            <div class="card-header"><div><h2>Monthly movement</h2><p>Cash and UPI movement by calendar month.</p></div>
              <div class="row"><input type="number" id="money-year" min="2000" max="2100" value="${new Date().getFullYear()}" style="width:100px" aria-label="Year" /><button class="btn btn-secondary btn-sm" type="button" id="load-money-year">Load</button></div>
            </div>
            <div class="card-body" id="money-monthly"><div class="app-loading"><span class="spinner"></span><span>Loading…</span></div></div>
          </section>
        </div>

        <div class="inline-note">${icon("info")}Cash and UPI balances are tracked separately. Use <strong>Cash / UPI transfer</strong> to move your own money between them: it updates both balances and is never counted as money in, money out or an ordinary expense. Balances depend on the opening cash and UPI balances in Settings &amp; Backup.</div>
      </div>`;

    const results = view.querySelector("#money-results");
    const summarySlot = view.querySelector("#money-summary");
    const pendingSlot = view.querySelector("#money-pending");
    const dailySlot = view.querySelector("#money-daily");
    const monthlySlot = view.querySelector("#money-monthly");

    function activeParams(limit = PAGE_SIZE) {
      return {
        range: filters.range,
        date_from: filters.range === "custom" ? filters.date_from : undefined,
        date_to: filters.range === "custom" ? filters.date_to : undefined,
        search: filters.search || undefined,
        direction: filters.direction || undefined,
        category: filters.category || undefined,
        method: filters.method || undefined,
        include_void: filters.include_void || undefined,
        limit,
        offset,
      };
    }

    function syncQuery() {
      const params = new URLSearchParams();
      if (filters.range && filters.range !== "month") params.set("range", filters.range);
      if (filters.range === "custom") {
        if (filters.date_from) params.set("date_from", filters.date_from);
        if (filters.date_to) params.set("date_to", filters.date_to);
      }
      if (filters.search) params.set("q", filters.search);
      if (filters.direction) params.set("direction", filters.direction);
      if (filters.category) params.set("category", filters.category);
      if (filters.method) params.set("method", filters.method);
      if (filters.include_void) params.set("include_void", "1");
      if (offset) params.set("offset", String(offset));
      const query = params.toString();
      if (focusId) {
        params.set("focus", String(focusId));
        history.replaceState(null, "", `/money-history?${params.toString()}`);
        return;
      }
      history.replaceState(null, "", `/money-history${query ? `?${query}` : ""}`);
    }

    function updateExportLink() {
      const params = new URLSearchParams({ type: "money" });
      if (filters.range === "custom") {
        if (filters.date_from) params.set("date_from", filters.date_from);
        if (filters.date_to) params.set("date_to", filters.date_to);
      }
      view.querySelector("#export-money").href = `/api/reports/export?${params.toString()}`;
    }

    async function renderPending() {
      try {
        const operations = (await pendingOperations()).filter((operation) => operation.kind === "money");
        if (disposed) return;
        pendingSlot.innerHTML = pendingPanel(operations);
        hydrateIcons(pendingSlot);
      } catch {
        pendingSlot.innerHTML = "";
      }
    }

    function attachRowActions() {
      results.querySelectorAll("[data-edit]").forEach((button) =>
        button.addEventListener("click", () => {
          const item = currentItems.find((row) => row.key === button.dataset.key);
          if (item) openTransactionModal(item);
        })
      );
      results.querySelectorAll("[data-void]").forEach((button) =>
        button.addEventListener("click", () => {
          const item = currentItems.find((row) => row.key === button.dataset.key);
          if (item) voidTransaction(item);
        })
      );
    }

    async function load() {
      const requestId = ++latestRequest;
      results.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading money history…</span></div>`;
      try {
        const data = await api.money.ledger(activeParams());
        if (disposed || requestId !== latestRequest) return;
        currentItems = data.items || [];
        summarySlot.innerHTML = summaryView(data.summary);
        hydrateIcons(summarySlot);
        updateExportLink();
        dailySlot.innerHTML = dailyTable(data.daily || []);
        results.innerHTML = currentItems.length
          ? `${ledgerTable(data, focusId)}<div class="card-footer">${paginationHtml({
              total: data.total,
              limit: data.limit,
              offset: data.offset,
              idPrefix: "money-page",
            })}</div>`
          : emptyState({
              iconName: "wallet",
              title: "No money entries match these filters",
              text: "Record money received, money given, expenses or sale payments. Entries are never silently deleted; corrections and voids stay in history.",
              action: `<button class="btn btn-primary btn-sm" type="button" data-add-money>${icon("plus")} Add transaction</button>`,
            });
        hydrateIcons(results);
        results.querySelectorAll("[data-add-money]").forEach((button) =>
          button.addEventListener("click", () => openTransactionModal(null))
        );
        results.querySelector("[data-money-page-prev]")?.addEventListener("click", () => {
          offset = Math.max(0, offset - PAGE_SIZE);
          load();
          syncQuery();
        });
        results.querySelector("[data-money-page-next]")?.addEventListener("click", () => {
          offset += PAGE_SIZE;
          load();
          syncQuery();
        });
        attachRowActions();
        if (focusId) {
          const node = results.querySelector(`[data-row-key="money:${focusId}"]`);
          node?.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      } catch (error) {
        if (disposed || requestId !== latestRequest) return;
        summarySlot.innerHTML = "";
        dailySlot.innerHTML = "";
        results.innerHTML = `<div class="empty-state">
          <span class="empty-icon">${icon("cloudOff")}</span>
          <strong>Money history is unavailable</strong>
          <p>${escapeHtml(error.message)}</p>
          <p class="small">New money entries can still be saved locally. They are listed above until they synchronize.</p>
          <div class="row"><button class="btn btn-secondary" type="button" id="retry-money">${icon("refresh")} Try again</button><button class="btn btn-primary" type="button" data-add-money>${icon("plus")} Add transaction</button></div>
        </div>`;
        hydrateIcons(results);
        results.querySelector("#retry-money")?.addEventListener("click", load);
        results.querySelector("[data-add-money]")?.addEventListener("click", () => openTransactionModal(null));
      }
    }

    async function loadMonthly() {
      const year = Number(view.querySelector("#money-year").value) || new Date().getFullYear();
      monthlySlot.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading…</span></div>`;
      try {
        const data = await api.money.monthly({ year });
        if (disposed) return;
        monthlySlot.innerHTML = monthlyTable(data.months || []);
      } catch (error) {
        if (disposed) return;
        monthlySlot.innerHTML = `<div class="inline-note warn">${icon("cloudOff")}Monthly movement unavailable: ${escapeHtml(error.message)}</div>`;
      }
    }

    function readFilters(resetOffset = true) {
      filters.range = view.querySelector("#money-ranges .active")?.dataset.range || "month";
      filters.date_from = view.querySelector("#money-from").value;
      filters.date_to = view.querySelector("#money-to").value;
      filters.search = view.querySelector("#money-search").value;
      filters.direction = view.querySelector("#money-direction").value;
      filters.category = view.querySelector("#money-category").value;
      filters.method = view.querySelector("#money-method").value;
      filters.include_void = view.querySelector("#money-void").checked;
      if (filters.range === "custom") {
        if (!filters.date_from || !filters.date_to) {
          toast("Choose both a start and end date for the custom range.", { type: "warn" });
          return;
        }
        if (filters.date_from > filters.date_to) {
          [filters.date_from, filters.date_to] = [filters.date_to, filters.date_from];
          view.querySelector("#money-from").value = filters.date_from;
          view.querySelector("#money-to").value = filters.date_to;
        }
      }
      if (resetOffset) offset = 0;
      focusId = 0;
      syncQuery();
      load();
    }

    const debouncedSearch = debounce(() => readFilters(), 320);
    view.querySelector("#money-search")?.addEventListener("input", debouncedSearch);
    ["#money-direction", "#money-category", "#money-method", "#money-void"].forEach((selector) => {
      view.querySelector(selector)?.addEventListener("change", () => readFilters());
    });
    view.querySelector("#money-ranges")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-range]");
      if (!button) return;
      view.querySelectorAll("#money-ranges [data-range]").forEach((item) => item.classList.toggle("active", item === button));
      const custom = view.querySelector("#money-custom");
      custom.hidden = button.dataset.range !== "custom";
      if (button.dataset.range === "custom") {
        const today = new Date();
        const first = new Date(today.getFullYear(), today.getMonth(), 1);
        if (!view.querySelector("#money-from").value) view.querySelector("#money-from").value = first.toISOString().slice(0, 10);
        if (!view.querySelector("#money-to").value) view.querySelector("#money-to").value = today.toISOString().slice(0, 10);
      }
      readFilters();
    });
    view.querySelector("#apply-money-range")?.addEventListener("click", () => readFilters());
    view.querySelector("#money-clear")?.addEventListener("click", () => {
      view.querySelector("#money-search").value = "";
      view.querySelector("#money-direction").value = "";
      view.querySelector("#money-category").value = "";
      view.querySelector("#money-method").value = "";
      view.querySelector("#money-void").checked = false;
      view.querySelectorAll("#money-ranges [data-range]").forEach((item) =>
        item.classList.toggle("active", item.dataset.range === "month")
      );
      view.querySelector("#money-custom").hidden = true;
      readFilters();
    });
    view.querySelector("#refresh-money")?.addEventListener("click", () => {
      renderPending();
      load();
      loadMonthly();
    });
    view.querySelector("#load-money-year")?.addEventListener("click", loadMonthly);
    view.querySelector("#add-money")?.addEventListener("click", () => openTransactionModal(null));
    view.querySelectorAll("[data-add-money]").forEach((button) =>
      button.addEventListener("click", () => openTransactionModal(null))
    );
    view.querySelector("#record-transfer")?.addEventListener("click", () => openTransferModal());
    view.querySelector("#record-handover")?.addEventListener("click", () => openHandoverModal());

    function categorySelectHtml(direction, selected) {
      const values = [...moneyCategories(direction)];
      if (selected && !values.includes(selected)) values.unshift(selected);
      return values
        .map((value) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(moneyCategoryLabel(value))}</option>`)
        .join("");
    }

    function openTransactionModal(existing) {
      if (existing && isOffline()) {
        toast("Editing a money entry needs the local server.", { type: "warn" });
        return;
      }
      let direction = existing?.direction || "in";
      const modal = openModal({
        title: existing ? "Correct money entry" : "Add money transaction",
        subtitle: existing
          ? "The original values stay in the audit trail. Saving creates a correction history."
          : "Record money received or given. A sale payment and an ordinary expense are separate records.",
        body: `<form id="money-form" autocomplete="off">
          <div class="segmented direction-toggle" id="money-direction-toggle" role="group" aria-label="Direction">
            <button type="button" data-direction="in" class="${direction === "in" ? "active" : ""}">${icon("arrowDownLeft")} Money in</button>
            <button type="button" data-direction="out" class="${direction === "out" ? "active" : ""}">${icon("arrowUpRight")} Money out</button>
          </div>
          <div class="form-grid">
            <div class="field"><label for="m-amount">Amount (₹)</label><input id="m-amount" name="amount" type="number" min="0.01" step="0.01" value="${existing ? Number(existing.amount).toFixed(2) : ""}" required placeholder="0.00" /></div>
            <div class="field"><label for="m-person">Person / party <span class="muted">(optional)</span></label><input id="m-person" name="person" maxlength="120" value="${escapeHtml(existing?.person || "")}" placeholder="e.g. Owner, supplier, customer" /></div>
            <div class="field"><label for="m-when">Date and time</label><input id="m-when" name="occurred_at" type="datetime-local" value="${dateTimeLocalValue(existing ? new Date(existing.occurred_at) : new Date())}" required /></div>
            <div class="field"><label for="m-method">Method</label><select id="m-method" name="method">${methodOptions(existing?.method || "cash")}</select></div>
            <div class="field"><label for="m-category">Category / reason</label><select id="m-category" name="category">${categorySelectHtml(direction, existing?.category || moneyCategories(direction)[0])}</select></div>
            <div class="field"><label for="m-reference">Reference <span class="muted">(optional)</span></label><input id="m-reference" name="reference" maxlength="120" value="${escapeHtml(existing?.reference || "")}" placeholder="Receipt, bill or transfer reference" /></div>
            <div class="field span-2"><label for="m-description">Description</label><input id="m-description" name="description" maxlength="200" required value="${escapeHtml(existing?.description || "")}" placeholder="e.g. Cash received from owner for stock" /></div>
            <div class="field span-2"><label for="m-notes">Note <span class="muted">(optional)</span></label><input id="m-notes" name="notes" value="${escapeHtml(existing?.notes || "")}" /></div>
          </div>
          <div class="inline-note">${icon("cloudOff")}${isOffline() ? "The server is unreachable. This entry will be stored on this device and synchronized later." : "If the connection drops, this entry is stored on this device and synchronized later."}</div>
          <div id="money-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="money-form" id="save-money">${icon("save")} ${existing ? "Save correction" : isOffline() ? "Save locally" : "Save transaction"}</button>`,
      });
      const form = modal.root.querySelector("#money-form");
      const errorBox = modal.root.querySelector("#money-error");
      const categorySelect = modal.root.querySelector("#m-category");
      const toggle = modal.root.querySelector("#money-direction-toggle");
      const methodSelect = modal.root.querySelector("#m-method");

      toggle.addEventListener("click", (event) => {
        const button = event.target.closest("[data-direction]");
        if (!button) return;
        direction = button.dataset.direction;
        toggle.querySelectorAll("[data-direction]").forEach((item) => item.classList.toggle("active", item === button));
        categorySelect.innerHTML = categorySelectHtml(direction, moneyCategories(direction)[0]);
      });

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const data = new FormData(form);
        const amount = Number(data.get("amount"));
        const description = String(data.get("description") || "").trim();
        if (!Number.isFinite(amount) || amount <= 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Enter an amount greater than zero.</div>`;
          return;
        }
        if (description.length < 2) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Add a short description (at least 2 characters).</div>`;
          return;
        }
        const when = data.get("occurred_at");
        const payload = {
          direction,
          amount: amount.toFixed(2),
          person: String(data.get("person") || "").trim() || null,
          category: data.get("category"),
          method: data.get("method"),
          occurred_at: when ? new Date(when).toISOString() : new Date().toISOString(),
          description,
          reference: String(data.get("reference") || "").trim() || null,
          notes: String(data.get("notes") || "").trim() || null,
        };
        const button = modal.root.querySelector("#save-money");
        setBusy(button, true, "Saving…");
        try {
          if (existing) {
            await api.money.update(existing.record_id, { ...payload, version: existing.version });
            toast("Money entry corrected. The audit trail keeps the original values.", { title: "Saved" });
          } else if (isOffline()) {
            await queueOperation({
              kind: "money",
              payload,
              label: `${payload.description} · ${money(amount)}`,
              amount,
            });
            toast("Money entry saved on this device. It will synchronize automatically.", { title: "Saved locally", type: "warn" });
          } else {
            const key = uid();
            await api.money.create({ ...payload, idempotency_key: key }, key);
            toast("Money transaction recorded.", { title: "Saved" });
          }
          closeModal();
          offset = 0;
          await Promise.all([renderPending(), load(), loadMonthly()]);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openTransferModal() {
      const modal = openModal({
        title: "Transfer between cash and UPI",
        subtitle: "Move your own money between the two balances. This is not income or an expense.",
        body: `<form id="transfer-form" autocomplete="off">
          <div class="form-grid">
            <div class="field"><label for="t-amount">Amount (₹)</label><input id="t-amount" name="amount" type="number" min="0.01" step="0.01" required placeholder="0.00" /></div>
            <div class="field"><label for="t-when">Date and time</label><input id="t-when" name="occurred_at" type="datetime-local" value="${dateTimeLocalValue(new Date())}" required /></div>
            <div class="field"><label for="t-from">Move from</label><select id="t-from" name="from_method"><option value="cash">Cash</option><option value="upi">UPI</option></select></div>
            <div class="field"><label for="t-to">Move to</label><input id="t-to" value="UPI" readonly /></div>
            <div class="field span-2"><label for="t-reference">Reference <span class="muted">(optional)</span></label><input id="t-reference" name="reference" maxlength="120" placeholder="e.g. Cash deposited to UPI wallet" /></div>
            <div class="field span-2"><label for="t-notes">Note <span class="muted">(optional)</span></label><input id="t-notes" name="notes" /></div>
          </div>
          <div class="inline-note">${icon("info")}Recorded once. The source balance decreases, the destination balance increases, and neither money-in nor money-out totals change.</div>
          <div id="transfer-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="transfer-form" id="save-transfer">${icon("save")} ${isOffline() ? "Save locally" : "Record transfer"}</button>`,
      });
      const form = modal.root.querySelector("#transfer-form");
      const errorBox = modal.root.querySelector("#transfer-error");
      const fromSelect = modal.root.querySelector("#t-from");
      const toInput = modal.root.querySelector("#t-to");
      const syncDestination = () => {
        toInput.value = fromSelect.value === "cash" ? "UPI" : "Cash";
      };
      fromSelect.addEventListener("change", syncDestination);

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const data = new FormData(form);
        const amount = Number(data.get("amount"));
        if (!Number.isFinite(amount) || amount <= 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Enter an amount greater than zero.</div>`;
          return;
        }
        const from = fromSelect.value;
        const to = from === "cash" ? "UPI" : "Cash";
        const fromLabel = from === "cash" ? "Cash" : "UPI";
        const when = data.get("occurred_at");
        const payload = {
          direction: "out",
          amount: amount.toFixed(2),
          person: null,
          category: "cash_upi_transfer",
          method: from,
          occurred_at: when ? new Date(when).toISOString() : new Date().toISOString(),
          description: `Transfer from ${fromLabel} to ${to}`,
          reference: String(data.get("reference") || "").trim() || null,
          notes: String(data.get("notes") || "").trim() || null,
        };
        const button = modal.root.querySelector("#save-transfer");
        setBusy(button, true, "Saving…");
        try {
          if (isOffline()) {
            await queueOperation({
              kind: "money",
              payload,
              label: `${payload.description} · ${money(amount)}`,
              amount,
            });
            toast("Transfer saved on this device. It will synchronize automatically.", { title: "Saved locally", type: "warn" });
          } else {
            const key = uid();
            await api.money.create({ ...payload, idempotency_key: key }, key);
            toast("Transfer recorded. Both balances were updated and in/out totals were not changed.", { title: "Saved" });
          }
          closeModal();
          offset = 0;
          await Promise.all([renderPending(), load(), loadMonthly()]);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openHandoverModal() {
      const modal = openModal({
        title: "Owner handover",
        subtitle: "Record cash or UPI handed to the owner. This is a custody transfer, not an expense.",
        body: `<form id="handover-form" autocomplete="off">
          <div class="form-grid">
            <div class="field"><label for="h-person">Handed to</label><input id="h-person" name="person" maxlength="120" value="Owner" required /></div>
            <div class="field"><label for="h-amount">Amount (₹)</label><input id="h-amount" name="amount" type="number" min="0.01" step="0.01" required placeholder="0.00" /></div>
            <div class="field"><label for="h-when">Date and time</label><input id="h-when" name="occurred_at" type="datetime-local" value="${dateTimeLocalValue(new Date())}" required /></div>
            <div class="field"><label for="h-method">Handed as</label><select id="h-method" name="method">${methodOptions("cash")}</select></div>
            <div class="field span-2"><label for="h-reason">Reason / note</label><input id="h-reason" name="description" maxlength="200" value="Cash handover to owner" required /></div>
          </div>
          <div class="inline-note">${icon("info")}Cash handovers reduce the physical cash balance. UPI handovers stay separate from cash. Neither is counted as an ordinary expense.</div>
          <div id="handover-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="handover-form" id="save-handover">${icon("save")} ${isOffline() ? "Save locally" : "Record handover"}</button>`,
      });
      const form = modal.root.querySelector("#handover-form");
      const errorBox = modal.root.querySelector("#handover-error");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const data = new FormData(form);
        const amount = Number(data.get("amount"));
        if (!Number.isFinite(amount) || amount <= 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Enter an amount greater than zero.</div>`;
          return;
        }
        const when = data.get("occurred_at");
        const payload = {
          direction: "out",
          amount: amount.toFixed(2),
          person: String(data.get("person") || "").trim() || "Owner",
          category: "cash_handover",
          method: data.get("method"),
          occurred_at: when ? new Date(when).toISOString() : new Date().toISOString(),
          description: String(data.get("description") || "").trim() || "Cash handover to owner",
          reference: null,
          notes: null,
        };
        const button = modal.root.querySelector("#save-handover");
        setBusy(button, true, "Saving…");
        try {
          if (isOffline()) {
            await queueOperation({
              kind: "money",
              payload,
              label: `${payload.description} · ${money(amount)}`,
              amount,
            });
            toast("Handover saved on this device. It will synchronize automatically.", { title: "Saved locally", type: "warn" });
          } else {
            const key = uid();
            await api.money.create({ ...payload, idempotency_key: key }, key);
            toast("Owner handover recorded.", { title: "Saved" });
          }
          closeModal();
          offset = 0;
          await Promise.all([renderPending(), load(), loadMonthly()]);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    async function voidTransaction(item) {
      const proceed = await confirmDialog({
        title: "Void this money entry?",
        message: `<strong>${escapeHtml(item.description)}</strong> for ${money(item.amount)} will be excluded from balances and totals but kept in history with a reason. This cannot be undone.`,
        confirmLabel: "Void entry",
        danger: true,
      });
      if (!proceed) return;
      const reason = await promptDialog({
        title: "Reason for voiding",
        label: "Reason",
        placeholder: "e.g. Duplicate entry",
        confirmLabel: "Void entry",
        danger: true,
      });
      if (!reason) return;
      try {
        await api.money.void(item.record_id, { version: item.version, reason });
        toast("Money entry voided. It remains visible in history.", { title: "Voided" });
        await load();
      } catch (error) {
        toast(error.message, { type: "error", title: "Could not void entry" });
      }
    }

    syncQuery();
    await Promise.all([renderPending(), load(), loadMonthly()]);
    if (ctx.query.get("new") === "1") {
      history.replaceState(null, "", "/money-history");
      openTransactionModal(null);
    }
    return () => {
      disposed = true;
    };
  },
};
