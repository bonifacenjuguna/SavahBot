/* SavahBot service worker (1.1.9).
 *
 * Deliberately small. The dashboard is a live, signed-in tool, so there is nothing safe to keep for offline use. This worker exists for two reasons:
 *   1. a friendly "you are offline" page when the installed app is opened without a connection (instead of the browser's error page);
 *   2. broader install support (some browsers only treat a page with a service worker as installable).
 *
 * What it caches: ONE static page, /offline.html. Nothing else, ever.
 * What it never touches, so authentication, the API and live events behave exactly as without it:
 *   - any request that is not a GET
 *   - any other origin (the backend API, Google Fonts, YouTube and so on)
 *   - same-origin /api/ paths, requests carrying an Authorization header, or a token in the address
 * Page loads always go to the network first. The offline page is only used when the network itself fails.
 */
"use strict";

const VERSION = "1.1.9";
const CACHE = `savahbot-offline-${VERSION}`;
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // remove caches from any earlier version of this worker
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n.startsWith("savahbot-") && n !== CACHE).map((n) => caches.delete(n)));
    // faster page loads: let the browser start the network request while this worker wakes up
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable().catch(() => undefined);
    await self.clients.claim();
  })());
});

function sensitive(request, url) {
  return request.headers.has("authorization")
    || url.pathname.startsWith("/api/")
    || /[?&](token|access_token|auth|key)=/i.test(url.search);
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate") return; // everything except page loads goes straight to the network
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || sensitive(request, url)) return;

  event.respondWith((async () => {
    try {
      const preloaded = await event.preloadResponse;
      return preloaded || await fetch(request);
    } catch {
      // the network failed (not a server error): show the offline page
      const cache = await caches.open(CACHE);
      return (await cache.match(OFFLINE_URL)) || Response.error();
    }
  })());
});
