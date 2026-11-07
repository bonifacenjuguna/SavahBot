/** 1.1.5: the two Moderation tools, rebuilt. Blocked phrases (add, bulk add, starter packs, severity) and the message test lab. */
import { del, get, patch, post } from "../api.js";
import { busy, debounce, duration, h, mount, toast, toastAction } from "../dom.js";
import { icon } from "../icons.js";
import { card, empty } from "./shared.js";
import { SIGNAL, autoGrow, iconAct, invite, niceName, plural, seg } from "./widgets.js";

export interface Thresholds { flag: number; delete: number; timeout: number; ban: number; default_weight: number }
const FALLBACK: Thresholds = { flag: 30, delete: 55, timeout: 90, ban: 100, default_weight: 70 };

/** What a score of this size does on its own. */
export function tierOf(score: number, t: Thresholds): { id: "none" | "flag" | "delete" | "timeout" | "ban"; label: string } {
  if (score >= t.ban) return { id: "ban", label: "Bans" };
  if (score >= t.timeout) return { id: "timeout", label: "Times out" };
  if (score >= t.delete) return { id: "delete", label: "Deletes" };
  if (score >= t.flag) return { id: "flag", label: "Flags only" };
  return { id: "none", label: "Adds points" };
}

interface Phrase { id: number; phrase: string; is_regex: boolean; weight: number; enabled: boolean }

/** Common spam, never insults. Pick a pack and the phrases already on your list are skipped. */
const PACKS: { id: string; title: string; text: string; phrases: string[] }[] = [
  { id: "promo", title: "Promo and sub-for-sub", text: "Viewers who only came to advertise their own channel.", phrases: ["sub for sub", "follow for follow", "like for like", "promo for promo", "check out my stream", "visit my channel", "subscribe to my channel"] },
  { id: "scam", title: "Giveaway and scam bait", text: "The usual lines in fake giveaways and account phishing.", phrases: ["free nitro", "claim your prize", "you have won", "send me your password", "verify your account", "gift card giveaway", "investment opportunity", "dm me to earn"] },
];

// ====================================================================================================== blocked phrases
export interface PhraseTool { el: HTMLElement; load(): Promise<void>; prefill(text: string): void }

export function phraseTool(): PhraseTool {
  let items: Phrase[] = [];
  let th: Thresholds = FALLBACK;
  let filter: "all" | "on" | "off" | "regex" = "all";
  let needle = "";

  // ---- add one
  const input = h("input", { type: "text", placeholder: "Word, phrase or pattern", required: true, maxLength: 200, "aria-label": "Phrase to block", autocomplete: "off", spellcheck: false });
  const hint = h("p", { class: "mt-hint", role: "status" });
  let kind: "text" | "regex" = "text";
  let sev: "standard" | "flag" | "delete" | "timeout" = "standard";
  const weightFor = (s: typeof sev): number => (s === "standard" ? 0 : th[s]);
  const checkRegex = () => {
    hint.textContent = "";
    if (kind !== "regex" || !input.value) return;
    try { new RegExp(input.value); } catch { hint.textContent = "This pattern looks invalid. Check brackets and slashes."; }
  };
  input.addEventListener("input", checkRegex);
  const kindSeg = seg("How to match", [{ id: "text" as const, label: "Phrase" }, { id: "regex" as const, label: "Pattern (regex)" }], kind, (v) => { kind = v; checkRegex(); });
  const sevBox = h("div", { class: "sev", role: "radiogroup", "aria-label": "What should a match do" });
  const drawSev = () => {
    const opts: { id: typeof sev; title: string; w: number }[] = [
      { id: "standard", title: "Standard", w: th.default_weight }, { id: "flag", title: "Flag", w: th.flag }, { id: "delete", title: "Delete", w: th.delete }, { id: "timeout", title: "Time out", w: th.timeout },
    ];
    mount(sevBox, opts.map((o) => h("button", { type: "button", class: "sev-opt", role: "radio", "aria-checked": String(sev === o.id), onclick: () => { sev = o.id; drawSev(); } },
      h("strong", null, o.title), h("span", null, tierOf(o.w, th).label))));
  };
  const addBtn = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Block it");
  const addForm = h("form", { class: "mt-add", onsubmit: (e: Event) => {
    e.preventDefault();
    const phrase = input.value.trim();
    if (!phrase) return;
    if (items.some((p) => p.phrase.toLowerCase() === phrase.toLowerCase() && p.is_regex === (kind === "regex"))) { toast("That one is already on the list.", "error"); return; }
    busy(addBtn, async () => {
      const r = await post<{ items: Phrase[] }>("/api/blacklist", { phrase, is_regex: kind === "regex", weight: weightFor(sev) });
      items = r.items; input.value = ""; hint.textContent = ""; draw(); input.focus();
    }, "Phrase blocked");
  } },
    h("div", { class: "mt-add-row" }, h("div", { class: "grow" }, input), addBtn),
    hint,
    h("div", { class: "mt-opts" }, h("div", { class: "mt-opt" }, h("span", { class: "mt-opt-label" }, "Match as"), kindSeg.el), h("div", { class: "mt-opt" }, h("span", { class: "mt-opt-label" }, "When it matches"), sevBox)));

  // ---- add many and packs
  const manyText = h("textarea", { rows: 5, placeholder: "One phrase per line", "aria-label": "Phrases, one per line", maxLength: 8000 }) as HTMLTextAreaElement;
  autoGrow(manyText, 240);
  const manyBtn = h("button", { class: "btn", type: "button" }, icon("plus", 16), "Block all");
  manyBtn.addEventListener("click", () => busy(manyBtn, async () => {
    const have = new Set(items.map((p) => p.phrase.toLowerCase()));
    const lines = Array.from(new Set(manyText.value.split("\n").map((l) => l.trim()).filter((l) => l && l.length <= 200)));
    if (!lines.length) throw new Error("Type or paste at least one phrase.");
    const fresh = lines.filter((l) => !have.has(l.toLowerCase()));
    let last = items;
    for (const phrase of fresh) last = (await post<{ items: Phrase[] }>("/api/blacklist", { phrase, is_regex: false, weight: weightFor(sev) })).items;
    items = last; manyText.value = ""; draw();
    toast(fresh.length ? `Blocked ${plural(fresh.length, "phrase")}${lines.length > fresh.length ? `, skipped ${lines.length - fresh.length} already listed` : ""}` : "All of those are already on the list");
  }));
  const manyPanel = h("div", { class: "mt-panel", hidden: true }, manyText, h("div", { class: "row" }, manyBtn, h("span", { class: "muted small" }, "Uses the “When it matches” choice above.")));

  const packPanel = h("div", { class: "mt-panel", hidden: true });
  const drawPacks = () => {
    const have = new Set(items.map((p) => p.phrase.toLowerCase()));
    mount(packPanel, PACKS.map((pk) => {
      const fresh = pk.phrases.filter((x) => !have.has(x));
      const b = h("button", { class: "btn small", type: "button", disabled: fresh.length === 0 }, icon(fresh.length ? "plus" : "check", 15), fresh.length ? `Add ${plural(fresh.length, "phrase")}` : "Already added");
      b.addEventListener("click", () => busy(b, async () => {
        let last = items;
        for (const phrase of fresh) last = (await post<{ items: Phrase[] }>("/api/blacklist", { phrase, is_regex: false, weight: weightFor(sev) })).items;
        items = last; draw();
      }, `${pk.title} added`));
      return h("div", { class: "pack" }, h("div", { class: "pack-main" }, h("strong", null, pk.title), h("span", { class: "muted small" }, pk.text),
        h("div", { class: "chip-row tight" }, pk.phrases.slice(0, 4).map((x) => h("span", { class: `chip${have.has(x) ? " ok" : ""}` }, x)), pk.phrases.length > 4 ? h("span", { class: "muted small" }, `+${pk.phrases.length - 4} more`) : null)), b);
    }));
  };
  const toggle = (btn: HTMLButtonElement, panel: HTMLElement, other: HTMLElement, otherBtn: HTMLButtonElement) => () => {
    panel.hidden = !panel.hidden; btn.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) { other.hidden = true; otherBtn.setAttribute("aria-expanded", "false"); if (panel === packPanel) drawPacks(); }
  };
  const manyToggle = h("button", { class: "link-quiet", type: "button", "aria-expanded": "false" }, icon("list", 14), "Add several at once");
  const packToggle = h("button", { class: "link-quiet", type: "button", "aria-expanded": "false" }, icon("package", 14), "Starter packs");
  manyToggle.addEventListener("click", toggle(manyToggle, manyPanel, packPanel, packToggle));
  packToggle.addEventListener("click", toggle(packToggle, packPanel, manyPanel, manyToggle));

  // ---- the list
  const filterBox = h("div", { class: "scroll-x" });
  const find = h("input", { type: "search", placeholder: "Search phrases", "aria-label": "Search phrases", autocomplete: "off" });
  find.addEventListener("input", () => { needle = find.value.trim().toLowerCase(); drawList(); });
  const findRow = h("div", { class: "mt-find", hidden: true }, h("div", { class: "input-icon grow" }, icon("search", 16), find));
  const list = h("div");
  const copyAll = iconAct("copy", "Copy every phrase", () => { void navigator.clipboard?.writeText(items.map((p) => p.phrase).join("\n")).then(() => toast("Copied the list")).catch(() => toast("Your browser blocked copying.", "error")); });
  const counts = () => ({ all: items.length, on: items.filter((p) => p.enabled).length, off: items.filter((p) => !p.enabled).length, regex: items.filter((p) => p.is_regex).length });
  const drawFilters = () => {
    const c = counts();
    const opts: ["all" | "on" | "off" | "regex", string][] = [["all", `All ${c.all}`], ["on", `On ${c.on}`], ["off", `Off ${c.off}`], ["regex", `Patterns ${c.regex}`]];
    mount(filterBox, items.length > 3 ? h("div", { class: "chip-row nowrap" }, opts.map(([id, label]) => h("button", { type: "button", class: `chip pick${filter === id ? " on" : ""}`, "aria-pressed": String(filter === id), onclick: () => { filter = id; drawFilters(); drawList(); } }, label))) : null);
  };
  const row = (p: Phrase): HTMLElement => {
    const tier = tierOf(p.weight || th.default_weight, th);
    const sw = h("input", { type: "checkbox", class: "switch", checked: p.enabled, "aria-label": `${p.enabled ? "Turn off" : "Turn on"} ${p.phrase}` });
    sw.addEventListener("change", () => {
      const next = sw.checked;
      p.enabled = next; drawFilters(); drawStatus();
      patch(`/api/blacklist/${p.id}`, { enabled: next }).then(() => drawList()).catch((e: Error) => { p.enabled = !next; toast(e.message, "error"); draw(); });
    });
    return h("li", { class: `ph-row${p.enabled ? "" : " off"}` },
      h("div", { class: "ph-main" }, h("code", { class: "ph-text" }, p.phrase),
        h("div", { class: "chip-row tight" }, p.is_regex ? h("span", { class: "chip" }, "Pattern") : null, h("span", { class: `chip tier-${tier.id}` }, tier.label), p.weight ? h("span", { class: "chip", title: "Points added to the message score" }, `+${p.weight}`) : null, p.enabled ? null : h("span", { class: "chip" }, icon("eyeOff", 12), "Off"))),
      h("div", { class: "acts" }, sw,
        iconAct("trash", `Remove ${p.phrase}`, (e) => busy(e.currentTarget as HTMLButtonElement, async () => {
          const keep = { phrase: p.phrase, is_regex: p.is_regex, weight: p.weight, enabled: p.enabled };
          await del(`/api/blacklist/${p.id}`); await load();
          toastAction("Phrase removed", "Undo", async () => { await post("/api/blacklist", keep); await load(); });
        }), "danger")));
  };
  const drawList = () => {
    const shown = items.filter((p) => (filter === "all" || (filter === "on" && p.enabled) || (filter === "off" && !p.enabled) || (filter === "regex" && p.is_regex)) && (!needle || p.phrase.toLowerCase().includes(needle))).sort((a, b) => b.id - a.id);
    findRow.hidden = items.length <= 8;
    if (!items.length) { mount(list, invite("ban", "Nothing is blocked yet", "Add a phrase above, or start with a pack of common spam lines.", h("button", { class: "btn ghost", type: "button", onclick: () => { packPanel.hidden = false; manyPanel.hidden = true; packToggle.setAttribute("aria-expanded", "true"); drawPacks(); packPanel.scrollIntoView({ block: "nearest", behavior: "smooth" }); } }, icon("package", 16), "See starter packs"))); return; }
    mount(list, shown.length ? h("ul", { class: "ph-list" }, shown.map(row)) : empty("search", "No phrases match."));
  };
  const status = h("span", { class: "chip" }, "0 on");
  const drawStatus = () => { const c = counts(); status.textContent = `${c.on} on`; status.className = `chip${c.on ? " ok" : ""}`; };
  const draw = () => { drawStatus(); drawFilters(); drawList(); drawPacks(); };
  drawSev();

  const body = h("div", { class: "mt-body" },
    h("p", { class: "lede" }, "A match adds to a message’s score. Extra spaces, symbols and look-alike letters do not get around it."),
    addForm, h("div", { class: "mt-links" }, manyToggle, packToggle), manyPanel, packPanel,
    h("div", { class: "mt-list-head" }, filterBox, copyAll), findRow, list);
  const el = card("ban", "Blocked phrases", body, { flush: true, actions: status, cls: "mt-card" });

  const load = async () => { const r = await get<{ items: Phrase[]; thresholds?: Thresholds }>("/api/blacklist"); items = r.items; if (r.thresholds) th = r.thresholds; drawSev(); draw(); };

  return {
    el,
    load,
    prefill(text) {
      const t = text.trim().replace(/\s+/g, " ").slice(0, 200);
      kind = "text"; kindSeg.set("text"); input.value = t; checkRegex();
      input.scrollIntoView({ block: "center", behavior: "smooth" });
      input.focus({ preventScroll: true });
    },
  };
}

// ====================================================================================================== test lab
interface Verdict { score: number; action: string; duration: number | null; exempt: boolean; confidence?: number; signals: { name: string; weight: number; detail: string; why?: string }[]; shadow?: { name: string; weight: number; why?: string }[] }
interface TestReply { verdict: Verdict; thresholds?: Thresholds; mode?: string; note: string }

const EXAMPLES: { label: string; text: string }[] = [
  { label: "Friendly", text: "Great stream today, thanks for the laughs!" },
  { label: "Shouting", text: "WOOOOOOOW THIS IS THE BEST STREAM EVER SUBSCRIBE NOW" },
  { label: "Disguised", text: "Fr33 R0bux at my pr0file, f r e e  v - b u c k s too" },
  { label: "Link spam", text: "FREE ROBUX at robux-gift.xyz right now everybody" },
];

const VERDICT: Record<string, { tone: "ok" | "warn" | "bad"; icon: string; title: string; text: string }> = {
  allow: { tone: "ok", icon: "checkCircle", title: "Allowed", text: "Nothing in this message needs action." },
  none: { tone: "ok", icon: "checkCircle", title: "Allowed", text: "Nothing in this message needs action." },
  flag: { tone: "warn", icon: "flag", title: "Flagged", text: "It would be logged for you. Flags never act on their own." },
  delete: { tone: "bad", icon: "trash", title: "Would be deleted", text: "The message would be removed from chat." },
  timeout: { tone: "bad", icon: "timer", title: "Would time out the sender", text: "The sender could not chat for a while." },
  ban: { tone: "bad", icon: "ban", title: "Would ban the sender", text: "The sender would be removed from the channel." },
};

export interface TestLab { el: HTMLElement }

export function testLab(hooks: { block(text: string): void }): TestLab {
  let level: "everyone" | "member" | "regular" | "mod" = "everyone";
  let seq = 0;
  const text = h("textarea", { rows: 3, maxLength: 1000, placeholder: "Type or paste a chat message", "aria-label": "Message to test" }) as HTMLTextAreaElement;
  autoGrow(text, 220);
  const result = h("div", { class: "lab-result", "aria-live": "polite" });
  const who = seg("Who sent it", [{ id: "everyone" as const, label: "Viewer" }, { id: "member" as const, label: "Member" }, { id: "regular" as const, label: "Regular" }, { id: "mod" as const, label: "Mod" }], level, (v) => { level = v; void run(); });

  const idle = () => mount(result, h("div", { class: "lab-idle" }, icon("gauge", 22), h("span", null, "Type a message, or tap an example. The result appears here as you type.")));

  const ladder = (score: number, t: Thresholds): HTMLElement => {
    const top = Math.max(t.ban, score, 1);
    const pos = (n: number) => `${Math.min(100, (n / top) * 100)}%`;
    const tier = tierOf(score, t).id;
    const marks: [string, number, string][] = [["Flag", t.flag, "flag"], ["Delete", t.delete, "delete"], ["Time out", t.timeout, "timeout"], ["Ban", t.ban, "ban"]];
    return h("div", { class: "ladder", role: "img", "aria-label": `Score ${score}. Flag at ${t.flag}, delete at ${t.delete}, time out at ${t.timeout}, ban at ${t.ban}.` },
      h("div", { class: "ld-track" }, h("i", { class: `ld-fill tier-${tier}`, style: `width:${pos(score)}` }), marks.map(([, n]) => h("span", { class: `ld-tick${score >= n ? " hit" : ""}`, style: `left:${pos(n)}` }))),
      h("ul", { class: "ld-legend" }, marks.map(([label, n, id]) => h("li", { class: score >= n ? `hit tier-${id}` : "" }, h("b", null, String(n)), h("span", null, label)))));
  };

  const show = (r: TestReply) => {
    const v = r.verdict, t = r.thresholds ?? FALLBACK;
    const meta = v.exempt ? { tone: "ok" as const, icon: "shield", title: "Exempt", text: "Chatters at this level are skipped by moderation, so nothing would happen." } : VERDICT[v.action] ?? VERDICT.allow;
    const title = v.action === "timeout" && v.duration && !v.exempt ? `${meta.title} for ${duration(v.duration)}` : meta.title;
    const acts = !v.exempt && (v.action === "delete" || v.action === "timeout" || v.action === "ban");
    const mode = r.mode ?? "suggest";
    const modeLine = !acts ? "" : mode === "off" ? "Moderation is Off, so the bot would only log this." : mode === "auto" ? "In Auto mode the bot would do this right away." : "In Suggest mode this would wait on the Desk for your approval.";
    const top = Math.max(1, ...v.signals.map((s) => Number(s.weight) || 0));
    const canBlock = !v.exempt && v.score < t.flag && text.value.trim().length >= 3 && text.value.trim().length <= 200;
    mount(result,
      h("div", { class: `verdict ${meta.tone}` }, h("span", { class: "vd-ico" }, icon(meta.icon, 24)),
        h("div", { class: "vd-text" }, h("strong", null, title), h("span", null, meta.text), modeLine ? h("span", { class: "vd-mode" }, modeLine) : null),
        v.exempt ? null : h("div", { class: "vd-score", "aria-label": `Score ${v.score}` }, h("b", null, String(v.score)), h("span", null, "score"))),
      v.exempt ? null : ladder(v.score, t),
      v.signals.length ? h("ul", { class: "sig-list" }, v.signals.map((s) => h("li", null,
        h("div", { class: "row between nowrap" }, h("strong", null, niceName(SIGNAL, s.name)), h("span", { class: "muted small" }, `+${s.weight} points`)),
        h("span", { class: "track" }, h("i", { class: "s2", style: `width:${Math.max(6, ((Number(s.weight) || 0) / top) * 100)}%` })),
        s.why || s.detail ? h("span", { class: "muted small wrap" }, s.why || s.detail) : null)))
        : v.exempt ? null : h("p", { class: "muted small" }, "No checks fired, so the score is 0."),
      !v.exempt && v.signals.length && typeof v.confidence === "number" ? h("p", { class: "muted small" }, `The bot is ${Math.round(v.confidence * 100)}% sure this is a real problem.`) : null,
      v.shadow && v.shadow.length ? h("p", { class: "muted small" }, `Also noticed, but not counted (shadow mode): ${v.shadow.map((x) => niceName(SIGNAL, x.name)).join(", ")}. See Settings > Knowledge.`) : null,
      canBlock ? h("div", { class: "lab-cta" }, h("span", { class: "muted small" }, "This got through. Want it caught next time?"), h("button", { class: "btn small", type: "button", onclick: () => hooks.block(text.value) }, icon("ban", 15), "Block this phrase")) : null,
      h("p", { class: "muted small" }, r.note));
  };

  const run = async () => {
    const value = text.value;
    if (!value.trim()) { seq++; idle(); return; }
    const mine = ++seq;
    result.classList.add("busy");
    try {
      const r = await post<TestReply>("/api/moderation/test", { text: value, level });
      if (mine === seq) show(r);
    } catch (e) {
      if (mine === seq) { mount(result, h("div", { class: "banner error" }, icon("alert", 18), h("span", null, `Could not score that: ${(e as Error).message}`))); }
    } finally { if (mine === seq) result.classList.remove("busy"); }
  };
  const soon = debounce(() => void run(), 450);
  text.addEventListener("input", soon);
  const examples = h("div", { class: "chip-row" }, h("span", { class: "muted small" }, "Try an example"), EXAMPLES.map((x) => h("button", { type: "button", class: "chip pick", onclick: () => { text.value = x.text; text.dispatchEvent(new Event("input")); void run(); } }, x.label)));
  idle();

  const body = h("div", { class: "mt-body lab" },
    h("p", { class: "lede" }, "See what the bot would do with a message, without sending anything to chat."),
    text, h("div", { class: "mt-opt" }, h("span", { class: "mt-opt-label" }, "Sent by"), who.el), examples, result);
  return { el: card("gauge", "Try a message", body, { flush: true, cls: "mt-card lab-card" }) };
}
