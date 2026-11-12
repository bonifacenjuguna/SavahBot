/* SavahBot service worker (1.3.8).
 *
 * Deliberately small. The dashboard is a live, signed-in tool, so there is nothing safe to keep for offline use. This worker exists for three reasons:
 *   1. a friendly "you are offline" page when the installed app is opened without a connection (instead of the browser's error page);
 *   2. broader install support (some browsers only treat a page with a service worker as installable);
 *   3. push notifications from Firebase Cloud Messaging: it shows them, and opens the right dashboard page when you tap one.
 *
 * Push messages carry only a title, a short body and an in-app route. Nothing sensitive is cached, and tapping a notification can only open
 * a dashboard page (a "#/..." route), never another site.
 *
 * What it caches: ONE static page, /offline.html. Nothing else, ever.
 * What it never touches, so authentication, the API and live events behave exactly as without it:
 *   - any request that is not a GET
 *   - any other origin (the backend API, Google Fonts, YouTube and so on)
 *   - same-origin /api/ paths, requests carrying an Authorization header, or a token in the address
 * Page loads always go to the network first. The offline page is only used when the network itself fails.
 */
"use strict";

const VERSION = "1.3.8";
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

// ------------------------------------------------------------------------------------------------ push
const ROUTE = /^#\/[A-Za-z0-9_\-/]{0,60}(\?[A-Za-z0-9_=&.\-%]{0,120})?$/;
const safeRoute = (r) => (typeof r === "string" && ROUTE.test(r) ? r : "#/notifications");

/** FCM wraps our data in { data: {...} }; accept that, a bare object, or a { notification } block. */
function readPayload(event) {
  if (!event.data) return null;
  let raw;
  try { raw = event.data.json(); } catch { return { title: "SavahBot", body: event.data.text().slice(0, 200) }; }
  const d = (raw && (raw.data || raw.notification)) || raw || {};
  return { title: String(d.title || "SavahBot").slice(0, 120), body: String(d.body || "").slice(0, 300), route: safeRoute(d.route), tag: String(d.tag || "").slice(0, 80), priority: d.priority, nid: d.nid, category: d.category };
}

self.addEventListener("push", (event) => {
  // A push with no readable content still has to show something: if a push handler shows nothing, Chrome adds its own generic
  // "SavahBot" notification (the stray one in the notification shade).
  const p = readPayload(event) || { title: "SavahBot", body: "Something needs a look.", route: "#/notifications", tag: "savahbot-generic", priority: "normal", nid: "", category: "" };
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    // Exactly the same test the page uses before it shows its own pop-up (visible AND focused), so one of the two always fires and never both.
    // Do not loosen this to "visible" alone: on a phone that hides the system alert while the dashboard is merely open in the background.
    const watching = wins.some((c) => c.visibilityState === "visible" && c.focused);
    wins.forEach((c) => c.postMessage({ type: "notify-push", nid: p.nid, category: p.category }));
    // You are looking at the dashboard: the bell and a toast already show it, so no second alert on top.
    // EXCEPT the explicit test notification: its whole purpose is to prove that a system notification appears, so it must show even
    // while the dashboard is open. (A tests/test_push_worker.py regression test pins this line. Do not drop the exception.)
    if (watching && p.category !== "test.test") return;
    await self.registration.showNotification(p.title, {
      body: p.body, icon: "/icon-192.png", badge: "/badge-96.png", tag: p.tag || undefined, renotify: !!p.tag,
      requireInteraction: p.priority === "critical", data: { route: p.route, nid: p.nid || "" }, timestamp: Date.now(),
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const route = safeRoute(event.notification.data && event.notification.data.route);
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const win = wins.find((c) => "focus" in c);
    if (win) {
      await win.focus();
      win.postMessage({ type: "notify-click", route, nid: event.notification.data && event.notification.data.nid });
      return;
    }
    await self.clients.openWindow(route.replace(/^#/, ""));   // the token "#/moderation" is the page "/moderation"
  })());
});

// The browser rotated or dropped the push subscription: tell an open dashboard to register again.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => wins.forEach((c) => c.postMessage({ type: "notify-resubscribe" }))));
});
