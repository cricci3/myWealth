/* Service worker: every file of the app is cached at install, so it works fully offline.
 * A new version waits until the page asks for it ("Aggiorna"), never mid-entry.
 * It only ever serves this site's own files: there is no other network traffic. */
const VERSION = "1.1.0"; // keep in sync with APP_VERSION in js/app.js
const CACHE = `mywealth-${VERSION}`;
const FILES = [
  "./",
  "index.html",
  "app.css",
  "theme.js",
  "manifest.webmanifest",
  "js/app.js",
  "js/crypto.js",
  "js/csv.js",
  "js/pairing.js",
  "js/scanner.js",
  "js/store.js",
  "icons/icon.svg",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "icons/icon-maskable-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES.map((f) => new Request(f, { cache: "reload" })))));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    if (req.mode === "navigate") return (await cache.match("index.html")) || fetch(req);
    return (await cache.match(req, { ignoreSearch: true })) || fetch(req);
  })());
});
