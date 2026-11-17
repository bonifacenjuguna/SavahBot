/* SavahBot service worker (1.4.11).
 *
 * The dashboard is a live, signed-in tool. This worker makes the installed app feel native without ever holding your data:
 *   1. App shell: the build's own files (/assets/*, which are public code with the version in their name) are kept after first use, and the last page
 *      HTML is kept, so the installed app opens and draws even with no connection. If there is no shell yet, a friendly /offline.html is shown.
 *   2. Updates wait: a new worker does NOT take over in the middle of a session. The page shows "A new version is ready" and sends skip-waiting.
 *   3. Push notifications from Firebase Cloud Messaging: it shows them, sets the app icon badge, and opens the right page when you tap one.
 *      An approval request has Approve / Reject buttons that work from the notification itself, using a short-lived signed link in the push
 *      (never your sign-in token): the server checks it, refuses it during lockdown, and it can decide that one request only.
 *   4. Background Sync: notes, quotes and clock-time reminders saved offline are sent when the connection returns (see outbox.ts).
 *   5. Periodic Background Sync (Chrome, installed app): refreshes the number on the app icon with a read-only link that can only read the waiting count.
 *
 * Push messages carry a title, a short body, an in-app route, a waiting count and (for approvals) a signed link. Tapping a notification can only open a
 * dashboard page (a "#/..." route), never another site.
 *
 * What it never touches, so authentication, the API and live events behave exactly as without it:
 *   - any request that is not a GET page load or a /assets/ file
 *   - any other origin (the backend API, Google Fonts, YouTube and so on)
 *   - same-origin /api/ paths, requests carrying an Authorization header, or a token in the address
 * Pages are always fetched from the network first; the saved shell is used only when the network itself fails.
 * It keeps NO API answers: the dashboard's own offline copy (offline.ts) lives in IndexedDB and is wiped on sign-out.
 */
"use strict";

const VERSION = "1.4.12";
const CACHE = `savahbot-offline-${VERSION}`;           // the offline page and the last app shell: replaced with each version
const ASSETS = "savahbot-assets";                       // the build's hashed files: a file name never changes its content, so this survives updates
const MAX_ASSETS = 160;
const OFFLINE_URL = "/offline.html";
const SHELL_URL = "/index.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then(async (cache) => {
        await cache.add(new Request(OFFLINE_URL, { cache: "reload" }));
        // keep the app shell from the very first install, so the next time offline the app opens (the page HTML is public and the same for everyone)
        try {
          const home = await fetch("/", { cache: "reload" });
          if (home.ok && (home.headers.get("content-type") || "").includes("text/html")) await cache.put(SHELL_URL, home);
        } catch { /* no shell yet: the offline page is the fallback */ }
      })
      // the very first install starts at once; an update waits until the page asks (message "skip-waiting"), so a session is never swapped under you
      .then(() => { if (!self.registration.active) return self.skipWaiting(); })
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "skip-waiting") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    // remove caches from any earlier version of this worker
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n.startsWith("savahbot-") && n !== CACHE && n !== ASSETS).map((n) => caches.delete(n)));
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

async function trimAssets(cache) {
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_ASSETS)).map((k) => cache.delete(k)));     // oldest first
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;                                       // everything except GET goes straight to the network
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || sensitive(request, url)) return;

  // the build's own files: public, named by content, so the saved copy is always right
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith((async () => {
      const cache = await caches.open(ASSETS);
      const hit = await cache.match(request);
      if (hit) return hit;
      const res = await fetch(request);
      if (res.ok && res.type === "basic") { cache.put(request, res.clone()).then(() => trimAssets(cache)).catch(() => undefined); }
      return res;
    })());
    return;
  }
  if (request.mode !== "navigate") return;

  event.respondWith((async () => {
    try {
      const preloaded = await event.preloadResponse;
      const res = preloaded || await fetch(request);
      // keep the latest page HTML (a public file, the same for everyone) so the app can open offline
      if (res.ok && (res.headers.get("content-type") || "").includes("text/html") && url.pathname !== OFFLINE_URL) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(SHELL_URL, copy)).catch(() => undefined);
      }
      return res;
    } catch {
      // the network failed (not a server error): the saved app shell if there is one, otherwise the offline page
      const cache = await caches.open(CACHE);
      return (await cache.match(SHELL_URL)) || (await cache.match(OFFLINE_URL)) || Response.error();
    }
  })());
});

// ------------------------------------------------------------------------------------------------ push
const ROUTE = /^#\/[A-Za-z0-9_\-/]{0,60}(\?[A-Za-z0-9_=&.\-%]{0,120})?$/;
const ACT_TOKEN = /^act\.\d{1,12}\.\d{9,12}\.[A-Za-z0-9_-]{16,40}$/;       // the signed link on an approval request
const safeRoute = (r) => (typeof r === "string" && ROUTE.test(r) ? r : "#/notifications");

/** FCM wraps our data in { data: {...} }; accept that, a bare object, or a { notification } block. */
function readPayload(event) {
  if (!event.data) return null;
  let raw;
  try { raw = event.data.json(); } catch { return { title: "SavahBot", body: event.data.text().slice(0, 200) }; }
  const d = (raw && (raw.data || raw.notification)) || raw || {};
  return { title: String(d.title || "SavahBot").slice(0, 120), body: String(d.body || "").slice(0, 300), route: safeRoute(d.route), tag: String(d.tag || "").slice(0, 80), priority: d.priority, nid: d.nid, category: d.category,
    pending: d.pending !== undefined && d.pending !== "" && Number.isFinite(+d.pending) ? Math.max(0, Math.min(9999, Math.floor(+d.pending))) : null,
    atk: typeof d.atk === "string" && ACT_TOKEN.test(d.atk) ? d.atk : "" };
}

self.addEventListener("push", (event) => {
  // a quiet placeholder left over from the last push is no longer needed
  event.waitUntil(self.registration.getNotifications({ tag: "savahbot-quiet" }).then((l) => l.forEach((n) => n.close())).catch(() => undefined));
  // A push with no readable content still has to show something: if a push handler shows nothing, Chrome adds its own generic
  // "SavahBot" notification (the stray one in the notification shade).
  const p = readPayload(event) || { title: "SavahBot", body: "Something needs a look.", route: "#/notifications", tag: "savahbot-generic", priority: "normal", nid: "", category: "" };
  event.waitUntil((async () => {
    await setBadge(p.pending);          // the number on the app icon follows the waiting count the server sent
    // Chrome requires every push to end in a visible notification. If the worker shows nothing (or throws before it does), Chrome adds its
    // own grey "SavahBot" notification in the Silent section, with "Open in browser" / "Share URL" buttons. So this block ALWAYS shows one.
    let shown = false;
    try {
      const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      // Exactly the same test the page uses before it shows its own pop-up (visible AND focused), so one of the two always fires and never both.
      // Do not loosen this to "visible" alone: on a phone that hides the system alert while the dashboard is merely open in the background.
      const watching = wins.some((c) => c.visibilityState === "visible" && c.focused);
      wins.forEach((c) => c.postMessage({ type: "notify-push", nid: p.nid, category: p.category }));
      // You are looking at the dashboard: the bell and a toast already show it, so no second alert on top.
      // EXCEPT the explicit test notification: its whole purpose is to prove that a system notification appears, so it must show even
      // while the dashboard is open. (A tests/test_push_worker.py regression test pins this line. Do not drop the exception.)
      if (watching && p.category !== "test.test") {
        // 1.4.0: skipping the alert used to make Chrome post its own generic one. Show a silent placeholder and take it down at once
        // instead: that satisfies Chrome, and you only see the dashboard's own pop-up.
        // 1.4.9: it must still be on screen when this push event ends: Chrome counts the visible notifications at that moment and posts its own
        // grey "SavahBot" one if there are none, and closing it here after 50 ms was exactly that. The open dashboard removes it a moment later
        // (closeQuietNotifications in push.ts), and every later push or start-up clears any that were left behind.
        await self.registration.showNotification(p.title, { body: "", tag: "savahbot-quiet", silent: true, icon: "/icon-192.png", badge: "/badge-96.png" });
        shown = true;
        return;
      }
      await self.registration.showNotification(p.title, {
        body: p.body, icon: "/icon-192.png", badge: "/badge-96.png", tag: p.tag || undefined, renotify: !!p.tag,
        requireInteraction: p.priority === "critical", data: { route: p.route, nid: p.nid || "", atk: p.atk || "" }, timestamp: Date.now(),
        // an approval request can be decided from the notification itself (Android and desktop; iOS ignores buttons)
        actions: p.atk ? [{ action: "approve", title: "Approve" }, { action: "reject", title: "Reject" }] : [],
      });
      shown = true;
    } finally {
      if (!shown) await self.registration.showNotification(p.title, { body: p.body, icon: "/icon-192.png", badge: "/badge-96.png", data: { route: p.route, nid: p.nid || "" } });
    }
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const route = safeRoute(event.notification.data && event.notification.data.route);
  const verb = event.action === "approve" || event.action === "reject" ? event.action : "";
  const atk = event.notification.data && typeof event.notification.data.atk === "string" ? event.notification.data.atk : "";
  if (verb && ACT_TOKEN.test(atk)) { event.waitUntil(decide(verb, atk, route, event.notification.title)); return; }
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

// ------------------------------------------------------------------------------------------------ small shared database (same names as src/idb.ts)
function db() {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open("savahbot-pwa", 1);
      req.onupgradeneeded = () => {
        const d = req.result;
        for (const [name, key] of [["cache", "key"], ["outbox", "id"], ["kv", "key"]]) if (!d.objectStoreNames.contains(name)) d.createObjectStore(name, { keyPath: key });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch { resolve(null); }
  });
}
async function tx(store, mode, fn) {
  const d = await db();
  if (!d) return null;
  return new Promise((resolve) => {
    try {
      const t = d.transaction(store, mode);
      const req = fn(t.objectStore(store));
      let out = null;
      if (req) req.onsuccess = () => { out = req.result === undefined ? null : req.result; };
      t.oncomplete = () => { d.close(); resolve(out); };
      t.onerror = t.onabort = () => { d.close(); resolve(null); };
    } catch { d.close(); resolve(null); }
  });
}
const kvGet = async (key) => { const r = await tx("kv", "readonly", (s) => s.get(key)); return r ? r.value : null; };
const kvPut = (key, value) => tx("kv", "readwrite", (s) => { s.put({ key, value }); return null; });

// ------------------------------------------------------------------------------------------------ app icon badge
async function setBadge(n) {
  if (n === null || n === undefined) return;
  try {
    if (n > 0 && self.navigator.setAppBadge) await self.navigator.setAppBadge(n);
    else if (self.navigator.clearAppBadge) await self.navigator.clearAppBadge();
  } catch { /* not installed, or no badge support */ }
  await kvPut("pending", { n, at: Date.now() });
}

// ------------------------------------------------------------------------------------------------ Approve / Reject from the notification
async function decide(verb, atk, route, title) {
  const cfg = await kvGet("config");
  const base = cfg && typeof cfg.base === "string" ? cfg.base : "";
  const tag = "savahbot-decision";
  const say = (body, opts = {}) => self.registration.showNotification(verb === "approve" ? "Approval" : "Rejection", { body, tag, icon: "/icon-192.png", badge: "/badge-96.png", silent: true, data: { route, nid: "", atk: "" }, ...opts });
  const openApp = async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const win = wins.find((c) => "focus" in c);
    if (win) { await win.focus(); win.postMessage({ type: "notify-click", route }); } else await self.clients.openWindow(route.replace(/^#/, ""));
  };
  try {
    const res = await fetch(base + "/api/notify/act", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: atk, verb }) });
    let data = {};
    try { data = await res.json(); } catch { /* an empty answer */ }
    if (res.ok) {
      await setBadge(typeof data.pending === "number" ? data.pending : null);
      const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      wins.forEach((c) => c.postMessage({ type: "notify-push", nid: "", category: "moderation.approval" }));    // an open dashboard refreshes its counts
      await say(verb === "approve" ? "Approved." : "Rejected.", { body: (verb === "approve" ? "Approved" : "Rejected") + (title ? `: ${title}` : ".") });
      await new Promise((r) => setTimeout(r, 3500));
      (await self.registration.getNotifications({ tag })).forEach((n) => n.close());
      return;
    }
    // expired, already decided, or lockdown: say so and open the dashboard where it can be handled
    await say((data && data.error) || "That did not go through. Tap to open the dashboard.", { silent: false });
    if (res.status === 403 || res.status === 410) await openApp();
  } catch {
    await say("No connection right now. Tap to open the dashboard.", { silent: false });
  }
}

// ------------------------------------------------------------------------------------------------ Background Sync: writes saved offline
async function replay() {
  const cfg = await kvGet("replay");
  const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  if (!cfg || !cfg.token) {
    wins.forEach((c) => c.postMessage({ type: "outbox-flush" }));       // no way to act without a window: an open app will send them
    return;
  }
  let sent = 0;
  let failed = false;
  const work = async () => {
    const items = ((await tx("outbox", "readonly", (s) => s.getAll())) || []).sort((a, b) => a.created - b.created);
    for (const item of items) {
      await tx("outbox", "readwrite", (s) => { s.delete(item.id); return null; });          // taken out first: never sent twice
      let res = null;
      try { res = await fetch((cfg.base || "") + item.path, { method: item.method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.token}` }, body: JSON.stringify(item.body) }); } catch { res = null; }
      if (!res || res.status >= 500 || res.status === 401 || res.status === 429) {
        await tx("outbox", "readwrite", (s) => { s.put({ ...item, tries: (item.tries || 0) + 1 }); return null; });
        failed = true;
        break;
      }
      if (res.ok) sent++;                                                                       // a refused one (4xx) is dropped: sending it again cannot help
    }
    const left = (await tx("outbox", "readonly", (s) => s.count())) || 0;
    if (left === 0) await tx("kv", "readwrite", (s) => { s.delete("replay"); return null; });
  };
  if (self.navigator.locks) await self.navigator.locks.request("savahbot-outbox-flush", work); else await work();
  if (sent) wins.forEach((c) => c.postMessage({ type: "outbox-sent", sent }));
  if (failed) throw new Error("not delivered yet");                                             // the browser tries again later
}

self.addEventListener("sync", (event) => {
  if (event.tag === "savahbot-outbox") event.waitUntil(replay());
});

// ------------------------------------------------------------------------------------------------ Periodic Background Sync: the number on the icon
self.addEventListener("periodicsync", (event) => {
  if (event.tag !== "savahbot-badge") return;
  event.waitUntil((async () => {
    const link = await kvGet("badge");
    if (!link || !link.token || typeof link.base !== "string") return;
    try {
      const res = await fetch(`${link.base}/api/notify/badge?t=${encodeURIComponent(link.token)}`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      if (typeof data.pending === "number") await setBadge(data.pending);
    } catch { /* offline: the next round tries again */ }
  })());
});
