/** "Why was this flagged" and "Teach the bot", opened from a Moderation history row. */
import { post } from "../api.js";
import { busy, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { signalName } from "./knowledge-shared.js";
import type { Action } from "./shared.js";

interface Sig { name: string; weight: number; detail: string; why: string }
interface Reply { verdict: { score: number; action: string; confidence: number; signals: Sig[]; shadow: Sig[] } }

export function openWhy(a: Action): void {
  const probes = h("div", { class: "stack" }, h("p", { class: "muted small" }, "Asking each part of the bot..."));
  const body = h("div", { class: "why" },
    h("blockquote", { class: "why-msg" }, a.body || "(no text)"),
    h("p", { class: "muted small" }, `${a.author_name || "Someone"}${a.demo ? " (demo)" : ""}, score ${a.score}.`),
    h("h3", { class: "coll-title" }, icon("flag", 14), "The reasons it was flagged"),
    a.reasons.length ? h("ul", { class: "chip-row tight" }, a.reasons.map((r) => h("li", { class: "chip accent", style: "list-style:none" }, r))) : h("p", { class: "muted small" }, "No reasons were recorded."),
    h("h3", { class: "coll-title" }, icon("sparkle", 14), "What each part of the bot thinks now"), probes);

  const teach = (label: "spam" | "ham", text: string, tone: string, ic: string) => {
    const b = h("button", { class: `btn ${tone}`, type: "button" }, icon(ic, 16), text);
    b.addEventListener("click", () => busy(b, async () => { await post("/api/knowledge/lessons", { label, action_id: a.id }); }, label === "spam" ? "Learned: that was spam" : "Learned: that was fine"));
    return b;
  };
  body.appendChild(h("div", { class: "why-teach" }, h("p", { class: "muted small" }, "Teach the bot what this really was. You can review, correct or forget it later in Settings, Knowledge, Learning."),
    h("div", { class: "row" }, teach("spam", "This was spam", "bad-btn", "ban"), teach("ham", "This was fine", "ok-btn", "check"))));
  sheet("Why was this flagged?", body);

  if (!a.body) { mount(probes, h("p", { class: "muted small" }, "There is no message text to examine.")); return; }
  post<Reply>("/api/knowledge/test", { text: a.body, author: a.author_name }).then((r) => {
    const rows = [...r.verdict.signals.map((s) => ({ s, shadow: false })), ...r.verdict.shadow.map((s) => ({ s, shadow: true }))].filter((x) => x.s.weight !== 0);
    mount(probes, rows.length
      ? h("ul", { class: "probe" }, rows.map(({ s, shadow }) => h("li", { class: s.weight > 0 ? "hit" : "trust" },
          h("span", { class: "pr-main" }, h("strong", null, signalName(s.name)), h("span", { class: "muted small wrap" }, s.why || s.detail)),
          h("span", { class: "pr-side" }, h("b", null, `${s.weight > 0 ? "+" : ""}${s.weight}`), shadow ? h("span", { class: "chip" }, "Shadow") : null))))
      : h("p", { class: "muted small" }, "None of the knowledge detectors has anything to add. The original moderation rules decided this one."));
  }).catch((e: Error) => { toast(e.message, "error"); mount(probes, h("p", { class: "muted small" }, "Could not ask the detectors.")); });
}
