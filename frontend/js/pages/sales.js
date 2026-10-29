import { api } from "../api.js";
import { getState, pendingOperations, productById } from "../store.js";
import {
  badge,
  debounce,
  emptyState,
  escapeHtml,
  formatDate,
  formatDateTime,
  formatTime,
  hydrateIcons,
  icon,
  money,
  num,
  paginationHtml,
  statusLabel,
} from "../ui.js";

const PAGE_SIZE = 50;

const SOURCE_OPTIONS = [
  ["", "All sources"],
  ["manual", "Manual"],
  ["website", "Website"],
  ["imported", "Imported"],
];

const PAYMENT_OPTIONS = [
  ["", "All payments"],
  ["paid", "Paid"],
  ["partial", "Partially paid"],
  ["unpaid", "Unpaid"],
  ["voided", "Voided"],
];

const DELIVERY_OPTIONS = [
  ["", "All deliveries"],
  ["none", "No delivery"],
  ["pending", "Pending"],
  ["out_for_delivery", "Out for delivery"],
  ["delivered", "Delivered"],
  ["cancelled", "Cancelled"],
];

function optionsHtml(options, selected) {
  return options
    .map(([value, label]) => `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(label)}</option>`)
    .join("");
}

function pendingSaleTotal(operation) {
  const payload = operation.payload || {};
  const subtotal = (payload.items || []).reduce((sum, item) => {
    const product = productById(item.product_id);
    return sum + Number(product?.selling_price || 0) * Number(item.quantity || 0);
  }, 0);
  return Math.max(0, subtotal - Number(payload.discount || 0));
}

function pendingRows(operations) {
  if (!operations.length) return "";
  return `<section class="card">
    <div class="card-header">
      <div><h2>Saved on this device</h2><p>These sales are waiting to synchronize. They will receive permanent IDs once the server accepts them.</p></div>
      <span class="badge badge-pending">${operations.length} pending</span>
    </div>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>Saved</th><th>Reference</th><th>Source</th><th class="num">Total</th><th>Status</th></tr></thead>
      <tbody>${operations
        .map((operation) => {
          const payload = operation.payload || {};
          const total = pendingSaleTotal(operation);
          const paid = Number(payload.initial_payment?.amount || 0);
          return `<tr>
            <td class="nowrap">${formatDateTime(operation.createdAt)}</td>
            <td><div class="cell-title"><span class="row-link">${escapeHtml(payload.customer_name || "Walk-in sale")}</span><span>${num((payload.items || []).length)} item${(payload.items || []).length === 1 ? "" : "s"}${payload.external_order_id ? ` · order ${escapeHtml(payload.external_order_id)}` : ""}</span></div></td>
            <td>${badge(payload.source || "manual")}</td>
            <td class="num strong-cell">${money(total)}</td>
            <td>${paid >= total && total > 0 ? badge("paid") : paid > 0 ? badge("partial") : badge("unpaid")} ${operation.status === "failed" ? `<span class="badge badge-failed" title="${escapeHtml(operation.lastError || "")}">Sync failed</span>` : `<span class="badge badge-local">Pending sync</span>`}</td>
          </tr>`;
        })
        .join("")}</tbody>
    </table></div>
    <div class="card-footer row-between">
      <span class="small muted">${operations.some((item) => item.status === "failed") ? "Some records failed to sync. Review them in Settings → Offline queue." : "Use Sync now when the connection is available."}</span>
      <a class="btn btn-secondary btn-sm" href="/settings">Open offline queue ${icon("arrowRight")}</a>
    </div>
  </section>`;
}

function summaryStrip(aggregates) {
  return `<div class="metric-strip">
    <div><span>Net sales in view</span><strong>${money(aggregates.revenue)}</strong></div>
    <div><span>Received</span><strong>${money(aggregates.collected)}</strong></div>
    <div><span>Outstanding</span><strong>${money(aggregates.outstanding)}</strong></div>
  </div>`;
}

function saleRow(sale) {
  const reference = sale.customer_name || sale.customer_ref || "Walk-in customer";
  const external = sale.external_order_id
    ? `<span class="tiny muted block">Website order ${escapeHtml(sale.external_order_id)}</span>`
    : "";
  const products = sale.items_summary || `${num(sale.item_count)} item${Number(sale.item_count) === 1 ? "" : "s"}`;
  const methods = sale.payment_methods_summary
    ? `<span class="tiny muted block cell-methods">${escapeHtml(sale.payment_methods_summary)}</span>`
    : "";
  const delivery = sale.delivery_status === "none" ? `<span class="tiny muted">None</span>` : badge(sale.delivery_status);
  return `<tr>
    <td class="cell-date nowrap">${formatDate(sale.occurred_at)}<span class="tiny muted block">${formatTime(sale.occurred_at)}</span></td>
    <td class="cell-ref">
      <div class="cell-title">
        <a class="row-link" href="/sales/${sale.id}">#${sale.id} · ${escapeHtml(reference)}</a>
        <span>${num(sale.item_count)} item${Number(sale.item_count) === 1 ? "" : "s"}${sale.customer_ref && sale.customer_ref !== reference ? ` · ${escapeHtml(sale.customer_ref)}` : ""}</span>
        <span class="mobile-sale-meta tiny muted">${escapeHtml(products)}</span>
        <span class="mobile-sale-meta tiny muted">${escapeHtml(sale.payment_methods_summary || "No payments recorded")} · ${escapeHtml(statusLabel(sale.source))} · Synced</span>
        ${external}
      </div>
    </td>
    <td class="cell-products small">${escapeHtml(products)}</td>
    <td class="cell-total num">
      <strong>${money(sale.total)}</strong>
      <span class="tiny muted block">Received ${money(sale.net_paid)}</span>
      <span class="tiny muted block">${Number(sale.outstanding) > 0 ? `Due ${money(sale.outstanding)}` : "Settled"}</span>
    </td>
    <td class="cell-payment">${badge(sale.payment_status)}${methods}</td>
    <td class="cell-delivery">${delivery}</td>
    <td class="cell-source">${badge(sale.source)}<span class="badge badge-synced block-badge">Synced</span></td>
    <td class="cell-actions text-right"><a class="btn btn-ghost btn-xs" href="/sales/${sale.id}">Open ${icon("chevronRight")}</a></td>
  </tr>`;
}

function saleTable(items) {
  return `<div class="table-wrap"><table class="data sales-table">
    <thead><tr>
      <th>Date</th><th>Sale</th><th>Products</th><th class="num">Amount</th><th>Payment</th><th>Delivery</th><th>Source</th><th></th>
    </tr></thead>
    <tbody>${items.map(saleRow).join("")}</tbody>
  </table></div>`;
}

export default {
  title: "Sales History",
  subtitle: "Every sale with its products, payments, delivery and sync status.",
  async render(view, ctx) {
    const state = getState();
    const filters = {
      search: ctx.query.get("q") || "",
      date_from: ctx.query.get("date_from") || "",
      date_to: ctx.query.get("date_to") || "",
      source: ctx.query.get("source") || "",
      payment_status: ctx.query.get("payment_status") || "",
      delivery_status: ctx.query.get("delivery_status") || "",
      product_id: ctx.query.get("product_id") || "",
      status: ctx.query.get("status") || "",
    };
    let offset = Number(ctx.query.get("offset") || 0) || 0;
    let disposed = false;
    let latestRequest = 0;

    const products = state.products || [];

    view.innerHTML = `
      <div class="stack">
        <div class="toolbar">
          <button class="btn btn-primary" type="button" data-go-new>${icon("plus")} New sale</button>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-secondary btn-sm" type="button" id="sales-refresh">${icon("refresh")} Refresh</button>
        </div>

        <div class="filter-bar" id="sales-filters">
          <div class="filter-field filter-search wide">
            <label for="sales-search">Search</label>
            <div class="filter-search">${icon("search")}<input id="sales-search" type="search" placeholder="Sale #, customer, product or website order ID" value="${escapeHtml(filters.search)}" /></div>
          </div>
          <div class="filter-field"><label for="sales-from">From</label><input id="sales-from" type="date" value="${escapeHtml(filters.date_from)}" /></div>
          <div class="filter-field"><label for="sales-to">To</label><input id="sales-to" type="date" value="${escapeHtml(filters.date_to)}" /></div>
          <div class="filter-field"><label for="sales-product">Product</label><select id="sales-product"><option value="">All products</option>${products
            .map((product) => `<option value="${product.id}" ${String(product.id) === filters.product_id ? "selected" : ""}>${escapeHtml(product.name)}${product.is_active ? "" : " (inactive)"}</option>`)
            .join("")}</select></div>
          <div class="filter-field"><label for="sales-source">Source</label><select id="sales-source">${optionsHtml(SOURCE_OPTIONS, filters.source)}</select></div>
          <div class="filter-field"><label for="sales-payment">Payment</label><select id="sales-payment">${optionsHtml(PAYMENT_OPTIONS, filters.payment_status)}</select></div>
          <div class="filter-field"><label for="sales-delivery">Delivery</label><select id="sales-delivery">${optionsHtml(DELIVERY_OPTIONS, filters.delivery_status)}</select></div>
          <div class="filter-field"><label>&nbsp;</label><button class="btn btn-secondary" type="button" id="sales-clear">${icon("x")} Clear</button></div>
        </div>
        <div id="local-sales"></div>
        <div id="sales-results"><div class="app-loading"><span class="spinner"></span><span>Loading sales…</span></div></div>
      </div>`;

    const results = view.querySelector("#sales-results");
    const localSlot = view.querySelector("#local-sales");

    async function renderLocalSales() {
      try {
        const operations = (await pendingOperations()).filter((operation) => operation.kind === "sale");
        if (disposed) return;
        const search = filters.search.trim().toLowerCase();
        const matching = operations.filter((operation) => {
          if (!search) return true;
          const payload = operation.payload || {};
          return `${payload.customer_name || ""} ${payload.external_order_id || ""} ${payload.notes || ""}`.toLowerCase().includes(search);
        });
        localSlot.innerHTML = pendingRows(matching);
        hydrateIcons(localSlot);
      } catch {
        localSlot.innerHTML = "";
      }
    }

    function activeParams() {
      return {
        search: filters.search || undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        source: filters.source || undefined,
        payment_status: filters.payment_status || undefined,
        delivery_status: filters.delivery_status || undefined,
        product_id: filters.product_id || undefined,
        status: filters.status || undefined,
        limit: PAGE_SIZE,
        offset,
      };
    }

    async function load() {
      const requestId = ++latestRequest;
      results.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading sales…</span></div>`;
      try {
        const data = await api.sales.list(activeParams());
        if (disposed || requestId !== latestRequest) return;
        const items = data.items || [];
        const body = items.length
          ? `${summaryStrip(data.aggregates || {})}
             <section class="card">
               ${saleTable(items)}
               <div class="card-footer">${paginationHtml({ total: data.total, limit: data.limit, offset: data.offset, idPrefix: "sales-page" })}</div>
             </section>`
          : `<section class="card">${emptyState({
              iconName: "receipt",
              title: "No sales match these filters",
              text: "Adjust the search or date range, or record a new sale. Sales recorded offline appear above until they sync.",
              action: `<button class="btn btn-primary btn-sm" type="button" data-go-new>${icon("plus")} New sale</button>`,
            })}</section>`;
        results.innerHTML = body;
        hydrateIcons(results);

        results.querySelectorAll("[data-go-new]").forEach((button) =>
          button.addEventListener("click", () => {
            ctx.navigate("/new-sale");
          })
        );

        const prev = results.querySelector("[data-sales-page-prev]");
        const next = results.querySelector("[data-sales-page-next]");
        prev?.addEventListener("click", () => {
          offset = Math.max(0, offset - PAGE_SIZE);
          load();
        });
        next?.addEventListener("click", () => {
          offset += PAGE_SIZE;
          load();
        });
      } catch (error) {
        if (disposed || requestId !== latestRequest) return;
        results.innerHTML = `<section class="card"><div class="empty-state">
          <span class="empty-icon">${icon("cloudOff")}</span>
          <strong>Sales history is unavailable</strong>
          <p>${escapeHtml(error.message)}</p>
          <p class="small">You can still record sales from the New Sale screen. Locally saved sales are listed above.</p>
          <div class="row"><button class="btn btn-secondary" type="button" id="sales-retry">${icon("refresh")} Try again</button><button class="btn btn-primary" type="button" data-go-new>${icon("cart")} New sale</button></div>
        </div></section>`;
        hydrateIcons(results);
        results.querySelector("#sales-retry")?.addEventListener("click", load);
        results.querySelector("[data-go-new]")?.addEventListener("click", () => {
          ctx.navigate("/new-sale");
        });
      }
    }

    function readFilters() {
      filters.search = view.querySelector("#sales-search").value;
      filters.date_from = view.querySelector("#sales-from").value;
      filters.date_to = view.querySelector("#sales-to").value;
      filters.source = view.querySelector("#sales-source").value;
      filters.payment_status = view.querySelector("#sales-payment").value;
      filters.delivery_status = view.querySelector("#sales-delivery").value;
      filters.product_id = view.querySelector("#sales-product").value;
      if (filters.date_from && filters.date_to && filters.date_from > filters.date_to) {
        [filters.date_from, filters.date_to] = [filters.date_to, filters.date_from];
        view.querySelector("#sales-from").value = filters.date_from;
        view.querySelector("#sales-to").value = filters.date_to;
      }
      offset = 0;
      const params = new URLSearchParams();
      if (filters.search) params.set("q", filters.search);
      if (filters.date_from) params.set("date_from", filters.date_from);
      if (filters.date_to) params.set("date_to", filters.date_to);
      if (filters.source) params.set("source", filters.source);
      if (filters.payment_status) params.set("payment_status", filters.payment_status);
      if (filters.delivery_status) params.set("delivery_status", filters.delivery_status);
      if (filters.product_id) params.set("product_id", filters.product_id);
      const query = params.toString();
      history.replaceState(null, "", `/sales${query ? `?${query}` : ""}`);
      renderLocalSales();
      load();
    }

    const debouncedSearch = debounce(readFilters, 320);

    view.querySelector("#sales-search")?.addEventListener("input", debouncedSearch);
    ["#sales-from", "#sales-to", "#sales-source", "#sales-payment", "#sales-delivery", "#sales-product"].forEach((selector) => {
      view.querySelector(selector)?.addEventListener("change", readFilters);
    });
    view.querySelector("#sales-clear")?.addEventListener("click", () => {
      view.querySelector("#sales-search").value = "";
      view.querySelector("#sales-from").value = "";
      view.querySelector("#sales-to").value = "";
      view.querySelector("#sales-source").value = "";
      view.querySelector("#sales-payment").value = "";
      view.querySelector("#sales-delivery").value = "";
      view.querySelector("#sales-product").value = "";
      filters.status = "";
      readFilters();
    });
    view.querySelector("#sales-refresh")?.addEventListener("click", () => {
      renderLocalSales();
      load();
    });
    view.querySelectorAll("[data-go-new]").forEach((button) =>
      button.addEventListener("click", () => {
        ctx.navigate("/new-sale");
      })
    );

    await Promise.all([renderLocalSales(), load()]);
    return () => {
      disposed = true;
    };
  },
};
