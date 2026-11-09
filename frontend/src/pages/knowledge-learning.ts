/** Settings > Knowledge > Learning: review, lessons, quality and history. Everything here talks to /api/knowledge/*. */
import { get, patch, post, del } from "../api.js";
import { busy, debounce, h, mount, toast, toastAction } from "../dom.js";
import { icon } from "../icons.js";
import { ago, kcard, meter, pct, signalName, type LearningData, type Suggestion } from "./knowledge-shared.js";
import { empty } from "./shared.js";
import { confirmAct, figures, invite, lede, plural, seg } from "./widgets.js";

type Part = "review" | "lessons" | "quality" | "history";
interface Lesson { id: number; ts: number; label: "spam" | "ham"; source: string; body: string; author: string; pred: number | null; demo: number; note: string }
interface QueueItem { id: number; author: string; text: string; ts: number; p_spam: number; words: string[]; score: number; verdict: string }
interface Acc { n: number; accuracy: number | null; precision: number | null; recall: number | null; false_alarms: number; missed: number }
interface Quality {
  counts: { total: number; spam: number; ham: number; by_source: Record<string, number> }; overall: Acc; recent: Acc; before: Acc; drifting: boolean;
  model_ready: boolean; active: boolean; needed: number; balance: number | null; timeline: { day: number; spam: number; ham: number }[];
}
interface Snapshot { id: number; ts: number; name: string; count: number }

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const SOURCE: Record<string, string> = { decision: "Your decision", teach: "Taught by you", trusted: "Trusted chat", import: "Imported", migrated: "From an older version", queue: "Review queue" };
const LEARN_HELP: Record<string, string> = {
  off: "The bot does not look for patterns in your decisions. Approve and Reject still work as always.",
  suggest: "The bot proposes changes from your decisions and you accept or dismiss each one. Nothing changes without you.",
  auto: "The bot applies the confident suggestions itself. Every change is logged and can be undone here. Safe phrases always wait for you.",
};

export function renderLearning(host: HTMLElement, initial: Part = "review"): void {
  const body = h("div", { class: "k-stack" });
  const views = seg<Part>("Learning view", [
    { id: "review", label: "Review", icon: "inbox" }, { id: "lessons", label: "Lessons", icon: "book" },
    { id: "quality", label: "Quality", icon: "target" }, { id: "history", label: "History", icon: "history" }], initial, (v) => show(v));
  mount(host, h("div", { class: "k-stack" }, lede("Every Approve, Reject and “teach” is a lesson. The bot learns by plain counting, with no AI model, and nothing leaves your bot. You can see, correct and forget every lesson."),
    views.el, body));
  const show = (p: Part) => {
    const draw = p === "review" ? review : p === "lessons" ? lessons : p === "quality" ? quality : history;
    mount(body, h("p", { class: "muted small" }, "Loading..."));
    void draw(body).catch((e) => { fail(e); mount(body, invite("alert", "Could not load this view", (e as Error).message)); });
  };
  show(initial);
}

// ------------------------------------------------------------------------------------------------ review
async function review(host: HTMLElement): Promise<void> {
  const [d, q] = await Promise.all([get<LearningData>("/api/knowledge/learning"), get<{ ready: boolean; items: QueueItem[] }>("/api/knowledge/learning/queue")]);
  const st = d.stats;
  const again = () => void review(host).catch(fail);
  const picked = new Set<number>();
  const bar = h("div", { class: "row between k-bulkbar", hidden: true });

  const paintBar = () => {
    bar.hidden = picked.size === 0;
    mount(bar, h("span", { class: "muted small" }, `${picked.size} selected`), h("div", { class: "row" },
      bulkBtn("accept", "Accept", "check", "primary"), bulkBtn("dismiss", "Dismiss", "x", "ghost")));
  };
  const bulkBtn = (action: "accept" | "dismiss", label: string, ic: string, tone: string) =>
    h("button", { class: `btn small ${tone}`, type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => {
      const r = await post<{ done: number; failed: number }>("/api/knowledge/suggestions/bulk", { ids: [...picked], action });
      toast(`${plural(r.done, "suggestion")} ${action === "accept" ? "accepted" : "dismissed"}${r.failed ? `, ${r.failed} could not be applied` : ""}`);
      again();
    }) }, icon(ic, 15), label);

  const mode = seg<"off" | "suggest" | "auto">("What to do with what it learns", [{ id: "off", label: "Off" }, { id: "suggest", label: "Suggest" }, { id: "auto", label: "Automatic" }],
    st.mode as "off" | "suggest" | "auto", async (m) => { try { await patch("/api/settings", { values: { intel_learning_mode: m } }); toast(`Learning: ${m}`); again(); } catch (e) { fail(e); } });

  const sugRow = (s: Suggestion): HTMLElement => {
    const title = s.kind === "phrase" ? `Add “${s.body}” to the learned phrases` : s.kind === "safe" ? `Never flag “${s.body}”`
      : s.kind === "scale" ? `Set ${signalName(s.body)} strength to ${(s.weight / 100).toFixed(2).replace(/0$/, "")}x` : `Switch ${signalName(s.body)} to live`;
    const pick = h("input", { type: "checkbox", "aria-label": `Select: ${title}`, onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? picked.add(s.id) : picked.delete(s.id); paintBar(); } });
    return h("div", { class: "k-sug" },
      h("div", { class: "top" }, h("label", { class: "row k-pick" }, pick, h("span", null, h("strong", null, title), h("div", { class: "k-note" }, s.detail))), h("span", { class: "chip" }, `${s.evidence} seen`)),
      h("div", { class: "acts" },
        h("button", { class: "btn small primary", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => {
          const r = await post<{ log_id: number }>(`/api/knowledge/suggestions/${s.id}/accept`); again();
          toastAction("Applied", "Undo", async () => { await post(`/api/knowledge/log/${r.log_id}/undo`); again(); }); }) }, icon("check", 15), "Accept"),
        h("button", { class: "btn small ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/knowledge/suggestions/${s.id}/dismiss`); again(); }) }, icon("x", 15), "Dismiss")));
  };
  const refresh = h("button", { class: "btn small", type: "button" }, icon("refresh", 15), "Look for suggestions") as HTMLButtonElement;
  refresh.onclick = () => busy(refresh, async () => { const r = await post<{ new: number; auto_applied: number }>("/api/knowledge/learning/refresh"); toast(r.new ? `${plural(r.new, "new suggestion")}${r.auto_applied ? `, ${r.auto_applied} applied` : ""}` : "Nothing new to suggest"); again(); });

  const queueRow = (it: QueueItem): HTMLElement => {
    const row = h("div", { class: "k-sug k-q" },
      h("div", { class: "top" }, h("div", null, h("strong", null, it.author || "viewer"), h("div", { class: "k-q-text" }, `“${it.text}”`)),
        h("span", { class: "chip", title: "How likely the bot thinks this is spam" }, `${Math.round(it.p_spam * 100)}% spam`)),
      it.words.length ? h("div", { class: "k-note" }, `Words that pushed it towards spam: ${it.words.join(", ")}`) : null,
      h("div", { class: "acts" }, label(it, "spam", "This is spam", "ban", "bad-btn"), label(it, "ham", "This is fine", "check", "ok-btn")));
    return row;
  };
  const label = (it: QueueItem, l: "spam" | "ham", text: string, ic: string, tone: string) =>
    h("button", { class: `btn small ${tone}`, type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => {
      await post("/api/knowledge/lessons", { label: l, text: it.text, author: it.author }); toast(l === "spam" ? "Learned: that is spam" : "Learned: that is fine"); again(); }) }, icon(ic, 15), text);

  mount(host,
    kcard("trending", "What it does with that", h("div", { class: "k-stack" }, mode.el, h("p", { class: "k-note" }, LEARN_HELP[st.mode] ?? ""))),
    kcard("sparkle", "Suggestions", h("div", null, bar, d.suggestions.length ? d.suggestions.map(sugRow) : h("div", { class: "k-sug" }, empty("check", "No suggestions waiting.")),
      h("div", { class: "k-sug" }, h("div", { class: "row between" }, h("span", { class: "muted small" }, `Last looked ${ago(st.last_refresh)}`), refresh))), { flush: true }),
    kcard("inbox", "Help it where it is unsure", h("div", null,
      !q.ready ? h("div", { class: "k-sug" }, empty("clock", "The bot needs a few lessons before it can tell what it is unsure about.")) :
        q.items.length ? [h("p", { class: "k-note k-pad" }, "Recent real messages the bot cannot call either way. Labelling these teaches it the most."), ...q.items.map(queueRow)]
          : h("div", { class: "k-sug" }, empty("check", "Nothing is borderline right now. New uncertain messages show up here as people chat."))), { flush: true }));
}

// ------------------------------------------------------------------------------------------------ lessons
async function lessons(host: HTMLElement): Promise<void> {
  let label = "", source = "", q = "", offset = 0;
  const list = h("div");
  const counts = h("div");
  const loadList = async () => {
    const r = await get<{ total: number; items: Lesson[] }>(`/api/knowledge/lessons?label=${label}&source=${source}&q=${encodeURIComponent(q)}&offset=${offset}&limit=25`);
    const redo = () => void loadList().catch(fail);
    mount(list, r.items.length ? h("div", null, r.items.map((l) => h("div", { class: "k-sug k-lesson" },
      h("div", { class: "top" }, h("div", null, h("div", { class: "k-q-text" }, `“${l.body}”`),
        h("div", { class: "k-note" }, `${SOURCE[l.source] ?? l.source}${l.author ? ` · ${l.author}` : ""} · ${ago(l.ts)}${l.demo ? " · simulated" : ""}${l.pred !== null && l.pred !== undefined ? ` · bot first guessed ${Math.round(l.pred * 100)}% spam` : ""}`)),
        h("span", { class: `chip ${l.label === "spam" ? "bad" : "ok"}` }, l.label === "spam" ? "Spam" : "Fine")),
      h("div", { class: "acts" },
        h("button", { class: "btn small ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/knowledge/lessons/${l.id}/flip`); redo(); void loadCounts(); }) },
          icon("refresh", 14), l.label === "spam" ? "Actually fine" : "Actually spam"),
        confirmAct({ icon: "trash", label: "Forget this lesson", text: "Forget", confirmText: "Forget it", onConfirm: async () => { await del(`/api/knowledge/lessons/${l.id}`); toast("Forgotten"); redo(); void loadCounts(); } })))),
      h("div", { class: "k-sug row between" }, h("span", { class: "muted small" }, `${Math.min(offset + 1, r.total)}-${Math.min(offset + 25, r.total)} of ${r.total}`),
        h("div", { class: "row" },
          h("button", { class: "btn small ghost", type: "button", disabled: offset === 0, onclick: () => { offset = Math.max(0, offset - 25); redo(); } }, "Previous"),
          h("button", { class: "btn small ghost", type: "button", disabled: offset + 25 >= r.total, onclick: () => { offset += 25; redo(); } }, "Next"))))
      : h("div", { class: "k-sug" }, empty("book", q || label || source ? "No lessons match." : "No lessons yet. Approve or reject actions on the Desk, or teach it something above.")));
  };
  const loadCounts = async () => {
    const s = await get<Quality>("/api/knowledge/learning/quality");
    mount(counts, figures([{ value: String(s.counts.total), label: "lessons" }, { value: String(s.counts.spam), label: "spam", tone: "bad" }, { value: String(s.counts.ham), label: "fine", tone: "ok" },
      { value: s.active ? "Yes" : `At ${s.needed}`, label: "counted in scoring", tone: s.active ? "ok" : "warn" }]));
  };
  const text = h("textarea", { rows: 2, maxlength: "300", placeholder: "Paste a message to teach the bot", "aria-label": "Message to teach" }) as HTMLTextAreaElement;
  const teach = (l: "spam" | "ham", t: string, ic: string, tone: string) => h("button", { class: `btn ${tone}`, type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => {
    const r = await post<{ status: string }>("/api/knowledge/lessons", { label: l, text: text.value });
    toast(r.status === "duplicate" ? "It already knew that" : l === "spam" ? "Learned: spam" : "Learned: fine"); text.value = ""; offset = 0; await loadList(); void loadCounts(); }) }, icon(ic, 16), t);
  const search = h("input", { type: "search", placeholder: "Search lessons", "aria-label": "Search lessons", oninput: debounce(() => { q = (search as HTMLInputElement).value; offset = 0; void loadList().catch(fail); }, 250) });
  const filt = (title: string, opts: [string, string][], set: (v: string) => void) => {
    const sel = h("select", { "aria-label": title, onchange: () => { set((sel as HTMLSelectElement).value); offset = 0; void loadList().catch(fail); } }, opts.map(([v, t]) => h("option", { value: v }, t)));
    return sel;
  };
  const file = h("input", { type: "file", accept: "application/json,.json", hidden: true, onchange: async () => {
    const f = (file as HTMLInputElement).files?.[0]; if (!f) return;
    try { const r = await post<{ added: number; skipped: number }>("/api/knowledge/lessons/import", JSON.parse(await f.text())); toast(`${plural(r.added, "lesson")} imported, ${r.skipped} skipped`); await loadList(); void loadCounts(); }
    catch (e) { fail(e instanceof SyntaxError ? new Error("That file is not valid JSON.") : e); } (file as HTMLInputElement).value = ""; } });
  const exportBtn = h("button", { class: "btn small ghost", type: "button", onclick: () => busy(exportBtn as HTMLButtonElement, async () => {
    const data = await get<unknown>("/api/knowledge/lessons/export");
    const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" })), download: "savahbot-lessons.json" }) as HTMLAnchorElement;
    a.click(); URL.revokeObjectURL(a.href); }) }, icon("download", 14), "Export");

  mount(host, kcard("book", "Teach it something", h("div", { class: "k-stack" }, text, h("div", { class: "row" }, teach("spam", "This is spam", "ban", "bad-btn"), teach("ham", "This is fine", "check", "ok-btn")))),
    counts,
    kcard("history", "Everything it has learned", h("div", null,
      h("div", { class: "k-sug k-filters" }, search,
        filt("Label", [["", "Spam and fine"], ["spam", "Spam"], ["ham", "Fine"]], (v) => { label = v; }),
        filt("Source", [["", "Any source"], ...Object.entries(SOURCE)], (v) => { source = v; })),
      list), { flush: true, actions: h("div", { class: "row" }, exportBtn, h("button", { class: "btn small ghost", type: "button", onclick: () => file.click() }, icon("upload", 14), "Import"), file) }));
  await Promise.all([loadList(), loadCounts()]);
}

// ------------------------------------------------------------------------------------------------ quality
async function quality(host: HTMLElement): Promise<void> {
  const [d, ld] = await Promise.all([get<Quality>("/api/knowledge/learning/quality"), get<LearningData>("/api/knowledge/learning")]);
  const acc = (a: Acc) => (a.n >= 5 ? pct(a.accuracy) : "too few");
  const max = Math.max(1, ...d.timeline.map((t) => t.spam + t.ham));
  const bars = h("div", { class: "k-bars", role: "img", "aria-label": `Lessons learned per day, last 30 days. ${d.counts.total} in total.` },
    d.timeline.map((t) => h("div", { class: "k-bar", title: `${new Date(t.day * 1000).toLocaleDateString()}: ${t.spam} spam, ${t.ham} fine` },
      h("span", { class: "ham", style: `height:${(t.ham / max) * 100}%` }), h("span", { class: "spam", style: `height:${(t.spam / max) * 100}%` }))));
  const reliable = ld.stats.signals.filter((s) => s.detector);
  mount(host,
    d.drifting ? h("div", { class: "k-warn", role: "status" }, icon("alert", 18), h("div", null, h("strong", null, "Its accuracy has dropped recently"),
      h("div", { class: "k-note" }, `Over the last 2 weeks it was right ${pct(d.recent.accuracy)} of the time, down from ${pct(d.before.accuracy)} before. Check the latest lessons, forget any that were mistakes, or restore a snapshot in History.`))) : null,
    kcard("target", "How well it is doing", d.overall.n ? h("div", { class: "k-stack" },
      figures([{ value: acc(d.overall), label: "right before it learned the answer", tone: (d.overall.accuracy ?? 0) >= 0.8 ? "ok" : "warn" }, { value: String(d.overall.n), label: "lessons measured" },
        { value: String(d.overall.false_alarms), label: "false alarms", tone: d.overall.false_alarms ? "warn" : "" }, { value: String(d.overall.missed), label: "spam it missed", tone: d.overall.missed ? "warn" : "" }]),
      h("p", { class: "k-note" }, "Measured fairly: each lesson counts the bot's guess from before it learned the answer, never its own training data. Last 14 days: " + acc(d.recent) + ". Before that: " + acc(d.before) + "."))
      : invite("target", "Nothing to measure yet", "Once you have approved, rejected or taught a few messages, the bot's honest hit rate shows up here.")),
    kcard("chart", "Lessons per day", h("div", { class: "k-stack" }, bars, h("div", { class: "row k-legend" }, h("span", { class: "chip ok" }, "Fine"), h("span", { class: "chip bad" }, "Spam"),
      h("span", { class: "muted small" }, d.balance === null ? "" : `${Math.round(d.balance * 100)}% of lessons are spam`)))),
    kcard("shield", "Is it counting yet?", h("div", { class: "k-stack" }, meter(Math.min(1, d.counts.total / d.needed), d.active ? "ok" : "warn"),
      h("p", { class: "k-note" }, d.active ? `It has ${plural(d.counts.total, "lesson")}, enough for what it learned to count in scoring.`
        : `It has ${plural(d.counts.total, "lesson")}. Learning only influences scoring from ${d.needed} lessons, so a few early decisions cannot swing the bot. Change this with INTEL_LEARN_MIN_LESSONS.`))),
    reliable.length ? kcard("target", "How far to trust each detector", h("div", null, reliable.map((s) => {
      const n = s.approved + s.rejected;
      const tone = s.precision === null ? "" : s.precision >= 0.8 ? "ok" : s.precision >= 0.5 ? "warn" : "bad";
      return h("div", { class: "k-row-sig" }, h("div", null, h("strong", null, signalName(s.name)), h("div", { class: "muted small" }, `${s.approved} approved, ${s.rejected} rejected`)),
        meter(s.precision ?? 0, tone as "" | "ok" | "warn" | "bad"), h("span", { class: "chip" }, n >= 5 ? pct(s.precision) : "too few"));
    }))) : null);
}

// ------------------------------------------------------------------------------------------------ history
async function history(host: HTMLElement): Promise<void> {
  const [d, snaps] = await Promise.all([get<LearningData>("/api/knowledge/learning"), get<{ items: Snapshot[] }>("/api/knowledge/snapshots")]);
  const again = () => void history(host).catch(fail);
  const name = h("input", { type: "text", maxlength: "60", placeholder: "Name this snapshot", "aria-label": "Snapshot name" }) as HTMLInputElement;
  mount(host,
    kcard("history", "Changes it made", d.log.length ? h("div", { class: "k-stack" }, d.log.map((l) => h("div", { class: `k-log${l.undone ? " undone" : ""}` },
      h("span", { class: "txt" }, h("span", { class: "muted small" }, `${ago(l.ts)} · `), l.summary),
      l.undone ? h("span", { class: "chip" }, "undone") : h("button", { class: "btn small ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/knowledge/log/${l.id}/undo`); again(); }, "Undone") }, icon("undo", 14), "Undo"))))
      : h("p", { class: "k-note" }, "Nothing has been changed yet. Accepted suggestions and automatic changes are listed here, each with an Undo.")),
    kcard("save", "Snapshots of what it has learned", h("div", { class: "k-stack" },
      h("p", { class: "k-note" }, "A snapshot is a saved copy of all lessons. Restore one to go back to how the bot was. Restoring and resetting save a snapshot first, so they can be undone too."),
      h("div", { class: "row" }, name, h("button", { class: "btn small primary", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post("/api/knowledge/snapshots", { name: name.value || "Snapshot" }); toast("Snapshot saved"); again(); }) }, icon("plus", 14), "Save snapshot")),
      snaps.items.length ? h("div", null, snaps.items.map((s) => h("div", { class: "k-log" }, h("span", { class: "txt" }, h("strong", null, s.name), h("span", { class: "muted small" }, ` · ${plural(s.count, "lesson")} · ${ago(s.ts)}`)),
        h("div", { class: "row" },
          confirmAct({ icon: "undo", label: `Restore ${s.name}`, text: "Restore", confirmText: "Replace current lessons", onConfirm: async () => { const r = await post<{ restored: number }>(`/api/knowledge/snapshots/${s.id}/restore`); toast(`${plural(r.restored, "lesson")} restored`); again(); } }),
          confirmAct({ icon: "trash", label: `Delete ${s.name}`, text: "Delete", confirmText: "Delete snapshot", onConfirm: async () => { await del(`/api/knowledge/snapshots/${s.id}`); again(); } })))))
        : h("p", { class: "k-note" }, "No snapshots yet."))),
    kcard("alert", "Start over", h("div", { class: "k-stack" }, h("p", { class: "k-note" }, "Forget every lesson. The built-in packs and your own entries are not touched. A snapshot is saved first."),
      confirmAct({ icon: "trash", label: "Forget all lessons", text: "Forget all lessons", confirmText: "Yes, forget them all", onConfirm: async () => { const r = await post<{ cleared: number }>("/api/knowledge/learning/reset"); toast(`${plural(r.cleared, "lesson")} forgotten`); again(); } }))));
}
