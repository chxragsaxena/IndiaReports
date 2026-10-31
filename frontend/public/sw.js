/* IndiaReports service worker.
 *
 * What it does: lets the app install and open instantly, and shows a friendly page when there is no network.
 * What it deliberately does NOT do:
 *   - cache the API or map tiles (they are on other origins, and stale reports would mislead),
 *   - queue reports for later (a report needs a live location check and duplicate warning).
 * Bump VERSION to drop every old cache on the next visit. */

const VERSION = "v1";
const SHELL = `indiareports-shell-${VERSION}`;
const ASSETS = `indiareports-assets-${VERSION}`;
const PRECACHE = ["/offline.html", "/icons/icon-192.png", "/favicon.svg"];

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((names) => Promise.all(names.filter((n) => n !== SHELL && n !== ASSETS).map((n) => caches.delete(n))))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== "GET" || url.origin !== self.location.origin) return; // the API and map tiles go straight to the network

    // Pages: the network first (so a new deploy shows at once), the last good copy if offline.
    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    const copy = response.clone();
                    caches.open(SHELL).then((cache) => cache.put("/", copy));
                    return response;
                })
                .catch(async () => (await caches.match("/")) || caches.match("/offline.html")),
        );
        return;
    }

    // Built files have a hash in their name, so a cached copy is never out of date.
    if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
        event.respondWith(
            caches.open(ASSETS).then(async (cache) => {
                const cached = await cache.match(request);
                if (cached) return cached;
                const response = await fetch(request);
                if (response.ok) cache.put(request, response.clone());
                return response;
            }),
        );
    }
});
