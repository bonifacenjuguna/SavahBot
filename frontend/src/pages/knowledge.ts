/** Settings > Knowledge: the shell, the Overview and the Test lab. Other views live in knowledge-packs.ts and knowledge-ops.ts. */
import { get, patch, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus } from "../state.js";
import { renderDetectors, renderFeeds } from "./knowledge-ops.js";
import { renderLearning } from "./knowledge-learning.js";
import { toolsCard } from "./knowledge-tools.js";
import { renderPacks } from "./knowledge-packs.js";
import { ago, goKnowledge, kcard, meter, pct, signalName, type Overview, type Shadow, type View } from "./knowledge-shared.js";
import { empty } from "./shared.js";
import { figures, invite, lede, plural, sentence } from "./widgets.js";

const TABS: { id: View; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "sparkle" },
  { id: "packs", label: "Knowledge", icon: "database" },
  { id: "detectors", label: "Detectors", icon: "target" },
  { id: "learning", label: "Learning", icon: "trending" },
  { id: "live", label: "Live data", icon: "radio" },
  { id: "test", label: "Test lab", icon: "flask" },
];

export function renderKnowledge(root: HTMLElement, query: URLSearchParams): () => void {
  const view = (TABS.some((t) => t.id === query.get("view")) ? query.get("view") : "overview") as View;
  const host = h("div", { class: "k-stack" });
  const tabs = h("nav", { class: "k-tabs", "aria-label": "Knowledge sections" }, TABS.map((t) =>
    h("button", { type: "button", "aria-current": t.id === view ? "page" : undefined, onclick: () => goKnowledge(t.id) }, icon(t.icon, 16), t.label)));
  mount(root, h("div", { class: "k-top" }, tabs), host);
  // keep the active tab in view on a narrow screen
  queueMicrotask(() => (tabs.querySelector("[aria-current=page]") as HTMLElement | null)?.scrollIntoView({ inline: "center", block: "nearest" }));
  switch (view) {
    case "packs": renderPacks(host, query); break;
    case "detectors": renderDetectors(host); break;
    case "learning": renderLearning(host); break;
    case "live": renderFeeds(host); break;
    case "test": renderTest(host, query); break;
    default: renderOverview(host);
  }
  return () => { /* nothing to stop: every view draws once from the address and from its own buttons */ };
}

// ------------------------------------------------------------------------------------------------ overview
function shadowList(items: Shadow[]): HTMLElement {
  if (!items.length) return empty("eyeOff", "Nothing yet. When a detector is in shadow mode, the messages it would have caught show up here.");
  return h("ul", { class: "list" }, items.map((s) => h("li", null,
    h("div", { class: "row between" }, h("strong", null, s.author || "viewer"), h("span", { class: "chip warn" }, `${signalName(s.detector)} · +${s.weight}`)),
    h("q", null, s.text), s.detail ? h("div", { class: "muted small" }, s.detail) : null)));
}

function renderOverview(host: HTMLElement): void {
  const load = async () => {
    const ov = await get<Overview>("/api/knowledge/overview");
    const st = ov.status;
    const total = Math.max(1, ov.detectors.length);
    const modes = ov.detector_modes;
    const master = h("input", { type: "checkbox", class: "switch", checked: st.enabled, "aria-label": "Use the knowledge layer" }) as HTMLInputElement;
    master.onchange = async () => {
      try { await patch("/api/settings", { values: { intel_enabled: master.checked } }); toast(master.checked ? "Knowledge layer on" : "Knowledge layer off, the bot behaves as in 1.1.5"); void refreshStatus(); await load(); }
      catch (e) { master.checked = !master.checked; toast((e as Error).message, "error"); }
    };
    const benchBox = h("div", { class: "k-stack" });
    const benchBtn = h("button", { class: "btn primary", type: "button" }, icon("target", 16), "Run accuracy check") as HTMLButtonElement;
    benchBtn.onclick = () => busy(benchBtn, async () => { mount(benchBox, renderBenchmark(await post<Benchmark>("/api/knowledge/benchmark"))); });
    mount(host,
      lede("SavahBot's knowledge works like a library of patterns plus a team of detectors that read them. It all runs inside your bot: no AI service, no outside calls to judge a message."),
      kcard("sparkle", "State of the knowledge", h("div", { class: "k-stack" },
        h("div", { class: "row between" }, h("span", { class: "muted" }, st.enabled ? "On: adding evidence to every message" : "Off: the bot behaves exactly as in 1.1.5"),
          h("label", { class: "check small" }, master, "Use it")),
        figures([
          { value: `${st.packs_active}/${st.packs_total}`, label: "packs in use" }, { value: st.rules.toLocaleString(), label: "phrase rules" },
          { value: st.domains.toLocaleString(), label: "threat domains", tone: st.domains ? "ok" : "" }, { value: String(st.safe_phrases), label: "safe phrases" },
        ]),
        h("div", null,
          h("div", { class: "k-modebar", role: "img", "aria-label": `${modes.live} live, ${modes.shadow} shadow, ${modes.off} off` },
            h("i", { class: "live", style: `width:${(modes.live / total) * 100}%` }), h("i", { class: "shadow", style: `width:${(modes.shadow / total) * 100}%` }), h("i", { class: "off", style: `width:${(modes.off / total) * 100}%` })),
          h("div", { class: "k-legend" }, h("span", null, h("span", { class: "k-dot live" }), h("b", null, modes.live), " live"), h("span", null, h("span", { class: "k-dot shadow" }), h("b", null, modes.shadow), " shadow"),
            h("span", null, h("span", { class: "k-dot off" }), h("b", null, modes.off), " off"))),
        h("p", { class: "k-note" }, st.model_ready ? `The word-statistics model is trained (${st.examples} spam examples remembered). ` : "The word-statistics model has nothing to learn from yet. ",
          st.wave_active ? "A raid wave is active right now." : st.waves_seen ? `${plural(st.waves_seen, "raid wave")} seen since the bot started.` : "")), ),
      ov.next ? h("section", { class: "next-up" }, h("div", { class: "nu-when" }, h("span", { class: "muted small" }, "Next up")), h("div", { class: "nu-what" }, ov.next.text),
        h("div", { class: "row" }, h("button", { class: "btn primary small", type: "button", onclick: () => goKnowledge(ov.next!.kind === "suggestions" ? "learning" : "detectors") }, "Take a look"))) : null,
      kcard("package", "What it knows", h("div", { class: "k-grid" }, ov.categories.map((c) => h("a", { class: "tile", href: `#/settings?tab=knowledge&view=packs&cat=${c.id}` },
        h("span", { class: "tile-ico" }, icon("database", 22)), h("span", { class: "tile-text" }, h("strong", null, c.title), h("span", null, `${plural(c.entries, "entry", "entries")} · ${c.active}/${c.packs} on`)), icon("chevronRight", 16, "tile-go"))))),
      kcard("eyeOff", "Caught in shadow mode", h("div", { class: "k-stack" }, h("p", { class: "k-note" }, "These messages were noticed by a detector in shadow mode. Nothing was done about them. If they look right, switch that detector to live."),
        shadowList(ov.recent_shadow), h("div", { class: "row" }, h("button", { class: "btn small", type: "button", onclick: () => goKnowledge("detectors") }, icon("target", 15), "Open detectors")))),
      toolsCard(),
      kcard("chart", "Accuracy check", h("div", { class: "k-stack" },
        h("p", { class: "k-note" }, "Runs a fixed set of real-looking spam and normal chat lines through your bot and shows what it catches with and without the knowledge layer. It never touches your chat."),
        h("div", { class: "row" }, benchBtn), benchBox)),
      ov.feeds.total ? kcard("radio", "Live data", h("div", { class: "row between" }, h("span", { class: "muted" }, `${ov.feeds.enabled} of ${ov.feeds.total} lists on · ${plural(ov.feeds.entries, "domain")} · last refreshed ${ago(ov.feeds.last_ok)}${ov.feeds.errors ? ` · ${plural(ov.feeds.errors, "problem")}` : ""}`),
        h("button", { class: "btn small", type: "button", onclick: () => goKnowledge("live") }, "Manage"))) : null);
  };
  void load().catch((e) => { toast((e as Error).message, "error"); mount(host, invite("alert", "Could not load the knowledge", (e as Error).message)); });
}

interface Cut { recall_flag: number; recall_delete: number; false_alarm_flag: number; false_alarm_delete: number; precision_flag: number | null; caught: number; spam_total: number; false_alarms: number; ham_total: number }
interface Benchmark { thresholds: { flag: number; delete: number }; without_intel: Cut; with_intel: Cut; missed: { text: string; score: number }[]; weak: { text: string; score: number }[]; false_alarms: { text: string; score: number; signals: string[] }[]; note: string }

function renderBenchmark(r: Benchmark): HTMLElement {
  const col = (title: string, c: Cut, tone: "ok" | "") => h("div", null, h("h4", null, title),
    figures([{ value: pct(c.recall_flag), label: `spam flagged (${c.caught} of ${c.spam_total})`, tone }, { value: pct(c.recall_delete), label: "reached delete level" },
      { value: pct(c.false_alarm_flag), label: `normal chat flagged (${c.false_alarms} of ${c.ham_total})`, tone: c.false_alarms ? "warn" : "ok" }]));
  const list = (title: string, items: { text: string; score: number }[], note: string) => items.length ? h("details", { class: "group" }, h("summary", null, h("span", null, title), h("span", { class: "chip" }, String(items.length))),
    h("div", { class: "k-stack", style: "padding:10px 14px" }, h("p", { class: "k-note" }, note), h("ul", { class: "list" }, items.map((m) => h("li", null, h("q", null, m.text), h("span", { class: "muted small" }, ` score ${m.score}`)))))) : null;
  return h("div", { class: "k-stack" },
    h("div", { class: "k-compare after" }, col("Without the knowledge layer", r.without_intel, ""), col("With it", r.with_intel, "ok")),
    h("p", { class: "k-note" }, `"Flagged" means a score of ${r.thresholds.flag} or more, "delete level" means ${r.thresholds.delete} or more. ${r.note}`),
    list("Spam it missed", r.missed, "These stayed below the flag line."), list("Spam it only flagged", r.weak, "Flagged, but not strong enough to delete without your approval."),
    r.false_alarms.length ? list("Normal chat it flagged by mistake", r.false_alarms, "These are false alarms. Find the pack responsible in the Test lab.") : h("p", { class: "k-note" }, "No normal chat was flagged."));
}

// ------------------------------------------------------------------------------------------------ test lab
interface TraceMatch { pack: string; pack_title: string; phrase: string; kind: string; weight: number; typos: number; protected_by_safe_phrase: boolean }
interface TestResult {
  verdict: { score: number; action: string; confidence: number; signals: { name: string; weight: number; detail: string; why: string }[]; shadow: { name: string; weight: number; detail: string; why: string }[] };
  trace: { matches: TraceMatch[]; facets: { pack: string; groups: string[]; weight: number }[]; links: { host: string; weight: number; reasons: string[] }[]; safe_phrases_found: string[]; bayes: { spam_probability: number; words: string[] }; normalised: string };
  reacts: Record<string, number>; detectors: Record<string, string>;
}
const EXAMPLES = ["free robux click my profile", "double your bitcoin send 0.1 btc get 0.2 back", "verify at youtub3.com/login", "nimekutumia pesa kwa makosa tafadhali rudisha", "frree robus hurry",
  "kill streak incoming, he is dead lol", "is that giveaway real or a scam?", "hello everyone!"];

function renderTest(host: HTMLElement, query: URLSearchParams): void {
  const box = h("textarea", { rows: 3, maxlength: 600, placeholder: "Type or paste a chat message", "aria-label": "Message to check" }) as HTMLTextAreaElement;
  box.value = query.get("text") ?? "";
  const out = h("div", { class: "k-stack" });
  const go = h("button", { class: "btn primary", type: "button" }, icon("flask", 16), "Check it") as HTMLButtonElement;
  const run = async () => {
    const text = box.value.trim();
    if (!text) { toast("Type a message first.", "error"); return; }
    mount(out, show(await post<TestResult>("/api/knowledge/test", { text })));
  };
  go.onclick = () => busy(go, run);
  box.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") go.click(); });
  mount(host,
    lede("Type any message to see exactly how the bot would judge it: the score, which rules fired and why, what only shadow mode noticed, and every raw match. Nothing is saved and nobody is punished."),
    kcard("flask", "Check a message", h("div", { class: "k-stack" }, box, h("div", { class: "row" }, go),
      h("div", { class: "k-examples" }, EXAMPLES.map((t) => h("button", { class: "chip pick", type: "button", onclick: () => { box.value = t; go.click(); } }, t.length > 34 ? t.slice(0, 33) + "…" : t))))),
    out);
  if (box.value.trim()) go.click();
}

function show(r: TestResult): HTMLElement {
  const v = r.verdict;
  const tone = v.action === "allow" ? "ok" : v.action === "flag" ? "warn" : "bad";
  const sig = (s: { name: string; weight: number; detail: string; why: string }, shadow = false) => h("div", { class: `k-sig${shadow ? " shadow" : ""}` },
    h("div", { class: "top" }, h("strong", null, signalName(s.name)), h("span", { class: `chip ${shadow ? "" : "warn"}` }, `+${s.weight}${shadow ? " (not scored)" : ""}`)), h("span", { class: "muted small" }, s.why));
  const t = r.trace;
  const reacts = Object.entries(r.reacts);
  return h("div", { class: "k-stack" },
    kcard("shield", "Verdict", h("div", { class: "k-stack" },
      h("div", { class: "k-score" }, h("span", { class: "big" }, String(v.score)), h("span", { class: `chip ${tone}` }, sentence(v.action)), h("span", { class: "muted small" }, "Confidence ", meter(v.confidence, v.confidence > 0.7 ? "bad" : v.confidence > 0.4 ? "warn" : ""), ` ${pct(v.confidence)}`)),
      v.signals.length ? h("div", null, v.signals.map((s) => sig(s))) : h("p", { class: "k-note" }, "Nothing counted against this message."),
      v.shadow.length ? h("div", null, h("h3", { class: "k-note", style: "margin:6px 0 0" }, "Noticed in shadow mode only"), v.shadow.map((s) => sig(s, true))) : null)),
    reacts.length ? kcard("target", "If every active detector were live", h("div", { class: "k-chips" }, reacts.map(([n, w]) => h("span", { class: "chip" }, `${signalName(n)} +${w}`)))) : null,
    kcard("search", "How it was read", h("div", { class: "k-trace" },
      h("div", null, h("span", { class: "muted small" }, "Cleaned up text: "), h("span", { class: "mono" }, t.normalised || "(empty)")),
      t.matches.length ? t.matches.map((m) => h("div", { class: "row-line" }, h("span", { class: "chip" }, m.pack_title), h("span", { class: "mono" }, m.phrase), h("span", { class: "muted small" }, `${m.kind}${m.typos ? `, ${plural(m.typos, "typo")}` : ""} · weight ${m.weight}`),
        m.protected_by_safe_phrase ? h("span", { class: "chip ok" }, "protected by a safe phrase") : null)) : h("span", { class: "muted" }, "No phrase rule matched."),
      t.facets.filter((f) => f.groups.length).map((f) => h("div", { class: "row-line" }, h("span", { class: "chip" }, "Scam intent"), h("span", null, f.groups.join(" + ")), h("span", { class: "muted small" }, f.weight ? `weight ${f.weight}` : "not enough groups together"))),
      t.links.map((l) => h("div", { class: "row-line" }, h("span", { class: "chip" }, "Link"), h("span", { class: "mono" }, l.host), h("span", { class: "muted small" }, `weight ${l.weight}: ${l.reasons.join("; ")}`))),
      t.safe_phrases_found.length ? h("div", { class: "row-line" }, h("span", { class: "chip ok" }, "Safe phrases found"), h("span", { class: "mono" }, t.safe_phrases_found.join(", "))) : null,
      h("div", { class: "row-line" }, h("span", { class: "chip" }, "Statistics"), h("span", null, `${pct(t.bayes.spam_probability)} like spam`), t.bayes.words.length ? h("span", { class: "muted small" }, `because of: ${t.bayes.words.join(", ")}`) : null))));
}
