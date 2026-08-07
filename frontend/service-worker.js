const CACHE_NAME = "sparkchat-shell-v84";
const APP_SHELL = [
  "./",
  "./index.html",
  "./styles/base.css",
  "./styles/components.css",
  "./styles/views.css",
  "./styles/responsive.css",
  "./scripts/main.js",
  "./scripts/custom-select.js",
  "./scripts/api.js",
  "./scripts/dom.js",
  "./scripts/state.js",
  "./scripts/realtime-text.js",
  "./scripts/doubao-realtime.js",
  "./scripts/avatar-cropper.js",
  "./scripts/views/auth.js",
  "./scripts/views/home.js",
  "./scripts/views/chat.js",
  "./scripts/views/create.js",
  "./scripts/views/profile.js",
  "./manifest.webmanifest",
  "./assets/images/sparkchat-logo.png",
  "./assets/icons/icon-192.png",
  "./assets/icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await Promise.all(
        APP_SHELL.map(async (url) => {
          try {
            const response = await fetch(url, { cache: "no-cache" });
            if (response.ok) {
              await cache.put(url, response);
            }
          } catch (_error) {
          }
        })
      );
    })
  );
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
            event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put("./index.html", copy)));
          }
          return response;
        });

        if (cachedResponse) {
          event.waitUntil(networkResponse.catch(() => undefined));
          return cachedResponse;
        }
        return networkResponse.catch(() => caches.match("./index.html"));
      })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }

      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)));
        }
        return response;
      });
    })
  );
});
