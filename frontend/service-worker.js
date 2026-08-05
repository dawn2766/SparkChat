const CACHE_NAME = "sparkchat-shell-v38";
const APP_SHELL = [
  "./",
  "./index.html",
  "./styles/base.css",
  "./styles/components.css",
  "./styles/views.css",
  "./styles/responsive.css",
  "./scripts/main.js",
  "./scripts/api.js",
  "./scripts/dom.js",
  "./scripts/state.js",
  "./scripts/realtime-text.js",
  "./scripts/views/auth.js",
  "./scripts/views/home.js",
  "./manifest.webmanifest",
  "./assets/images/sparkchat-logo.png",
  "./assets/icons/icon-192.png",
  "./assets/icons/icon-512.png",
  "./assets/images/megatron-portrait.jpg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.includes("/api/")) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      caches.match("./index.html").then((cachedResponse) => {
        const networkResponse = fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put("./index.html", copy));
          }
          return response;
        });
        return cachedResponse || networkResponse.catch(() => caches.match("./index.html"));
      })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      const networkResponse = fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      });

      event.waitUntil(networkResponse.catch(() => undefined));

      return cachedResponse || networkResponse;
    })
  );
});
