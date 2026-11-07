import { del, get, post } from "../../api.js";
import { busy, dateTime, h, mount, toast, toastAction } from "../../dom.js";
import { icon } from "../../icons.js";
import { empty } from "../shared.js";
import { autoGrow, confirmAct, iconAct, invite, plural, seg } from "../widgets.js";
import { lineChart, n0, pct, setSetting } from "./common.js";

interface Stats {
  examples: { spam: number; ham: number; total: number }; seed: { spam: number; ham: number }; ready: boolean; vocabulary: number; prior: number; mode: string;
  accuracy: { n: number; overall: number | null; recent: number | null; catches_spam: number | null; spares_ham: number | null; series: { t: number; acc: number; n: number }[] };
  distrust: { token: string; score: number; spam: number; ham: number }[]; trust: { token: string; score: number; spam: number; ham: number }[];
}
interface Example { id: number; ts: number; label: "spam" | "ham"; source: string; body: string; author: string; weight: number }
interface SettingItem { name: string; value: unknown }

const SOURCE: Record<string, string> = { decision: "Your decision", teach: "Taught by you", trusted: "Trusted chatter" };

export function renderLearning(root: HTMLElement): void {
  const top = h("div");
  const words = h("div");
  const lessons = h("div");
  const more = h("div", { class: "row center" });
  const toggles = h("div");
  let label: "all" | "spam" | "ham" = "all";
  let needle = "";
  let limit = 30;
  let total = 0;

  // ---------------------------------------------------------------- teach box
  const text = h("textarea", { rows: 2, maxLength: 1000, placeholder: "Paste any chat message to teach the bot about it", "aria-label": "Message to teach" }) as HTMLTextAreaElement;
  autoGrow(text, 180);
  const teach = (l: "spam" | "ham", btn: HTMLButtonElement) => busy(btn, async () => {
    if (!text.value.trim()) throw new Error("Paste a message first.");
    const r = await post<{ skipped: boolean }>("/api/intel/teach", { label: l, text: text.value });
    if (r.skipped) { toast("It already knows that one."); return; }
    text.value = ""; await loadAll();
  }, l === "spam" ? "Learned: that is spam" : "Learned: that is fine");
  const spamBtn = h("button", { class: "btn bad-btn", type: "button" }, icon("ban", 16), "This is spam");
  const hamBtn = h("button", { class: "btn ok-btn", type: "button" }, icon("check", 16), "This is fine");
  spamBtn.addEventListener("click", () => teach("spam", spamBtn));
  hamBtn.addEventListener("click", () => teach("ham", hamBtn));
  const teachBox = h("section", { class: "wb", "aria-label": "Teach the bot" }, h("h2", null, "Teach the bot"),
    h("p", { class: "lede" }, "A deliberate lesson counts double. You can also teach from Moderation history, and every Approve or Reject teaches it automatically."), text, h("div", { class: "row" }, spamBtn, hamBtn));

  // ---------------------------------------------------------------- the numbers
  const drawTop = (s: Stats) => {
    const a = s.accuracy;
    const series = a.series.map((p) => ({ label: new Date(p.t * 1000).toLocaleDateString([], { month: "short", day: "numeric" }), v: p.acc }));
    mount(top, h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("sparkle", 18), "How well it is doing"), h("span", { class: `chip ${s.ready ? "ok" : ""}` }, s.ready ? "Ready" : "Warming up")),
      h("div", { class: "kn-figs wide" },
        h("div", { class: "fig" }, h("b", null, n0(s.examples.total)), h("span", null, `lessons from you (${s.examples.spam} spam, ${s.examples.ham} fine)`)),
        h("div", { class: "fig" }, h("b", null, `${s.seed.spam + s.seed.ham}`), h("span", null, "shipped head-start examples")),
        h("div", { class: "fig" }, h("b", null, pct(a.recent)), h("span", null, "recent accuracy")),
        h("div", { class: "fig" }, h("b", null, n0(s.vocabulary)), h("span", null, "words and fragments known"))),
      a.n >= 10
        ? h("div", { class: "lc-wrap" }, h("div", { class: "row between" }, h("strong", { class: "small" }, "Accuracy as it learned"), h("span", { class: "muted small" }, `${pct(a.catches_spam)} of spam caught, ${pct(a.spares_ham)} of normal chat spared`)),
            lineChart(series, { guide: 0.5, aria: `Accuracy over time, now ${pct(a.recent)}` }), h("p", { class: "muted small" }, `Honest figures: each message was guessed at before it was learned (${plural(a.n, "guess", "guesses")} so far). The dashed line is guessing by coin toss.`))
        : h("p", { class: "muted small", style: "padding:0 16px 16px" }, a.n ? `${plural(a.n, "guess", "guesses")} so far. The accuracy chart appears after 10.` : "No guesses to score yet. Accuracy appears once it has been taught a few messages.")));
  };
  const rank = (title: string, ic: string, rows: Stats["distrust"], tone: string) => h("section", { class: "block flush" }, h("header", null, h("h2", null, icon(ic, 18), title)),
    rows.length ? h("ol", { class: "rank" }, rows.slice(0, 12).map((r, i) => h("li", null, h("span", { class: "rk-n" }, String(i + 1)),
      h("div", { class: "rk-main" }, h("div", { class: "row between nowrap" }, h("strong", { class: "wrap" }, r.token), h("span", { class: "muted small" }, `${r.spam} spam, ${r.ham} fine`)),
        h("span", { class: "track" }, h("i", { class: tone, style: `width:${Math.min(100, Math.abs(r.score) * 12 + 6)}%` })))))) : empty("sparkle", "Nothing stands out yet."));
  const drawWords = (s: Stats) => mount(words, h("div", { class: "cols even" }, rank("Words it distrusts", "alert", s.distrust, "s4"), rank("Words it trusts", "check", s.trust, "s3")));

  // ---------------------------------------------------------------- lessons
  const find = h("input", { type: "search", placeholder: "Search lessons", "aria-label": "Search lessons", autocomplete: "off" });
  let timer = 0;
  find.addEventListener("input", () => { window.clearTimeout(timer); timer = window.setTimeout(() => { needle = find.value.trim(); limit = 30; void loadLessons(); }, 250); });
  const labelSeg = seg("Lessons shown", [{ id: "all" as const, label: "All" }, { id: "spam" as const, label: "Spam" }, { id: "ham" as const, label: "Fine" }], label, (v) => { label = v; limit = 30; void loadLessons(); });
  const drawLessons = (items: Example[]) => {
    if (!items.length) { mount(lessons, label === "all" && !needle ? invite("sparkle", "No lessons yet", "Approve or reject a request in Moderation, or paste a message above, and it shows up here. You can forget any lesson later.") : empty("search", "No lessons match.")); mount(more, null); return; }
    mount(lessons, h("ul", { class: "lessons" }, items.map((x) => h("li", null,
      h("span", { class: `lbl ${x.label}` }, icon(x.label === "spam" ? "ban" : "check", 14), x.label === "spam" ? "Spam" : "Fine"),
      h("div", { class: "ls-main" }, h("span", { class: "ls-text wrap" }, x.body), h("span", { class: "muted small" }, [SOURCE[x.source] ?? x.source, x.author, dateTime(x.ts)].filter(Boolean).join(" · "))),
      iconAct("trash", "Forget this lesson", (e) => busy(e.currentTarget as HTMLButtonElement, async () => {
        await del(`/api/intel/examples/${x.id}`); await loadAll();
        toastAction("Lesson forgotten", "Undo", async () => { await post("/api/intel/teach", { label: x.label, text: x.body, author: x.author }); await loadAll(); });
      }), "danger")))));
    mount(more, total > items.length ? h("button", { class: "btn ghost", type: "button", onclick: () => { limit += 30; void loadLessons(); } }, `Show more (${n0(total - items.length)} left)`) : null);
  };
  const loadLessons = async () => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (label !== "all") q.set("label", label);
    if (needle) q.set("q", needle);
    const r = await get<{ items: Example[]; total: number }>(`/api/intel/examples?${q.toString()}`);
    total = r.total; drawLessons(r.items);
  };

  // ---------------------------------------------------------------- what it may learn from
  const drawToggles = (items: SettingItem[]) => {
    const val = (n: string) => Boolean(items.find((i) => i.name === n)?.value);
    const row = (name: string, title: string, help: string) => h("label", { class: "ambient" }, h("span", { class: "ambient-text" }, h("strong", null, title), h("span", { class: "muted small" }, help)),
      h("input", { type: "checkbox", class: "switch", checked: val(name), "aria-label": title, onchange: (e: Event) => { const el = e.target as HTMLInputElement; void setSetting(name, el.checked).then((ok) => { if (!ok) el.checked = !el.checked; }); } }));
    mount(toggles, h("section", { class: "block flush" }, h("header", null, h("h2", null, icon("sliders", 18), "What it may learn from")),
      h("div", { class: "kn-toggles" },
        row("intel_learn_auto", "My Approve and Reject decisions", "Approve teaches 'spam', Reject teaches 'fine'."),
        row("intel_learn_trusted_ham", "Ordinary messages from trusted chatters", "A few a minute at most, never commands, only messages that were left alone."),
        row("intel_learn_from_demo", "Demo messages too", "Off by default so test data never teaches the bot."))));
  };

  const danger = h("section", { class: "danger-zone" }, h("div", null, h("strong", null, "Forget everything it learned from you"), h("p", { class: "muted small" }, "Removes every lesson. The shipped head-start examples stay, so it keeps working.")),
    confirmAct({ icon: "trash", label: "Forget all lessons", text: "Forget everything", confirmText: "Tap again to forget", onConfirm: async () => { try { const r = await post<{ forgotten: number }>("/api/intel/learning/reset"); toast(`Forgot ${plural(r.forgotten, "lesson")}`); await loadAll(); } catch (e) { toast((e as Error).message, "error"); } } }));

  const loadAll = async () => {
    const [s, st] = await Promise.all([get<Stats>("/api/intel/learning"), get<{ items: SettingItem[] }>("/api/settings")]);
    drawTop(s); drawWords(s); drawToggles(st.items); await loadLessons();
  };
  mount(root, h("div", { class: "stack" }, top, teachBox, words,
    h("section", { class: "nb-list" }, h("h3", { class: "coll-title" }, icon("notebook", 14), "Lessons"), h("div", { class: "nb-tools" }, h("div", { class: "input-icon grow" }, icon("search", 16), find)), labelSeg.el, lessons, more),
    toggles, danger));
  void loadAll().catch((e) => toast(e.message, "error"));
}
