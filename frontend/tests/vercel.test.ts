// The Vercel rewrite is what makes a refresh or a shared link on a clean URL (/security) land on the app instead of a 404.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const cfg = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
const rule = cfg.rewrites[0];
const re = new RegExp("^" + rule.source + "$");
const rewritten = (path: string) => re.test(path);

test("vercel: pages, the root and unknown paths fall back to index.html", () => {
  assert.equal(rule.destination, "/index.html");
  for (const p of ["/", "/desk", "/security", "/settings", "/desk/", "/Moderation", "/nope", "/settings/extra", "/api"]) assert.ok(rewritten(p), p);
});

test("vercel: the API, built assets and any file are left alone", () => {
  for (const p of ["/api/status", "/api/", "/assets/index-abc123.js", "/sw.js", "/manifest.webmanifest", "/favicon.svg", "/offline.html", "/privacy.html", "/icon-192.png"]) assert.ok(!rewritten(p), p);
});

test("vercel: every response is framed-denied and not sniffed", () => {
  const all = cfg.headers.find((h: { source: string }) => h.source === "/(.*)").headers as { key: string; value: string }[];
  const get = (k: string) => all.find((h) => h.key === k)?.value ?? "";
  assert.equal(get("X-Frame-Options"), "DENY");
  assert.equal(get("X-Content-Type-Options"), "nosniff");
  assert.match(get("Content-Security-Policy"), /frame-ancestors 'none'/);
  assert.match(get("Content-Security-Policy"), /object-src 'none'/);
});
