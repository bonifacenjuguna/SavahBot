import assert from "node:assert/strict";
import { test } from "node:test";
import { isReadable } from "../src/offline.ts";
import { canQueue, isRelativeReminder } from "../src/outbox.ts";
import { fromProtocol, sharedText } from "../src/route-utils.ts";

test("offline copies are kept only for read-only paths that are safe to keep", () => {
  for (const ok of ["/api/status", "/api/notes", "/api/notes?tag=game", "/api/analytics?hours=24", "/api/notify/inbox", "/api/moderation/pending", "/api/quotes"]) assert.equal(isReadable(ok), true, ok);
  for (const no of ["/api/auth/login", "/api/security/overview", "/api/security/sessions", "/api/backup/info", "/api/notify/devices", "/api/notify/config", "/api/notify/badge-token", "/api/settings",
    "/api/youtube/status", "/api/telegram/status", "/api/events", "/api/notes/export", "/api/history?download=1", "/api/unknown", "/api/statusx", "/api/knowledge/x"]) assert.equal(isReadable(no), false, no);
});

test("only notes, quotes and clock-time reminders may wait in the outbox", () => {
  assert.equal(canQueue("POST", "/api/notes", { body: "x" }), true);
  assert.equal(canQueue("POST", "/api/quotes", { body: "x" }), true);
  assert.equal(canQueue("POST", "/api/reminders", { what: "x", when: "18:30" }), true);
  assert.equal(canQueue("POST", "/api/reminders", { what: "x", when: "tomorrow 09:00" }), true);
  assert.equal(canQueue("POST", "/api/reminders", { what: "x", when: "daily 08:00" }), true);
  assert.equal(canQueue("POST", "/api/reminders", { what: "x", when: "30m" }), false);        // would be wrong by the time it is sent
  assert.equal(canQueue("POST", "/api/reminders", { what: "x" }), false);
  for (const [m, p] of [["POST", "/api/moderation/1/approve"], ["POST", "/api/bans"], ["POST", "/api/commands"], ["DELETE", "/api/notes/1"], ["PUT", "/api/notes/1"], ["GET", "/api/notes"], ["POST", "/api/security/lockdown"]]) {
    assert.equal(canQueue(m, p, {}), false, `${m} ${p}`);
  }
});

test("relative reminder times are recognised", () => {
  for (const r of ["30m", "15m", "1h", "in 2 hours", "90 min", "2d", " 45 seconds "]) assert.equal(isRelativeReminder(r), true, r);
  for (const r of ["18:30", "tomorrow 09:00", "daily 08:00", "friday 7pm", ""]) assert.equal(isRelativeReminder(r), false, r);
});

test("web+savahbot links lead only to pages of the app", () => {
  assert.equal(fromProtocol("web+savahbot:moderation"), "/moderation");
  assert.equal(fromProtocol("web%2Bsavahbot%3Amoderation"), "/moderation");
  assert.equal(fromProtocol("web+savahbot://notebook?compose=1"), "/notebook?compose=1");
  assert.equal(fromProtocol("web+savahbot:settings?tab=knowledge&view=test"), "/settings?tab=knowledge&view=test");
  assert.equal(fromProtocol("WEB+SAVAHBOT:Desk/"), "/desk");
  for (const bad of ["", "web+savahbot:", "web+savahbot:login", "web+savahbot:../../etc", "web+savahbot:moderation?x=<script>", "https://evil.test/", "javascript:alert(1)",
    "web+savahbot:http://evil.test", "web+other:desk", "web+savahbot:" + "a".repeat(300), "web+savahbot:moderation\nX: y", "%E0%A4%A"]) assert.equal(fromProtocol(bad), null, bad);
});

test("shared text is joined without saying anything twice", () => {
  assert.equal(sharedText("A title", "Some text", "https://x.test/a"), "A title\nSome text\nhttps://x.test/a");
  assert.equal(sharedText("", "Look at this https://x.test/a", "https://x.test/a"), "Look at this https://x.test/a");   // Android puts the link in the text too
  assert.equal(sharedText("Same", "Same", ""), "Same");
  assert.equal(sharedText("", "", ""), "");
  assert.equal(sharedText("x".repeat(6000), "", "").length, 5000);
});
