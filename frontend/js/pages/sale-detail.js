import { api } from "../api.js";
import { getState, refreshProducts } from "../store.js";
import {
  badge,
  confirmDialog,
  dateTimeLocalValue,
  decimal,
  escapeHtml,
  formatDate,
  formatDateTime,
  hydrateIcons,
  icon,
  money,
  num,
  openModal,
  setBusy,
  statusLabel,
  toast,
  uid,
} from "../ui.js";

const ACTION_LABELS = {
  created: "Sale created",
  updated: "Sale details updated",
  payment_recorded: "Payment recorded",
  return_recorded: "Return recorded",
  voided: "Sale cancelled",
  reconciliation_updated: "Reconciliation status updated",
  reconciliation_linked: "Website order linked",
  stock_sold: "Stock reduced",
  stock_returned: "Stock returned",
  stock_restored_after_void: "Stock restored",
};

function paymentRows(sale) {
  if (!sale.payments.length) {
    return `<div class="empty-state" style="padding:28px 20px"><span class="empty-icon">${icon("wallet")}</span><strong>No payments recorded</strong><p>Record cash, UPI or other payments against this sale.</p><button class="btn btn-secondary btn-sm" type="button" data-action="payment">${icon("plus")} Add payment</button></div>`;
  }
  return `<div class="table-wrap"><table class="data compact">
    <thead><tr><th>When</th><th>Method</th><th>Reference</th><th class="num">Amount</th></tr></thead>
    <tbody>${sale.payments
      .map(
        (payment) => `<tr>
        <td>${formatDateTime(payment.paid_at)}</td>
        <td>${badge(payment.method)} ${payment.kind === "refund" ? `<span class="badge badge-return">Refund</span>` : ""}</td>
        <td class="truncate">${escapeHtml(payment.reference || payment.notes || "—")}</td>
        <td class="num ${payment.direction === "out" ? "negative" : "positive"}">${payment.direction === "out" ? "−" : ""}${money(payment.amount)}</td>
      </tr>`
      )
      .join("")}</tbody>
  </table></div>`;
}

function returnsHtml(sale) {
  if (!sale.returns.length) {
    return `<div class="empty-state" style="padding:28px 20px"><span class="empty-icon">${icon("rotate")}</span><strong>No returns recorded</strong><p>Returned items update stock only when you choose to restock them.</p><button class="btn btn-secondary btn-sm" type="button" data-action="return">${icon("rotate")} Record return</button></div>`;
  }
  return `<div class="stack" style="padding:16px 20px;gap:12px">${sale.returns
    .map(
      (row) => `<div style="border:1px solid var(--border);border-radius:9px;padding:12px 14px">
        <div class="row-between">
          <div><strong class="small">${formatDateTime(row.returned_at)}</strong><div class="tiny muted">${escapeHtml(row.reason)}</div></div>
          <div class="text-right"><div class="strong">${money(row.returned_value)}</div><div class="tiny muted">refund ${money(row.refund_amount)} · ${row.restock ? "restocked" : "not restocked"}</div></div>
        </div>
        <div class="row-wrap" style="margin-top:8px;gap:6px">${row.items
          .map((item) => `<span class="chip">${escapeHtml(item.product_name || "Item")} × ${num(item.quantity)}</span>`)
          .join("")}</div>
      </div>`
    )
    .join("")}</div>`;
}

function auditTimeline(entries) {
  if (!entries.length) {
    return `<div class="empty-state" style="padding:28px 20px"><span class="empty-icon">${icon("clock")}</span><strong>No audit entries yet</strong><p>Changes to this sale will be recorded here.</p></div>`;
  }
  return `<div class="card-body"><div class="timeline">${entries
    .map((entry) => {
      const tone = ["voided"].includes(entry.action) ? "bad" : ["return_recorded", "reconciliation_updated", "reconciliation_linked"].includes(entry.action) ? "warn" : entry.action === "created" ? "good" : "";
      return `<div class="timeline-item ${tone}">
        <span class="timeline-dot"></span>
        <div class="timeline-title">${escapeHtml(ACTION_LABELS[entry.action] || statusLabel(entry.action))}</div>
        <div class="timeline-meta">${formatDateTime(entry.changed_at)}${entry.note ? ` · ${escapeHtml(entry.note)}` : ""}</div>
      </div>`;
    })
    .join("")}</div></div>`;
}

function detailBody(sale) {
  const delivery = sale.delivery;
  const netPaid = Number(sale.amount_paid) - Number(sale.refunded_amount);
  const canVoid = sale.status === "completed" && !sale.returns.length;
  return `
    <div class="stack">
      <div class="stat-grid cols-4">
        <div class="stat-card"><div class="stat-top"><span class="stat-label">Sale total</span><span class="stat-icon accent">${icon("receipt")}</span></div><div class="stat-value">${money(sale.total)}</div><div class="stat-meta">${sale.items.length} line item${sale.items.length === 1 ? "" : "s"}${Number(sale.discount) > 0 ? ` · ${money(sale.discount)} discount` : ""}</div></div>
        <div class="stat-card"><div class="stat-top"><span class="stat-label">Net collected</span><span class="stat-icon success">${icon("wallet")}</span></div><div class="stat-value">${money(netPaid)}</div><div class="stat-meta">${money(sale.refunded_amount)} refunded</div></div>
        <div class="stat-card"><div class="stat-top"><span class="stat-label">Outstanding</span><span class="stat-icon ${Number(sale.outstanding) > 0 ? "warn" : ""}">${icon("clock")}</span></div><div class="stat-value">${money(sale.outstanding)}</div><div class="stat-meta">${badge(sale.payment_status)}</div></div>
        <div class="stat-card"><div class="stat-top"><span class="stat-label">Returned value</span><span class="stat-icon ${Number(sale.returned_value) > 0 ? "warn" : ""}">${icon("rotate")}</span></div><div class="stat-value">${money(sale.returned_value)}</div><div class="stat-meta">${sale.returns.length} return record${sale.returns.length === 1 ? "" : "s"}</div></div>
      </div>

      <div class="detail-grid">
        <div class="stack">
          <section class="card">
            <div class="card-header"><div><h2>Items</h2><p>Prices and costs are frozen at the time of sale</p></div><span class="badge badge-website no-dot">${escapeHtml(sale.source === "website" ? "Website order" : statusLabel(sale.source))}</span></div>
            <div class="table-wrap"><table class="data sale-items-table">
              <thead><tr><th>Product</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Line total</th><th class="num">Returned</th></tr></thead>
              <tbody>${sale.items
                .map(
                  (item) => `<tr>
                  <td class="cell-product"><div class="cell-title"><span class="strong-cell">${escapeHtml(item.product_name)}</span><span>${escapeHtml(item.sku || "No SKU")}</span></div></td>
                  <td class="cell-qty num">${num(item.quantity)}</td>
                  <td class="cell-unit num">${money(item.unit_price)}</td>
                  <td class="cell-line num strong-cell">${money(item.line_total)}</td>
                  <td class="cell-returned num">${num(item.returned_quantity)}</td>
                </tr>`
                )
                .join("")}</tbody>
              <tfoot>
                <tr><td colspan="3">Subtotal</td><td class="num">${money(sale.subtotal)}</td><td></td></tr>
                <tr><td colspan="3">Discount</td><td class="num">− ${money(sale.discount)}</td><td></td></tr>
                <tr><td colspan="3">Total</td><td class="num">${money(sale.total)}</td><td></td></tr>
              </tfoot>
            </table></div>
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Payments</h2><p>Every inflow and refund is traceable in Money History</p></div><div class="row-wrap"><a class="btn btn-ghost btn-sm" href="/money-history?q=${encodeURIComponent(`sale #${sale.id}`)}">${icon("wallet")} Money history</a><button class="btn btn-secondary btn-sm" type="button" data-action="payment" ${sale.status === "voided" ? "disabled" : ""}>${icon("plus")} Add payment</button></div></div>
            ${paymentRows(sale)}
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Returns &amp; refunds</h2><p>Refunds are financial events, not new sales</p></div><button class="btn btn-secondary btn-sm" type="button" data-action="return" ${sale.status === "voided" ? "disabled" : ""}>${icon("rotate")} Record return</button></div>
            ${returnsHtml(sale)}
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Audit trail</h2><p>Who changed what, and when</p></div></div>
            <div id="audit-list"><div class="loading-block"><span class="spinner"></span>Loading history…</div></div>
          </section>
        </div>

        <div class="stack">
          <section class="card">
            <div class="card-header"><div><h2>Status</h2><p>Payment, delivery and website verification</p></div></div>
            <div class="card-body">
              <dl class="detail-list">
                <div class="detail-row"><dt>Payment</dt><dd>${badge(sale.payment_status)}</dd></div>
                <div class="detail-row"><dt>Sale status</dt><dd>${badge(sale.status)}</dd></div>
                <div class="detail-row"><dt>Delivery</dt><dd>${delivery ? badge(delivery.status) : `<span class="muted">Not set</span>`}</dd></div>
                <div class="detail-row"><dt>Website verification</dt><dd>${badge(sale.reconciliation_status)}</dd></div>
                <div class="detail-row"><dt>Source</dt><dd>${badge(sale.source)}</dd></div>
                <div class="detail-row"><dt>Website order ID</dt><dd>${sale.external_order_id ? `<span class="mono">${escapeHtml(sale.external_order_id)}</span>` : `<span class="muted">None</span>`}</dd></div>
                <div class="detail-row"><dt>Recorded</dt><dd>${formatDateTime(sale.created_at)}</dd></div>
                <div class="detail-row"><dt>Last updated</dt><dd>${formatDateTime(sale.updated_at)}</dd></div>
                <div class="detail-row"><dt>Internal ID</dt><dd><span class="mono">${escapeHtml(sale.uuid.slice(0, 8))}…</span></dd></div>
              </dl>
            </div>
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Website verification</h2><p>Compare this sale with the College Cart website manually</p></div></div>
            <div class="card-body stack" style="gap:12px">
              <p class="small muted">Status is editable and never inferred automatically. Marking “Verified” means you personally confirmed this order on the website.</p>
              <button class="btn btn-secondary btn-block" type="button" data-action="reconcile">${icon("compare")} Update reconciliation</button>
            </div>
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Delivery</h2><p>Optional delivery tracking</p></div></div>
            <div class="card-body stack" style="gap:12px">
              ${
                delivery
                  ? `<div class="form-grid">
                      <div class="field"><label for="delivery-status-select">Status</label>
                        <select id="delivery-status-select" data-delivery-version="${delivery.version}">
                          ${["pending", "out_for_delivery", "delivered", "cancelled"].map((status) => `<option value="${status}" ${delivery.status === status ? "selected" : ""}>${statusLabel(status)}</option>`).join("")}
                        </select>
                      </div>
                      <div class="field"><label for="delivery-person">Delivery person</label><input id="delivery-person" maxlength="120" value="${escapeHtml(delivery.delivery_person || "")}" placeholder="Optional" /></div>
                    </div>
                    <div class="field"><label for="delivery-notes">Notes</label><textarea id="delivery-notes" rows="2">${escapeHtml(delivery.notes || "")}</textarea></div>
                    <button class="btn btn-primary btn-sm" type="button" data-action="save-delivery">${icon("save")} Save delivery</button>`
                  : `<p class="small muted">No delivery record yet. Create one to track this order through delivery.</p>
                     <button class="btn btn-secondary btn-sm" type="button" data-action="create-delivery">${icon("truck")} Create delivery record</button>`
              }
            </div>
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Customer &amp; notes</h2><p>Only what you chose to record</p></div><button class="btn btn-ghost btn-sm" type="button" data-action="edit">${icon("edit")} Edit</button></div>
            <div class="card-body">
              <dl class="detail-list">
                <div class="detail-row"><dt>Name</dt><dd>${escapeHtml(sale.customer_name || "Walk-in / anonymous")}</dd></div>
                <div class="detail-row"><dt>Reference</dt><dd>${escapeHtml(sale.customer_ref || "—")}</dd></div>
                <div class="detail-row"><dt>Room / building</dt><dd>${escapeHtml(sale.customer?.room_ref || "—")}</dd></div>
                <div class="detail-row"><dt>Contact</dt><dd>${escapeHtml(sale.customer?.phone || "—")}</dd></div>
                <div class="detail-row"><dt>Delivery person</dt><dd>${escapeHtml(sale.delivery_person || "—")}</dd></div>
              </dl>
              <div class="hr-space"></div>
              <p class="small muted" style="white-space:pre-wrap">${escapeHtml(sale.notes || "No notes recorded.")}</p>
              ${sale.void_reason ? `<div class="inline-note danger" style="margin-top:12px">${icon("alert")}<div><strong>Cancelled</strong>${escapeHtml(sale.void_reason)} · ${formatDateTime(sale.voided_at)}</div></div>` : ""}
            </div>
          </section>

          <section class="card">
            <div class="card-header"><div><h2>Cancel sale</h2><p>Preserves history instead of deleting</p></div></div>
            <div class="card-body stack" style="gap:10px">
              <p class="small muted">Cancelling refunds collected money, optionally restocks items, and keeps the sale and its audit trail visible. Sales with returns must use the returns flow instead.</p>
              <button class="btn btn-danger-soft btn-block" type="button" data-action="void" ${canVoid ? "" : "disabled"}>${icon("xCircle")} ${sale.status === "voided" ? "Sale already cancelled" : sale.returns.length ? "Returns already recorded" : "Cancel this sale"}</button>
            </div>
          </section>
        </div>
      </div>
    </div>`;
}

export default {
  title: "Sale detail",
  subtitle: "Items, payments, returns and delivery.",
  async render(view, ctx) {
    const saleId = Number(ctx.params[0]);
    if (!saleId) {
      view.innerHTML = `<div class="card"><div class="empty-state"><strong>Sale not found</strong><a class="btn btn-secondary" href="/sales">Back to sales</a></div></div>`;
      return;
    }

    let sale = null;
    let disposed = false;
    let auditLoading = false;

    view.innerHTML = `<div class="app-loading"><span class="spinner"></span><span>Loading sale #${saleId}…</span></div>`;

    function updateHeaderTitle() {
      if (!sale) return;
      ctx.titleNode.textContent = `Sale #${sale.id}`;
      ctx.subtitleNode.textContent = `${formatDateTime(sale.occurred_at)} · ${statusLabel(sale.source)} · ${money(sale.total)}`;
      document.title = `Sale #${sale.id} · College Cart Manager`;
    }

    function shell() {
      return `<div class="stack">
        <div class="row-between">
          <div class="row">
            <a class="btn btn-secondary btn-sm" href="/sales">${icon("arrowLeft")} Sales</a>
            <div>
              <div class="row" style="gap:7px"><h2 style="font-size:18px">Sale #${sale.id}</h2>${badge(sale.status)}${sale.is_pending_sync ? badge("local") : ""}</div>
              <p class="small muted">${formatDateTime(sale.occurred_at)} · ${escapeHtml(sale.customer_name || "Walk-in")} · ${escapeHtml(sale.uuid.slice(0, 8))}</p>
            </div>
          </div>
          <div class="row-wrap">
            <button class="btn btn-secondary btn-sm" type="button" data-action="refresh">${icon("refresh")} Refresh</button>
            <button class="btn btn-secondary btn-sm" type="button" data-action="payment" ${sale.status === "voided" ? "disabled" : ""}>${icon("plus")} Payment</button>
            <button class="btn btn-primary btn-sm" type="button" data-action="return" ${sale.status === "voided" ? "disabled" : ""}>${icon("rotate")} Return</button>
          </div>
        </div>
        <div id="sale-body"></div>
      </div>`;
    }

    async function loadAudit() {
      if (auditLoading) return;
      auditLoading = true;
      try {
        const entries = await api.sales.audit(saleId);
        if (disposed) return;
        const node = view.querySelector("#audit-list");
        if (node) {
          node.innerHTML = auditTimeline(entries);
          hydrateIcons(node);
        }
      } catch (error) {
        if (disposed) return;
        const node = view.querySelector("#audit-list");
        if (node) node.innerHTML = `<div class="card-body small muted">${escapeHtml(error.message)}</div>`;
      } finally {
        auditLoading = false;
      }
    }

    async function load() {
      try {
        sale = await api.sales.get(saleId);
      } catch (error) {
        if (disposed) return;
        view.innerHTML = `<div class="card"><div class="empty-state">
          <span class="empty-icon">${icon("alert")}</span>
          <strong>Could not load sale #${saleId}</strong>
          <p>${escapeHtml(error.message)}</p>
          <a class="btn btn-secondary" href="/sales">Back to sales</a>
        </div></div>`;
        return;
      }
      if (disposed) return;
      updateHeaderTitle();
      view.innerHTML = shell();
      view.querySelector("#sale-body").innerHTML = detailBody(sale);
      hydrateIcons(view);
      loadAudit();
    }

    const methods = () => getState().settings.payment_methods?.length ? getState().settings.payment_methods : ["cash", "upi"];
    const methodOptions = (selected) =>
      methods()
        .map(
          (method) =>
            `<option value="${escapeHtml(method)}" ${selected === method ? "selected" : ""}>${escapeHtml(method === "upi" ? "UPI" : method.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()))}</option>`
        )
        .join("");

    function openPaymentModal() {
      if (!sale || sale.status === "voided") return;
      const outstanding = Number(sale.outstanding);
      const modal = openModal({
        title: "Add payment",
        subtitle: `Sale #${sale.id} · ${money(sale.outstanding)} outstanding`,
        body: `<form id="payment-form" class="form-grid">
          <div class="field"><label for="pay-amount">Amount</label><input id="pay-amount" name="amount" type="number" min="0.01" step="0.01" value="${outstanding > 0 ? decimal(outstanding) : ""}" required /></div>
          <div class="field"><label for="pay-method">Method</label><select id="pay-method" name="method">${methodOptions()}</select></div>
          <div class="field"><label for="pay-when">Received at</label><input id="pay-when" name="paid_at" type="datetime-local" value="${dateTimeLocalValue()}" required /></div>
          <div class="field"><label for="pay-reference">Reference</label><input id="pay-reference" name="reference" maxlength="120" placeholder="UPI ref, receipt no. (optional)" /></div>
          <div class="field span-2"><label for="pay-notes">Notes</label><input id="pay-notes" name="notes" maxlength="300" placeholder="Optional" /></div>
          <div class="span-2" id="payment-error"></div>
        </form>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="button" id="save-payment">${icon("check")} Record payment</button>`,
      });
      const button = modal.footer.querySelector("#save-payment");
      button.addEventListener("click", async () => {
        const form = modal.body.querySelector("#payment-form");
        const errorBox = modal.body.querySelector("#payment-error");
        const amount = Number(form.elements.amount.value);
        if (!Number.isFinite(amount) || amount <= 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Enter an amount greater than zero.</div>`;
          return;
        }
        if (!form.elements.paid_at.value) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Choose when the payment was received.</div>`;
          return;
        }
        setBusy(button, true, "Recording…");
        try {
          await api.sales.addPayment(
            sale.id,
            {
              amount: decimal(amount),
              method: form.elements.method.value,
              paid_at: new Date(form.elements.paid_at.value).toISOString(),
              reference: form.elements.reference.value.trim() || null,
              notes: form.elements.notes.value.trim() || null,
            },
            uid()
          );
          modal.close();
          toast(`${money(amount)} payment recorded on sale #${sale.id}.`);
          await load();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openReturnModal() {
      if (!sale || sale.status === "voided") return;
      const eligible = sale.items.filter((item) => item.remaining_quantity > 0);
      if (!eligible.length) {
        toast("Every item on this sale has already been returned.", { type: "info" });
        return;
      }
      const rows = eligible
        .map((item, index) => {
          const unitValue = Number(item.line_total) / Number(item.quantity);
          return `<div class="cart-item" style="grid-template-columns:auto minmax(0,1fr) auto auto;padding-left:0;padding-right:0">
            <input type="checkbox" data-return-check="${item.id}" style="width:16px;height:16px;accent-color:var(--accent)" aria-label="Return ${escapeHtml(item.product_name)}" />
            <div><div class="cart-item-name">${escapeHtml(item.product_name)}</div><div class="cart-item-sub">${num(item.remaining_quantity)} of ${num(item.quantity)} eligible · ${money(unitValue)} per unit</div></div>
            <div class="qty-control"><input type="number" min="1" max="${item.remaining_quantity}" value="1" data-return-qty="${item.id}" disabled style="border:0;border-radius:6px;width:46px" aria-label="Return quantity" /></div>
            <span class="tiny muted" data-return-line="${item.id}">${money(0)}</span>
          </div>`;
        })
        .join("");
      const modal = openModal({
        title: "Record return",
        subtitle: `Sale #${sale.id} · refunds reduce collected money, not the sale total`,
        body: `<div class="form-section">
          <div>${rows}</div>
          <div class="form-grid">
            <div class="field"><label for="return-refund">Refund amount</label><input id="return-refund" type="number" min="0" step="0.01" value="0" /></div>
            <div class="field"><label for="return-method">Refund method</label><select id="return-method">${methodOptions()}</select></div>
            <div class="field"><label for="return-when">Returned at</label><input id="return-when" type="datetime-local" value="${dateTimeLocalValue()}" required /></div>
            <div class="field"><label for="return-reason">Reason</label><input id="return-reason" maxlength="300" placeholder="e.g. Damaged pack, wrong item" /></div>
            <label class="checkbox-row span-2"><input type="checkbox" id="return-restock" checked /> Add returned items back to saleable stock</label>
          </div>
          <div class="inline-note">${icon("info")}Return quantities can never exceed what was sold minus earlier returns. Only tick restock if the goods are actually resalable.</div>
          <div id="return-error"></div>
        </div>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="button" id="save-return">${icon("rotate")} Record return</button>`,
        size: "wide",
      });

      const netPaid = Number(sale.amount_paid) - Number(sale.refunded_amount);
      const checks = () => [...modal.body.querySelectorAll("[data-return-check]")];
      const recompute = () => {
        let value = 0;
        checks().forEach((check) => {
          const item = eligible.find((row) => row.id === Number(check.dataset.returnCheck));
          const qtyInput = modal.body.querySelector(`[data-return-qty="${check.dataset.returnCheck}"]`);
          qtyInput.disabled = !check.checked;
          if (check.checked) {
            const max = Number(item.remaining_quantity);
            const quantity = Math.min(Math.max(1, Number(qtyInput.value) || 1), max);
            qtyInput.value = quantity;
            const lineValue = (Number(item.line_total) / Number(item.quantity)) * quantity;
            value += lineValue;
            const label = modal.body.querySelector(`[data-return-line="${check.dataset.returnCheck}"]`);
            if (label) label.textContent = money(lineValue);
          } else {
            const label = modal.body.querySelector(`[data-return-line="${check.dataset.returnCheck}"]`);
            if (label) label.textContent = money(0);
          }
        });
        const cap = Math.min(value, Math.max(0, netPaid));
        const refundField = modal.body.querySelector("#return-refund");
        refundField.value = cap > 0 ? decimal(cap) : "0";
        refundField.max = decimal(cap);
        return { value, cap };
      };

      modal.body.querySelectorAll("[data-return-check]").forEach((check) => check.addEventListener("change", recompute));
      modal.body.querySelectorAll("[data-return-qty]").forEach((input) => input.addEventListener("input", recompute));

      const button = modal.footer.querySelector("#save-return");
      button.addEventListener("click", async () => {
        const errorBox = modal.body.querySelector("#return-error");
        const selected = checks().filter((check) => check.checked);
        const reason = modal.body.querySelector("#return-reason").value.trim();
        if (!selected.length) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Select at least one item to return.</div>`;
          return;
        }
        if (reason.length < 2) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Add a short reason for the return.</div>`;
          return;
        }
        const refund = Number(modal.body.querySelector("#return-refund").value);
        if (!Number.isFinite(refund) || refund < 0) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Refund amount is invalid.</div>`;
          return;
        }
        const returnedAt = modal.body.querySelector("#return-when").value;
        if (!returnedAt) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Choose when the return happened.</div>`;
          return;
        }
        const items = selected.map((check) => ({
          sale_item_id: Number(check.dataset.returnCheck),
          quantity: Number(modal.body.querySelector(`[data-return-qty="${check.dataset.returnCheck}"]`).value),
        }));
        setBusy(button, true, "Recording…");
        try {
          await api.sales.addReturn(sale.id, {
            items,
            restock: modal.body.querySelector("#return-restock").checked,
            refund_amount: decimal(refund),
            refund_method: refund > 0 ? modal.body.querySelector("#return-method").value : null,
            returned_at: new Date(returnedAt).toISOString(),
            reason,
            idempotency_key: uid(),
          });
          modal.close();
          toast("Return recorded and inventory updated where applicable.");
          await Promise.all([load(), refreshProducts().catch(() => {})]);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openEditModal() {
      const modal = openModal({
        title: "Edit sale details",
        subtitle: `Sale #${sale.id} · version ${sale.version}`,
        body: `<div class="form-grid">
          <div class="field"><label for="edit-customer-ref">Customer reference</label><input id="edit-customer-ref" maxlength="120" value="${escapeHtml(sale.customer_ref || "")}" /></div>
          <div class="field"><label for="edit-external">Website order ID</label><input id="edit-external" maxlength="120" value="${escapeHtml(sale.external_order_id || "")}" placeholder="Optional" /></div>
          <div class="field span-2"><label for="edit-notes">Notes</label><textarea id="edit-notes" rows="4">${escapeHtml(sale.notes || "")}</textarea></div>
          <div class="span-2" id="edit-error"></div>
        </div>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-primary" type="button" id="save-edit">${icon("save")} Save changes</button>`,
      });
      const button = modal.footer.querySelector("#save-edit");
      button.addEventListener("click", async () => {
        const errorBox = modal.body.querySelector("#edit-error");
        setBusy(button, true, "Saving…");
        try {
          await api.sales.update(sale.id, {
            version: sale.version,
            notes: modal.body.querySelector("#edit-notes").value.trim() || null,
            customer_ref: modal.body.querySelector("#edit-customer-ref").value.trim() || null,
            external_order_id: modal.body.querySelector("#edit-external").value.trim() || null,
          });
          modal.close();
          toast("Sale details updated.");
          await load();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    function openReconcileModal() {
      const statuses = ["recorded", "verified", "not_found", "needs_review", "potential_duplicate"];
      const modal = openModal({
        title: "Reconciliation",
        subtitle: `Sale #${sale.id} · current status: ${statusLabel(sale.reconciliation_status)}`,
        body: `<div class="form-grid">
          <div class="field span-2"><label for="recon-status">Verification status</label>
            <select id="recon-status">${statuses.map((status) => `<option value="${status}" ${sale.reconciliation_status === status ? "selected" : ""}>${statusLabel(status)}</option>`).join("")}</select>
            <span class="hint">“Verified” means you checked this order on the College Cart website yourself. The app has no automatic website integration.</span>
          </div>
          <div class="field"><label for="recon-website-id">Website order ID</label><input id="recon-website-id" maxlength="120" value="${escapeHtml(sale.external_order_id || "")}" placeholder="e.g. CC-2026-1042" /></div>
          <div class="field"><label for="recon-total">Website total</label><input id="recon-total" type="number" min="0" step="0.01" placeholder="Optional" /></div>
          <div class="field span-2"><label for="recon-notes">Notes</label><textarea id="recon-notes" rows="3" placeholder="What did you compare?"></textarea></div>
          <div class="span-2" id="recon-error"></div>
        </div>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-secondary" type="button" id="link-order">${icon("externalLink")} Save order ID &amp; verify</button><button class="btn btn-primary" type="button" id="save-recon">${icon("save")} Save status</button>`,
      });
      const errorBox = modal.body.querySelector("#recon-error");
      const saveStatus = async (button) => {
        setBusy(button, true, "Saving…");
        try {
          await api.reconciliation.updateSale(sale.id, {
            status: modal.body.querySelector("#recon-status").value,
            notes: modal.body.querySelector("#recon-notes").value.trim() || null,
            version: sale.version,
          });
          modal.close();
          toast("Reconciliation status updated.");
          await load();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
          setBusy(button, false);
        }
      };
      modal.footer.querySelector("#save-recon").addEventListener("click", (event) => saveStatus(event.currentTarget));
      modal.footer.querySelector("#link-order").addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const orderId = modal.body.querySelector("#recon-website-id").value.trim();
        if (!orderId) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Enter the website order ID to link.</div>`;
          return;
        }
        setBusy(button, true, "Linking…");
        try {
          await api.reconciliation.link({
            sale_id: sale.id,
            external_order_id: orderId,
            notes: modal.body.querySelector("#recon-notes").value.trim() || null,
            version: sale.version,
          });
          modal.close();
          toast(`Sale #${sale.id} linked to website order ${orderId} and marked verified.`);
          await load();
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
          setBusy(button, false);
        }
      });
    }

    function openVoidModal() {
      const netPaid = Number(sale.amount_paid) - Number(sale.refunded_amount);
      const modal = openModal({
        title: `Cancel sale #${sale.id}?`,
        subtitle: "This preserves the sale record and adds a cancellation trail.",
        body: `<div class="form-section">
          <div class="inline-note danger">${icon("alert")}The sale stops counting toward completed revenue. Collected money can be refunded, and stock can be restored. The record is never deleted.</div>
          <div class="field"><label for="void-reason">Reason</label><textarea id="void-reason" rows="3" placeholder="Why is this sale being cancelled?" required></textarea></div>
          <label class="checkbox-row"><input type="checkbox" id="void-restock" checked /> Restore the sold quantities to stock</label>
          <label class="checkbox-row"><input type="checkbox" id="void-refund" ${netPaid > 0 ? "checked" : "disabled"} /> Refund net collected amount (${money(Math.max(0, netPaid))})</label>
          <div class="field"><label for="void-method">Refund method</label><select id="void-method">${methodOptions()}</select></div>
          <div id="void-error"></div>
        </div>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Keep sale</button><button class="btn btn-danger" type="button" id="confirm-void">${icon("xCircle")} Cancel sale</button>`,
      });
      const button = modal.footer.querySelector("#confirm-void");
      button.addEventListener("click", async () => {
        const errorBox = modal.body.querySelector("#void-error");
        const reason = modal.body.querySelector("#void-reason").value.trim();
        if (reason.length < 2) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Provide a reason of at least 2 characters.</div>`;
          return;
        }
        setBusy(button, true, "Cancelling…");
        try {
          await api.sales.void(sale.id, {
            version: sale.version,
            reason,
            restock: modal.body.querySelector("#void-restock").checked,
            refund_paid: !modal.body.querySelector("#void-refund").disabled && modal.body.querySelector("#void-refund").checked,
            refund_method: modal.body.querySelector("#void-method").value,
          });
          modal.close();
          toast(`Sale #${sale.id} cancelled. History preserved for audit.`, { type: "warn" });
          await Promise.all([load(), refreshProducts().catch(() => {})]);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
        } finally {
          setBusy(button, false);
        }
      });
    }

    async function saveDelivery(button) {
      const statusSelect = view.querySelector("#delivery-status-select");
      if (!statusSelect) return;
      const version = Number(statusSelect.dataset.deliveryVersion);
      setBusy(button, true, "Saving…");
      try {
        await api.deliveries.update(sale.delivery.id, {
          status: statusSelect.value,
          delivery_person: view.querySelector("#delivery-person").value.trim() || null,
          notes: view.querySelector("#delivery-notes").value.trim() || null,
          version,
        });
        toast("Delivery updated.");
        await load();
      } catch (error) {
        toast(error.message, { type: "error", title: "Could not update delivery" });
      } finally {
        setBusy(button, false);
      }
    }

    async function createDelivery(button) {
      setBusy(button, true, "Creating…");
      try {
        await api.deliveries.create({ sale_id: sale.id, status: "pending" });
        toast("Delivery record created.");
        await load();
      } catch (error) {
        toast(error.message, { type: "error", title: "Could not create delivery" });
      } finally {
        setBusy(button, false);
      }
    }

    view.addEventListener("click", (event) => {
      const target = event.target.closest("[data-action]");
      if (!target) return;
      const action = target.dataset.action;
      if (action === "refresh") load();
      else if (action === "payment") openPaymentModal();
      else if (action === "return") openReturnModal();
      else if (action === "edit") openEditModal();
      else if (action === "reconcile") openReconcileModal();
      else if (action === "void") openVoidModal();
      else if (action === "save-delivery") saveDelivery(target);
      else if (action === "create-delivery") createDelivery(target);
    });

    await load();
    return () => {
      disposed = true;
    };
  },
};
