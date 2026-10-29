import { closeModal, errorBlock, escapeHtml } from "./ui.js";

const PAGES = {
  dashboard: () => import("./pages/dashboard.js"),
  "new-sale": () => import("./pages/new-sale.js"),
  sales: () => import("./pages/sales.js"),
  inventory: () => import("./pages/inventory.js"),
  expenses: () => import("./pages/expenses.js"),
  "money-history": () => import("./pages/money-history.js"),
  reports: () => import("./pages/reports.js"),
  settings: () => import("./pages/settings.js"),
  "sale-detail": () => import("./pages/sale-detail.js"),
  "not-found": () => import("./pages/not-found.js"),
};

const SALE_DETAIL_PATH = /^\/sales\/(\d+)$/;

function readAppMeta() {
  try {
    return JSON.parse(document.getElementById("app-meta")?.textContent || "{}");
  } catch {
    return {};
  }
}

const APP_META = readAppMeta();
const APP_NAME = APP_META.appName || "College Cart Manager";
const BASE_URL = (APP_META.baseUrl || window.location.origin).replace(/\/+$/, "");
const ROUTE_META = APP_META.routes || {};
const NOT_FOUND_META = APP_META.notFound || {
  title: "Page not found",
  subtitle: "That address does not match any page in this app.",
  description: "The page you requested does not exist.",
  nav: "",
};
const SHARE_IMAGE = `${BASE_URL}/social/college-cart-share.png`;
const SHARE_IMAGE_ALT = "College Cart Manager — sales, inventory, money and expense tracking";

let activeCleanup = null;
let navigationToken = 0;

function normalizePathname(pathname) {
  if (!pathname || pathname === "/") return "/dashboard";
  const trimmed = pathname.replace(/\/+$/, "");
  return trimmed || "/dashboard";
}

function knownPath(path) {
  return Boolean(ROUTE_META[path]) || SALE_DETAIL_PATH.test(path);
}

function metaFor(path, route, params) {
  if (route === "sale-detail") {
    const saleId = params[0];
    return {
      path,
      nav: "sales",
      title: `Sale #${saleId}`,
      description: `Items, payments, returns, delivery and audit history for sale #${saleId} in College Cart Manager.`,
    };
  }
  const meta = ROUTE_META[path];
  if (meta) return { ...meta, path };
  return { ...NOT_FOUND_META, path, nav: "" };
}

function parseLocation() {
  const path = normalizePathname(window.location.pathname);
  const query = new URLSearchParams(window.location.search);
  if (path === "/dashboard") return { route: "dashboard", params: [], query, path };
  const sale = path.match(SALE_DETAIL_PATH);
  if (sale) return { route: "sale-detail", params: [sale[1]], query, path };
  const segment = path.slice(1);
  if (segment && PAGES[segment] && segment !== "sale-detail" && segment !== "not-found" && ROUTE_META[path]) {
    return { route: segment, params: [], query, path };
  }
  return { route: "not-found", params: [], query, path };
}

export function navigate(target, { replace = false } = {}) {
  if (!target) return;
  let next = String(target);
  if (next.startsWith("#")) {
    next = `/${next.replace(/^#\/?/, "")}`;
  } else if (!next.startsWith("/")) {
    next = `/${next}`;
  }
  const current = `${window.location.pathname}${window.location.search}`;
  if (next === current) {
    handleRoute();
    return;
  }
  if (replace) window.history.replaceState({}, "", next);
  else window.history.pushState({}, "", next);
  handleRoute();
}

function setActiveNav(route) {
  const navKey = route === "sale-detail" ? "sales" : route;
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === navKey);
    if (link.dataset.nav === navKey) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}

function upsertMeta(attribute, name, content) {
  let node = document.head.querySelector(`meta[${attribute}="${name}"]`);
  if (!node) {
    node = document.createElement("meta");
    node.setAttribute(attribute, name);
    document.head.appendChild(node);
  }
  node.setAttribute("content", content);
}

function setCanonical(url) {
  let link = document.getElementById("canonical-link");
  if (!url) {
    link?.remove();
    return;
  }
  if (!link) {
    link = document.createElement("link");
    link.id = "canonical-link";
    link.rel = "canonical";
    document.head.appendChild(link);
  }
  link.setAttribute("href", url);
}

function breadcrumbItems(route, meta) {
  const items = [{ name: "Dashboard", path: "/dashboard" }];
  if (route === "dashboard" || route === "not-found") return items;
  if (route === "sale-detail") {
    items.push({ name: "Sales History", path: "/sales" });
  }
  items.push({ name: meta.title, path: meta.path });
  return items;
}

function renderBreadcrumbs(items) {
  const nav = document.getElementById("breadcrumbs");
  if (!nav) return;
  if (items.length < 2) {
    nav.hidden = true;
    nav.innerHTML = "";
    return;
  }
  nav.hidden = false;
  nav.innerHTML = items
    .map((item, index) => {
      if (index === items.length - 1) {
        return `<span aria-current="page">${escapeHtml(item.name)}</span>`;
      }
      return `<a href="${escapeHtml(item.path)}">${escapeHtml(item.name)}</a><span aria-hidden="true">/</span>`;
    })
    .join("");
}

function renderBreadcrumbSchema(items, route) {
  const node = document.getElementById("breadcrumb-jsonld");
  if (!node) return;
  if (route === "not-found" || !items.length) {
    node.textContent = "null";
    return;
  }
  node.textContent = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: item.name,
      item: `${BASE_URL}${item.path}`,
    })),
  });
}

function applyMetadata(route, meta) {
  const title = `${meta.title} · ${APP_NAME}`;
  const url = `${BASE_URL}${meta.path}`;
  const robots = "noindex, nofollow";

  document.title = title;
  upsertMeta("name", "description", meta.description);
  upsertMeta("name", "robots", robots);
  upsertMeta("property", "og:title", title);
  upsertMeta("property", "og:description", meta.description);
  upsertMeta("property", "og:url", route === "not-found" ? `${BASE_URL}${window.location.pathname}` : url);
  upsertMeta("property", "og:image", SHARE_IMAGE);
  upsertMeta("property", "og:image:alt", SHARE_IMAGE_ALT);
  upsertMeta("name", "twitter:title", title);
  upsertMeta("name", "twitter:description", meta.description);
  upsertMeta("name", "twitter:image", SHARE_IMAGE);
  upsertMeta("name", "twitter:image:alt", SHARE_IMAGE_ALT);
  setCanonical(route === "not-found" ? "" : url);

  const items = breadcrumbItems(route, meta);
  renderBreadcrumbs(items);
  renderBreadcrumbSchema(items, route);
}

async function handleRoute() {
  const token = ++navigationToken;
  closeModal();
  if (typeof activeCleanup === "function") {
    try {
      activeCleanup();
    } catch (error) {
      console.warn("Page cleanup failed", error);
    }
    activeCleanup = null;
  }

  const { route, params, query, path } = parseLocation();
  const meta = metaFor(path, route, params);
  const view = document.getElementById("view");
  const titleNode = document.getElementById("page-title");
  const subtitleNode = document.getElementById("page-subtitle");
  const appShell = document.getElementById("app-shell");
  appShell.classList.remove("nav-open");
  document.getElementById("menu-toggle")?.setAttribute("aria-expanded", "false");
  document.getElementById("mobile-more-sheet")?.setAttribute("hidden", "");
  setActiveNav(route);
  applyMetadata(route, meta);
  titleNode.textContent = meta.title;
  subtitleNode.textContent = meta.subtitle || "";
  view.innerHTML = `<div class="app-loading"><span class="spinner" aria-hidden="true"></span><span>Loading…</span></div>`;
  window.scrollTo({ top: 0 });

  try {
    const module = await PAGES[route]();
    if (token !== navigationToken) return;
    const page = module.default;
    if (page.subtitle) subtitleNode.textContent = page.subtitle;
    const maybeCleanup = await page.render(view, { params, query, route, path, navigate, titleNode, subtitleNode });
    if (token !== navigationToken) {
      if (typeof maybeCleanup === "function") maybeCleanup();
      return;
    }
    activeCleanup = typeof maybeCleanup === "function" ? maybeCleanup : null;
  } catch (error) {
    if (token !== navigationToken) return;
    console.error(error);
    view.innerHTML = errorBlock(error?.message || "Unexpected error while loading this page.");
    document.getElementById("retry-load")?.addEventListener("click", handleRoute);
    document.title = `Something went wrong · ${APP_NAME}`;
    titleNode.textContent = "Something went wrong";
    subtitleNode.textContent = "The application shell is still available.";
    setCanonical("");
    upsertMeta("name", "robots", "noindex, nofollow");
  }
}

function shouldHandleLink(event, anchor) {
  if (event.defaultPrevented || event.button !== 0) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  if (!anchor || anchor.target || anchor.hasAttribute("download")) return false;
  const rawHref = anchor.getAttribute("href") || "";
  if (!rawHref || rawHref.startsWith("#")) return false;
  const url = new URL(anchor.href, window.location.href);
  if (url.origin !== window.location.origin) return false;
  if (url.pathname.startsWith("/api/")) return false;
  return knownPath(normalizePathname(url.pathname));
}

function setupLinkInterception() {
  document.addEventListener("click", (event) => {
    const anchor = event.target.closest("a[href]");
    if (!shouldHandleLink(event, anchor)) return;
    const url = new URL(anchor.href, window.location.href);
    event.preventDefault();
    navigate(`${url.pathname}${url.search}`);
  });
}

function redirectLegacyHash() {
  if (!window.location.hash.startsWith("#/")) return false;
  const target = `/${window.location.hash.replace(/^#\/?/, "")}`;
  window.history.replaceState({}, "", target);
  return true;
}

export function startRouter() {
  window.addEventListener("popstate", handleRoute);
  window.addEventListener("hashchange", () => {
    if (redirectLegacyHash()) handleRoute();
  });
  setupLinkInterception();
  if (!redirectLegacyHash()) {
    if (window.location.pathname === "/") {
      window.history.replaceState({}, "", `/dashboard${window.location.search}`);
    }
  }
  handleRoute();
}
