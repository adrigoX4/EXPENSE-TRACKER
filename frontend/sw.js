const CACHE_NAME = "college-cart-shell-v16";
const SHELL = [
  "/dashboard",
  "/index.html",
  "/css/app.css",
  "/js/main.js",
  "/js/router.js",
  "/js/api.js",
  "/js/db.js",
  "/js/store.js",
  "/js/sync.js",
  "/js/ui.js",
  "/js/auth.js",
  "/js/pages/dashboard.js",
  "/js/pages/new-sale.js",
  "/js/pages/sales.js",
  "/js/pages/sale-detail.js",
  "/js/pages/inventory.js",
  "/js/pages/expenses.js",
  "/js/pages/money-history.js",
  "/js/pages/reports.js",
  "/js/pages/settings.js",
  "/js/pages/not-found.js",
  "/manifest.webmanifest",
  "/favicon.ico",
  "/icons/app-icon.svg",
  "/icons/favicon-32.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(request, fallbackUrl) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    if (fallbackUrl) {
      const fallback = await caches.match(fallbackUrl);
      if (fallback) return fallback;
    }
    return new Response("Offline. The application shell is not cached yet.", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, "/index.html"));
    return;
  }

  if (
    url.pathname.endsWith(".js") ||
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".svg") ||
    url.pathname.endsWith(".webmanifest") ||
    url.pathname.endsWith(".png")
  ) {
    event.respondWith(networkFirst(request));
  }
});
