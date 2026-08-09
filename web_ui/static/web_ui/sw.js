// Minimal service worker: precache static assets (icons/CSS/manifest) and
// stale-while-revalidate for the JS bundle.
//
// HTML navigations (/, /login/, …) are network-first and are NOT precached — they
// embed CSRF tokens; cache-first HTML caused logout failures after deploys.
// Offline launch therefore has no HTML shell (intentional CSRF tradeoff).
//
// Routing rules are mirrored in web_ui/static/web_ui/ts/swRouting.ts (vitest).

const VERSION = "my-tracks-pwa-v6";
const PRECACHE = [
  "/static/web_ui/manifest.webmanifest",
  "/static/web_ui/icons/icon-192.png",
  "/static/web_ui/icons/icon-512.png",
  "/static/web_ui/icons/app-icon.svg",
  "/static/web_ui/css/main.css",
];

function isMainBundlePath(pathname) {
  return (
    pathname.endsWith("/main.js") ||
    /\/static\/web_ui\/js\/main\.[a-f0-9]+\.js$/.test(pathname)
  );
}

function shouldBypassServiceWorker(pathname) {
  return pathname.startsWith("/api/") || pathname.startsWith("/ws/");
}

function isShellHtmlPath(pathname) {
  return (
    pathname === "/" ||
    pathname === "/login/" ||
    pathname === "/logout/" ||
    pathname === "/profile/" ||
    pathname === "/geofences/" ||
    pathname === "/admin-panel/" ||
    pathname === "/about/"
  );
}

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(VERSION).then((cache) => cache.addAll(PRECACHE)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => {
          if (key !== VERSION) {
            return caches.delete(key);
          }
          return undefined;
        }),
      ),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") {
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  // Live API/WebSocket traffic must not go through cache-first handling — a failed
  // network fetch here surfaces as "network error" in the Last Known UI.
  if (shouldBypassServiceWorker(url.pathname)) {
    return;
  }

  // Document navigations and known HTML shells must always prefer the network so
  // CSRF tokens and new deploys are not stuck behind a stale precache.
  if (request.mode === "navigate" || isShellHtmlPath(url.pathname)) {
    event.respondWith(
      fetch(request).catch(() => caches.match(request).then((hit) => hit ?? Response.error())),
    );
    return;
  }

  if (isMainBundlePath(url.pathname)) {
    event.respondWith(
      caches.open(VERSION).then(async (cache) => {
        const cached = await cache.match(request);
        const network = fetch(request)
          .then((response) => {
            if (response.ok) {
              void cache.put(request, response.clone());
            }
            return response;
          })
          .catch(() => cached);
        return (await network) ?? cached ?? Response.error();
      }),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => hit ?? fetch(request)),
  );
});
