// Minimal service worker: installability plus a faster, offline-tolerant shell.
// Only same-origin GETs are touched, so the API (Cloud Run) and Firestore are never cached.
const CACHE = "corridor-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) =>
  e.waitUntil(
    caches
      .keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  ),
);

const keep = (key, res) => {
  if (res.ok) {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(key, copy));
  }
  return res;
};

self.addEventListener("fetch", (e) => {
  const r = e.request;
  const u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin) return;
  if (u.pathname.startsWith("/assets/")) {
    // hashed filenames never change: cache first
    e.respondWith(caches.match(r).then((hit) => hit || fetch(r).then((res) => keep(r, res))));
  } else if (r.mode === "navigate") {
    // every route is the same index.html (hosting rewrite): network first, the stored copy when offline
    e.respondWith(
      fetch(r)
        .then((res) => keep("/", res))
        .catch(() => caches.match("/")),
    );
  }
});
