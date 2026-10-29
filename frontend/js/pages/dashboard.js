import { api } from "../api.js";
import { getState } from "../store.js";
import {
  dayParam,
  escapeHtml,
  formatDate,
  formatDateTime,
  formatTime,
  hydrateIcons,
  icon,
  money,
  num,
  relativeTime,
  startOfMonthParam,
  statusLabel,
} from "../ui.js";

const RANGES = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "Last 7 days" },
  { key: "month", label: "This month" },
  { key: "custom", label: "Custom" },
];

const CACHE_KEY = "cartflow_dashboard_cache_v2";

function cacheKey(range, from, to) {
  return `${range}|${from || ""}|${to || ""}`;
}

function readCache(key) {
  try {
    const parsed = JSON.parse(localStorage.getItem(CACHE_KEY) || "{}");
    return parsed[key] || null;
  } catch {
    return null;
  }
}

function writeCache(key, data) {
  try {
    const parsed = JSON.parse(localStorage.getItem(CACHE_KEY) || "{}");
    parsed[key] = { data, savedAt: new Date().toISOString() };
    const keys = Object.keys(parsed);
    if (keys.length > 8) delete parsed[keys[0]];
    localStorage.setItem(CACHE_KEY, JSON.stringify(parsed));
  } catch {
    /* cache is optional */
  }
}

function statCard({ label, value, meta = "", iconName, tone = "", href = "" }) {
  const inner = `
    <div class="stat-top">
      <span class="stat-label">${escapeHtml(label)}</span>
      <span class="stat-icon ${tone}">${icon(iconName)}</span>
    </div>
    <div class="stat-value">${value}</div>
    <div class="stat-meta">${meta}</div>`;
  return href ? `<a class="stat-card" href="${href}">${inner}</a>` : `<div class="stat-card">${inner}</div>`;
}

function activityRows(items) {
  if (!items.length) {
    return `<div class="empty-state" style="padding:30px 20px"><span class="empty-icon">${icon("receipt")}</span><strong>No activity yet</strong><p>Sales, payments, expenses and money entries appear here.</p></div>`;
  }
  return `<div class="table-wrap"><table class="data compact">
    <tbody>${items
      .map((item) => {
        const incoming = item.direction === "in";
        const outgoing = item.direction === "out";
        const amountClass = incoming ? "positive" : outgoing ? "negative" : "";
        const sign = incoming ? "+" : outgoing ? "−" : "";
        return `<tr>
          <td class="nowrap">${formatTime(item.occurred_at)}<span class="tiny muted block">${formatDate(item.occurred_at)}</span></td>
          <td><div class="cell-title">
            <span class="row-link">${escapeHtml(item.title)}</span>
            <span>${escapeHtml(item.description || "")}</span>
          </div></td>
          <td class="num ${amountClass}">${sign}${money(item.amount)}</td>
          <td class="text-right">${item.link ? `<a class="btn btn-ghost btn-xs" href="${escapeHtml(item.link)}">Open ${icon("chevronRight")}</a>` : ""}</td>
        </tr>`;
      })
      .join("")}</tbody>
  </table></div>`;
}

function lowStockRows(products) {
  if (!products.length) {
    return `<div class="empty-state" style="padding:28px 18px"><span class="empty-icon">${icon("checkCircle")}</span><strong>Stock levels look healthy</strong><p>Products at or below their threshold appear here.</p></div>`;
  }
  return `<div class="table-wrap"><table class="data compact">
    <tbody>${products
      .slice(0, 6)
      .map(
        (product) => `<tr>
        <td><div class="cell-title"><span class="row-link">${escapeHtml(product.name)}</span><span>${escapeHtml(product.category || "Uncategorised")}</span></div></td>
        <td class="num"><span class="badge ${Number(product.stock_quantity) <= 0 ? "badge-out" : "badge-low"}">${Number(product.stock_quantity) <= 0 ? "Out of stock" : `${num(product.stock_quantity)} left`}</span></td>
        <td class="text-right"><a class="btn btn-ghost btn-xs" href="/inventory">${icon("arrowRight")}</a></td>
      </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function pendingPaymentRows(sales) {
  if (!sales.length) {
    return `<div class="empty-state" style="padding:28px 18px"><span class="empty-icon">${icon("checkCircle")}</span><strong>No pending customer payments</strong><p>Every recorded sale is fully paid.</p></div>`;
  }
  return `<div class="table-wrap"><table class="data compact">
    <tbody>${sales
      .map(
        (sale) => `<tr>
        <td><div class="cell-title">
          <a class="row-link" href="/sales/${sale.id}">#${sale.id} · ${escapeHtml(sale.customer_name || sale.customer_ref || "Walk-in")}</a>
          <span>${formatDate(sale.occurred_at)} · ${sale.payment_status === "partial" ? "Partially paid" : "Unpaid"}</span>
        </div></td>
        <td class="num strong-cell negative">${money(sale.outstanding)}<span class="tiny muted block">due of ${money(sale.total)}</span></td>
      </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function recentMoneyRows(rows) {
  if (!rows.length) {
    return `<div class="empty-state" style="padding:26px 18px"><span class="empty-icon">${icon("wallet")}</span><strong>No money movement yet</strong><p>Sale payments, expenses, handovers and manual entries appear here.</p></div>`;
  }
  return `<div class="table-wrap"><table class="data compact">
    <thead><tr><th>When</th><th>Money entry</th><th>Method</th><th class="num">Amount</th><th></th></tr></thead>
    <tbody>${rows
      .map((row) => {
        const incoming = row.direction === "in";
        const transfer = row.category === "cash_upi_transfer";
        const transferLabel = row.method === "cash" ? "Cash → UPI" : "UPI → Cash";
        return `<tr>
          <td class="nowrap">${formatDate(row.occurred_at)}<span class="tiny muted block">${formatTime(row.occurred_at)}</span></td>
          <td><div class="cell-title"><span class="row-link">${escapeHtml(row.person || row.category_label)}</span><span>${escapeHtml(row.description)}</span></div></td>
          <td>${escapeHtml(statusLabel(row.method))}</td>
          <td class="num strong-cell ${transfer ? "" : incoming ? "positive" : "negative"}">${transfer ? `<span class="row">${icon("arrowRight")} ${money(row.amount)}</span><span class="tiny muted block">${transferLabel}</span>` : `${incoming ? "+" : "−"}${money(row.amount)}`}</td>
          <td class="text-right"><a class="btn btn-ghost btn-xs" href="${escapeHtml(row.link || "/money-history")}">${icon("chevronRight")}</a></td>
        </tr>`;
      })
      .join("")}</tbody>
  </table></div>`;
}

function dateScopeLabel(range) {
  return range === "today" ? "today" : "in this range";
}

function renderBody(data, meta, range) {
  const state = getState();
  const summary = data.summary;
  const scope = dateScopeLabel(range);
  const pending = Number(state.pendingCount || 0);
  const syncLabel = state.syncing
    ? "Synchronizing…"
    : pending > 0
      ? `${num(pending)} local record${pending === 1 ? "" : "s"} awaiting sync`
      : "All local records synchronized";

  const connectionLabel =
    state.online === false
      ? "Device offline"
      : state.serverReachable === false
        ? "Local mode — server unreachable"
        : "Connected";
  return `
    <div class="stack">
      ${meta.cached ? `<div class="alert alert-warn">${icon("cloudOff")}<div><strong>Showing the last saved snapshot</strong>Saved ${relativeTime(meta.cachedAt)}. The local server is unreachable, but you can still record sales, expenses and money entries locally.</div></div>` : ""}
      <div class="banner">
        ${icon(state.online && state.serverReachable !== false ? "checkCircle" : "cloudOff")}
        <span><strong>${escapeHtml(connectionLabel)}</strong> · ${escapeHtml(syncLabel)}</span>
        <a class="btn btn-secondary btn-sm" href="/settings">${pending > 0 ? "Review offline queue" : "Sync settings"}</a>
      </div>

      <div class="section-heading">
        <div>
          <h2>Business snapshot</h2>
          <p>${formatDate(summary.date_from)} – ${formatDate(summary.date_to)} · sales, money received and expenses ${scope}.</p>
        </div>
        <div class="row-wrap dashboard-quick-actions">
          <a class="btn btn-primary btn-sm" href="/new-sale">${icon("cart")} New Sale</a>
          <a class="btn btn-secondary btn-sm" href="/expenses?new=1">${icon("banknote")} Add Expense</a>
          <a class="btn btn-secondary btn-sm" href="/money-history?new=1">${icon("wallet")} Add Transaction</a>
          <a class="btn btn-secondary btn-sm" href="/inventory?receive=1">${icon("package")} Add Stock</a>
        </div>
      </div>

      <div class="stat-grid cols-4">
        ${statCard({
          label: range === "today" ? "Today's sales" : "Sales (net of returns)",
          value: money(summary.net_sales),
          meta: `${num(summary.sales_count)} sale${Number(summary.sales_count) === 1 ? "" : "s"} · ${money(summary.returns_value)} returns`,
          iconName: "cart",
          tone: "accent",
          href: "/sales",
        })}
        ${statCard({
          label: range === "today" ? "Money received today" : "Money received",
          value: money(data.money_received),
          meta: `${money(data.sale_payments_received)} sale payments · ${money(data.other_money_received)} other money in`,
          iconName: "wallet",
          tone: "success",
          href: "/money-history",
        })}
        ${statCard({
          label: range === "today" ? "Today's expenses" : "Ordinary expenses",
          value: money(data.ordinary_expenses),
          meta: `Stock purchases ${money(summary.stock_purchases)} are tracked separately`,
          iconName: "banknote",
          tone: "warn",
          href: "/expenses",
        })}
        ${statCard({
          label: "Cash available",
          value: money(data.cash_available),
          meta: `UPI ${money(data.upi_available)} kept separately${data.balance_complete ? "" : " · opening balance not set"}`,
          iconName: "banknote",
          tone: Number(data.cash_available) < 0 ? "danger" : "success",
          href: "/money-history",
        })}
      </div>

      ${data.balance_complete ? "" : `<div class="alert alert-warn">${icon("alert")}<div><strong>Cash and UPI balances may be incomplete</strong>Set the opening cash and UPI balances in Settings &amp; Backup so running balances start from a known point.</div></div>`}

      <div class="grid-main-side">
        <div class="stack">
          <section class="card">
            <div class="card-header">
              <div><h2>Recent activity</h2><p>The five latest sales, payments, expenses, returns and money entries.</p></div>
              <a class="btn btn-ghost btn-sm" href="/money-history">Money History ${icon("arrowRight")}</a>
            </div>
            ${activityRows(data.recent_activity || [])}
          </section>

          <section class="card">
            <div class="card-header">
              <div><h2>Recent money in and out</h2><p>Money received, money given and cash/UPI transfers. Sale payments and expenses stay linked to their source.</p></div>
              <a class="btn btn-ghost btn-sm" href="/money-history">View ledger ${icon("arrowRight")}</a>
            </div>
            ${recentMoneyRows(data.recent_money || [])}
          </section>
        </div>

        <div class="stack">
          <section class="card">
            <div class="card-header">
              <div><h2>Pending customer payments</h2><p>Outstanding balances are not counted as money received.</p></div>
              <a class="btn btn-ghost btn-sm" href="/sales?payment_status=unpaid">Sales ${icon("arrowRight")}</a>
            </div>
            ${pendingPaymentRows(data.pending_payments || [])}
          </section>

          <section class="card">
            <div class="card-header">
              <div><h2>Low stock</h2><p>In stock, low stock and out of stock products.</p></div>
              <a class="btn btn-ghost btn-sm" href="/inventory">Inventory ${icon("arrowRight")}</a>
            </div>
            ${lowStockRows(data.low_stock_products || [])}
          </section>
        </div>
      </div>
    </div>`;
}

export default {
  title: "Dashboard",
  subtitle: "Sales, money, expenses and cash at a glance.",
  async render(view, ctx) {
    let range = ctx.query.get("range") || "today";
    let dateFrom = ctx.query.get("date_from") || "";
    let dateTo = ctx.query.get("date_to") || "";
    if (range === "custom") {
      dateFrom = dateFrom || startOfMonthParam();
      dateTo = dateTo || dayParam();
    }
    let disposed = false;
    let latestRequest = 0;

    view.innerHTML = `
      <div class="stack">
        <div class="toolbar">
          <div class="segmented" id="range-controls">
            ${RANGES.map((item) => `<button type="button" data-range="${item.key}" class="${item.key === range ? "active" : ""}">${item.label}</button>`).join("")}
          </div>
          <div class="row" id="custom-range" ${range === "custom" ? "" : "hidden"}>
            <input type="date" id="range-from" value="${escapeHtml(dateFrom)}" style="width:150px" aria-label="From date" />
            <span class="muted small">to</span>
            <input type="date" id="range-to" value="${escapeHtml(dateTo)}" style="width:150px" aria-label="To date" />
            <button class="btn btn-secondary btn-sm" type="button" id="apply-custom-range">Apply</button>
          </div>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-secondary btn-sm" type="button" id="refresh-dashboard">${icon("refresh")} Refresh</button>
        </div>
        <div id="dashboard-body"><div class="app-loading"><span class="spinner"></span><span>Building your snapshot…</span></div></div>
      </div>`;

    const body = view.querySelector("#dashboard-body");

    function syncQuery() {
      const params = new URLSearchParams();
      params.set("range", range);
      if (range === "custom") {
        if (dateFrom) params.set("date_from", dateFrom);
        if (dateTo) params.set("date_to", dateTo);
      }
      history.replaceState(null, "", `/dashboard?${params.toString()}`);
    }

    async function load() {
      const requestId = ++latestRequest;
      const params = { range };
      if (range === "custom") {
        if (!dateFrom || !dateTo) {
          body.innerHTML = `<div class="alert alert-warn">${icon("info")}<div><strong>Choose a custom range</strong>Select a start and end date, then apply.</div></div>`;
          return;
        }
        params.date_from = dateFrom;
        params.date_to = dateTo;
      }
      body.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Building your snapshot…</span></div>`;
      const key = cacheKey(range, params.date_from, params.date_to);
      try {
        const data = await api.reports.dashboard(params);
        if (disposed || requestId !== latestRequest) return;
        writeCache(key, data);
        body.innerHTML = renderBody(data, { cached: false }, range);
        hydrateIcons(body);
      } catch (error) {
        if (disposed || requestId !== latestRequest) return;
        const cached = readCache(key);
        if (cached?.data) {
          body.innerHTML = renderBody(cached.data, { cached: true, cachedAt: cached.savedAt }, range);
          hydrateIcons(body);
        } else {
          body.innerHTML = `<div class="card"><div class="empty-state">
            <span class="empty-icon">${icon("cloudOff")}</span>
            <strong>Dashboard unavailable</strong>
            <p>${escapeHtml(error.message)}</p>
            <p class="small">You can still record sales, expenses and money entries locally.</p>
            <div class="row"><button class="btn btn-secondary" type="button" id="retry-dashboard">${icon("refresh")} Try again</button><a class="btn btn-primary" href="/new-sale">${icon("cart")} New sale</a></div>
          </div></div>`;
          body.querySelector("#retry-dashboard")?.addEventListener("click", load);
        }
      }
    }

    view.querySelector("#range-controls")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-range]");
      if (!button) return;
      range = button.dataset.range;
      view.querySelectorAll("[data-range]").forEach((item) => item.classList.toggle("active", item === button));
      const custom = view.querySelector("#custom-range");
      custom.hidden = range !== "custom";
      if (range === "custom") {
        dateFrom = view.querySelector("#range-from").value || startOfMonthParam();
        dateTo = view.querySelector("#range-to").value || dayParam();
        view.querySelector("#range-from").value = dateFrom;
        view.querySelector("#range-to").value = dateTo;
      }
      syncQuery();
      load();
    });

    view.querySelector("#apply-custom-range")?.addEventListener("click", () => {
      dateFrom = view.querySelector("#range-from").value;
      dateTo = view.querySelector("#range-to").value;
      if (dateFrom && dateTo && dateFrom > dateTo) {
        [dateFrom, dateTo] = [dateTo, dateFrom];
        view.querySelector("#range-from").value = dateFrom;
        view.querySelector("#range-to").value = dateTo;
      }
      syncQuery();
      load();
    });

    view.querySelector("#refresh-dashboard")?.addEventListener("click", load);

    syncQuery();
    await load();
    return () => {
      disposed = true;
    };
  },
};
