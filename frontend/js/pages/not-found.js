import { icon } from "../ui.js";

export default {
  title: "Page not found",
  subtitle: "That address does not match any page in this app.",
  async render(view) {
    view.innerHTML = `
      <div class="stack">
        <section class="card">
          <div class="empty-state not-found-state">
            <span class="empty-icon">${icon("alert")}</span>
            <strong>This page does not exist</strong>
            <p>The address may have a typo or the link may be out of date. Your records have not been changed.</p>
            <div class="row-wrap">
              <a class="btn btn-primary" href="/dashboard">${icon("dashboard")} Go to Dashboard</a>
              <a class="btn btn-secondary" href="/sales">${icon("receipt")} Sales History</a>
              <a class="btn btn-secondary" href="/money-history">${icon("wallet")} Money History</a>
            </div>
          </div>
        </section>
        <section class="card">
          <div class="card-header">
            <div><h2>Common pages</h2><p>Everything in the tracker is still one click away.</p></div>
          </div>
          <div class="card-body">
            <div class="row-wrap">
              <a class="btn btn-ghost btn-sm" href="/new-sale">${icon("cart")} New Sale</a>
              <a class="btn btn-ghost btn-sm" href="/inventory">${icon("package")} Inventory</a>
              <a class="btn btn-ghost btn-sm" href="/expenses">${icon("banknote")} Expenses</a>
              <a class="btn btn-ghost btn-sm" href="/reports">${icon("chart")} Reports</a>
              <a class="btn btn-ghost btn-sm" href="/settings">${icon("settings")} Settings &amp; Backup</a>
            </div>
          </div>
        </section>
      </div>`;
  },
};
