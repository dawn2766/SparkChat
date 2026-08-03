const CACHE_NAME = "sparkchat-shell-v3";
const APP_SHELL = [
  "./",
  "./index.html",
  "./styles/app.css",
  "./styles/base.css",
  "./styles/components.css",
  "./styles/views.css",
  "./styles/responsive.css",
  "./scripts/main.js",
  "./scripts/api.js",
  "./scripts/dom.js",
  "./scripts/state.js",
  "./scripts/avatar-cropper.js",
  "./scripts/doubao-realtime.js",
  "./scripts/realtime-text.js",
  "./scripts/views/auth.js",
  "./scripts/views/chat.js",
  "./scripts/views/create.js",
  "./scripts/views/home.js",
  "./scripts/views/profile.js",
  "./manifest.webmanifest",
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
    event.respondWith(fetch(request).catch(() => caches.match("./index.html")));
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
