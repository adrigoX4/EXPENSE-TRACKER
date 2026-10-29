import { api, ApiError } from "../api.js";
import { getState, queueOperation, refreshPendingCount, refreshProducts, adjustCachedStock } from "../store.js";
import {
  badge,
  confirmDialog,
  decimal,
  escapeHtml,
  formatTime,
  hydrateIcons,
  icon,
  money,
  num,
  promptDialog,
  setBusy,
  toast,
  uid,
} from "../ui.js";

function isoNow() {
  return new Date().toISOString();
}

function cartPayload(state, overrides = {}) {
  const payload = {
    source: state.source,
    items: state.cart.map((line) => ({
      product_id: line.product.id,
      quantity: line.quantity,
    })),
    discount: decimal(state.discount),
    notes: state.notes || undefined,
    occurred_at: isoNow(),
    client_uuid: state.clientUuid,
  };
  if (state.source !== "manual" && state.externalOrderId.trim()) {
    payload.external_order_id = state.externalOrderId.trim();
  }
  if (state.customerName.trim()) {
    payload.customer_name = state.customerName.trim();
    payload.customer_ref = state.customerName.trim();
  }
  if (state.customerPhone.trim()) payload.customer_phone = state.customerPhone.trim();
  if (state.customerRoom.trim()) payload.customer_room_ref = state.customerRoom.trim();
  if (state.deliveryStatus) {
    payload.delivery_status = state.deliveryStatus;
    if (state.deliveryPerson.trim()) payload.delivery_person = state.deliveryPerson.trim();
  }
  const payments = (state.payments || []).filter((row) => Number(row.amount) > 0);
  if (payments.length) {
    payload.initial_payments = payments.map((row) => ({
      amount: decimal(row.amount),
      method: row.method,
    }));
  }
  const { payments: _payments, ...rest } = overrides;
  return { ...payload, ...rest };
}

function saleTotals(cart, discount) {
  const subtotal = cart.reduce((sum, line) => sum + line.quantity * Number(line.product.selling_price), 0);
  const total = Math.max(0, subtotal - discount);
  return { subtotal, total };
}

export default {
  title: "New Sale",
  subtitle: "Record a walk-in, website or phone order — works offline.",
  async render(view, ctx) {
    const state = getState();
    const settings = state.settings;
    const methods = settings.payment_methods?.length ? settings.payment_methods : ["cash", "upi"];

    let cart = [];
    let selectedCategory = "all";
    let search = "";
    let source = "manual";
    let externalOrderId = "";
    let discount = 0;
    let paymentLines = [{ method: methods[0] || "cash", amount: 0 }];
    let paidTouched = false;
    let deliveryStatus = "";
    let externalDuplicate = null;
    let externalChecking = false;
    let clientUuid = uid();
    let lastSale = null;
    let disposed = false;
    let externalCheckTimer = null;

    const soldOut = (product) => Number(product.stock_quantity) <= 0;

    const totals = () => saleTotals(cart, discount);

    const receivedNow = () => paymentLines.reduce((sum, line) => sum + Number(line.amount || 0), 0);

    const paymentSnapshot = () => {
      const { total } = totals();
      const paid = Math.min(Math.max(0, receivedNow()), total);
      if (total === 0) return { status: "paid", paid: 0, balance: 0 };
      if (paid >= total - 0.005) return { status: "paid", paid, balance: Math.max(0, total - paid) };
      if (paid > 0) return { status: "partial", paid, balance: total - paid };
      return { status: "unpaid", paid: 0, balance: total };
    };

    function methodOptions(selected) {
      return methods
        .map(
          (value) =>
            `<option value="${escapeHtml(value)}" ${value === selected ? "selected" : ""}>${escapeHtml(value === "upi" ? "UPI" : value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()))}</option>`
        )
        .join("");
    }

    function renderPaymentLines() {
      const slot = view.querySelector("#payment-lines");
      if (!slot) return;
      slot.innerHTML = paymentLines
        .map(
          (line, index) => `<div class="payment-line" data-payment-line="${index}">
            <select data-payment-method="${index}" aria-label="Payment method ${index + 1}">${methodOptions(line.method)}</select>
            <input type="number" min="0" step="0.01" inputmode="decimal" data-payment-amount="${index}" value="${line.amount ? decimal(line.amount) : ""}" placeholder="0.00" aria-label="Amount received by ${escapeHtml(line.method)}" />
            ${paymentLines.length > 1 ? `<button class="icon-btn" type="button" data-remove-payment="${index}" aria-label="Remove this payment method">${icon("x")}</button>` : ""}
          </div>`
        )
        .join("");
      view.querySelector("#add-payment-line").hidden = paymentLines.length >= 5;
    }

    function syncPaymentInputs() {
      paymentLines.forEach((line, index) => {
        const input = view.querySelector(`[data-payment-amount="${index}"]`);
        if (input) input.value = Number(line.amount) ? decimal(line.amount) : "";
        const select = view.querySelector(`[data-payment-method="${index}"]`);
        if (select) select.value = line.method;
      });
    }

    function cartLineHtml(line, index) {
      const available = Number(line.product.stock_quantity);
      const short = line.quantity > available;
      return `<div class="cart-item" data-line="${index}">
        <div class="grow">
          <div class="cart-item-name">${escapeHtml(line.product.name)}</div>
          <div class="cart-item-sub">${money(line.product.selling_price)} each${short ? ` · <span class="warn-text">only ${num(available)} in stock</span>` : ""}</div>
        </div>
        <div class="qty-control">
          <button type="button" data-qty="-1" data-line="${index}" aria-label="Decrease quantity of ${escapeHtml(line.product.name)}">−</button>
          <input type="number" min="1" step="1" value="${line.quantity}" data-qty-input="${index}" aria-label="Quantity of ${escapeHtml(line.product.name)}" />
          <button type="button" data-qty="1" data-line="${index}" aria-label="Increase quantity of ${escapeHtml(line.product.name)}">+</button>
        </div>
        <div class="row" style="gap:6px">
          <span class="cart-line-total">${money(line.quantity * Number(line.product.selling_price))}</span>
          <button class="icon-btn" style="width:26px;height:26px;border:0;background:transparent;color:var(--faint)" type="button" data-remove="${index}" aria-label="Remove ${escapeHtml(line.product.name)}">${icon("x")}</button>
        </div>
      </div>`;
    }

    function renderCart() {
      const list = view.querySelector("#cart-list");
      const { subtotal, total } = totals();
      if (!cart.length) {
        list.innerHTML = `<div class="cart-empty">
          <div class="muted" style="font-size:12.5px">No items yet.</div>
          <div class="small" style="margin-top:4px">Select a product to start this sale.</div>
        </div>`;
      } else {
        list.innerHTML = cart.map(cartLineHtml).join("");
      }
      view.querySelector("#sum-subtotal").textContent = money(subtotal);
      view.querySelector("#sum-discount").textContent = discount > 0 ? `− ${money(discount)}` : money(0);
      view.querySelector("#sum-total").textContent = money(total);
      if (!paidTouched && paymentLines.length === 1) {
        paymentLines[0].amount = total;
        syncPaymentInputs();
      }
      updatePaymentSummary();
      view.querySelector("#save-sale").disabled = !cart.length || Boolean(externalDuplicate) || externalChecking;
      view.querySelector("#cart-count").textContent = cart.length ? `${cart.length} item${cart.length === 1 ? "" : "s"}` : "";
    }

    function updatePaymentSummary() {
      const { total } = totals();
      const snapshot = paymentSnapshot();
      const preview = view.querySelector("#payment-preview");
      if (preview) {
        preview.innerHTML = cart.length
          ? `${badge(snapshot.status)}<span class="muted small">${snapshot.balance > 0 ? `${money(snapshot.balance)} due after saving` : "Settled in full"}</span>`
          : `<span class="muted small">Add an item to see payment status.</span>`;
      }
      const received = view.querySelector("#sum-received");
      if (received) received.textContent = money(snapshot.paid);
      const balance = view.querySelector("#sum-balance");
      if (balance) {
        balance.textContent = money(snapshot.balance);
        balance.classList.toggle("negative", snapshot.balance > 0);
      }
      const hint = view.querySelector("#payment-hint");
      if (hint) {
        const entered = receivedNow();
        hint.textContent =
          entered > total + 0.005
            ? `Entered ${money(entered)} — payments cannot exceed the total.`
            : snapshot.status === "unpaid"
              ? "No payment yet: the sale will be saved as unpaid."
              : "";
        hint.classList.toggle("negative", entered > total + 0.005);
      }
    }

    function renderProducts() {
      const grid = view.querySelector("#product-grid");
      if (!getState().products.length) {
        grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
          <span class="empty-icon">${icon("cloudOff")}</span>
          <strong>No products available offline</strong>
          <p>The product catalogue has not been cached on this device yet. Connect to the server and reload, or add products in Inventory once online.</p>
          <a class="btn btn-secondary btn-sm" href="/inventory">${icon("package")} Open inventory</a>
        </div>`;
        return;
      }
      const categories = [...new Set(getState().products.filter((p) => p.is_active).map((p) => p.category))].sort();
      const chips = view.querySelector("#category-chips");
      chips.innerHTML = [`<button type="button" data-category="all" class="${selectedCategory === "all" ? "active" : ""}">All</button>`]
        .concat(
          categories.map(
            (category) =>
              `<button type="button" data-category="${escapeHtml(category)}" class="${selectedCategory === category ? "active" : ""}">${escapeHtml(category)}</button>`
          )
        )
        .join("");

      const term = search.trim().toLowerCase();
      const matches = getState()
        .products.filter((product) => product.is_active)
        .filter((product) => selectedCategory === "all" || product.category === selectedCategory)
        .filter(
          (product) =>
            !term ||
            product.name.toLowerCase().includes(term) ||
            (product.sku || "").toLowerCase().includes(term) ||
            (product.category || "").toLowerCase().includes(term)
        )
        .sort((a, b) => a.name.localeCompare(b.name));

      if (!matches.length) {
        grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
          <span class="empty-icon">${icon("search")}</span>
          <strong>No matching products</strong>
          <p>Try another name or clear the category filter.</p>
        </div>`;
        return;
      }

      grid.innerHTML = matches
        .map((product) => {
          const inCart = cart.find((line) => line.product.id === product.id)?.quantity || 0;
          const stock = Number(product.stock_quantity);
          const stockClass = stock <= 0 ? "out" : stock <= Number(product.low_stock_threshold) ? "low" : "";
          return `<button class="product-tile" type="button" data-product="${product.id}" ${product.is_active ? "" : "disabled"}>
            <span class="tile-name">${escapeHtml(product.name)}</span>
            <span class="tile-meta">
              <span class="tile-price">${money(product.selling_price)}</span>
              <span class="tile-stock ${stockClass}">${stock <= 0 ? "Out of stock" : `${num(stock)} left`}${inCart ? ` · ${inCart} in cart` : ""}</span>
            </span>
          </button>`;
        })
        .join("");
      hydrateIcons(grid);
    }

    function addProduct(productId) {
      const product = getState().products.find((row) => row.id === Number(productId));
      if (!product || !product.is_active) return;
      const existing = cart.find((line) => line.product.id === product.id);
      if (existing) {
        existing.quantity += 1;
      } else {
        cart.push({ product, quantity: 1 });
      }
      lastSale = null;
      view.querySelector("#last-sale").innerHTML = "";
      renderProducts();
      renderCart();
      view.querySelector("#product-search")?.focus({ preventScroll: true });
    }

    function changeQuantity(index, delta) {
      const line = cart[index];
      if (!line) return;
      line.quantity += delta;
      if (line.quantity <= 0) cart.splice(index, 1);
      renderProducts();
      renderCart();
    }

    function setQuantity(index, value) {
      const line = cart[index];
      if (!line) return;
      const quantity = Math.max(1, Math.floor(Number(value) || 1));
      line.quantity = Math.min(quantity, 99999);
      renderProducts();
      renderCart();
    }

    function resetForm() {
      cart = [];
      discount = 0;
      paymentLines = [{ method: methods[0] || "cash", amount: 0 }];
      paidTouched = false;
      externalOrderId = "";
      externalDuplicate = null;
      deliveryStatus = "";
      source = "manual";
      clientUuid = uid();
      const form = view.querySelector("#sale-form");
      form.reset();
      view.querySelector("#discount-input").value = "0";
      view.querySelector("#source-select").value = "manual";
      view.querySelector("#external-field").hidden = true;
      view.querySelector("#external-warning").innerHTML = "";
      view.querySelector("#delivery-person-field").hidden = true;
      view.querySelector("#sale-error").innerHTML = "";
      renderPaymentLines();
      renderProducts();
      renderCart();
      view.querySelector("#product-search")?.focus({ preventScroll: true });
    }

    async function checkExternalId() {
      const field = view.querySelector("#external-order-id");
      externalOrderId = field?.value.trim() || "";
      const warning = view.querySelector("#external-warning");
      externalDuplicate = null;
      if (!externalOrderId || source === "manual") {
        warning.innerHTML = "";
        renderCart();
        return;
      }
      externalChecking = true;
      renderCart();
      try {
        const result = await api.sales.checkExternal(externalOrderId);
        if (disposed) return;
        if (result.exists) {
          externalDuplicate = result.sale;
          warning.innerHTML = `<div class="alert alert-warn">${icon("alert")}<div><strong>This website order is already recorded</strong>Sale #${result.sale.id} uses order ID “${escapeHtml(externalOrderId)}”. <a href="/sales/${result.sale.id}">Open that sale</a> instead of creating a duplicate.</div></div>`;
        } else if (source === "website") {
          warning.innerHTML = `<div class="inline-note success">${icon("checkCircle")}Order ID is not yet recorded in this app. Saving will link it for reconciliation.</div>`;
        } else {
          warning.innerHTML = `<div class="inline-note">${icon("info")}No matching order ID found. The sale will be saved as imported.</div>`;
        }
      } catch (error) {
        if (disposed) return;
        if (error.offline) {
          warning.innerHTML = `<div class="inline-note warn">${icon("cloudOff")}Cannot check the order ID while offline. It will be validated when the sale syncs.</div>`;
        } else {
          warning.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        }
      } finally {
        externalChecking = false;
        if (!disposed) renderCart();
      }
    }

    async function requestNegativeReason(message) {
      const proceed = await confirmDialog({
        title: "Stock would go negative",
        message,
        confirmLabel: "Continue",
        danger: true,
      });
      if (!proceed) return null;
      const reason = await promptDialog({
        title: "Reason for negative stock",
        label: "Reason",
        placeholder: "e.g. Stock count was not updated before this sale",
        confirmLabel: "Record sale",
        danger: true,
      });
      const cleaned = (reason || "").trim();
      if (cleaned.length < 2) {
        view.querySelector("#sale-error").innerHTML = `<div class="inline-note danger">${icon("alert")}A short reason is required before recording a sale with negative stock.</div>`;
        return null;
      }
      return cleaned;
    }

    async function saveLocally(payload, { allowNegative = false } = {}) {
      if (!allowNegative) {
        const total = totals().total;
        const available = cart.some((line) => line.quantity > Number(line.product.stock_quantity));
        if (available) {
          const reason = await requestNegativeReason(
            "One or more products are short on locally cached stock. Record the sale anyway? The sync step may still report a stock conflict."
          );
          if (!reason) return false;
          payload.allow_negative_stock = true;
          payload.negative_stock_reason = reason;
        }
        if (total > 0 && receivedNow() > total + 0.005) {
          view.querySelector("#sale-error").innerHTML = `<div class="inline-note danger">${icon("alert")}Payments received cannot exceed the sale total.</div>`;
          return false;
        }
      }
      const finalPayload = { ...payload, allow_negative_stock: allowNegative || payload.allow_negative_stock || false };
      finalPayload.client_uuid = clientUuid;
      const operation = await queueOperation({
        kind: "sale",
        payload: finalPayload,
        label: `${cart.length} item${cart.length === 1 ? "" : "s"} · ${money(totals().total)}`,
        amount: totals().total,
        id: clientUuid,
      });
      cart.forEach((line) => adjustCachedStock(line.product.id, -line.quantity));
      await refreshPendingCount();
      toast("Sale saved on this device. It will synchronize when the server is available.", {
        title: "Saved locally",
        type: "warn",
      });
      lastSale = { local: true, total: totals().total, operationId: operation.id };
      resetForm();
      view.querySelector("#last-sale").innerHTML = `<div class="alert alert-warn">${icon("cloudOff")}<div><strong>Last sale saved locally</strong>${money(lastSale.total)} · local reference ${escapeHtml(String(operation.id).slice(0, 8))} · pending synchronization. <a href="/sales">View sales</a></div></div>`;
      return true;
    }

    async function submitSale(button) {
      const errorBox = view.querySelector("#sale-error");
      errorBox.innerHTML = "";
      if (!cart.length) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Add at least one product to the sale.</div>`;
        return;
      }
      if (externalDuplicate) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}This website order ID is already recorded. Open the existing sale before saving.</div>`;
        return;
      }
      const { total } = totals();
      if (discount < 0) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Discount cannot be negative.</div>`;
        return;
      }
      if (discount > totals().subtotal) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Discount cannot be greater than the subtotal.</div>`;
        return;
      }
      if (receivedNow() > total + 0.005) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Payments received cannot exceed the sale total of ${money(total)}.</div>`;
        return;
      }

      const payload = cartPayload({
        source,
        externalOrderId,
        discount,
        payments: paymentLines,
        customerName: view.querySelector("#customer-name").value,
        customerPhone: view.querySelector("#customer-phone").value,
        customerRoom: view.querySelector("#customer-room").value,
        deliveryStatus,
        deliveryPerson: view.querySelector("#delivery-person").value,
        notes: view.querySelector("#sale-notes").value,
        cart,
        clientUuid,
      });

      if (!navigator.onLine || getState().serverReachable === false) {
        try {
          await saveLocally(payload);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Could not save locally: ${escapeHtml(error.message)}</div>`;
        }
        return;
      }

      setBusy(button, true, "Saving…");
      try {
        const sale = await api.sales.create(payload, clientUuid);
        toast(`Sale #${sale.id} recorded for ${money(sale.total)}.`, { title: "Sale saved" });
        lastSale = sale;
        resetForm();
        view.querySelector("#last-sale").innerHTML = `<div class="alert alert-success">${icon("checkCircle")}<div><strong>Sale #${sale.id} recorded</strong>${money(sale.total)} · ${escapeHtml(sale.customer_name || "Walk-in")} · ${formatTime(sale.occurred_at)}. <a href="/sales/${sale.id}">View sale</a></div></div>`;
        refreshProducts()
          .then(() => {
            if (!disposed) renderProducts();
          })
          .catch(() => {});
      } catch (error) {
        if (error instanceof ApiError && error.code === "negative_stock" && !payload.allow_negative_stock) {
          const reason = await requestNegativeReason(
            "This sale would make stock negative. Continue only if you are correcting an untracked stock movement."
          );
          if (reason) {
            try {
              const sale = await api.sales.create(
                { ...payload, allow_negative_stock: true, negative_stock_reason: reason },
                clientUuid
              );
              toast(`Sale #${sale.id} recorded with negative stock override.`, { title: "Sale saved", type: "warn" });
              lastSale = sale;
              resetForm();
              view.querySelector("#last-sale").innerHTML = `<div class="alert alert-success">${icon("checkCircle")}<div><strong>Sale #${sale.id} recorded</strong>${money(sale.total)} · stock was manually overridden. <a href="/sales/${sale.id}">View sale</a></div></div>`;
              refreshProducts()
                .then(() => {
                  if (!disposed) renderProducts();
                })
                .catch(() => {});
            } catch (retryError) {
              errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(retryError.message)}</div>`;
            }
          }
        } else if (error instanceof ApiError && error.code === "duplicate_external_order_id") {
          const existing = error.details?.existing_sale;
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}${existing ? ` <a href="/sales/${existing.sale_id}">Open sale #${existing.sale_id}</a>` : ""}</div>`;
          if (existing) externalDuplicate = existing;
          renderCart();
        } else if (error?.offline) {
          await saveLocally(payload);
        } else {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        }
      } finally {
        setBusy(button, false);
        renderCart();
      }
    }

    const offline = !navigator.onLine || getState().serverReachable === false;
    const offlineMessage = !navigator.onLine
      ? "This device is offline. Sales are saved on this device and sync when the connection returns."
      : "The local server is unreachable. Sales are saved on this device and sync when it returns. The College Cart website is not required.";
    const cachedAt = getState().productsCachedAt ? new Date(getState().productsCachedAt).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "never";

    view.innerHTML = `
      <div class="stack">
        ${offline ? `<div class="banner">${icon("cloudOff")}<span>${escapeHtml(offlineMessage)}</span></div>` : ""}
        <div id="last-sale"></div>
        <div class="sale-layout">
          <section class="card product-picker">
            <div class="card-header">
              <div><h2>Select products</h2><p>${num(getState().products.filter((p) => p.is_active).length)} active products · cached ${escapeHtml(cachedAt)}</p></div>
              <button class="btn btn-secondary btn-sm" type="button" id="refresh-products">${icon("refresh")} Refresh</button>
            </div>
            <div class="product-toolbar">
              <div class="product-search">
                ${icon("search")}
                <input type="search" id="product-search" placeholder="Search by name or SKU…" autocomplete="off" />
              </div>
              <div class="segmented" id="category-chips"></div>
            </div>
            <div class="product-grid" id="product-grid"></div>
            <div class="product-hint">Tap a product to add it. Stock levels are checked at save time · <span class="kbd">/</span> to search.</div>
          </section>

          <aside class="card sale-summary">
            <div class="card-header">
              <div><h2>Current sale</h2><p id="cart-count"></p></div>
              <button class="btn btn-ghost btn-sm" type="button" id="clear-cart">${icon("trash")} Clear</button>
            </div>
            <div class="cart-list" id="cart-list"></div>
            <div class="totals">
              <div class="totals-row"><span>Subtotal</span><span id="sum-subtotal">${money(0)}</span></div>
              <div class="totals-row"><span>Discount</span><span class="discount-value" id="sum-discount">${money(0)}</span></div>
              <div class="totals-row grand"><span>Total</span><span id="sum-total">${money(0)}</span></div>
              <div class="totals-row"><span>Received now</span><span id="sum-received">${money(0)}</span></div>
              <div class="totals-row"><span>Balance due</span><span id="sum-balance">${money(0)}</span></div>
            </div>

            <form id="sale-form" novalidate>
              <div class="sale-form-section">
                <div class="form-grid">
                  <div class="field">
                    <label for="source-select">Sale source</label>
                    <select id="source-select" name="source">
                      <option value="manual">Manual / direct sale</option>
                      <option value="website">Website order</option>
                      <option value="imported">Imported website order</option>
                    </select>
                  </div>
                  <div class="field">
                    <label for="discount-input">Discount (${settings.currency === "INR" ? "₹" : settings.currency})</label>
                    <input type="number" id="discount-input" name="discount" min="0" step="0.01" value="0" />
                  </div>
                  <div class="field span-2" id="external-field" hidden>
                    <label for="external-order-id">Website order ID</label>
                    <div class="field-row">
                      <input type="text" id="external-order-id" maxlength="120" placeholder="e.g. CC-2026-1042" autocomplete="off" />
                      <button class="btn btn-secondary" type="button" id="check-order">${icon("search")} Check</button>
                    </div>
                    <span class="hint">Enter the order ID exactly as shown on the College Cart website. The app does not import orders automatically.</span>
                  </div>
                </div>
                <div id="external-warning"></div>
              </div>

              <div class="sale-form-section">
                <div class="form-section-title">${icon("wallet")} Payment</div>
                <div class="payment-lines" id="payment-lines"></div>
                <div class="row-between" style="gap:8px">
                  <button class="btn btn-ghost btn-sm" type="button" id="add-payment-line">${icon("plus")} Split payment</button>
                  <span class="hint" id="payment-hint"></span>
                </div>
                <div class="quick-amounts">
                  <button type="button" data-paid="full">Full amount</button>
                  <button type="button" data-paid="half">Half</button>
                  <button type="button" data-paid="zero">No payment yet</button>
                </div>
                <div class="payment-preview"><span class="muted">Payment status after saving</span><span class="row" id="payment-preview">${badge("unpaid")}</span></div>
              </div>

              <div class="sale-form-section">
                <details>
                  <summary class="strong" style="cursor:pointer;font-size:13px;color:var(--text-2)">Customer &amp; delivery details <span class="muted small">(optional)</span></summary>
                  <div class="form-grid" style="margin-top:12px">
                    <div class="field">
                      <label for="customer-name">Customer name / reference</label>
                      <input type="text" id="customer-name" maxlength="120" placeholder="Walk-in" />
                    </div>
                    <div class="field">
                      <label for="customer-room">Room / building</label>
                      <input type="text" id="customer-room" maxlength="120" placeholder="e.g. Hostel B, Room 214" />
                    </div>
                    <div class="field">
                      <label for="customer-phone">Contact number</label>
                      <input type="tel" id="customer-phone" maxlength="30" placeholder="Only if needed" />
                    </div>
                    <div class="field">
                      <label for="delivery-status">Delivery status</label>
                      <select id="delivery-status">
                        <option value="">No delivery</option>
                        <option value="pending">Pending</option>
                        <option value="out_for_delivery">Out for delivery</option>
                        <option value="delivered">Delivered</option>
                      </select>
                    </div>
                    <div class="field span-2" id="delivery-person-field" hidden>
                      <label for="delivery-person">Delivery person</label>
                      <input type="text" id="delivery-person" maxlength="120" placeholder="Optional" />
                    </div>
                    <div class="field span-2">
                      <label for="sale-notes">Notes</label>
                      <textarea id="sale-notes" rows="2" placeholder="Anything worth remembering about this sale"></textarea>
                    </div>
                  </div>
                </details>
              </div>

              <div class="sale-form-section">
                <div id="sale-error"></div>
                <button class="btn btn-primary btn-block" type="submit" id="save-sale">${icon("check")} Save sale</button>
                <p class="tiny muted" style="text-align:center">Saves with a unique ID so retries never duplicate the sale.</p>
              </div>
            </form>
          </aside>
        </div>
      </div>`;

    hydrateIcons(view);
    renderProducts();
    renderPaymentLines();
    renderCart();
    updatePaymentSummary();

    const searchInput = view.querySelector("#product-search");
    searchInput.addEventListener("input", () => {
      search = searchInput.value;
      renderProducts();
    });
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        const first = view.querySelector("#product-grid .product-tile:not([disabled])");
        if (first) addProduct(first.dataset.product);
      }
    });

    const onGlobalKey = (event) => {
      if (
        event.key === "/" &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA" &&
        document.activeElement?.tagName !== "SELECT"
      ) {
        event.preventDefault();
        searchInput.focus();
      }
    };
    document.addEventListener("keydown", onGlobalKey);

    view.querySelector("#category-chips").addEventListener("click", (event) => {
      const button = event.target.closest("[data-category]");
      if (!button) return;
      selectedCategory = button.dataset.category;
      renderProducts();
    });

    view.querySelector("#product-grid").addEventListener("click", (event) => {
      const tile = event.target.closest("[data-product]");
      if (tile) addProduct(tile.dataset.product);
    });

    view.querySelector("#cart-list").addEventListener("click", (event) => {
      const qtyButton = event.target.closest("[data-qty]");
      if (qtyButton) {
        changeQuantity(Number(qtyButton.dataset.line), Number(qtyButton.dataset.qty));
        return;
      }
      const remove = event.target.closest("[data-remove]");
      if (remove) {
        cart.splice(Number(remove.dataset.remove), 1);
        renderProducts();
        renderCart();
      }
    });

    view.querySelector("#cart-list").addEventListener("change", (event) => {
      const input = event.target.closest("[data-qty-input]");
      if (input) setQuantity(Number(input.dataset.qtyInput), input.value);
    });

    view.querySelector("#discount-input").addEventListener("input", (event) => {
      const value = Number.parseFloat(event.target.value);
      discount = Number.isFinite(value) && value > 0 ? value : 0;
      renderCart();
    });

    view.querySelector("#payment-lines").addEventListener("input", (event) => {
      const input = event.target.closest("[data-payment-amount]");
      if (!input) return;
      const index = Number(input.dataset.paymentAmount);
      const value = Number.parseFloat(input.value);
      paymentLines[index].amount = Number.isFinite(value) && value > 0 ? value : 0;
      paidTouched = true;
      updatePaymentSummary();
    });

    view.querySelector("#payment-lines").addEventListener("change", (event) => {
      const select = event.target.closest("[data-payment-method]");
      if (!select) return;
      paymentLines[Number(select.dataset.paymentMethod)].method = select.value;
      paidTouched = true;
      updatePaymentSummary();
    });

    view.querySelector("#add-payment-line").addEventListener("click", () => {
      if (paymentLines.length >= 5) return;
      const used = new Set(paymentLines.map((line) => line.method));
      const nextMethod = methods.find((value) => !used.has(value)) || methods[0] || "cash";
      paymentLines.push({ method: nextMethod, amount: 0 });
      paidTouched = true;
      renderPaymentLines();
      updatePaymentSummary();
    });

    view.querySelector("#payment-lines").addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove-payment]");
      if (!remove) return;
      paymentLines.splice(Number(remove.dataset.removePayment), 1);
      paidTouched = true;
      renderPaymentLines();
      updatePaymentSummary();
    });

    view.querySelector(".quick-amounts").addEventListener("click", (event) => {
      const button = event.target.closest("[data-paid]");
      if (!button) return;
      const { total } = totals();
      const first = paymentLines[0];
      if (button.dataset.paid === "full") first.amount = total;
      else if (button.dataset.paid === "half") first.amount = Math.round(total * 50) / 100;
      else first.amount = 0;
      paymentLines.slice(1).forEach((line) => {
        line.amount = 0;
      });
      paidTouched = true;
      syncPaymentInputs();
      updatePaymentSummary();
    });

    view.querySelector("#source-select").addEventListener("change", (event) => {
      source = event.target.value;
      const externalField = view.querySelector("#external-field");
      externalField.hidden = source === "manual";
      view.querySelector("#external-warning").innerHTML = "";
      externalDuplicate = null;
      if (source === "manual") {
        externalOrderId = "";
        view.querySelector("#external-order-id").value = "";
      }
      renderCart();
    });

    const externalInput = view.querySelector("#external-order-id");
    externalInput.addEventListener("input", () => {
      externalOrderId = externalInput.value.trim();
      externalDuplicate = null;
      view.querySelector("#external-warning").innerHTML = "";
      renderCart();
      clearTimeout(externalCheckTimer);
      if (externalOrderId.length >= 3) externalCheckTimer = setTimeout(checkExternalId, 600);
    });
    view.querySelector("#check-order").addEventListener("click", checkExternalId);

    view.querySelector("#delivery-status").addEventListener("change", (event) => {
      deliveryStatus = event.target.value;
      view.querySelector("#delivery-person-field").hidden = !deliveryStatus;
    });

    view.querySelector("#clear-cart").addEventListener("click", async () => {
      if (!cart.length && !discount && !receivedNow()) return;
      const proceed = await confirmDialog({
        title: "Clear this sale?",
        message: "The items and amounts currently entered will be discarded. Nothing has been saved yet.",
        confirmLabel: "Clear sale",
        danger: true,
      });
      if (proceed) {
        resetForm();
        view.querySelector("#last-sale").innerHTML = "";
      }
    });

    view.querySelector("#refresh-products").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      setBusy(button, true, "Refreshing…");
      try {
        await refreshProducts();
        renderProducts();
        renderCart();
        toast("Product catalogue refreshed from the server.");
      } catch (error) {
        toast(error.message, { type: "error", title: "Could not refresh products" });
      } finally {
        setBusy(button, false);
      }
    });

    const form = view.querySelector("#sale-form");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const button = view.querySelector("#save-sale");
      if (button.disabled) return;
      submitSale(button);
    });

    setTimeout(() => searchInput.focus(), 80);

    return () => {
      disposed = true;
      clearTimeout(externalCheckTimer);
      document.removeEventListener("keydown", onGlobalKey);
    };
  },
};
