// Run with: npm test   (Node 22.18+ runs TypeScript directly; no dependencies)
import test from "node:test";
import assert from "node:assert/strict";
import { fromLegacyHash, normalize, queryString, resolvePath, stripSecrets } from "../src/route-utils.ts";

const IDS = ["desk", "moderation", "commands", "security", "settings", "setup", "reader", "more", "notifications"];
const n = (x: string) => normalize(x, IDS);

test("resolvePath: pages, root, aliases, trailing slash, case", () => {
  assert.deepEqual(resolvePath("/desk", IDS), { kind: "page", id: "desk", canonical: true });
  assert.deepEqual(resolvePath("/", IDS), { kind: "page", id: "desk", canonical: false });
  assert.deepEqual(resolvePath("/index.html", IDS), { kind: "page", id: "desk", canonical: false });
  assert.deepEqual(resolvePath("/dashboard", IDS), { kind: "page", id: "desk", canonical: false });
  assert.deepEqual(resolvePath("/chat-reader", IDS), { kind: "page", id: "reader", canonical: false });
  assert.deepEqual(resolvePath("/Moderation/", IDS), { kind: "page", id: "moderation", canonical: false });
});

test("resolvePath: unknown and malformed paths are not found", () => {
  for (const p of ["/nope", "/desk/extra", "/a.b", "/%E0%A4%A", "/..", "/desk%2Fx", "/" + "a".repeat(61)])
    assert.equal(resolvePath(p, IDS).kind, "notfound", p);
});

test("normalize: every spelling gives the clean URL", () => {
  assert.equal(n("/settings?tab=knowledge"), "/settings?tab=knowledge");
  assert.equal(n("#/settings?tab=knowledge"), "/settings?tab=knowledge");
  assert.equal(n("#!/security"), "/security");
  assert.equal(n("security"), "/security");
  assert.equal(n("/dashboard"), "/desk");
  assert.equal(n("#/chat-reader"), "/reader");
});

test("normalize: open redirects and non-routes are refused", () => {
  for (const x of ["//evil.com", "https://evil.com", "javascript:alert(1)", "data:text/html,x", "/\\evil.com", "\\\\evil.com", "#top", "#", "/a/b", "/x.js", "/%2e%2e", "/de\nsk", "/de\u0000sk", "mailto:a@b.c"])
    assert.equal(n(x), null, x);
});

test("normalize: an unknown but well-formed id leads to a 404 path, not a loop", () => {
  assert.equal(n("#/nope"), "/nope");
  assert.equal(resolvePath("/nope", IDS).kind, "notfound");
});

test("normalize: secrets never survive; ordinary params do", () => {
  assert.equal(n("/setup?step=youtube&token=abc&access_token=x&Password=p"), "/setup?step=youtube");
  assert.equal(stripSecrets(new URLSearchParams("a=1&code_verifier=z&key=k")).toString(), "a=1");
});

test("normalize: a fragment after the route is dropped", () => {
  assert.equal(n("/settings?tab=x#frag"), "/settings?tab=x");
});

test("fromLegacyHash: old bookmarks convert, with query preserved", () => {
  assert.equal(fromLegacyHash("#/security", "", IDS), "/security");
  assert.equal(fromLegacyHash("#/moderation?tab=rules", "", IDS), "/moderation?tab=rules");
  assert.equal(fromLegacyHash("#/dashboard", "", IDS), "/desk");
  assert.equal(fromLegacyHash("#!/more", "", IDS), "/more");
});

test("fromLegacyHash: real query string is kept, hash params win, secrets dropped", () => {
  assert.equal(fromLegacyHash("#/setup", "?youtube=connected", IDS), "/setup?youtube=connected");
  assert.equal(fromLegacyHash("#/setup?step=a", "?step=b&x=1", IDS), "/setup?step=a&x=1");
  assert.equal(fromLegacyHash("#/setup?step=a", "?token=secret", IDS), "/setup?step=a");
});

test("fromLegacyHash: plain fragments are left alone; unusable routes land on the Desk", () => {
  assert.equal(fromLegacyHash("#section-2", "", IDS), null);
  assert.equal(fromLegacyHash("", "", IDS), null);
  assert.equal(fromLegacyHash("#/", "", IDS), "/desk");
  assert.equal(fromLegacyHash("#//evil.com", "", IDS), "/desk");
  assert.equal(fromLegacyHash("#/a/b/c", "", IDS), "/desk");
});

test("fromLegacyHash: the result is idempotent (no redirect loop)", () => {
  const once = fromLegacyHash("#/Dashboard?tab=1", "", IDS)!;
  assert.equal(n(once), once);
});

test("queryString", () => {
  assert.equal(queryString("a=1"), "?a=1");
  assert.equal(queryString("?a=1"), "?a=1");
  assert.equal(queryString(""), "");
  assert.equal(queryString(new URLSearchParams({ a: "b c" })), "?a=b+c");
});
