import { api, ApiError } from "../api.js";
import { getState, refreshProducts } from "../store.js";
import {
  badge,
  closeModal,
  confirmDialog,
  dateTimeLocalValue,
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
  readFormNumber,
  setBusy,
  statusLabel,
  toast,
  uid,
} from "../ui.js";

const MOVEMENT_TYPES = [
  ["", "All movements"],
  ["opening", "Opening stock"],
  ["receipt", "Received"],
  ["sale", "Sale"],
  ["return", "Return"],
  ["damage", "Damaged"],
  ["correction", "Correction"],
];

const CACHE_KEY = "cartflow_inventory_cache_v1";

function readCache() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CACHE_KEY) || "null");
    return parsed && parsed.summary ? parsed : null;
  } catch {
    return null;
  }
}

function writeCache(data) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ ...data, savedAt: new Date().toISOString() }));
  } catch {
    /* optional */
  }
}

function isOffline() {
  const state = getState();
  return state.online === false || state.serverReachable === false;
}

function stockBar(product) {
  const stock = Number(product.stock_quantity || 0);
  const threshold = Math.max(1, Number(product.low_stock_threshold || 0));
  const target = Math.max(10, threshold * 4);
  const width = stock <= 0 ? 0 : Math.min(100, Math.max(4, (stock / target) * 100));
  const cls = stock <= 0 ? "out" : stock <= threshold ? "low" : "";
  return `<div class="stock-cell">
    <strong class="${stock <= 0 ? "negative" : stock <= threshold ? "warn-text" : ""}">${num(stock)}</strong>
    <div class="stock-bar ${cls}"><span style="width:${width}%"></span></div>
    <span class="tiny muted">Low at ${num(threshold)}</span>
  </div>`;
}

function stockStatus(product) {
  const stock = Number(product.stock_quantity || 0);
  const threshold = Number(product.low_stock_threshold || 0);
  if (stock <= 0) return "out_of_stock";
  if (stock <= threshold) return "low_stock";
  return "in_stock";
}

function summaryCards(summary) {
  return `<div class="stat-grid cols-4">
    <div class="stat-card"><div class="stat-top"><span class="stat-label">Products</span><span class="stat-icon">${icon("package")}</span></div><div class="stat-value">${num(summary.product_count)}</div><div class="stat-meta">${num(summary.active_product_count)} active</div></div>
    <div class="stat-card"><div class="stat-top"><span class="stat-label">Units in stock</span><span class="stat-icon accent">${icon("layers")}</span></div><div class="stat-value">${num(summary.total_units)}</div><div class="stat-meta">Across tracked products</div></div>
    <div class="stat-card"><div class="stat-top"><span class="stat-label">Low stock</span><span class="stat-icon ${Number(summary.low_stock_count) > 0 ? "warn" : "success"}">${icon("alert")}</span></div><div class="stat-value">${num(summary.low_stock_count)}</div><div class="stat-meta">At or below threshold</div></div>
    <div class="stat-card"><div class="stat-top"><span class="stat-label">Out of stock</span><span class="stat-icon ${Number(summary.out_of_stock_count) > 0 ? "warn" : "success"}">${icon("xCircle")}</span></div><div class="stat-value">${num(summary.out_of_stock_count)}</div><div class="stat-meta">Needs restocking</div></div>
  </div>`;
}

function productRow(product) {
  return `<tr>
    <td class="cell-product">
      <div class="product-name-cell">
        <span class="product-avatar">${escapeHtml((product.name || "?").slice(0, 2).toUpperCase())}</span>
        <div class="cell-title">
          <a class="row-link" href="#" data-action="product-history" data-id="${product.id}">${escapeHtml(product.name)}</a>
          <span>${escapeHtml(product.category)}${product.sku ? ` · ${escapeHtml(product.sku)}` : ""}${product.expiry_date ? ` · expires ${formatDate(product.expiry_date)}` : ""}</span>
        </div>
      </div>
    </td>
    <td class="cell-stock">${stockBar(product)}</td>
    <td class="cell-cost num">${money(product.purchase_cost)}</td>
    <td class="cell-price num">${money(product.selling_price)}</td>
    <td class="cell-status">${badge(stockStatus(product))} ${product.is_active ? `<span class="badge badge-active">Active</span>` : `<span class="badge no-dot">Inactive</span>`}</td>
    <td class="cell-actions text-right">
      <div class="row">
        <button class="btn btn-ghost btn-xs" type="button" data-action="product-history" data-id="${product.id}">History</button>
        <button class="btn btn-secondary btn-xs" type="button" data-action="edit-product" data-id="${product.id}">${icon("edit")} Edit</button>
      </div>
    </td>
  </tr>`;
}

function movementRow(movement) {
  const qty = Number(movement.quantity_change);
  const link = movement.sale_id
    ? `<a class="row-link" href="/sales/${movement.sale_id}">Sale #${movement.sale_id}</a>`
    : movement.stock_receipt_id
      ? `Receipt #${movement.stock_receipt_id}`
      : "";
  return `<tr>
    <td class="nowrap">${formatDateTime(movement.occurred_at)}</td>
    <td><a class="row-link" href="#" data-action="product-history" data-id="${movement.product_id}">${escapeHtml(movement.product_name || `Product #${movement.product_id}`)}</a></td>
    <td>${badge(movement.movement_type)}</td>
    <td class="num strong-cell ${qty >= 0 ? "positive" : "negative"}">${qty >= 0 ? "+" : ""}${num(qty)}</td>
    <td><div class="cell-title"><span>${escapeHtml(movement.reason)}</span>${movement.notes ? `<span>${escapeHtml(movement.notes)}</span>` : ""}${link ? `<span>${link}</span>` : ""}</div></td>
    <td class="num">${movement.unit_cost === null || movement.unit_cost === undefined ? "—" : money(movement.unit_cost)}</td>
  </tr>`;
}

function receiptCard(receipt) {
  return `<section class="card">
    <div class="card-header">
      <div><h2>Receipt #${receipt.id}${receipt.supplier_ref ? ` · ${escapeHtml(receipt.supplier_ref)}` : ""}</h2><p>${formatDateTime(receipt.received_at)} · ${escapeHtml(statusLabel(receipt.payment_method))}${receipt.expense_id ? ` · linked expense #${receipt.expense_id}` : ""}</p></div>
      <strong>${money(receipt.total_cost)}</strong>
    </div>
    <div class="table-wrap"><table class="data compact">
      <thead><tr><th>Product</th><th class="num">Qty</th><th class="num">Unit cost</th><th class="num">Line total</th></tr></thead>
      <tbody>${receipt.items
        .map(
          (item) => `<tr>
            <td>${escapeHtml(item.product_name || `Product #${item.product_id}`)}</td>
            <td class="num">${num(item.quantity)}</td>
            <td class="num">${money(item.unit_cost)}</td>
            <td class="num">${money(item.line_total)}</td>
          </tr>`
        )
        .join("")}</tbody>
    </table></div>
    ${receipt.notes ? `<div class="card-footer small muted">${escapeHtml(receipt.notes)}</div>` : ""}
  </section>`;
}

export default {
  title: "Inventory",
  subtitle: "Products, stock levels, receipts and every movement.",
  async render(view, ctx) {
    let tab = ctx.query.get("tab") || "products";
    if (!["products", "movements", "receipts"].includes(tab)) tab = "products";
    let disposed = false;

    const productsState = getState();
    let products = productsState.products || [];
    const filter = {
      search: "",
      category: ctx.query.get("category") || "",
      active: "",
      low: ctx.query.get("low") === "1",
    };
    const movementFilter = {
      product_id: ctx.query.get("product_id") || "",
      movement_type: "",
      date_from: "",
      date_to: "",
      search: "",
      offset: 0,
    };
    let receiptOffset = 0;

    view.innerHTML = `
      <div class="stack">
        <div class="toolbar">
          <button class="btn btn-primary" type="button" data-action="new-product">${icon("plus")} Add product</button>
          <button class="btn btn-secondary" type="button" data-action="new-receipt">${icon("upload")} Receive stock</button>
          <button class="btn btn-secondary" type="button" data-action="new-movement">${icon("layers")} Manual adjustment</button>
          <div class="toolbar-spacer"></div>
          <button class="btn btn-ghost btn-sm" type="button" id="inventory-refresh">${icon("refresh")} Refresh</button>
        </div>
        <div id="inventory-offline"></div>
        <div id="inventory-summary"></div>
        <div class="tabs" role="tablist" aria-label="Inventory sections">
          <button class="tab ${tab === "products" ? "active" : ""}" type="button" data-tab="products" role="tab" aria-selected="${tab === "products"}">Products</button>
          <button class="tab ${tab === "movements" ? "active" : ""}" type="button" data-tab="movements" role="tab" aria-selected="${tab === "movements"}">Movement history</button>
          <button class="tab ${tab === "receipts" ? "active" : ""}" type="button" data-tab="receipts" role="tab" aria-selected="${tab === "receipts"}">Stock receipts</button>
        </div>
        <section id="inventory-panel"></section>
      </div>`;

    const panel = view.querySelector("#inventory-panel");
    const summarySlot = view.querySelector("#inventory-summary");

    function refreshOfflineBanner() {
      const slot = view.querySelector("#inventory-offline");
      slot.innerHTML = isOffline()
        ? `<div class="alert alert-warn">${icon("cloudOff")}<div><strong>Working from cached stock data</strong>You can browse products, but adding products, receiving stock and adjustments need the local server. Sales can still be recorded offline.</div></div>`
        : "";
    }

    function setTab(next) {
      tab = next;
      view.querySelectorAll("[data-tab]").forEach((button) => {
        const active = button.dataset.tab === tab;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
      });
      const params = new URLSearchParams();
      params.set("tab", tab);
      history.replaceState(null, "", `/inventory?${params.toString()}`);
      renderTab();
    }

    function requireOnline() {
      if (isOffline()) {
        toast("This change needs the local server. Reconnect and try again.", { type: "warn", title: "Offline" });
        return false;
      }
      return true;
    }

    async function loadProducts({ silent = false } = {}) {
      if (!silent) {
        panel.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading inventory…</span></div>`;
      }
      try {
        const [summary, list] = await Promise.all([
          api.inventory.summary(),
          api.products.list({
            search: filter.search || undefined,
            category: filter.category || undefined,
            active: filter.active || undefined,
            low_stock: filter.low || undefined,
            limit: 500,
          }),
        ]);
        if (disposed) return;
        products = list.items || [];
        summarySlot.innerHTML = summaryCards(summary);
        writeCache({ summary, list });
        hydrateIcons(summarySlot);
        panel.innerHTML = productsTable(list);
        hydrateIcons(panel);
        attachProductTableEvents();
      } catch (error) {
        if (disposed) return;
        const cached = readCache();
        if (cached) {
          summarySlot.innerHTML = summaryCards(cached.summary);
          panel.innerHTML = `<div class="alert alert-warn">${icon("cloudOff")}<div><strong>Showing cached product data</strong>${escapeHtml(error.message)}</div></div>${productsTable(cached.list)}`;
          hydrateIcons(view);
          attachProductTableEvents();
        } else {
          summarySlot.innerHTML = "";
          showError(error.message, loadProducts);
        }
      }
    }

    function productsTable(list) {
      const categories = Array.from(new Set((productsState.categories || []).concat(list.categories || [])));
      const categoryOptions = categories
        .map((category) => `<option value="${escapeHtml(category)}" ${filter.category === category ? "selected" : ""}>${escapeHtml(category)}</option>`)
        .join("");
      const empty = `<section class="card">${emptyState({
        iconName: "package",
        title: list.items.length ? "No products match these filters" : "No products yet",
        text: list.items.length ? "Adjust the search, category or stock filters." : "Add your first product with its cost, selling price and opening stock.",
        action: `<button class="btn btn-primary btn-sm" type="button" data-action="new-product">${icon("plus")} Add product</button>`,
      })}</section>`;
      if (!list.items.length) return empty;
      return `<section class="card">
        <div class="card-header">
          <div><h2>Products</h2><p>${num(list.total)} product${Number(list.total) === 1 ? "" : "s"} · stock updates automatically with every sale, receipt, return and adjustment.</p></div>
        </div>
        <div class="filter-bar" style="border-radius:0;border-left:0;border-right:0;margin:0">
          <div class="filter-field filter-search wide"><label for="product-search">Search</label><div class="filter-search">${icon("search")}<input id="product-search" type="search" placeholder="Name, SKU or category" value="${escapeHtml(filter.search)}" /></div></div>
          <div class="filter-field"><label for="product-category">Category</label><select id="product-category"><option value="">All categories</option>${categoryOptions}</select></div>
          <div class="filter-field"><label for="product-active">Status</label><select id="product-active"><option value="">All</option><option value="true" ${filter.active === "true" ? "selected" : ""}>Active</option><option value="false" ${filter.active === "false" ? "selected" : ""}>Inactive</option></select></div>
          <div class="filter-field"><label>Stock</label><label class="checkbox-row small"><input type="checkbox" id="product-low" ${filter.low ? "checked" : ""} /> Low stock only</label></div>
        </div>
        <div class="table-wrap"><table class="data product-table">
          <thead><tr><th>Product</th><th>Stock</th><th class="num">Cost</th><th class="num">Price</th><th>Status</th><th></th></tr></thead>
          <tbody>${list.items.map(productRow).join("")}</tbody>
        </table></div>
        <div class="card-footer row-between"><span class="small muted">Showing ${num(list.items.length)} of ${num(list.total)} products</span><span class="small muted">Tap a product name to view its movements.</span></div>
      </section>`;
    }

    function attachProductTableEvents() {
      const search = panel.querySelector("#product-search");
      if (search) {
        search.addEventListener(
          "input",
          debounce(() => {
            filter.search = search.value;
            loadProducts();
          }, 300)
        );
        const value = search.value;
        search.focus();
        search.setSelectionRange(value.length, value.length);
      }
      panel.querySelector("#product-category")?.addEventListener("change", (event) => {
        filter.category = event.target.value;
        loadProducts();
      });
      panel.querySelector("#product-active")?.addEventListener("change", (event) => {
        filter.active = event.target.value;
        loadProducts();
      });
      panel.querySelector("#product-low")?.addEventListener("change", (event) => {
        filter.low = event.target.checked;
        loadProducts();
      });
      panel.querySelectorAll("[data-action='edit-product']").forEach((button) =>
        button.addEventListener("click", () => {
          const product = findProduct(Number(button.dataset.id));
          if (product) openProductModal(product);
        })
      );
      panel.querySelectorAll("[data-action='product-history']").forEach((button) =>
        button.addEventListener("click", (event) => {
          event.preventDefault();
          movementFilter.product_id = button.dataset.id;
          movementFilter.offset = 0;
          setTab("movements");
        })
      );
      panel.querySelectorAll("[data-action='new-product']").forEach((button) =>
        button.addEventListener("click", () => openProductModal(null))
      );
    }

    function findProduct(id) {
      return products.find((product) => Number(product.id) === Number(id)) || null;
    }

    async function renderMovements() {
      panel.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading stock movements…</span></div>`;
      try {
        const data = await api.inventory.movements({
          product_id: movementFilter.product_id || undefined,
          movement_type: movementFilter.movement_type || undefined,
          date_from: movementFilter.date_from || undefined,
          date_to: movementFilter.date_to || undefined,
          search: movementFilter.search || undefined,
          limit: 100,
          offset: movementFilter.offset,
        });
        if (disposed) return;
        const productOptions = products
          .map((product) => `<option value="${product.id}" ${String(product.id) === String(movementFilter.product_id) ? "selected" : ""}>${escapeHtml(product.name)}</option>`)
          .join("");
        panel.innerHTML = `<section class="card">
          <div class="card-header"><div><h2>Stock movement history</h2><p>Every receipt, sale, return, damage record and correction, newest first.</p></div><button class="btn btn-secondary btn-sm" type="button" data-action="new-movement">${icon("plus")} Adjustment</button></div>
          <div class="filter-bar" style="border-left:0;border-right:0;margin:0">
            <div class="filter-field filter-search wide"><label for="movement-search">Search</label><div class="filter-search">${icon("search")}<input id="movement-search" type="search" placeholder="Product, reason or notes" value="${escapeHtml(movementFilter.search)}" /></div></div>
            <div class="filter-field"><label for="movement-product">Product</label><select id="movement-product"><option value="">All products</option>${productOptions}</select></div>
            <div class="filter-field"><label for="movement-type">Type</label><select id="movement-type">${MOVEMENT_TYPES.map(([value, label]) => `<option value="${value}" ${movementFilter.movement_type === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
            <div class="filter-field"><label for="movement-from">From</label><input id="movement-from" type="date" value="${escapeHtml(movementFilter.date_from)}" /></div>
            <div class="filter-field"><label for="movement-to">To</label><input id="movement-to" type="date" value="${escapeHtml(movementFilter.date_to)}" /></div>
          </div>
          ${data.items.length
            ? `<div class="table-wrap"><table class="data">
                <thead><tr><th>When</th><th>Product</th><th>Type</th><th class="num">Change</th><th>Reason</th><th class="num">Unit cost</th></tr></thead>
                <tbody>${data.items.map(movementRow).join("")}</tbody>
              </table></div>
              <div class="card-footer">${paginationHtml({ total: data.total, limit: data.limit, offset: data.offset, idPrefix: "movement-page" })}</div>`
            : emptyState({ iconName: "layers", title: "No stock movements found", text: "Sales, restocks, returns and adjustments appear here as they happen.", action: `<button class="btn btn-secondary btn-sm" type="button" data-action="new-movement">${icon("layers")} Add adjustment</button>` })}
        </section>`;
        hydrateIcons(panel);
        attachMovementEvents();
      } catch (error) {
        if (disposed) return;
        showError(error.message, renderMovements);
      }
    }

    function attachMovementEvents() {
      const search = panel.querySelector("#movement-search");
      if (search) {
        search.addEventListener(
          "input",
          debounce(() => {
            movementFilter.search = search.value;
            movementFilter.offset = 0;
            renderMovements();
          }, 300)
        );
        const value = search.value;
        search.focus();
        search.setSelectionRange(value.length, value.length);
      }
      ["product", "type"].forEach((key) => {
        panel.querySelector(`#movement-${key}`)?.addEventListener("change", (event) => {
          if (key === "product") movementFilter.product_id = event.target.value;
          else movementFilter.movement_type = event.target.value;
          movementFilter.offset = 0;
          renderMovements();
        });
      });
      ["from", "to"].forEach((key) => {
        panel.querySelector(`#movement-${key}`)?.addEventListener("change", (event) => {
          movementFilter[`date_${key}`] = event.target.value;
          movementFilter.offset = 0;
          renderMovements();
        });
      });
      panel.querySelector("[data-movement-page-prev]")?.addEventListener("click", () => {
        movementFilter.offset = Math.max(0, movementFilter.offset - 100);
        renderMovements();
      });
      panel.querySelector("[data-movement-page-next]")?.addEventListener("click", () => {
        movementFilter.offset += 100;
        renderMovements();
      });
      panel.querySelectorAll("[data-action='new-movement']").forEach((button) =>
        button.addEventListener("click", () => openMovementModal())
      );
      panel.querySelectorAll("[data-action='product-history']").forEach((button) =>
        button.addEventListener("click", (event) => {
          event.preventDefault();
          movementFilter.product_id = button.dataset.id;
          movementFilter.offset = 0;
          renderMovements();
        })
      );
    }

    async function renderReceipts() {
      panel.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading stock receipts…</span></div>`;
      try {
        const data = await api.inventory.receipts({ limit: 20, offset: receiptOffset });
        if (disposed) return;
        panel.innerHTML = `<div class="stack">
          <div class="toolbar">
            <span class="small muted">${num(data.total)} receipt${Number(data.total) === 1 ? "" : "s"} recorded. Each receipt creates a linked inventory-purchase expense.</span>
            <div class="toolbar-spacer"></div>
            <button class="btn btn-secondary btn-sm" type="button" data-action="new-receipt">${icon("plus")} Receive stock</button>
          </div>
          ${data.items.length
            ? data.items.map(receiptCard).join("")
            : `<section class="card">${emptyState({
                iconName: "box",
                title: "No stock receipts yet",
                text: "Use Receive stock to add purchased units, update purchase cost and record the inventory expense in one step.",
                action: `<button class="btn btn-primary btn-sm" type="button" data-action="new-receipt">${icon("upload")} Receive stock</button>`,
              })}</section>`}
          ${data.items.length ? `<div class="card"><div class="card-footer">${paginationHtml({ total: data.total, limit: data.limit, offset: data.offset, idPrefix: "receipt-page" })}</div></div>` : ""}
        </div>`;
        hydrateIcons(panel);
        panel.querySelectorAll("[data-action='new-receipt']").forEach((button) =>
          button.addEventListener("click", () => openReceiptModal())
        );
        panel.querySelector("[data-receipt-page-prev]")?.addEventListener("click", () => {
          receiptOffset = Math.max(0, receiptOffset - 20);
          renderReceipts();
        });
        panel.querySelector("[data-receipt-page-next]")?.addEventListener("click", () => {
          receiptOffset += 20;
          renderReceipts();
        });
      } catch (error) {
        if (disposed) return;
        showError(error.message, renderReceipts);
      }
    }

    function showError(message, retry) {
      panel.innerHTML = `<section class="card"><div class="empty-state">
        <span class="empty-icon">${icon("alert")}</span>
        <strong>Could not load inventory</strong>
        <p>${escapeHtml(message)}</p>
        <button class="btn btn-secondary" type="button" id="inventory-retry">${icon("refresh")} Try again</button>
      </div></section>`;
      panel.querySelector("#inventory-retry")?.addEventListener("click", retry);
    }

    async function renderTab() {
      refreshOfflineBanner();
      if (tab === "products") {
        await loadProducts();
        summarySlot.style.display = "";
      } else if (tab === "movements") {
        summarySlot.style.display = "none";
        await renderMovements();
      } else {
        summarySlot.style.display = "none";
        await renderReceipts();
      }
    }

    function productFormFields(product) {
      const categoryList = (productsState.categories || []).map((category) => `<option value="${escapeHtml(category)}"></option>`).join("");
      return `
        <div class="form-grid">
          <div class="field span-2"><label for="p-name">Product name</label><input id="p-name" name="name" required maxlength="120" value="${escapeHtml(product?.name || "")}" placeholder="e.g. Kurkure Masala Munch 90g" /></div>
          <div class="field"><label for="p-category">Category</label><input id="p-category" name="category" list="category-options" maxlength="80" value="${escapeHtml(product?.category || "Snacks")}" placeholder="Snacks" /><datalist id="category-options">${categoryList}</datalist></div>
          <div class="field"><label for="p-sku">SKU / code <span class="muted">(optional)</span></label><input id="p-sku" name="sku" maxlength="64" value="${escapeHtml(product?.sku || "")}" /></div>
          <div class="field"><label for="p-cost">Purchase cost (₹)</label><input id="p-cost" name="purchase_cost" type="number" min="0" step="0.01" value="${product ? Number(product.purchase_cost).toFixed(2) : "0.00"}" /></div>
          <div class="field"><label for="p-price">Selling price (₹)</label><input id="p-price" name="selling_price" type="number" min="0" step="0.01" value="${product ? Number(product.selling_price).toFixed(2) : "0.00"}" /></div>
          ${product ? "" : `<div class="field"><label for="p-opening">Opening stock</label><input id="p-opening" name="opening_stock" type="number" min="0" step="1" value="0" /></div>`}
          <div class="field"><label for="p-threshold">Low-stock threshold</label><input id="p-threshold" name="low_stock_threshold" type="number" min="0" step="1" value="${product ? product.low_stock_threshold : 5}" /></div>
          <div class="field"><label for="p-expiry">Expiry date <span class="muted">(optional)</span></label><input id="p-expiry" name="expiry_date" type="date" value="${product?.expiry_date || ""}" /></div>
          <div class="field span-2"><label for="p-batch">Batch note <span class="muted">(optional)</span></label><input id="p-batch" name="batch_note" maxlength="200" value="${escapeHtml(product?.batch_note || "")}" /></div>
          ${product ? `<div class="field span-2"><label class="checkbox-row"><input type="checkbox" name="is_active" ${product.is_active ? "checked" : ""} /> Product is active and available for sale</label><span class="hint">Inactive products stay in history but cannot be sold or restocked.</span></div>` : ""}
        </div>`;
    }

    function openProductModal(product) {
      if (!requireOnline()) return;
      const { root } = openModal({
        title: product ? `Edit ${product.name}` : "Add product",
        subtitle: product ? "Update pricing, stock thresholds or availability." : "Create a product, then receive or sell stock.",
        body: `<form id="product-form" autocomplete="off">${productFormFields(product)}<div id="product-form-error"></div></form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="product-form" id="save-product">${icon("save")} ${product ? "Save changes" : "Create product"}</button>`,
        size: "wide",
      });
      const form = root.querySelector("#product-form");
      const errorBox = root.querySelector("#product-form-error");
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const button = root.querySelector("#save-product");
        const data = new FormData(form);
        const payload = {
          name: String(data.get("name") || "").trim(),
          category: String(data.get("category") || "").trim() || "Uncategorized",
          sku: String(data.get("sku") || "").trim() || null,
          purchase_cost: readFormNumber(form, "purchase_cost").toFixed(2),
          selling_price: readFormNumber(form, "selling_price").toFixed(2),
          low_stock_threshold: Math.trunc(readFormNumber(form, "low_stock_threshold")),
          expiry_date: data.get("expiry_date") || null,
          batch_note: String(data.get("batch_note") || "").trim() || null,
        };
        if (!payload.name) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Product name is required.</div>`;
          return;
        }
        setBusy(button, true, product ? "Saving…" : "Creating…");
        try {
          if (product) {
            payload.version = product.version;
            payload.is_active = form.elements.is_active.checked;
            await api.products.update(product.id, payload);
            toast(`${payload.name} updated.`, { title: "Product saved" });
          } else {
            payload.opening_stock = Math.max(0, Math.trunc(readFormNumber(form, "opening_stock")));
            payload.is_active = true;
            await api.products.create(payload);
            toast(`${payload.name} added with ${num(payload.opening_stock)} opening units.`, { title: "Product created" });
          }
          closeModal();
          await refreshProducts();
          await renderTab();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openReceiptModal() {
      if (!requireOnline()) return;
      const active = products.filter((product) => product.is_active);
      if (!active.length) {
        toast("Add at least one active product before receiving stock.", { type: "warn" });
        return;
      }
      const methods = (getState().settings.payment_methods || ["cash"]).slice();
      let lines = [{ key: uid(), product_id: active[0].id, quantity: 1, unit_cost: Number(active[0].purchase_cost || 0) }];

      const { root } = openModal({
        title: "Receive stock",
        subtitle: "Add purchased units. This updates purchase cost and records a linked inventory purchase expense.",
        size: "wide",
        body: `<form id="receipt-form" autocomplete="off">
          <div class="form-grid">
            <div class="field"><label for="r-supplier">Supplier / invoice reference</label><input id="r-supplier" name="supplier_ref" maxlength="150" placeholder="e.g. Sharma Distributors" /></div>
            <div class="field"><label for="r-method">Paid with</label><select id="r-method" name="payment_method">${methods.map((method) => `<option value="${escapeHtml(method)}">${escapeHtml(statusLabel(method))}</option>`).join("")}</select></div>
            <div class="field"><label for="r-when">Received at</label><input id="r-when" name="received_at" type="datetime-local" value="${dateTimeLocalValue()}" /></div>
            <div class="field span-2"><label for="r-notes">Notes <span class="muted">(optional)</span></label><textarea id="r-notes" name="notes" rows="2" placeholder="Condition, batch details or payment reference"></textarea></div>
          </div>
          <div class="form-section">
            <div class="form-section-title"><strong>Items received</strong><span class="small muted">Unit cost updates the product purchase cost.</span></div>
            <div id="receipt-lines" class="stack"></div>
            <button class="btn btn-secondary btn-sm" type="button" id="add-receipt-line">${icon("plus")} Add another product</button>
          </div>
          <div class="totals"><div class="totals-row total"><span>Total cost</span><strong id="receipt-total">${money(0)}</strong></div></div>
          <div id="receipt-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="receipt-form" id="save-receipt">${icon("save")} Save receipt</button>`,
      });

      const form = root.querySelector("#receipt-form");
      const linesRoot = root.querySelector("#receipt-lines");
      const errorBox = root.querySelector("#receipt-error");
      const totalNode = root.querySelector("#receipt-total");

      function productOptions(selected) {
        return active
          .map((product) => `<option value="${product.id}" ${Number(product.id) === Number(selected) ? "selected" : ""}>${escapeHtml(product.name)} · ${num(product.stock_quantity)} in stock</option>`)
          .join("");
      }

      function renderLines() {
        linesRoot.innerHTML = lines
          .map(
            (line, index) => `<div class="receipt-line grid-3" data-line="${line.key}" style="align-items:end;gap:10px">
              <div class="field"><label>Product</label><select data-line-product>${productOptions(line.product_id)}</select></div>
              <div class="field"><label>Quantity</label><input data-line-qty type="number" min="1" step="1" value="${line.quantity}" /></div>
              <div class="field" style="display:flex;gap:8px;align-items:flex-end"><div class="grow"><label>Unit cost (₹)</label><input data-line-cost type="number" min="0" step="0.01" value="${Number(line.unit_cost).toFixed(2)}" /></div>${lines.length > 1 ? `<button class="btn btn-danger-soft btn-sm" type="button" data-remove-line aria-label="Remove line">${icon("trash")}</button>` : ""}</div>
            </div>`
          )
          .join("");
        linesRoot.querySelectorAll("[data-line]").forEach((row) => {
          const line = lines.find((item) => item.key === row.dataset.line);
          row.querySelector("[data-line-product]")?.addEventListener("change", (event) => {
            line.product_id = Number(event.target.value);
            const product = active.find((item) => Number(item.id) === line.product_id);
            line.unit_cost = Number(product?.purchase_cost || 0);
            renderLines();
          });
          row.querySelector("[data-line-qty]")?.addEventListener("input", (event) => {
            line.quantity = Math.max(1, Math.trunc(Number(event.target.value) || 1));
            updateTotal();
          });
          row.querySelector("[data-line-cost]")?.addEventListener("input", (event) => {
            line.unit_cost = Math.max(0, Number(event.target.value) || 0);
            updateTotal();
          });
          row.querySelector("[data-remove-line]")?.addEventListener("click", () => {
            lines = lines.filter((item) => item.key !== line.key);
            renderLines();
          });
        });
        updateTotal();
      }

      function updateTotal() {
        const total = lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_cost || 0), 0);
        totalNode.textContent = money(total);
      }

      root.querySelector("#add-receipt-line").addEventListener("click", () => {
        const next = active.find((product) => !lines.some((line) => Number(line.product_id) === Number(product.id))) || active[0];
        lines.push({ key: uid(), product_id: next.id, quantity: 1, unit_cost: Number(next.purchase_cost || 0) });
        renderLines();
      });

      renderLines();

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const seen = new Set();
        for (const line of lines) {
          if (seen.has(line.product_id)) {
            errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Each product may appear only once per receipt.</div>`;
            return;
          }
          seen.add(line.product_id);
        }
        if (lines.some((line) => !line.product_id || line.quantity <= 0)) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Every line needs a product and a positive quantity.</div>`;
          return;
        }
        const button = root.querySelector("#save-receipt");
        setBusy(button, true, "Saving receipt…");
        try {
          const data = new FormData(form);
          const receivedAt = data.get("received_at");
          const payload = {
            supplier_ref: String(data.get("supplier_ref") || "").trim() || null,
            payment_method: data.get("payment_method") || "cash",
            notes: String(data.get("notes") || "").trim() || null,
            received_at: receivedAt ? new Date(receivedAt).toISOString() : null,
            items: lines.map((line) => ({
              product_id: line.product_id,
              quantity: Math.trunc(line.quantity),
              unit_cost: Number(line.unit_cost).toFixed(2),
            })),
            idempotency_key: uid(),
          };
          const receipt = await api.inventory.createReceipt(payload);
          toast(`Receipt #${receipt.id} saved for ${money(receipt.total_cost)}.`, { title: "Stock received" });
          closeModal();
          await refreshProducts();
          await renderTab();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openMovementModal(prefillProductId = null) {
      if (!requireOnline()) return;
      const active = products.filter((product) => product.is_active);
      if (!active.length) {
        toast("Add an active product before recording a stock adjustment.", { type: "warn" });
        return;
      }
      const selectedId = Number(prefillProductId || movementFilter.product_id || active[0].id);
      const { root } = openModal({
        title: "Manual stock adjustment",
        subtitle: "Record opening stock, damage or a verified correction. Every change is audited.",
        body: `<form id="movement-form" autocomplete="off">
          <div class="form-grid">
            <div class="field span-2"><label for="m-product">Product</label><select id="m-product" name="product_id">${active
              .map((product) => `<option value="${product.id}" ${Number(product.id) === selectedId ? "selected" : ""}>${escapeHtml(product.name)} · ${num(product.stock_quantity)} in stock</option>`)
              .join("")}</select></div>
            <div class="field"><label for="m-type">Adjustment type</label><select id="m-type" name="movement_type"><option value="damage">Damaged / lost</option><option value="correction">Correction (add or remove)</option><option value="opening">Opening stock</option></select></div>
            <div class="field"><label for="m-qty"><span id="m-qty-label">Quantity damaged</span></label><input id="m-qty" name="quantity" type="number" step="1" min="1" value="1" /><span class="hint" id="m-qty-hint">Enter a positive number; it will reduce stock.</span></div>
            <div class="field"><label for="m-cost">New unit cost (₹) <span class="muted">optional</span></label><input id="m-cost" name="unit_cost" type="number" min="0" step="0.01" placeholder="Leave blank to keep current cost" /></div>
            <div class="field span-2"><label for="m-reason">Reason</label><input id="m-reason" name="reason" maxlength="300" required placeholder="e.g. Packets crushed during transport" /></div>
            <div class="field span-2"><label for="m-notes">Notes <span class="muted">(optional)</span></label><textarea id="m-notes" name="notes" rows="2"></textarea></div>
          </div>
          <div class="inline-note">${icon("info")}The resulting stock is shown before saving. Negative stock requires an explicit confirmation.</div>
          <div id="movement-preview" class="metric-strip" style="margin-top:12px"></div>
          <div id="movement-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="submit" form="movement-form" id="save-movement">${icon("save")} Save adjustment</button>`,
      });
      const form = root.querySelector("#movement-form");
      const typeSelect = root.querySelector("#m-type");
      const qtyInput = root.querySelector("#m-qty");
      const qtyLabel = root.querySelector("#m-qty-label");
      const qtyHint = root.querySelector("#m-qty-hint");
      const preview = root.querySelector("#movement-preview");
      const errorBox = root.querySelector("#movement-error");

      function currentProduct() {
        return active.find((product) => Number(product.id) === Number(form.elements.product_id.value));
      }

      function signedQuantity() {
        const raw = Number(qtyInput.value || 0);
        const type = typeSelect.value;
        if (type === "damage") return -Math.abs(Math.trunc(raw));
        if (type === "opening") return Math.abs(Math.trunc(raw));
        return Math.trunc(raw);
      }

      function updatePreview() {
        const product = currentProduct();
        const change = signedQuantity();
        const resulting = Number(product?.stock_quantity || 0) + change;
        preview.innerHTML = `<div><span>Current stock</span><strong>${num(product?.stock_quantity || 0)}</strong></div><div><span>Change</span><strong class="${change >= 0 ? "positive" : "negative"}">${change >= 0 ? "+" : ""}${num(change)}</strong></div><div><span>Resulting stock</span><strong class="${resulting < 0 ? "negative" : ""}">${num(resulting)}</strong></div>`;
      }

      typeSelect.addEventListener("change", () => {
        if (typeSelect.value === "damage") {
          qtyLabel.textContent = "Quantity damaged";
          qtyHint.textContent = "Enter a positive number; it will reduce stock.";
          qtyInput.min = "1";
          if (Number(qtyInput.value) < 0) qtyInput.value = Math.abs(Number(qtyInput.value));
        } else if (typeSelect.value === "opening") {
          qtyLabel.textContent = "Opening quantity";
          qtyHint.textContent = "Positive number added as opening stock.";
          qtyInput.min = "1";
          qtyInput.value = Math.max(1, Math.abs(Number(qtyInput.value) || 1));
        } else {
          qtyLabel.textContent = "Quantity change";
          qtyHint.textContent = "Use a minus sign to remove units, or a positive number to add them.";
          qtyInput.removeAttribute("min");
        }
        updatePreview();
      });
      qtyInput.addEventListener("input", updatePreview);
      form.elements.product_id.addEventListener("change", updatePreview);
      updatePreview();

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        errorBox.innerHTML = "";
        const change = signedQuantity();
        const reason = String(form.elements.reason.value || "").trim();
        if (!change) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Quantity change cannot be zero.</div>`;
          return;
        }
        if (reason.length < 2) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Provide a short reason for the audit trail.</div>`;
          return;
        }
        if (typeSelect.value === "damage" && change > 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Damage adjustments must reduce stock.</div>`;
          return;
        }
        if (typeSelect.value === "opening" && change <= 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Opening stock must be a positive quantity.</div>`;
          return;
        }
        const button = root.querySelector("#save-movement");
        setBusy(button, true, "Saving…");
        const payload = {
          product_id: Number(form.elements.product_id.value),
          movement_type: typeSelect.value,
          quantity_change: change,
          reason,
          notes: String(form.elements.notes.value || "").trim() || null,
          idempotency_key: uid(),
        };
        const cost = form.elements.unit_cost.value;
        if (cost !== "" && Number(cost) >= 0) payload.unit_cost = Number(cost).toFixed(2);
        try {
          await api.inventory.createMovement(payload);
          toast("Stock adjustment saved.", { title: "Inventory updated" });
          closeModal();
          await refreshProducts();
          await renderTab();
        } catch (error) {
          if (error instanceof ApiError && error.code === "negative_stock") {
            const detail = error.details?.resulting_stock;
            const proceed = await confirmDialog({
              title: "Stock would go negative",
              message: `This adjustment would leave the product at ${detail ?? "a negative"} units. Record it anyway?`,
              confirmLabel: "Record negative stock",
              danger: true,
            });
            if (proceed) {
              payload.allow_negative_stock = true;
              try {
                await api.inventory.createMovement(payload);
                toast("Stock adjustment saved with negative stock.", { type: "warn" });
                closeModal();
                await refreshProducts();
                await renderTab();
                return;
              } catch (retryError) {
                errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(retryError.message)}</div>`;
              }
            }
          } else {
            errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
          }
        } finally {
          setBusy(button, false);
        }
      });
    }

    view.querySelectorAll("[data-tab]").forEach((button) =>
      button.addEventListener("click", () => setTab(button.dataset.tab))
    );
    view.querySelector("[data-action='new-product']")?.addEventListener("click", () => openProductModal(null));
    view.querySelector("[data-action='new-receipt']")?.addEventListener("click", () => openReceiptModal());
    view.querySelector("[data-action='new-movement']")?.addEventListener("click", () => openMovementModal());
    view.querySelector("#inventory-refresh")?.addEventListener("click", async () => {
      try {
        await refreshProducts();
        products = getState().products || [];
      } catch {
        /* cached data remains */
      }
      renderTab();
    });

    await renderTab();
    if (ctx.query.get("receive") === "1" && !isOffline()) {
      openReceiptModal();
      history.replaceState(null, "", "/inventory");
    }
    return () => {
      disposed = true;
    };
  },
};
