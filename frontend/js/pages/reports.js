import { api } from "../api.js";
import {
  dayParam,
  escapeHtml,
  formatDate,
  hydrateIcons,
  icon,
  money,
  num,
  startOfMonthParam,
  statusLabel,
} from "../ui.js";

const RANGES = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "month", label: "This month" },
  { key: "custom", label: "Custom" },
];

const EXPORT_TYPES = [
  ["sales", "Sales"],
  ["money", "Money history"],
  ["expenses", "Expenses"],
  ["payments", "Sale payments"],
  ["inventory", "Inventory"],
  ["movements", "Stock movements"],
  ["receivables", "Pending payments"],
  ["reconciliation", "Website verification"],
  ["monthly", "Monthly summaries"],
  ["daily", "Daily summary"],
];

function chart(daily) {
  if (!daily.length) return `<div class="empty-state"><span class="empty-icon">${icon("chart")}</span><strong>No daily data</strong><p>No sales were recorded in this range.</p></div>`;
  const peak = Math.max(...daily.map((row) => Math.max(0, Number(row.net_sales))), 0);
  const max = Math.max(peak, 1);
  const step = Math.max(1, Math.ceil(daily.length / 12));
  return `<div class="bar-chart" role="img" aria-label="Daily net sales chart">${daily
    .map((row, index) => {
      const value = Number(row.net_sales);
      const height = Math.max(2, Math.min(100, (Math.max(0, value) / max) * 100));
      const showLabel = daily.length <= 14 || index % step === 0;
      const shortDate = new Date(`${row.date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
      return `<div class="bar-col" title="${escapeHtml(formatDate(row.date))} · net sales ${money(row.net_sales)} · ${num(row.sales_count)} sale(s)">
        <div class="bar-track"><div class="bar-fill" style="height:${height}%"></div></div>
        <span class="bar-label">${showLabel ? escapeHtml(shortDate) : "&nbsp;"}</span>
      </div>`;
    })
    .join("")}</div>
    <div class="chart-legend" style="margin-top:10px"><span><span class="legend-dot" style="background:var(--accent)"></span> Net sales</span><span>Peak ${money(peak)}</span></div>`;
}

function topProductRows(rows) {
  if (!rows.length) return `<div class="card-body"><div class="empty-state"><span class="empty-icon">${icon("package")}</span><strong>No product sales</strong><p>Best-selling products appear after sales are recorded in this range.</p></div></div>`;
  const sorted = [...rows].sort((a, b) => Number(b.quantity) - Number(a.quantity)).slice(0, 12);
  return `<div class="table-wrap"><table class="data compact">
    <thead><tr><th>Product</th><th class="num">Quantity sold</th><th class="num">Net revenue</th></tr></thead>
    <tbody>${sorted
      .map(
        (product) => `<tr>
          <td>${escapeHtml(product.name)}</td>
          <td class="num strong-cell">${num(product.quantity)}</td>
          <td class="num">${money(product.revenue)}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function miniBars(rows, tone = "var(--accent)") {
  if (!rows.length) return `<p class="muted small">No data in this range.</p>`;
  const max = Math.max(...rows.map((row) => Math.abs(Number(row.value || 0))), 1);
  return `<div class="stack" style="gap:12px">${rows
    .map(
      (row) => `<div>
        <div class="row-between small"><span>${escapeHtml(row.label)}${row.meta ? `<span class="muted"> · ${escapeHtml(row.meta)}</span>` : ""}</span><span class="strong">${row.display}</span></div>
        <div class="stock-bar" style="margin-top:5px"><span style="width:${Math.max(2, (Math.abs(Number(row.value || 0)) / max) * 100)}%;background:${row.tone || tone}"></span></div>
      </div>`
    )
    .join("")}</div>`;
}

function dailyTable(daily) {
  if (!daily.length) return `<div class="card-body"><p class="muted">No daily records.</p></div>`;
  return `<div class="table-wrap" style="max-height:420px;overflow-y:auto"><table class="data compact">
    <thead><tr><th>Date</th><th class="num">Sales</th><th class="num">Gross</th><th class="num">Returns</th><th class="num">Net sales</th><th class="num">Collected</th><th class="num">Ordinary exp.</th><th class="num">Stock purchases</th><th class="num">Money in</th><th class="num">Money out</th></tr></thead>
    <tbody>${[...daily]
      .reverse()
      .map(
        (row) => `<tr>
          <td class="nowrap">${formatDate(row.date)}</td>
          <td class="num">${num(row.sales_count)}</td>
          <td class="num">${money(row.gross_sales)}</td>
          <td class="num">${money(row.returns_value)}</td>
          <td class="num strong-cell">${money(row.net_sales)}</td>
          <td class="num positive">${money(row.collected)}</td>
          <td class="num">${money(row.ordinary_expenses)}</td>
          <td class="num">${money(row.stock_purchases)}</td>
          <td class="num positive">${money(row.money_in)}</td>
          <td class="num negative">${money(row.money_out)}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function monthlyTable(months) {
  if (!months.length) return `<div class="empty-state" style="padding:30px 16px"><span class="empty-icon">${icon("chart")}</span><strong>No monthly data</strong></div>`;
  return `<div class="table-wrap"><table class="data compact">
    <thead><tr><th>Month</th><th class="num">Sales</th><th class="num">Net sales</th><th class="num">Collected</th><th class="num">Refunds</th><th class="num">Ordinary exp.</th><th class="num">Stock purchases</th><th class="num">Money in</th><th class="num">Money out</th><th class="num">Outstanding</th></tr></thead>
    <tbody>${months
      .map(
        (row) => `<tr>
          <td>${escapeHtml(row.label)}</td>
          <td class="num">${num(row.sales_count)}</td>
          <td class="num strong-cell">${money(row.net_sales)}</td>
          <td class="num positive">${money(row.collected)}</td>
          <td class="num">${money(row.refunds)}</td>
          <td class="num">${money(row.ordinary_expenses)}</td>
          <td class="num">${money(row.stock_purchases)}</td>
          <td class="num positive">${money(row.money_in)}</td>
          <td class="num negative">${money(row.money_out)}</td>
          <td class="num">${money(row.outstanding)}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function stockSnapshot(inventory) {
  if (!inventory) return `<p class="muted small">Inventory snapshot unavailable.</p>`;
  const low = (inventory.low_stock_products || []).slice(0, 8);
  return `<div class="metric-strip">
      <div><span>Active products</span><strong>${num(inventory.active_product_count)}</strong></div>
      <div><span>Units in stock</span><strong>${num(inventory.total_units)}</strong></div>
      <div><span>Low stock</span><strong class="${Number(inventory.low_stock_count) > 0 ? "negative" : ""}">${num(inventory.low_stock_count)}</strong></div>
      <div><span>Out of stock</span><strong class="${Number(inventory.out_of_stock_count) > 0 ? "negative" : ""}">${num(inventory.out_of_stock_count)}</strong></div>
    </div>
    ${low.length
      ? `<div class="table-wrap" style="margin-top:12px"><table class="data compact"><thead><tr><th>Product</th><th>Status</th><th class="num">Units</th><th class="num">Threshold</th></tr></thead><tbody>${low
          .map(
            (product) => `<tr>
              <td>${escapeHtml(product.name)}</td>
              <td><span class="badge ${Number(product.stock_quantity) <= 0 ? "badge-out" : "badge-low"}">${Number(product.stock_quantity) <= 0 ? "Out of stock" : "Low stock"}</span></td>
              <td class="num">${num(product.stock_quantity)}</td>
              <td class="num">${num(product.low_stock_threshold)}</td>
            </tr>`
          )
          .join("")}</tbody></table></div>`
      : `<p class="muted small" style="margin-top:10px">All active products are above their low-stock thresholds.</p>`}`;
}

function summaryView(data, inventory) {
  const methods = data.payment_methods || [];
  const categories = data.expense_categories || [];
  const otherMoneyIn = Number(data.money_in) - Number(data.collected);
  return `
    <div class="stack">
      <div class="section-heading">
        <div><h2>Report</h2><p>${formatDate(data.date_from)} – ${formatDate(data.date_to)} · ${num(data.sales_count)} recorded sale${Number(data.sales_count) === 1 ? "" : "s"}.</p></div>
      </div>

      <div class="report-hero">
        <div><span class="label">Net sales</span><div class="value">${money(data.net_sales)}</div><div class="sub">${money(data.gross_sales)} gross · ${money(data.returns_value)} returns</div></div>
        <div><span class="label">Money received</span><div class="value">${money(data.money_in)}</div><div class="sub">${money(data.collected)} sale payments · ${money(otherMoneyIn)} other money in</div></div>
        <div><span class="label">Ordinary expenses</span><div class="value">${money(data.ordinary_expenses)}</div><div class="sub">Stock purchases ${money(data.stock_purchases)} shown separately</div></div>
      </div>

      <div class="metric-strip">
        <div><span>Money given (out)</span><strong>${money(data.money_out)}</strong></div>
        <div><span>Refunds</span><strong>${money(data.refunds)}</strong></div>
        <div><span>Pending customer payments</span><strong>${money(data.outstanding)}</strong></div>
        <div><span>Cash available</span><strong>${money(data.cash_balance)}</strong></div>
        <div><span>UPI available</span><strong>${money(data.upi_balance)}</strong></div>
        <div><span>Average sale</span><strong>${money(data.average_sale)}</strong></div>
      </div>

      <section class="card">
        <div class="card-header"><div><h2>Daily net sales</h2><p>Sales after returns. Hover a bar for the day's figures.</p></div></div>
        <div class="card-body">${chart(data.daily || [])}</div>
      </section>

      <div class="grid-main-side">
        <section class="card">
          <div class="card-header"><div><h2>Best-selling products</h2><p>Ranked by quantity sold after returns.</p></div></div>
          ${topProductRows(data.top_products || [])}
        </section>

        <div class="stack">
          <section class="card">
            <div class="card-header"><div><h2>Cash and UPI movement</h2><p>Physical cash and UPI are tracked separately.</p></div></div>
            <div class="card-body stack" style="gap:10px">
              <div class="row-between small"><span>Cash in</span><strong class="positive">${money(data.cash_in)}</strong></div>
              <div class="row-between small"><span>Cash out</span><strong class="negative">${money(data.cash_out)}</strong></div>
              <div class="row-between small"><span>UPI in</span><strong class="positive">${money(data.upi_in)}</strong></div>
              <div class="row-between small"><span>UPI out</span><strong class="negative">${money(data.upi_out)}</strong></div>
              ${data.balance_complete ? "" : `<div class="inline-note warn" style="margin:0">${icon("alert")}Opening balances are not set; available balances may be incomplete.</div>`}
            </div>
          </section>
          <section class="card">
            <div class="card-header"><div><h2>Payment methods</h2><p>Net movement by method for the range.</p></div></div>
            <div class="card-body">${miniBars(
              methods.map((row) => ({
                label: statusLabel(row.method),
                meta: `${num(row.count)} payments`,
                value: row.net,
                display: money(row.net),
              }))
            )}</div>
          </section>
          <section class="card">
            <div class="card-header"><div><h2>Expense categories</h2><p>Ordinary and stock spending.</p></div></div>
            <div class="card-body">${miniBars(
              categories.map((row) => ({
                label: row.label || statusLabel(row.category),
                meta: `${num(row.count)} record${Number(row.count) === 1 ? "" : "s"}`,
                value: row.amount,
                display: money(row.amount),
                tone: "var(--warn)",
              })),
              "var(--warn)"
            )}</div>
          </section>
        </div>
      </div>

      <section class="card">
        <div class="card-header"><div><h2>Daily breakdown</h2><p>Money and sales figures for every day in the range.</p></div></div>
        ${dailyTable(data.daily || [])}
      </section>

      <section class="card">
        <div class="card-header"><div><h2>Current stock</h2><p>Products that are in stock, low stock or out of stock.</p></div><a class="btn btn-ghost btn-sm" href="/inventory">Inventory ${icon("arrowRight")}</a></div>
        <div class="card-body">${stockSnapshot(inventory)}</div>
      </section>

      <div class="inline-note">${icon("info")}Money in is not automatically income and money out is not automatically an expense. These reports show recorded movements. Outstanding balances are not counted as money received.</div>
    </div>`;
}

export default {
  title: "Reports",
  subtitle: "Sales, money movement, expenses and stock without accounting jargon.",
  async render(view, ctx) {
    let range = ctx.query.get("range") || "month";
    let dateFrom = ctx.query.get("date_from") || "";
    let dateTo = ctx.query.get("date_to") || "";
    if (range === "custom") {
      dateFrom = dateFrom || startOfMonthParam();
      dateTo = dateTo || dayParam();
    }
    let currentSummary = null;
    let disposed = false;
    let latestRequest = 0;

    view.innerHTML = `
      <div class="stack">
        <div class="toolbar">
          <div class="segmented" id="report-ranges">
            ${RANGES.map((item) => `<button type="button" data-range="${item.key}" class="${range === item.key ? "active" : ""}">${item.label}</button>`).join("")}
          </div>
          <div class="row" id="report-custom" ${range === "custom" ? "" : "hidden"}>
            <input type="date" id="report-from" value="${escapeHtml(dateFrom)}" aria-label="From date" style="width:150px" />
            <span class="muted small">to</span>
            <input type="date" id="report-to" value="${escapeHtml(dateTo)}" aria-label="To date" style="width:150px" />
            <button class="btn btn-secondary btn-sm" type="button" id="apply-report-range">Apply</button>
          </div>
          <div class="toolbar-spacer"></div>
          <select id="export-type" aria-label="Export type">${EXPORT_TYPES.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select>
          <button class="btn btn-secondary btn-sm" type="button" id="export-report">${icon("download")} Export CSV</button>
          <a class="btn btn-ghost btn-sm" href="/dashboard">${icon("dashboard")} Dashboard</a>
        </div>
        <div id="report-body"><div class="app-loading"><span class="spinner"></span><span>Calculating reports…</span></div></div>
        <section class="card">
          <div class="card-header">
            <div><h2>Monthly performance</h2><p>Calendar months for the selected year. The current month is included up to today.</p></div>
            <div class="row"><input type="number" id="report-year" min="2000" max="2100" value="${new Date().getFullYear()}" style="width:100px" aria-label="Report year" /><button class="btn btn-secondary btn-sm" type="button" id="apply-year">Load</button></div>
          </div>
          <div id="monthly-body"><div class="app-loading"><span class="spinner"></span><span>Loading months…</span></div></div>
        </section>
      </div>`;

    const body = view.querySelector("#report-body");
    const monthlyBody = view.querySelector("#monthly-body");

    function params() {
      const data = { range };
      if (range === "custom") {
        data.date_from = dateFrom;
        data.date_to = dateTo;
      }
      return data;
    }

    function syncQuery() {
      const search = new URLSearchParams();
      search.set("range", range);
      if (range === "custom") {
        if (dateFrom) search.set("date_from", dateFrom);
        if (dateTo) search.set("date_to", dateTo);
      }
      history.replaceState(null, "", `/reports?${search.toString()}`);
    }

    async function loadSummary() {
      const requestId = ++latestRequest;
      if (range === "custom" && (!dateFrom || !dateTo)) {
        body.innerHTML = `<div class="alert alert-warn">${icon("info")}<div><strong>Choose a custom range</strong>Select both a start and end date.</div></div>`;
        return;
      }
      body.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Calculating reports…</span></div>`;
      try {
        const [data, inventory] = await Promise.all([
          api.reports.summary(params()),
          api.inventory.summary().catch(() => null),
        ]);
        if (disposed || requestId !== latestRequest) return;
        currentSummary = data;
        body.innerHTML = summaryView(data, inventory);
        hydrateIcons(body);
      } catch (error) {
        if (disposed || requestId !== latestRequest) return;
        body.innerHTML = `<section class="card"><div class="empty-state">
          <span class="empty-icon">${icon("cloudOff")}</span>
          <strong>Report could not be calculated</strong>
          <p>${escapeHtml(error.message)}</p>
          <button class="btn btn-secondary" type="button" id="retry-report">${icon("refresh")} Try again</button>
        </div></section>`;
        body.querySelector("#retry-report")?.addEventListener("click", loadSummary);
      }
    }

    async function loadMonthly() {
      const year = Number(view.querySelector("#report-year").value) || new Date().getFullYear();
      monthlyBody.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading months…</span></div>`;
      try {
        const data = await api.reports.monthly({ year });
        if (disposed) return;
        monthlyBody.innerHTML = monthlyTable(data.months || []);
      } catch (error) {
        if (disposed) return;
        monthlyBody.innerHTML = `<div class="empty-state" style="padding:26px 16px"><span class="empty-icon">${icon("cloudOff")}</span><strong>Monthly report unavailable</strong><p>${escapeHtml(error.message)}</p></div>`;
      }
    }

    view.querySelector("#export-report")?.addEventListener("click", () => {
      const type = view.querySelector("#export-type")?.value || "sales";
      const search = new URLSearchParams({ type });
      if (currentSummary) {
        search.set("date_from", currentSummary.date_from);
        search.set("date_to", currentSummary.date_to);
      }
      window.location.href = `/api/reports/export?${search.toString()}`;
    });

    view.querySelector("#report-ranges").addEventListener("click", (event) => {
      const button = event.target.closest("[data-range]");
      if (!button) return;
      range = button.dataset.range;
      view.querySelectorAll("[data-range]").forEach((item) => item.classList.toggle("active", item === button));
      const custom = view.querySelector("#report-custom");
      custom.hidden = range !== "custom";
      if (range === "custom") {
        dateFrom = view.querySelector("#report-from").value || startOfMonthParam();
        dateTo = view.querySelector("#report-to").value || dayParam();
        view.querySelector("#report-from").value = dateFrom;
        view.querySelector("#report-to").value = dateTo;
      }
      syncQuery();
      loadSummary();
    });

    view.querySelector("#apply-report-range").addEventListener("click", () => {
      dateFrom = view.querySelector("#report-from").value;
      dateTo = view.querySelector("#report-to").value;
      if (dateFrom && dateTo && dateFrom > dateTo) {
        [dateFrom, dateTo] = [dateTo, dateFrom];
        view.querySelector("#report-from").value = dateFrom;
        view.querySelector("#report-to").value = dateTo;
      }
      syncQuery();
      loadSummary();
    });

    view.querySelector("#apply-year").addEventListener("click", loadMonthly);

    syncQuery();
    await Promise.all([loadSummary(), loadMonthly()]);
    return () => {
      disposed = true;
    };
  },
};
