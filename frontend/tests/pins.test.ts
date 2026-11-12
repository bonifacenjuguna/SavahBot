// A pinned line must keep what the options sheet needs, and unpinning must remove exactly that pin.
import test from "node:test";
import assert from "node:assert/strict";

const store = new Map<string, string>();
const g = globalThis as any;
g.localStorage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) };
g.location = { pathname: "/desk", search: "", hash: "" };

const { pinLine, pins, unpin } = await import("../src/chat-actions.ts");

test("a pin saved by an older version still opens as a plain viewer line", () => {
  const line = pinLine({ author_name: "Zawadi", text: "what game is this?", ts: 5 });
  assert.equal(line.level, "viewer");
  assert.equal(line.verdict, null);
  assert.equal(line.id, undefined);
});

test("a newer pin keeps the details the sheet needs", () => {
  const line = pinLine({ author_name: "Mod", text: "hi", ts: 6, id: 42, author_id: "UCx", platform: "youtube", level: "mod", verdict: "allow", demo: true });
  assert.deepEqual([line.id, line.author_id, line.platform, line.level, line.verdict, line.demo], [42, "UCx", "youtube", "mod", "allow", true]);
});

test("unpin removes only that pin, and a broken store reads as no pins", () => {
  store.set("savah.chat.pins", JSON.stringify([{ author_name: "A", text: "one", ts: 1 }, { author_name: "B", text: "two", ts: 2 }]));
  unpin({ author_name: "A", ts: 1 });
  assert.deepEqual(pins().map((p) => p.author_name), ["B"]);
  store.set("savah.chat.pins", "{not json");
  assert.deepEqual(pins(), []);
});
