/** Runs the real public/sw.js against a fake worker runtime, so the push, badge and Approve / Reject paths are tested without a browser. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const SRC = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
/** Values made inside the worker's own realm: compare their content, not their prototypes. */
const plain = <T>(x: T): T => JSON.parse(JSON.stringify(x));
const TOKEN = "act.42.1700000600.AbCdEfGhIjKlMnOpQrStUvWx";

function boot(opts: { fetchImpl?: (url: string, init?: { body?: string }) => Promise<unknown>; visible?: boolean; badgeFails?: boolean; slowList?: boolean } = {}) {
  const handlers: Record<string, (e: unknown) => void> = {};
  const shown: { title: string; opts: Record<string, unknown> }[] = [];
  const badge: (number | "clear")[] = [];
  const fetched: { url: string; body: unknown }[] = [];
  const opened: string[] = [];
  const skips = { count: 0 };
  const screen: { tag: string; title: string }[] = [];
  const listNow = (f?: { tag?: string }) => screen.filter((s) => !f?.tag || s.tag === f.tag).map((s) => ({ close() { const i = screen.findIndex((x) => x.tag === s.tag); if (i >= 0) screen.splice(i, 1); } }));
  const self = {
    location: { origin: "https://app.test" },
    addEventListener: (t: string, f: (e: unknown) => void) => { handlers[t] = f; },
    registration: {
      active: true,
      // a small model of the notification shade: a notification with the same tag replaces the old one, and close() removes it
      showNotification: async (title: string, o: Record<string, unknown>) => { shown.push({ title, opts: o }); const tag = (o.tag as string) || `#${shown.length}`; const i = screen.findIndex((s) => s.tag === tag); if (i >= 0) screen.splice(i, 1); screen.push({ tag, title }); },
      getNotifications: async (f?: { tag?: string }) => { if (opts.slowList) for (let i = 0; i < 40; i++) await null; return listNow(f); },
    },
    clients: { matchAll: async () => (opts.visible ? [{ visibilityState: "visible", focused: true, postMessage() {} }] : []), openWindow: async (u: string) => { opened.push(u); } },
    navigator: { setAppBadge: async (n: number) => { if (opts.badgeFails) throw new Error("no badge"); badge.push(n); }, clearAppBadge: async () => { badge.push("clear"); } },
    skipWaiting: () => { skips.count++; },
  };
  const ctx = vm.createContext({
    self, caches: { open: async () => ({ add: async () => undefined, put: async () => undefined, match: async () => undefined, keys: async () => [] }), keys: async () => [], delete: async () => true },
    fetch: async (url: string, init?: { body?: string }) => { fetched.push({ url, body: init?.body ? JSON.parse(init.body) : null }); return (opts.fetchImpl ?? (async () => ({ ok: true, status: 200, json: async () => ({ ok: true, pending: 2 }), headers: new Headers({ "content-type": "text/html" }) })))(url, init); },
    Request, Response, URL, Headers, console, setTimeout: (f: () => void) => { f(); return 0; }, indexedDB: undefined, Promise,
  });
  vm.runInContext(SRC, ctx);
  const run = async (type: string, event: Record<string, unknown>) => {
    let p: Promise<unknown> = Promise.resolve();
    handlers[type]({ ...event, waitUntil: (x: Promise<unknown>) => { p = Promise.all([p, x]); } });
    await p;
  };
  return { run, shown, badge, fetched, opened, handlers, skips, screen };
}
const push = (data: Record<string, string>) => ({ data: { json: () => ({ data }), text: () => "" } });

test("a push sets the icon badge from the waiting count and shows the notification", async () => {
  const w = boot();
  await w.run("push", push({ title: "Request waiting", body: "promo: ban", route: "#/moderation", category: "moderation.approval", pending: "3", nid: "9" }));
  assert.deepEqual(w.badge, [3]);
  const n = w.shown.find((s) => s.title === "Request waiting");
  assert.ok(n);
  assert.deepEqual(plain(n.opts.actions), []);                       // no signed link, no buttons
});

test("a count of zero clears the badge, and garbage counts are ignored", async () => {
  const w = boot();
  await w.run("push", push({ title: "t", body: "b", pending: "0" }));
  await w.run("push", push({ title: "t", body: "b", pending: "lots" }));
  await w.run("push", push({ title: "t", body: "b" }));
  assert.deepEqual(w.badge, ["clear"]);
});

test("an approval push with a genuine-looking signed link gets Approve and Reject buttons", async () => {
  const w = boot();
  await w.run("push", push({ title: "Request waiting", body: "promo: ban", category: "moderation.approval", pending: "1", atk: TOKEN }));
  const n = w.shown.find((s) => s.title === "Request waiting")!;
  assert.deepEqual(plain(n.opts.actions as { action: string }[]).map((a) => a.action), ["approve", "reject"]);
  assert.equal((n.opts.data as { atk: string }).atk, TOKEN);
});

test("a malformed or injected link never gets buttons", async () => {
  for (const atk of ["", "act.1.2.x", "../../etc", "act.42.1700000600.AbCdEfGhIjKlMnOpQrStUvWx\nX-Evil: 1", "http://evil.test/"]) {
    const w = boot();
    await w.run("push", push({ title: "Request waiting", body: "b", atk }));
    assert.deepEqual(plain(w.shown.find((s) => s.title === "Request waiting")!.opts.actions), [], atk);
  }
});

test("pressing Approve posts only the token and the verb, then confirms and updates the badge", async () => {
  const w = boot();
  await w.run("notificationclick", { action: "approve", notification: { title: "promo: ban", data: { route: "#/moderation", atk: TOKEN }, close() {} } });
  assert.equal(w.fetched.length, 1);
  assert.equal(w.fetched[0].url, "/api/notify/act");
  assert.deepEqual(plain(w.fetched[0].body), { token: TOKEN, verb: "approve" });
  assert.deepEqual(w.badge, [2]);
  assert.ok(w.shown.some((s) => String(s.opts.body).startsWith("Approved")));
});

test("pressing Reject says rejected; a refused link says so and opens the dashboard when it expired", async () => {
  const rej = boot();
  await rej.run("notificationclick", { action: "reject", notification: { title: "x", data: { route: "#/moderation", atk: TOKEN }, close() {} } });
  assert.deepEqual(plain(rej.fetched[0].body), { token: TOKEN, verb: "reject" });
  assert.ok(rej.shown.some((s) => String(s.opts.body).startsWith("Rejected")));

  const expired = boot({ fetchImpl: async () => ({ ok: false, status: 410, json: async () => ({ error: "This button has expired. Open the dashboard to decide." }) }) });
  await expired.run("notificationclick", { action: "approve", notification: { title: "x", data: { route: "#/moderation", atk: TOKEN }, close() {} } });
  assert.ok(expired.shown.some((s) => String(s.opts.body).includes("expired")));
  assert.equal(expired.opened.length, 1);
});

test("an action with a forged link is ignored and just opens the app; a plain tap still opens the page", async () => {
  const w = boot();
  await w.run("notificationclick", { action: "approve", notification: { title: "x", data: { route: "#/moderation", atk: "not-a-token" }, close() {} } });
  assert.equal(w.fetched.length, 0);                          // nothing is sent anywhere
  const tap = boot();
  await tap.run("notificationclick", { action: "", notification: { title: "x", data: { route: "#/notebook", atk: TOKEN }, close() {} } });
  assert.equal(tap.fetched.length, 0);
  assert.equal(tap.opened.length, 1);
});

test("no connection while pressing a button gives a clear message instead of failing silently", async () => {
  const w = boot({ fetchImpl: async () => { throw new TypeError("offline"); } });
  await w.run("notificationclick", { action: "approve", notification: { title: "x", data: { route: "#/moderation", atk: TOKEN }, close() {} } });
  assert.ok(w.shown.some((s) => String(s.opts.body).includes("No connection")));
});

test("an update waits: the worker only takes over when the page asks", async () => {
  const w = boot();
  (w.handlers.message as (e: unknown) => void)({ data: { type: "something-else" } });
  assert.equal(w.skips.count, 0);
  (w.handlers.message as (e: unknown) => void)({ data: { type: "skip-waiting" } });
  assert.equal(w.skips.count, 1);
});

// ---- 1.4.12: Chrome's grey "SavahBot / Tap to copy the URL for this app" notification must never appear.
// Chrome posts it when no notification is on screen at the moment a push event ends.
test("a push while you are looking at the dashboard leaves a silent placeholder on screen when the event ends", async () => {
  const w = boot({ visible: true });
  await w.run("push", push({ title: "Request waiting", body: "b", pending: "2" }));
  assert.equal(w.screen.length, 1);
  assert.equal(w.screen[0].tag, "savahbot-quiet");
});

test("a placeholder left by an earlier push is replaced, not closed, by the next placeholder", async () => {
  const w = boot({ visible: true });
  await w.run("push", push({ title: "a", body: "b" }));
  await w.run("push", push({ title: "c", body: "d" }));
  await w.run("push", push({ title: "e", body: "f", pending: "1" }));
  assert.equal(w.screen.length, 1);
});

test("a real notification clears the leftover placeholder, but only after it is on screen", async () => {
  const w = boot({ visible: true });
  await w.run("push", push({ title: "a", body: "b" }));
  const bg = boot({ visible: false });
  bg.screen.push({ tag: "savahbot-quiet", title: "old" });
  await bg.run("push", push({ title: "Request waiting", body: "b", tag: "req-1" }));
  assert.deepEqual(bg.screen.map((s) => s.tag), ["req-1"]);
});

test("a failing badge or storage can never stop the notification", async () => {
  const w = boot({ visible: false, badgeFails: true });
  await w.run("push", push({ title: "Request waiting", body: "b", pending: "5", tag: "req-2" }));
  assert.deepEqual(w.screen.map((s) => s.tag), ["req-2"]);
  const q = boot({ visible: true, badgeFails: true });
  await q.run("push", push({ title: "t", body: "b", pending: "5" }));
  assert.equal(q.screen.length, 1);
});

test("a push with no readable content still ends with something on screen", async () => {
  const w = boot({ visible: true });
  await w.run("push", { data: null });
  assert.ok(w.screen.length >= 1);
});

test("a slow look at the shade can never close the placeholder this push just showed", async () => {
  // in a real browser getNotifications() takes a while; the old worker asked at the start of the push and closed by tag when the answer came
  const w = boot({ visible: true, slowList: true });
  w.screen.push({ tag: "savahbot-quiet", title: "left over" });
  await w.run("push", push({ title: "Request waiting", body: "b", pending: "2" }));
  assert.equal(w.screen.length, 1);
});
