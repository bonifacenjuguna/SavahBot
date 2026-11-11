// The browser side of the router, run against a small fake of location / history / window events.
import test from "node:test";
import assert from "node:assert/strict";

const g = globalThis as any;
let url = new URL("https://app.test/");
const entries: string[] = [];
const fire: Record<string, ((e: any) => void)[]> = {};
const add = (type: string, fn: (e: any) => void) => { (fire[type] ??= []).push(fn); };
const emit = (type: string, e: any = {}) => (fire[type] ?? []).forEach((f) => f(e));
g.location = { get pathname() { return url.pathname; }, get search() { return url.search; }, get hash() { return url.hash; } };
g.history = {
  pushState: (_s: unknown, _t: string, u: string) => { url = new URL(u, url); entries.push(u); },
  replaceState: (_s: unknown, _t: string, u: string) => { url = new URL(u, url); entries.push("~" + u); },
};
g.window = { addEventListener: add };
g.document = { addEventListener: add };

const router = await import("../src/router.ts");
const IDS = ["desk", "moderation", "security", "settings", "setup", "notifications"];

function start(at: string): { renders: () => number } {
  router._reset();
  for (const k of Object.keys(fire)) delete fire[k];
  entries.length = 0;
  url = new URL(at, "https://app.test");
  router.startRouter(IDS);
  let n = 0;
  router.onRoute(() => { n += 1; });
  return { renders: () => n };
}
const at = () => url.pathname + url.search + url.hash;
const back = (to: string) => { url = new URL(to, url); emit("popstate"); };

test("opening /security directly shows the security page and keeps its query", () => {
  start("/security?tab=sessions");
  assert.equal(router.current().id, "security");
  assert.equal(router.current().query.get("tab"), "sessions");
  assert.equal(at(), "/security?tab=sessions");
});

test("an old /#/security link is rewritten in place, with its query, without a new history entry", () => {
  start("/#/security");
  assert.equal(at(), "/security");
  assert.deepEqual(entries, ["~/security"]);
  start("/?x=1#/moderation?tab=rules");
  assert.equal(at(), "/moderation?x=1&tab=rules");
});

test("an old hash link clicked while the app is open converts and redraws once", () => {
  const s = start("/desk");
  url = new URL("/desk#/settings?tab=appearance", url);
  emit("hashchange");
  assert.equal(at(), "/settings?tab=appearance");
  assert.equal(s.renders(), 1);
  url = new URL("/settings?tab=appearance#section-2", url);   // a plain anchor is not a route
  emit("hashchange");
  assert.equal(s.renders(), 1);
});

test("an unusual spelling is canonicalised and its #fragment survives", () => {
  start("/Security?tab=x#keys");
  assert.equal(at(), "/security?tab=x#keys");
  start("/dashboard");
  assert.equal(at(), "/desk");
});

test("unknown routes are 'not found', never the Desk, and never loop", () => {
  start("/nope");
  assert.equal(router.current().notFound, true);
  assert.equal(router.current().id, null);
  assert.equal(at(), "/nope");
  start("/#/nope");
  assert.equal(at(), "/nope");
  assert.equal(router.current().notFound, true);
});

test("navigate pushes once, ignores the page you are on, and refuses other sites", () => {
  const s = start("/desk");
  assert.equal(router.navigate("/security"), true);
  assert.equal(router.navigate("/security"), true);
  assert.equal(s.renders(), 1);
  assert.deepEqual(entries, ["/security"]);
  for (const bad of ["//evil.com", "https://evil.com", "javascript:alert(1)", "/a/b"]) assert.equal(router.navigate(bad), false, bad);
  assert.equal(at(), "/security");
});

test("back and forward redraw; a step that only moves the #fragment does not", () => {
  const s = start("/desk");
  router.navigate("/settings?tab=appearance");
  assert.equal(s.renders(), 1);
  back("/desk");
  assert.equal(s.renders(), 2);
  back("/settings?tab=appearance");
  assert.equal(s.renders(), 3);
  back("/settings?tab=appearance#top");
  assert.equal(s.renders(), 3);
});

test("replaceQuery keeps the page in step with the address, so a later back step still redraws", () => {
  const s = start("/settings");
  router.navigate("/setup");
  router.replaceQuery("step=youtube");
  assert.equal(at(), "/setup?step=youtube");
  back("/setup");                                    // the entry before the query was set
  assert.equal(s.renders(), 2);
});

test("href builds clean links and falls back to the Desk for a non-route", () => {
  start("/desk");
  assert.equal(router.href("settings?tab=x"), "/settings?tab=x");
  assert.equal(router.href("#/security"), "/security");
  assert.equal(router.href("//evil.com"), "/desk");
});
