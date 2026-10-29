import { api } from "../api.js";
import {
  getState,
  pendingOperations,
  refreshPendingCount,
  refreshSettings,
  removeOperation,
} from "../store.js";
import { syncOutbox } from "../sync.js";
import {
  badge,
  closeModal,
  confirmDialog,
  emptyState,
  escapeHtml,
  formatDateTime,
  hydrateIcons,
  icon,
  money,
  num,
  openModal,
  relativeTime,
  setBusy,
  statusLabel,
  toast,
} from "../ui.js";

const OPERATION_LABELS = {
  sale: "Sale",
  expense: "Expense",
  payment: "Sale payment",
  return: "Return / refund",
  movement: "Stock adjustment",
  handover: "Cash handover",
  money: "Money entry",
};

const ACTION_LABELS = {
  created: "Created",
  updated: "Updated",
  voided: "Voided",
  stock_received: "Stock received",
  reconciliation_updated: "Reconciliation updated",
  reconciliation_linked: "Website order linked",
  confirmed_duplicate: "Duplicate confirmed",
  dismissed: "Duplicate dismissed",
  adjustment_created: "Cash adjustment",
  stock_opening: "Opening stock",
  stock_damage: "Damage recorded",
  stock_correction: "Stock corrected",
};

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(2)} MB`;
}

function chipEditor(id, values, placeholder) {
  return `<div class="chip-editor" id="${id}">
    <div class="row-wrap" data-chips>${values.map((value) => chip(value)).join("")}</div>
    <div class="inline-form">
      <input type="text" data-chip-input placeholder="${escapeHtml(placeholder)}" maxlength="40" aria-label="${escapeHtml(placeholder)}" />
      <button class="btn btn-secondary btn-sm" type="button" data-chip-add>${icon("plus")} Add</button>
    </div>
  </div>`;
}

function chip(value) {
  return `<span class="chip" data-chip="${escapeHtml(value)}">${escapeHtml(statusLabel(value))}<button type="button" data-chip-remove aria-label="Remove ${escapeHtml(value)}">${icon("x")}</button></span>`;
}

function operationRow(operation) {
  return `<tr>
    <td class="nowrap">${formatDateTime(operation.createdAt)}<span class="tiny muted block">${relativeTime(operation.createdAt)}</span></td>
    <td><div class="cell-title"><span>${escapeHtml(OPERATION_LABELS[operation.kind] || operation.kind)}</span><span>${escapeHtml(operation.label || "")}</span></div></td>
    <td class="num">${operation.amount ? money(operation.amount) : "—"}</td>
    <td>${operation.status === "failed" ? `<span class="badge badge-failed">Failed</span>` : `<span class="badge badge-pending">Pending</span>`}</td>
    <td class="num">${num(operation.attempts || 0)}</td>
    <td>${operation.lastError ? `<span class="small negative">${escapeHtml(operation.lastError)}</span>` : `<span class="muted">—</span>`}</td>
    <td class="text-right"><button class="btn btn-ghost btn-xs" type="button" data-discard="${escapeHtml(operation.id)}">${icon("trash")} Discard</button></td>
  </tr>`;
}

function auditRow(entry) {
  return `<tr>
    <td class="nowrap">${formatDateTime(entry.changed_at)}</td>
    <td><div class="cell-title"><span>${escapeHtml(statusLabel(entry.entity_type))} ${escapeHtml(entry.entity_id)}</span><span>${entry.note ? escapeHtml(entry.note) : ""}</span></div></td>
    <td>${escapeHtml(ACTION_LABELS[entry.action] || statusLabel(entry.action))}</td>
  </tr>`;
}

export default {
  title: "Settings & Backup",
  subtitle: "Business preferences, money categories, opening balances, backups and offline queue.",
  async render(view) {
    let disposed = false;
    let selectedBackup = null;
    const state = getState();
    let paymentMethods = [...(state.settings.payment_methods || ["cash", "upi"])];
    let expenseCategories = [...(state.settings.expense_categories || ["inventory_purchase", "travel", "food", "packaging", "personal_other", "miscellaneous"])];
    let moneyInCategories = [...(state.settings.money_in_categories || ["customer_payment", "money_from_owner", "repayment_received", "other_money_received"])];
    let moneyOutCategories = [...(state.settings.money_out_categories || ["money_to_owner", "stock_purchase", "expense_payment", "cash_handover", "repayment_given", "other_money_given"])];

    view.innerHTML = `
      <div class="stack">
        <div class="alert alert-info">${icon("info")}<div><strong>Privacy and integration</strong>This manager is local-first. It does not send customer data to third parties, run analytics, or automatically read the public College Cart website. Automatic import requires an authorized College Cart API; without one, create sales manually and reconcile website order IDs by hand.</div></div>

        <div class="grid-main-side">
          <div class="stack">
            <section class="card">
              <div class="card-header"><div><h2>Business preferences</h2><p>Payment methods and expense categories used across the app.</p></div><span class="badge no-dot">${escapeHtml(state.settings.business_timezone || "Asia/Kolkata")}</span></div>
              <form id="settings-form">
                <div class="card-body">
                  <div class="form-grid">
                    <div class="field"><label for="business-name">Business name</label><input id="business-name" name="business_name" maxlength="120" value="${escapeHtml(state.settings.business_name || "College Cart")}" required /></div>
                    <div class="field"><label for="default-low-stock">Default low-stock threshold</label><input id="default-low-stock" name="default_low_stock_threshold" type="number" min="0" max="1000000" step="1" value="${escapeHtml(state.settings.default_low_stock_threshold ?? 5)}" /></div>
                    <div class="field"><label>Business timezone</label><input value="${escapeHtml(state.settings.business_timezone || "Asia/Kolkata")}" disabled /><span class="hint">All dates and times are shown in this timezone.</span></div>
                  </div>
                  <div class="form-section">
                    <div class="form-section-title"><strong>Payment methods</strong><span class="small muted">Used for sales, refunds, expenses, handovers and money entries. “Cash” affects the physical drawer.</span></div>
                    ${chipEditor("payment-methods", paymentMethods, "Add a payment method, e.g. upi")}
                  </div>
                  <div class="form-section">
                    <div class="form-section-title"><strong>Expense categories</strong><span class="small muted">“Stock purchase” is reserved for inventory receipts.</span></div>
                    ${chipEditor("expense-categories", expenseCategories, "Add an expense category")}
                  </div>
                  <div class="form-section">
                    <div class="form-section-title"><strong>Money in categories</strong><span class="small muted">Reasons for money received. Sale payments are added automatically.</span></div>
                    ${chipEditor("money-in-categories", moneyInCategories, "Add a money-in reason")}
                  </div>
                  <div class="form-section">
                    <div class="form-section-title"><strong>Money out categories</strong><span class="small muted">Reasons for money given. Expenses, stock purchases and handovers appear automatically.</span></div>
                    ${chipEditor("money-out-categories", moneyOutCategories, "Add a money-out reason")}
                  </div>
                  <div class="form-section">
                    <div class="form-section-title"><strong>Opening balances</strong><span class="small muted">Starting cash and UPI balances used to calculate running balances. Leave blank if unknown.</span></div>
                    <div class="form-grid">
                      <div class="field"><label for="opening-cash">Opening cash (₹)</label><input id="opening-cash" name="opening_cash_balance" type="number" min="0" step="0.01" value="${state.settings.opening_cash_balance !== null && state.settings.opening_cash_balance !== undefined ? Number(state.settings.opening_cash_balance).toFixed(2) : ""}" placeholder="Unknown" /></div>
                      <div class="field"><label for="opening-upi">Opening UPI (₹)</label><input id="opening-upi" name="opening_upi_balance" type="number" min="0" step="0.01" value="${state.settings.opening_upi_balance !== null && state.settings.opening_upi_balance !== undefined ? Number(state.settings.opening_upi_balance).toFixed(2) : ""}" placeholder="Unknown" /></div>
                      <div class="field"><label for="opening-date">Effective from</label><input id="opening-date" name="opening_balance_date" type="date" value="${escapeHtml(state.settings.opening_balance_date || "")}" /></div>
                      <div class="field"><label>&nbsp;</label><label class="checkbox-row small"><input type="checkbox" id="clear-openings" /> Clear opening balances</label></div>
                    </div>
                  </div>
                  <div class="inline-note">${icon("info")}Changing these lists does not rewrite historical records. Existing values remain visible in older transactions.</div>
                  <div class="row-between" style="margin-top:14px"><span class="small muted">Settings changes are audited.</span><button class="btn btn-primary" type="submit" id="save-settings">${icon("save")} Save preferences</button></div>
                  <div id="settings-error"></div>
                </div>
              </form>
            </section>

            <section class="card">
              <div class="card-header"><div><h2>Offline queue</h2><p>Records saved on this device and waiting to reach the server.</p></div><button class="btn btn-secondary btn-sm" type="button" id="sync-now">${icon("refresh")} Sync now</button></div>
              <div id="offline-queue"><div class="app-loading"><span class="spinner"></span><span>Checking queue…</span></div></div>
              <div class="card-footer small muted">Sales, expenses, money transactions and handovers are stored in IndexedDB (with a local-storage fallback). Each queued item carries an idempotency key, so retrying cannot create duplicates.</div>
            </section>

            <section class="card">
              <div class="card-header"><div><h2>Sync activity</h2><p>Server-side record of idempotent sync operations.</p></div></div>
              <div id="sync-log"><div class="app-loading"><span class="spinner"></span><span>Loading sync log…</span></div></div>
            </section>

            <section class="card">
              <div class="card-header"><div><h2>Audit history</h2><p>Recent changes across sales, products, expenses and settings.</p></div></div>
              <div id="audit-log"><div class="app-loading"><span class="spinner"></span><span>Loading audit history…</span></div></div>
            </section>
          </div>

          <div class="stack">
            <section class="card">
              <div class="card-header"><div><h2>Backup</h2><p>Create and download a consistent snapshot of the database.</p></div></div>
              <div class="card-body stack">
                <div id="backup-info"><div class="app-loading"><span class="spinner"></span><span>Reading backup info…</span></div></div>
                <div class="row-wrap">
                  <button class="btn btn-primary btn-sm" type="button" id="create-backup">${icon("database")} Create snapshot</button>
                  <a class="btn btn-secondary btn-sm" href="/api/backup/download">${icon("download")} Download database</a>
                  <button class="btn btn-ghost btn-sm" type="button" id="refresh-backup">${icon("refresh")} Refresh</button>
                </div>
                <div class="card-footer small muted" style="padding:0">Snapshots are written to the app's backups folder. Downloading creates a fresh snapshot and removes the temporary download file afterwards.</div>
              </div>
            </section>

            <section class="card">
              <div class="card-header"><div><h2>Restore</h2><p>Validate a SQLite backup before replacing the current database.</p></div></div>
              <div class="card-body stack">
                <div class="file-drop" id="backup-drop">
                  <span class="empty-icon">${icon("upload")}</span>
                  <div class="file-copy"><strong>Choose a database backup</strong><p>Maximum 250 MB. Validation checks integrity, required tables and migration version.</p></div>
                  <input type="file" id="backup-file" accept=".db,.sqlite,.sqlite3,application/x-sqlite3" aria-label="Choose a database backup file" />
                </div>
                <div id="backup-validation"></div>
                <button class="btn btn-danger btn-block" type="button" id="restore-backup" disabled>${icon("rotate")} Restore selected backup</button>
                <div class="inline-note warn">${icon("alert")}Restore replaces all current data. The app automatically creates a “before-restore” safety snapshot, and you must type REPLACE to confirm. Use Download database first for an extra copy.</div>
              </div>
            </section>

            <section class="card">
              <div class="card-header"><div><h2>Local security</h2><p>Keep this personal finance dashboard private.</p></div><span class="stat-icon">${icon("shield")}</span></div>
              <div class="card-body">
                <ul class="reason-list" style="flex-direction:column;gap:8px">
                  <li style="background:var(--surface-2);color:var(--text-2);border-color:var(--border)">Run the app on localhost only unless you add authentication and HTTPS.</li>
                  <li style="background:var(--surface-2);color:var(--text-2);border-color:var(--border)">Never expose this dashboard directly to a public network without access control.</li>
                  <li style="background:var(--surface-2);color:var(--text-2);border-color:var(--border)">Customer phone numbers are optional; avoid storing unnecessary personal data.</li>
                  <li style="background:var(--surface-2);color:var(--text-2);border-color:var(--border)">Keep regular backups on a trusted device or drive.</li>
                </ul>
              </div>
            </section>
          </div>
        </div>
      </div>`;

    function bindChipEditor(rootId, getValues, setValues) {
      const root = view.querySelector(`#${rootId}`);
      const chips = root.querySelector("[data-chips]");
      const input = root.querySelector("[data-chip-input]");

      function render() {
        chips.innerHTML = getValues().map((value) => chip(value)).join("");
        chips.querySelectorAll("[data-chip-remove]").forEach((button) =>
          button.addEventListener("click", () => {
            setValues(getValues().filter((value) => value !== button.closest("[data-chip]").dataset.chip));
            render();
          })
        );
      }

      function add() {
        const raw = input.value.trim().toLowerCase().replace(/\s+/g, "_");
        if (!raw) return;
        if (!getValues().includes(raw)) {
          setValues([...getValues(), raw]);
          render();
        }
        input.value = "";
        input.focus();
      }

      root.querySelector("[data-chip-add]").addEventListener("click", add);
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          add();
        }
      });
      render();
    }

    bindChipEditor(
      "payment-methods",
      () => paymentMethods,
      (values) => {
        paymentMethods = values;
      }
    );
    bindChipEditor(
      "expense-categories",
      () => expenseCategories,
      (values) => {
        expenseCategories = values;
      }
    );
    bindChipEditor(
      "money-in-categories",
      () => moneyInCategories,
      (values) => {
        moneyInCategories = values;
      }
    );
    bindChipEditor(
      "money-out-categories",
      () => moneyOutCategories,
      (values) => {
        moneyOutCategories = values;
      }
    );

    view.querySelector("#settings-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const errorBox = view.querySelector("#settings-error");
      errorBox.innerHTML = "";
      const name = view.querySelector("#business-name").value.trim();
      if (!name) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Business name is required.</div>`;
        return;
      }
      if (!paymentMethods.length || !expenseCategories.length) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Keep at least one payment method and one expense category.</div>`;
        return;
      }
      if (!moneyInCategories.length || !moneyOutCategories.length) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Keep at least one money-in and one money-out category.</div>`;
        return;
      }
      if (!expenseCategories.includes("inventory_purchase")) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Keep “Stock purchase” in the list; inventory receipts use it automatically.</div>`;
        return;
      }
      const lowStockRaw = view.querySelector("#default-low-stock").value;
      const lowStock = Number(lowStockRaw);
      if (!Number.isInteger(lowStock) || lowStock < 0) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Default low-stock threshold must be a whole number of zero or more.</div>`;
        return;
      }
      const clearOpenings = view.querySelector("#clear-openings").checked;
      const cashRaw = view.querySelector("#opening-cash").value.trim();
      const upiRaw = view.querySelector("#opening-upi").value.trim();
      const openingDate = view.querySelector("#opening-date").value;
      if (!clearOpenings && (cashRaw || upiRaw) && !openingDate) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}Choose an effective date for the opening balances.</div>`;
        return;
      }
      const button = view.querySelector("#save-settings");
      setBusy(button, true, "Saving…");
      try {
        await api.settings.update({
          business_name: name,
          payment_methods: paymentMethods,
          expense_categories: expenseCategories,
          money_in_categories: moneyInCategories,
          money_out_categories: moneyOutCategories,
          default_low_stock_threshold: lowStock,
          opening_cash_balance: clearOpenings || cashRaw === "" ? null : Number(cashRaw).toFixed(2),
          opening_upi_balance: clearOpenings || upiRaw === "" ? null : Number(upiRaw).toFixed(2),
          opening_balance_date: clearOpenings || !openingDate ? null : openingDate,
          clear_opening_balances: clearOpenings,
        });
        await refreshSettings();
        toast("Business preferences saved.", { title: "Settings updated" });
      } catch (error) {
        errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
      } finally {
        setBusy(button, false);
      }
    });

    async function loadQueue() {
      const slot = view.querySelector("#offline-queue");
      try {
        const operations = await pendingOperations();
        if (disposed) return;
        slot.innerHTML = operations.length
          ? `<div class="table-wrap"><table class="data compact">
              <thead><tr><th>Saved</th><th>Record</th><th class="num">Amount</th><th>Status</th><th class="num">Tries</th><th>Last error</th><th></th></tr></thead>
              <tbody>${operations.map(operationRow).join("")}</tbody>
            </table></div>`
          : `<div class="empty-state" style="padding:28px 16px"><span class="empty-icon">${icon("checkCircle")}</span><strong>Everything is synchronized</strong><p>New offline sales, expenses and money entries appear here until the server accepts them.</p></div>`;
        hydrateIcons(slot);
        slot.querySelectorAll("[data-discard]").forEach((button) =>
          button.addEventListener("click", () => discardOperation(button.dataset.discard))
        );
      } catch (error) {
        slot.innerHTML = `<div class="inline-note danger">${icon("alert")}Could not read the local queue: ${escapeHtml(error.message)}</div>`;
      }
    }

    async function discardOperation(id) {
      const operations = await pendingOperations();
      const operation = operations.find((item) => item.id === id);
      if (!operation) return;
      const proceed = await confirmDialog({
        title: "Discard this local record?",
        message: `<strong>${escapeHtml(OPERATION_LABELS[operation.kind] || operation.kind)}</strong> saved ${relativeTime(operation.createdAt)} will be permanently removed from this device and never sent to the server.`,
        confirmLabel: "Discard record",
        danger: true,
      });
      if (!proceed) return;
      await removeOperation(operation);
      toast("Local record discarded.", { type: "warn" });
      await loadQueue();
    }

    view.querySelector("#sync-now").addEventListener("click", async () => {
      const button = view.querySelector("#sync-now");
      setBusy(button, true, "Syncing…");
      try {
        await syncOutbox({ manual: true });
        await loadQueue();
        await refreshPendingCount();
        await loadSyncLog();
      } finally {
        setBusy(button, false);
      }
    });

    async function loadSyncLog() {
      const slot = view.querySelector("#sync-log");
      try {
        const data = await api.settings.syncOperations({ limit: 30 });
        if (disposed) return;
        slot.innerHTML = data.items?.length
          ? `<div class="table-wrap"><table class="data compact">
              <thead><tr><th>When</th><th>Entity</th><th>Operation</th><th>Status</th><th class="num">Tries</th><th>Error</th></tr></thead>
              <tbody>${data.items
                .map(
                  (item) => `<tr>
                  <td class="nowrap">${formatDateTime(item.synced_at || item.created_at)}</td>
                  <td>${escapeHtml(statusLabel(item.entity_type))} ${item.entity_id ? `#${escapeHtml(item.entity_id)}` : ""}</td>
                  <td>${escapeHtml(statusLabel(item.operation_type))}</td>
                  <td>${badge(item.status)}</td>
                  <td class="num">${num(item.attempts)}</td>
                  <td>${item.error ? `<span class="small negative">${escapeHtml(item.error)}</span>` : `<span class="muted">—</span>`}</td>
                </tr>`
                )
                .join("")}</tbody>
            </table></div>`
          : `<div class="empty-state" style="padding:26px 16px"><span class="empty-icon">${icon("shield")}</span><strong>No sync operations yet</strong><p>Idempotent replays and sync records appear here after local records are processed.</p></div>`;
        hydrateIcons(slot);
      } catch (error) {
        slot.innerHTML = `<div class="inline-note warn">${icon("cloudOff")}Sync log unavailable: ${escapeHtml(error.message)}</div>`;
      }
    }

    async function loadAudit() {
      const slot = view.querySelector("#audit-log");
      try {
        const entries = await api.settings.audit({ limit: 100 });
        if (disposed) return;
        slot.innerHTML = entries.length
          ? `<div class="table-wrap"><table class="data compact"><tbody>${entries.map(auditRow).join("")}</tbody></table></div>`
          : `<div class="empty-state" style="padding:26px 16px"><span class="empty-icon">${icon("list")}</span><strong>No audited changes yet</strong><p>Sales, payments, returns, stock, expenses and settings changes are recorded here.</p></div>`;
      } catch (error) {
        slot.innerHTML = `<div class="inline-note warn">${icon("cloudOff")}Audit history unavailable: ${escapeHtml(error.message)}</div>`;
      }
    }

    async function loadBackupInfo() {
      const slot = view.querySelector("#backup-info");
      try {
        const info = await api.backup.info();
        if (disposed) return;
        const counts = Object.entries(info.table_counts || {});
        slot.innerHTML = `<div class="key-value-list">
          <div><span>Database</span><span class="mono text-right" style="word-break:break-all">${escapeHtml(info.database_path)}</span></div>
          <div><span>Size</span><strong>${formatBytes(info.size_bytes)}</strong></div>
          <div><span>Last modified</span><strong>${info.last_modified ? formatDateTime(info.last_modified) : "Unknown"}</strong></div>
        </div>
        <div class="data-stat-grid" style="margin-top:12px">${counts
          .map(([table, count]) => `<div class="data-stat"><span>${escapeHtml(statusLabel(table))}</span><strong>${num(count)}</strong></div>`)
          .join("")}</div>`;
      } catch (error) {
        slot.innerHTML = `<div class="inline-note warn">${icon("cloudOff")}${escapeHtml(error.message)}</div>`;
      }
    }

    view.querySelector("#create-backup").addEventListener("click", async () => {
      const button = view.querySelector("#create-backup");
      setBusy(button, true, "Snapshotting…");
      try {
        const result = await api.backup.create();
        toast(`Snapshot ${result.filename} created (${formatBytes(result.size_bytes)}).`, { title: "Backup ready" });
        await loadBackupInfo();
      } catch (error) {
        toast(error.message, { type: "error", title: "Could not create backup" });
      } finally {
        setBusy(button, false);
      }
    });

    view.querySelector("#refresh-backup").addEventListener("click", loadBackupInfo);

    view.querySelector("#backup-file").addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      const slot = view.querySelector("#backup-validation");
      const restoreButton = view.querySelector("#restore-backup");
      selectedBackup = null;
      restoreButton.disabled = true;
      if (!file) {
        slot.innerHTML = "";
        return;
      }
      slot.innerHTML = `<div class="inline-note">${icon("clock")}Validating ${escapeHtml(file.name)}…</div>`;
      try {
        const result = await api.backup.validate(file);
        if (disposed) return;
        selectedBackup = file;
        restoreButton.disabled = false;
        slot.innerHTML = `<div class="alert alert-success">${icon("checkCircle")}<div><strong>Backup is valid</strong>${formatBytes(result.size_bytes)} · migration ${escapeHtml(result.alembic_version || "unknown")} · ${num(result.tables.length)} tables · integrity check passed.</div></div>`;
        hydrateIcons(slot);
      } catch (error) {
        slot.innerHTML = `<div class="alert alert-danger">${icon("xCircle")}<div><strong>Backup rejected</strong>${escapeHtml(error.message)}</div></div>`;
        hydrateIcons(slot);
      }
    });

    view.querySelector("#restore-backup").addEventListener("click", () => {
      if (!selectedBackup) return;
      const file = selectedBackup;
      const { root } = openModal({
        title: "Restore database backup",
        subtitle: `${file.name} · ${formatBytes(file.size)}`,
        body: `<div class="alert alert-danger">${icon("alert")}<div><strong>This replaces all current data</strong>Your current database will be replaced by this backup. A “before-restore” snapshot is created automatically, but download a copy first if you need certainty.</div></div>
          <div class="field" style="margin-top:14px"><label for="replace-confirm">Type REPLACE to confirm</label><input id="replace-confirm" autocomplete="off" spellcheck="false" placeholder="REPLACE" /><span class="hint">The restore only proceeds after validation and this exact confirmation.</span></div>
          <div id="restore-error"></div>`,
        footer: `<button class="btn btn-secondary" type="button" data-modal-close>Cancel</button><button class="btn btn-danger" type="button" id="confirm-restore" disabled>${icon("rotate")} Replace database</button>`,
      });
      const input = root.querySelector("#replace-confirm");
      const confirmButton = root.querySelector("#confirm-restore");
      input.addEventListener("input", () => {
        confirmButton.disabled = input.value !== "REPLACE";
      });
      confirmButton.addEventListener("click", async () => {
        const errorBox = root.querySelector("#restore-error");
        errorBox.innerHTML = "";
        if (input.value !== "REPLACE") return;
        setBusy(confirmButton, true, "Restoring…");
        try {
          const result = await api.backup.restore(file, "REPLACE");
          closeModal();
          toast(`Database restored. Safety snapshot: ${result.safety_backup}`, { title: "Restore complete", type: "warn" });
          setTimeout(() => window.location.reload(), 1600);
        } catch (error) {
          errorBox.innerHTML = `<div class="inline-note danger">${icon("alert")}${escapeHtml(error.message)}</div>`;
          setBusy(confirmButton, false);
        }
      });
    });

    await Promise.all([loadQueue(), loadSyncLog(), loadAudit(), loadBackupInfo()]);
    return () => {
      disposed = true;
    };
  },
};
