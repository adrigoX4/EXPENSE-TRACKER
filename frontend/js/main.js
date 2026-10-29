import { hydrateIcons, initials, toast } from "./ui.js";
import { startRouter } from "./router.js";
import { syncOutbox, startAutoSync } from "./sync.js";
import { setOfflineUser } from "./db.js";
import {
  getState,
  initStore,
  setOnline,
  subscribe,
} from "./store.js";

let businessSchemaSynced = false;

function readAppMeta() {
  try {
    return JSON.parse(document.getElementById("app-meta")?.textContent || "{}");
  } catch {
    return {};
  }
}

const APP_META = readAppMeta();

function redirectToAuth() {
  const next = `${window.location.pathname}${window.location.search}`;
  const target = APP_META.hasAccounts ? `/login?next=${encodeURIComponent(next)}` : "/signup";
  window.location.replace(target);
}

async function signOut() {
  const button = document.getElementById("account-logout");
  if (button) button.disabled = true;
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    /* the cookie is short-lived; still return to the sign-in page */
  }
  window.location.replace("/login");
}

function renderAccount(user) {
  if (!user) return;
  const card = document.getElementById("account-card");
  const email = document.getElementById("account-email");
  const avatar = document.getElementById("account-avatar");
  if (card) card.hidden = false;
  if (email) {
    email.textContent = user.email;
    email.title = user.email;
  }
  if (avatar) avatar.textContent = initials(user.email);
  document.getElementById("account-logout")?.addEventListener("click", signOut);
}

function formatToday() {
  return new Date().toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function syncBusinessSchema(name) {
  if (businessSchemaSynced || !name) return;
  const node = document.getElementById("local-business-jsonld");
  if (!node) return;
  try {
    const data = JSON.parse(node.textContent || "{}");
    if (data && data["@type"] === "LocalBusiness") {
      data.name = name;
      node.textContent = JSON.stringify(data);
    }
  } catch {
    /* keep the server-rendered schema */
  }
  businessSchemaSynced = true;
}

function updateConnectionUi(state) {
  const online = state.online && state.serverReachable !== false;
  const sidebarPill = document.getElementById("sidebar-connection");
  const topbarPill = document.getElementById("topbar-connection");
  const label = state.syncing
    ? "Synchronizing…"
    : !state.online
      ? "Offline — entries saved locally"
      : state.serverReachable === false
        ? "Server unreachable — local mode"
        : "Online — connected";

  [sidebarPill, topbarPill].forEach((pill) => {
    if (!pill) return;
    pill.classList.toggle("online", online && !state.syncing);
    pill.classList.toggle("offline", !online);
    pill.classList.toggle("pending", state.syncing);
    const text = pill.querySelector(".connection-label");
    if (text) {
      text.textContent =
        pill === topbarPill
          ? state.syncing
            ? "Syncing"
            : online
              ? "Online"
              : "Offline"
          : label;
    }
  });

  const syncLabel = document.getElementById("sidebar-sync-label");
  const syncRow = document.getElementById("sidebar-sync");
  syncRow?.classList.toggle("syncing", Boolean(state.syncing));
  if (syncLabel) {
    if (state.syncing) syncLabel.textContent = "Synchronizing local records…";
    else if (state.pendingCount > 0) {
      syncLabel.textContent = `${state.pendingCount} record${state.pendingCount === 1 ? "" : "s"} pending sync`;
    } else syncLabel.textContent = "All changes saved";
  }

  const pendingBadge = document.getElementById("nav-pending-sales");
  if (pendingBadge) {
    pendingBadge.hidden = !state.pendingCount;
    pendingBadge.textContent = state.pendingCount ? String(state.pendingCount) : "";
    pendingBadge.title = `${state.pendingCount} local change(s) awaiting synchronization`;
  }

  const lowStockCount = state.products.filter(
    (product) => product.is_active && Number(product.stock_quantity) <= Number(product.low_stock_threshold)
  ).length;
  const lowBadge = document.getElementById("nav-low-stock");
  if (lowBadge) {
    lowBadge.hidden = lowStockCount === 0;
    lowBadge.textContent = lowStockCount ? String(lowStockCount) : "";
    lowBadge.title = `${lowStockCount} low-stock product(s)`;
  }

  const brandName = document.getElementById("brand-name");
  if (brandName && state.settings?.business_name) brandName.textContent = state.settings.business_name;
  syncBusinessSchema(state.settings?.business_name);
}

function setupNavigation() {
  const shell = document.getElementById("app-shell");
  const menuToggle = document.getElementById("menu-toggle");

  menuToggle?.addEventListener("click", () => {
    const open = shell.classList.toggle("nav-open");
    menuToggle.setAttribute("aria-expanded", String(open));
  });

  document.querySelectorAll(".nav-link, .mobile-link[href], .sheet-link").forEach((link) => {
    link.addEventListener("click", () => {
      shell.classList.remove("nav-open");
      menuToggle?.setAttribute("aria-expanded", "false");
      document.getElementById("mobile-more-sheet")?.setAttribute("hidden", "");
    });
  });

  document.addEventListener("click", (event) => {
    if (shell.classList.contains("nav-open")) {
      const insideSidebar = event.target.closest("#sidebar");
      if (!insideSidebar && !event.target.closest("#menu-toggle")) {
        shell.classList.remove("nav-open");
        menuToggle?.setAttribute("aria-expanded", "false");
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      shell.classList.remove("nav-open");
      menuToggle?.setAttribute("aria-expanded", "false");
      document.getElementById("mobile-more-sheet")?.setAttribute("hidden", "");
    }
  });

  const moreButton = document.getElementById("mobile-more");
  const moreSheet = document.getElementById("mobile-more-sheet");
  const moreClose = document.getElementById("mobile-more-close");
  const openSheet = () => {
    if (!moreSheet) return;
    moreSheet.hidden = false;
    moreButton?.setAttribute("aria-expanded", "true");
  };
  const closeSheet = () => {
    if (!moreSheet) return;
    moreSheet.hidden = true;
    moreButton?.setAttribute("aria-expanded", "false");
  };
  moreButton?.addEventListener("click", () => (moreSheet.hidden ? openSheet() : closeSheet()));
  moreClose?.addEventListener("click", closeSheet);
  moreSheet?.addEventListener("click", (event) => {
    if (event.target === moreSheet) closeSheet();
  });
}

function setupSyncControls() {
  const trigger = () => syncOutbox({ manual: true });
  document.getElementById("sidebar-sync")?.addEventListener("click", trigger);
  document.getElementById("topbar-sync")?.addEventListener("click", trigger);
}

function setupConnectivity() {
  window.addEventListener("online", () => {
    setOnline(true);
    toast("Connection restored. Pending local records will sync automatically.", { type: "info" });
    syncOutbox({ silent: true });
  });
  window.addEventListener("offline", () => {
    setOnline(false);
    toast("You are offline. New sales, expenses and money entries are saved on this device.", {
      type: "warn",
      title: "Local mode enabled",
    });
  });
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (window.location.protocol !== "https:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    return;
  }
  try {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch (error) {
    console.warn("Service worker registration failed", error);
  }
}

function currentAppPath() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/dashboard";
  if (path === "/dashboard" || APP_META.routes?.[path]) return path;
  if (/^\/sales\/\d+$/.test(path)) return path;
  return null;
}

async function boot() {
  if (!APP_META.authenticated || !APP_META.user?.id) {
    if (currentAppPath()) {
      redirectToAuth();
      return;
    }
    startRouter();
    registerServiceWorker();
    return;
  }

  setOfflineUser(APP_META.user.id);
  renderAccount(APP_META.user);
  hydrateIcons(document);
  const todayChip = document.getElementById("today-chip");
  if (todayChip) todayChip.textContent = formatToday();

  setupNavigation();
  setupSyncControls();
  setupConnectivity();
  subscribe(updateConnectionUi);
  updateConnectionUi(getState());

  try {
    await initStore();
  } catch (error) {
    console.error("Store initialization failed", error);
  }
  updateConnectionUi(getState());

  startRouter();
  startAutoSync();
  registerServiceWorker();

  window.addEventListener("store:change", () => {
    updateConnectionUi(getState());
  });

  if (getState().pendingCount > 0 && navigator.onLine) {
    setTimeout(() => syncOutbox({ silent: true }), 1500);
  }
}

boot();
