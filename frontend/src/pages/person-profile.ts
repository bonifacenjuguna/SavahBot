/** The profile of a banned or timed-out person (1.4.3): who they are, WHY it happened (the messages that caused it, what flagged them, the chat around
 *  it) and everything that has happened to them. Opened from the Bans ledger. Data comes from GET /api/bans/{id}/profile. */
import { get, post } from "../api.js";
import { ago, dateTime, duration, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { SIGNAL, avatar, figures, niceName } from "./widgets.js";

interface Msg { id: number; ts: number; body: string; verdict: string; score: number; level: string; demo?: number }
interface Line { id: number; ts: number; name: string; body: string; verdict: string; mine: boolean; evidence: boolean; bot: boolean }
interface Past { id: number; ts: number; kind: "ban" | "timeout"; duration: number | null; source: string; reason: string; status: string; lifted_ts: number | null; lifted_by: string; demo: number }
interface Logged { id: number; ts: number; action: string; duration: number | null; score: number; reasons: string[]; status: string; mode: string; body: string; demo: number }
interface Profile {
  ban: Past & { author_id: string; author_name: string; can_lift: boolean; error: string };
  person: { id: string; name: string; platform: string; messages: number; flagged: number; first_seen: number | null; last_seen: number | null; regular: boolean; notes: { body: string }[] };
  why: { how: "recorded" | "kept" | "guess" | "none"; reason: string; source: string; score: number | null; signals: string[]; evidence: Msg[] };
  context: Line[]; history: Past[]; actions: Logged[]; recent: Msg[];
}

const SOURCE: Record<string, string> = { auto: "Done by the bot", approved: "Approved by you", manual: "Added by you", dashboard: "Chosen by you in the chat" };
const when = (t: number) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const what = (k: string, d: number | null) => (k === "ban" ? "Banned" : `Timed out${d ? " for " + duration(d) : ""}`);
const chip = (text: string, tone = "") => h("span", { class: `chip${tone ? " " + tone : ""}` }, text);
const verdictChip = (v: string) => (v === "block" ? chip("held back", "bad") : v === "flag" ? chip("flagged", "warn") : null);
const section = (ico: string, title: string, ...kids: (Node | null)[]) => h("section", { class: "pf-sec" }, h("h3", null, icon(ico, 16), title), ...kids.filter(Boolean) as Node[]);

export function openBanProfile(b: { id: number; author_name: string; author_id: string }, onChange?: () => void): void {
  const body = h("div", { class: "pf" }, h("p", { class: "muted" }, "Loading the profile…"));
  sheet(b.author_name || b.author_id, body);
  body.closest(".sheet")?.classList.add("profile-sheet");
  const load = async () => { try { draw(await get<Profile>(`/api/bans/${b.id}/profile`)); } catch (e) { mount(body, h("p", { class: "muted" }, e instanceof Error ? e.message : "Could not load the profile.")); } };

  const draw = (p: Profile) => {
    const { ban, person, why } = p;
    const name = person.name || ban.author_name || person.id;
    const state = ban.status === "active" ? (ban.kind === "ban" ? "Banned now" : "Timed out now") : ban.status === "lifted" ? "Lifted" : "Ended";
    const lift = h("button", { class: "btn primary small", type: "button", disabled: !ban.can_lift, title: ban.can_lift ? "" : "YouTube gave no id for this ban, so it can only be lifted in YouTube Studio." }, icon("undo", 15), "Lift this") as HTMLButtonElement;
    lift.onclick = () => { lift.disabled = true; void post(`/api/bans/${ban.id}/lift`).then(async () => { toast(`${name} can chat again`, "ok"); onChange?.(); await load(); }).catch((e) => { lift.disabled = false; toast(e instanceof Error ? e.message : "Could not lift", "error"); }); };
    const note = h("button", { class: "btn small", type: "button" }, icon("edit", 15), "Add a note") as HTMLButtonElement;
    note.onclick = () => { note.disabled = true; void post("/api/notes", { body: `@${name}: ${what(ban.kind, ban.duration)} on ${dateTime(ban.ts)}. ${ban.reason || ""}`.trim().slice(0, 1000), tags: ["ban"], pinned: false }).then(() => toast("Added to the Notebook", "ok")).catch((e) => { note.disabled = false; toast(e.message, "error"); }); };
    const copyId = h("button", { class: "btn small ghost", type: "button", onclick: () => { void navigator.clipboard?.writeText(person.id).then(() => toast("ID copied", "ok")); } }, icon("copy", 15), "Copy ID");

    // ---- why it happened
    const evidenceNote = { recorded: "The message that caused it, as the bot saw it:", kept: "The text that caused it, kept in the moderation log (the chat line itself is no longer stored):",
      guess: "This was chosen by hand, so no single message is recorded. Their latest messages just before it:", none: "No messages from this person are stored." }[why.how];
    const signals = why.signals.map((s) => { const [k, ...rest] = s.split(":"); return h("span", { class: "chip", title: s }, niceName(SIGNAL, k.trim()), rest.length ? h("span", { class: "muted small" }, ` ${rest.join(":").trim()}`) : null); });
    const quote = (m: Msg) => h("blockquote", { class: "pf-quote" }, h("div", { class: "pf-qmeta" }, h("span", { class: "muted small" }, when(m.ts)), verdictChip(m.verdict)), h("div", { class: "pf-qtext" }, m.body));
    const whySec = section("search", "Why it happened",
      h("p", null, h("strong", null, what(ban.kind, ban.duration)), ` · ${when(ban.ts)} · ${SOURCE[why.source] ?? why.source}${ban.demo ? " · demo" : ""}`),
      why.reason ? h("p", { class: "pf-reason" }, why.reason) : null,
      signals.length || why.score !== null ? h("div", { class: "chip-row tight" }, why.score !== null ? chip(`Score ${why.score}`, "warn") : null, ...signals) : null,
      h("p", { class: "muted small" }, evidenceNote), ...why.evidence.map(quote));

    // ---- the chat around it
    const log = h("div", { class: "pf-chat", role: "log", tabindex: 0, "aria-label": "Chat around the ban" }, p.context.map((l) =>
      h("div", { class: `pf-line${l.mine ? " mine" : ""}${l.evidence ? " evi" : ""}${l.bot ? " bot" : ""}` },
        h("span", { class: "pf-time muted small" }, new Date(l.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })),
        h("strong", null, l.name || "?"), " ", h("span", { class: "pf-text" }, l.body), l.evidence ? h("span", { class: "pf-flag", title: "A message that caused it" }, icon("flag", 13)) : null)));
    const chatSec = p.context.length ? section("message", "The chat around it", h("p", { class: "muted small" }, "Everyone's messages from just before to just after. Theirs are highlighted."), log) : null;

    // ---- history
    const past = (x: Past) => h("li", { class: `pf-item${x.id === ban.id ? " here" : ""}` },
      h("div", { class: "row between wrap", style: "gap:8px;align-items:center" }, h("strong", null, what(x.kind, x.duration)), chip(x.status, x.status === "active" ? "warn" : "")),
      h("div", { class: "muted small" }, `${when(x.ts)} · ${SOURCE[x.source] ?? x.source}${x.id === ban.id ? " · this entry" : ""}`),
      x.reason ? h("div", { class: "muted small wrap" }, x.reason) : null,
      x.status === "lifted" && x.lifted_ts ? h("div", { class: "muted small" }, `Lifted ${when(x.lifted_ts)} by ${x.lifted_by}`) : null);
    const histSec = section("clock", `Bans and timeouts (${p.history.length})`, h("ol", { class: "pf-list" }, p.history.map(past)));
    const logged = p.actions.length ? h("details", { class: "pf-more" }, h("summary", null, `Moderation log (${p.actions.length})`), h("ol", { class: "pf-list" }, p.actions.map((a) =>
      h("li", { class: "pf-item" }, h("div", { class: "row between wrap", style: "gap:8px" }, h("strong", null, a.action === "delete" ? "Message deleted" : a.action === "ban" ? "Ban" : `Timeout${a.duration ? " " + duration(a.duration) : ""}`), chip(a.status)),
        h("div", { class: "muted small" }, `${when(a.ts)} · score ${a.score} · ${a.mode}`),
        a.reasons.length ? h("div", { class: "chip-row tight" }, a.reasons.map((r) => chip(niceName(SIGNAL, r.split(":")[0].trim())))) : null,
        a.body ? h("div", { class: "muted small wrap" }, a.body.slice(0, 200)) : null)))) : null;
    const recent = h("details", { class: "pf-more" }, h("summary", null, `Latest messages (${p.recent.length})`),
      p.recent.length ? h("ol", { class: "pf-list" }, p.recent.map((m) => h("li", { class: "pf-item" }, h("div", { class: "muted small" }, when(m.ts), " ", verdictChip(m.verdict)), h("div", { class: "wrap" }, m.body)))) : h("p", { class: "muted small" }, "None stored."));
    const notes = person.notes.length ? section("edit", "Notes", ...person.notes.map((n) => h("div", { class: "muted small wrap" }, n.body))) : null;

    mount(body,
      h("div", { class: "pf-head" }, avatar(name, 56), h("div", { class: "pf-who" }, h("strong", { class: "pf-name" }, name),
        h("div", { class: "chip-row tight" }, chip(state, ban.status === "active" ? "bad" : ""), person.regular ? chip("Regular") : null, ban.demo ? chip("Demo") : null),
        h("div", { class: "muted small" }, `${person.platform} · ID ${person.id}`))),
      figures([{ value: person.messages.toLocaleString(), label: "messages stored" }, { value: person.flagged.toLocaleString(), label: "flagged", tone: person.flagged ? "warn" : "" },
        { value: String(p.history.length), label: p.history.length === 1 ? "time restricted" : "times restricted", tone: p.history.length > 1 ? "bad" : "" },
        { value: person.first_seen ? ago(person.first_seen) : "-", label: "first seen" }]),
      ban.error ? h("p", { class: "small", style: "color:var(--bad, #c0392b)" }, ban.error) : null,
      h("div", { class: "row wrap pf-actions" }, ban.status === "active" ? lift : null, note, copyId),
      whySec, chatSec, histSec, logged, recent, notes);
    const first = log.querySelector<HTMLElement>(".evi");
    if (first) log.scrollTop = Math.max(0, first.offsetTop - 60);
  };
  void load();
}
