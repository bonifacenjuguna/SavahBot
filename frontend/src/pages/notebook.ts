import { del, get, patch, post } from "../api.js";
import { busy, dateTime, h, inUntil, mount, toast, toastAction } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav, dateRange, type RangeValue } from "./kit.js";
import { pageHead, paneTabs } from "./shared.js";
import type { Page } from "./types.js";
import { autoGrow, dayTime, iconAct, invite, linkify } from "./widgets.js";

interface Note { id: number; body: string; tags: string[] | string; pinned: boolean; created: number; updated: number }
interface Reminder { id: number; body: string; due: number; repeat_kind: string }

const tagList = (n: Note): string[] => (Array.isArray(n.tags) ? n.tags : String(n.tags || "").split(",")).map((t) => t.trim()).filter(Boolean);
const MAX = 5000;
const VIEW_KEY = "savahbot.noteview";

/** Starting points for the things a streamer writes most. A line that starts with [ ] becomes a tick box. */
const TEMPLATES: { id: string; label: string; icon: string; text: string; tag: string }[] = [
  { id: "plan", label: "Stream plan", icon: "checklist", tag: "stream", text: "Stream plan\n[ ] Title and thumbnail ready\n[ ] Audio and camera tested\n[ ] Chat rules pinned\n[ ] Post to socials\n[ ] Say hello to regulars" },
  { id: "ideas", label: "Ideas", icon: "sparkle", tag: "ideas", text: "Ideas\n- \n- \n- " },
  { id: "shout", label: "Shout-outs", icon: "users", tag: "shoutouts", text: "Shout-outs for this stream\n[ ] \n[ ] \n[ ] " },
];

const TASK = /^(\s*(?:[-*]\s+)?)\[( |x|X)\]\s?(.*)$/;
type Block = { kind: "text"; text: string } | { kind: "task"; line: number; done: boolean; text: string };

function blocks(body: string): Block[] {
  const out: Block[] = [];
  body.split("\n").forEach((line, i) => {
    const m = TASK.exec(line);
    if (m) { out.push({ kind: "task", line: i, done: m[2].toLowerCase() === "x", text: m[3] }); return; }
    const last = out[out.length - 1];
    if (last?.kind === "text") last.text += `\n${line}`;
    else out.push({ kind: "text", text: line });
  });
  return out.filter((b) => b.kind === "task" || b.text.trim() !== "");
}

/** Flips one tick box and returns the new text of the note. */
export function toggleTask(body: string, line: number): string {
  const lines = body.split("\n");
  const m = lines[line] !== undefined ? TASK.exec(lines[line]) : null;
  if (!m) return body;
  lines[line] = `${m[1]}[${m[2] === " " ? "x" : " "}] ${m[3]}`;
  return lines.join("\n");
}

export const notebook: Page = {
  id: "notebook",
  title: "Notebook",
  icon: "notebook",
  blurb: "Private notes and reminders",
  render(root, query) {
    let notes: Note[] = [];
    let reminders: Reminder[] = [];
    let needle = "";
    let tagFilter = "";
    let range: RangeValue = { label: "", active: false };
    let order: "new" | "old" = "new";
    let view: "grid" | "list" = (() => { try { return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid"; } catch { return "grid"; } })();
    let editing: number | null = null;
    let alive = true;

    // ================================================================== composer
    const body = h("textarea", { rows: 3, maxLength: MAX, placeholder: "Write a note. Start a line with [ ] to make a checklist.", "aria-label": "Note" });
    autoGrow(body, 320);
    const tagsIn = h("input", { type: "text", placeholder: "Tags, separated by commas", "aria-label": "Tags", autocomplete: "off", maxLength: 120 });
    const suggest = h("div", { class: "chip-row" });
    const counter = h("span", { class: "muted small" }, `0 / ${MAX.toLocaleString()}`);
    const save = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Save note");
    const finePointer = typeof matchMedia === "function" && matchMedia("(pointer: fine)").matches;
    const drawSuggest = () => {
      const typed = tagsIn.value.split(",").map((t) => t.trim().toLowerCase());
      const known = Array.from(new Set(notes.flatMap(tagList))).filter((t) => !typed.includes(t.toLowerCase())).slice(0, 6);
      mount(suggest, known.length ? [h("span", { class: "muted small" }, "Tap to add"), ...known.map((t) => h("button", { type: "button", class: "chip pick", onclick: () => { tagsIn.value = [...tagsIn.value.split(",").map((x) => x.trim()).filter(Boolean), t].join(", "); drawSuggest(); } }, icon("tag", 12), t))] : null);
    };
    const refit = () => (body as HTMLTextAreaElement & { refit?: () => void }).refit?.();
    body.addEventListener("input", () => { counter.textContent = `${body.value.length.toLocaleString()} / ${MAX.toLocaleString()}`; });
    tagsIn.addEventListener("input", drawSuggest);
    body.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); composer.requestSubmit(); } });
    const templates = h("div", { class: "chip-row" }, h("span", { class: "muted small" }, "Start from"), TEMPLATES.map((t) => h("button", { type: "button", class: "chip pick", onclick: () => {
      body.value = body.value.trim() ? `${body.value.replace(/\s+$/, "")}\n\n${t.text}` : t.text;
      if (!tagsIn.value.trim()) tagsIn.value = t.tag;
      body.dispatchEvent(new Event("input"));
      refit(); drawSuggest(); body.focus();
    } }, icon(t.icon, 13), t.label)));
    const composer = h("form", { class: "wb-form", onsubmit: (e: Event) => {
      e.preventDefault();
      const text = body.value.trim();
      if (!text) { toast("Write something first.", "error"); body.focus(); return; }
      busy(save, async () => {
        await post("/api/notes", { body: text, tags: tagsIn.value.split(",").map((t) => t.trim()).filter(Boolean) });
        body.value = ""; tagsIn.value = ""; counter.textContent = `0 / ${MAX.toLocaleString()}`; refit();
        await loadNotes();
      }, "Note saved");
    } },
      body, templates, h("div", { class: "wb-row" }, h("div", { class: "grow" }, tagsIn)), suggest,
      h("div", { class: "wb-foot" }, h("span", { class: "row", style: "gap:10px" }, counter, finePointer ? h("span", { class: "muted small" }, "Ctrl+Enter saves") : null), save));
    const composerBox = h("section", { class: "wb", "aria-label": "New note" }, h("h2", null, "New note"), composer);

    // ================================================================== notes list
    const search = h("input", { type: "search", placeholder: "Search notes", "aria-label": "Search notes", autocomplete: "off" });
    search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); drawBoard(); });
    const dates = dateRange({ presets: ["any", "today", "7d", "30d", "custom"], label: "Notes by date written" }, (v) => { range = v; datesBtn.classList.toggle("on", v.active); drawBoard(); });
    const datesPanel = h("div", { class: "toolbar-dates", hidden: true }, dates.el);
    const datesBtn = h("button", { class: "tool-btn", type: "button", "aria-label": "Filter by date", "aria-expanded": "false", onclick: () => { datesPanel.hidden = !datesPanel.hidden; datesBtn.setAttribute("aria-expanded", String(!datesPanel.hidden)); } }, icon("calendar", 17));
    const sortBtn = h("button", { class: "tool-btn", type: "button", onclick: () => { order = order === "new" ? "old" : "new"; paintTools(); drawBoard(); } });
    const viewBtn = h("button", { class: "tool-btn", type: "button", onclick: () => { view = view === "grid" ? "list" : "grid"; try { localStorage.setItem(VIEW_KEY, view); } catch { /* private mode */ } paintTools(); drawBoard(); } });
    const paintTools = () => {
      mount(sortBtn, icon("clock", 17), h("span", { class: "hide-narrow" }, order === "new" ? "Newest" : "Oldest"));
      sortBtn.setAttribute("aria-label", order === "new" ? "Showing newest first. Switch to oldest first." : "Showing oldest first. Switch to newest first.");
      mount(viewBtn, icon(view === "grid" ? "list" : "grid", 17));
      viewBtn.setAttribute("aria-label", view === "grid" ? "Switch to list" : "Switch to grid");
    };
    paintTools();
    const tagBox = h("div", { class: "scroll-x" });
    const tools = h("div", { class: "nb-tools", hidden: true }, h("div", { class: "input-icon grow" }, icon("search", 16), search), datesBtn, sortBtn, viewBtn);
    const board = h("div");

    const reloadAfter = async (fn: () => Promise<unknown>) => { await fn(); await loadNotes(); };

    const noteBody = (n: Note): HTMLElement => {
      const parts = blocks(n.body);
      const tasks = parts.filter((b): b is Extract<Block, { kind: "task" }> => b.kind === "task");
      const done = tasks.filter((t) => t.done).length;
      const out: HTMLElement[] = [];
      let run: HTMLElement[] = [];
      const flush = () => { if (run.length) { out.push(h("ul", { class: "tasks" }, run)); run = []; } };
      for (const b of parts) {
        if (b.kind === "text") { flush(); out.push(h("div", { class: "note-text" }, linkify(b.text))); continue; }
        const box = h("input", { type: "checkbox", checked: b.done, "aria-label": b.text || "Item" });
        box.addEventListener("change", () => {
          const next = toggleTask(n.body, b.line);
          n.body = next;
          drawBoard();
          patch(`/api/notes/${n.id}`, { body: next }).catch((e: Error) => { toast(e.message, "error"); void loadNotes(); });
        });
        run.push(h("li", { class: b.done ? "task done" : "task" }, h("label", null, box, h("span", null, b.text ? linkify(b.text) : h("em", { class: "muted" }, "Empty item")))));
      }
      flush();
      if (tasks.length) out.push(h("div", { class: "task-meter", role: "img", "aria-label": `${done} of ${tasks.length} done` }, h("span", { class: "tm-bar" }, h("i", { style: `width:${Math.round((done / tasks.length) * 100)}%` })), h("span", { class: "muted small" }, `${done} of ${tasks.length} done`)));
      return h("div", { class: "note-body" }, out);
    };

    const editor = (n: Note): HTMLElement => {
      const text = h("textarea", { maxLength: MAX, "aria-label": "Edit note", rows: 4 }) as HTMLTextAreaElement;
      text.value = n.body;
      autoGrow(text, 360);
      const tg = h("input", { type: "text", value: tagList(n).join(", "), "aria-label": "Edit tags", placeholder: "Tags, separated by commas" });
      const ok = h("button", { class: "btn small primary", type: "button" }, icon("check", 15), "Save");
      ok.addEventListener("click", () => busy(ok, async () => {
        if (!text.value.trim()) throw new Error("A note cannot be empty. Delete it instead.");
        await patch(`/api/notes/${n.id}`, { body: text.value, tags: tg.value.split(",").map((t) => t.trim()).filter(Boolean) });
        editing = null; await loadNotes();
      }, "Note updated"));
      const no = h("button", { class: "btn small ghost", type: "button", onclick: () => { editing = null; drawBoard(); } }, "Cancel");
      text.addEventListener("keydown", (e) => { if (e.key === "Escape") { editing = null; drawBoard(); } if ((e.ctrlKey || e.metaKey) && e.key === "Enter") ok.click(); });
      queueMicrotask(() => text.focus());
      return h("div", { class: "note-edit" }, text, tg, h("div", { class: "row" }, ok, no));
    };

    const noteCard = (n: Note): HTMLElement => {
      if (editing === n.id) return h("article", { class: `note editing${n.pinned ? " pinned" : ""}` }, editor(n));
      const edited = n.updated - n.created > 60;
      return h("article", { class: `note${n.pinned ? " pinned" : ""}` },
        h("div", { class: "note-meta" }, n.pinned ? h("span", { class: "pin-mark", title: "Pinned" }, icon("pin", 13)) : null, h("span", { title: dateTime(n.created) }, dayTime(n.created)), edited ? h("span", { class: "muted" }, "edited") : null),
        noteBody(n),
        h("div", { class: "note-foot" },
          h("div", { class: "chip-row tight" }, tagList(n).map((t) => h("button", { type: "button", class: `chip pick${tagFilter === t ? " on" : ""}`, "aria-label": `Show notes tagged ${t}`, onclick: () => { tagFilter = tagFilter === t ? "" : t; drawTags(); drawBoard(); } }, t))),
          h("div", { class: "acts" },
            iconAct("pin", n.pinned ? "Unpin note" : "Pin note", (e) => busy(e.currentTarget as HTMLButtonElement, () => reloadAfter(() => patch(`/api/notes/${n.id}`, { pinned: !n.pinned }))), n.pinned ? "accent" : ""),
            iconAct("edit", "Edit note", () => { editing = n.id; drawBoard(); }),
            iconAct("copy", "Copy note", () => { void navigator.clipboard?.writeText(n.body).then(() => toast("Copied")).catch(() => toast("Your browser blocked copying.", "error")); }),
            iconAct("trash", "Delete note", (e) => busy(e.currentTarget as HTMLButtonElement, async () => {
              const keep = { body: n.body, tags: tagList(n), pinned: n.pinned };
              await del(`/api/notes/${n.id}`); await loadNotes();
              toastAction("Note deleted", "Undo", async () => { await post("/api/notes", keep); await loadNotes(); });
            }), "danger"))));
    };

    const shown = (): Note[] => notes
      .filter((n) => (!needle || `${n.body} ${tagList(n).join(" ")}`.toLowerCase().includes(needle)) && (!tagFilter || tagList(n).includes(tagFilter))
        && (range.since === undefined || n.created >= range.since) && (range.until === undefined || n.created < range.until))
      .sort((a, b) => (order === "new" ? b.created - a.created : a.created - b.created));

    const drawBoard = () => {
      const list = shown();
      const pinned = list.filter((n) => n.pinned), rest = list.filter((n) => !n.pinned);
      const grid = (items: Note[]) => h("div", { class: `nb-board${view === "list" ? " as-list" : ""}` }, items.map(noteCard));
      if (!notes.length) {
        mount(board, invite("notebook", "Your notebook is empty", "Keep segment plans, shout-outs and things to remember. Only you can see them.",
          h("button", { class: "btn primary", type: "button", onclick: () => { const t = TEMPLATES[0]; body.value = t.text; tagsIn.value = t.tag; body.dispatchEvent(new Event("input")); refit(); body.focus(); composerBox.scrollIntoView({ block: "center", behavior: "smooth" }); } }, icon("checklist", 16), "Start a stream plan")));
        return;
      }
      if (!list.length) {
        const filtered = !!(needle || tagFilter || range.active);
        mount(board, invite("search", "No notes match", range.active ? `Nothing was written ${range.label.toLowerCase()} that fits.` : "Try a different word or clear the tag filter.",
          filtered ? h("button", { class: "btn ghost", type: "button", onclick: () => { needle = ""; search.value = ""; tagFilter = ""; dates.reset(); range = { label: "", active: false }; datesBtn.classList.remove("on"); drawTags(); drawBoard(); } }, "Clear filters") : null));
        return;
      }
      mount(board,
        pinned.length ? h("div", { class: "coll" }, h("h3", { class: "coll-title" }, icon("pin", 14), "Pinned"), grid(pinned)) : null,
        rest.length ? h("div", { class: "coll" }, pinned.length ? h("h3", { class: "coll-title" }, "Everything else") : null, grid(rest)) : null);
    };
    const drawTags = () => {
      const tags = Array.from(new Set(notes.flatMap(tagList)));
      if (tagFilter && !tags.includes(tagFilter)) tagFilter = "";
      mount(tagBox, tags.length ? h("div", { class: "chip-row nowrap" }, [["", "All"], ...tags.slice(0, 12).map((t) => [t, t])].map(([v, l]) => h("button", { type: "button", class: `chip pick${tagFilter === v ? " on" : ""}`, "aria-pressed": String(tagFilter === v), onclick: () => { tagFilter = v; drawTags(); drawBoard(); } }, v ? icon("tag", 12) : null, l))) : null);
    };
    const loadNotes = async () => {
      notes = (await get<{ items: Note[] }>("/api/notes")).items;
      tools.hidden = notes.length < 2;
      drawTags(); drawSuggest(); drawBoard();
    };

    const notesPane = h("div", { class: "stack" }, composerBox, h("section", { class: "nb-list", "aria-label": "Your notes" }, tools, datesPanel, tagBox, board));

    // ================================================================== reminders
    const when = h("input", { type: "text", required: true, placeholder: "30m, 18:30, tomorrow 09:00, daily 08:00", maxLength: 100, "aria-label": "When", autocomplete: "off" });
    const what = h("input", { type: "text", required: true, maxLength: 500, placeholder: "What should I remind you about?", "aria-label": "Reminder", autocomplete: "off" });
    const setBtn = h("button", { class: "btn primary", type: "submit" }, icon("bell", 16), "Set reminder");
    const tzNote = h("p", { class: "muted small" }, "");
    const quick = h("div", { class: "chip-row" }, ["15m", "1h", "tomorrow 09:00", "daily 08:00"].map((v) => h("button", { type: "button", class: "chip pick", onclick: () => { when.value = v; when.focus(); } }, icon("clock", 12), v)));
    const remForm = h("form", { class: "wb-form", onsubmit: (e: Event) => {
      e.preventDefault();
      busy(setBtn, async () => { await post("/api/reminders", { when: when.value, text: what.value }); when.value = ""; what.value = ""; await loadRem(); }, "Reminder set");
    } },
      h("label", { class: "field" }, "What", what), h("label", { class: "field" }, "When", when), quick,
      h("div", { class: "wb-foot" }, tzNote, setBtn));
    const upcoming = h("div");
    const drawRem = () => {
      const items = [...reminders].sort((a, b) => a.due - b.due);
      if (!items.length) { mount(upcoming, invite("bell", "Nothing coming up", "Set a reminder and it arrives in Telegram and on the Desk when it is due.")); return; }
      const cancel = (x: Reminder) => iconAct("x", "Cancel reminder", (e) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/reminders/${x.id}`); await loadRem(); }), "danger");
      const repeat = (x: Reminder) => (x.repeat_kind !== "none" ? h("span", { class: "chip accent" }, icon("refresh", 12), x.repeat_kind) : null);
      const [next, ...later] = items;
      mount(upcoming,
        h("div", { class: "next-up" }, h("div", { class: "nu-when" }, h("span", { class: "nu-count" }, inUntil(next.due)), h("span", { class: "muted small" }, dateTime(next.due))),
          h("div", { class: "nu-what" }, next.body), h("div", { class: "row between" }, repeat(next) ?? h("span", { class: "muted small" }, "Next up"), cancel(next))),
        later.length ? h("ul", { class: "rem-list" }, later.map((x) => h("li", null, h("div", { class: "rem-main" }, h("span", { class: "rem-text" }, x.body), h("span", { class: "row", style: "gap:6px" }, h("span", { class: "chip" }, icon("clock", 12), inUntil(x.due)), h("span", { class: "muted small" }, dateTime(x.due)), repeat(x))), cancel(x)))) : null);
    };
    const loadRem = async () => {
      const r = await get<{ items: Reminder[]; timezone: string }>("/api/reminders");
      reminders = r.items;
      tzNote.textContent = `Times use your timezone (${r.timezone}).`;
      drawRem(); tabs.refreshBadges();
    };
    const remPane = h("div", { class: "stack" }, h("section", { class: "wb", "aria-label": "New reminder" }, h("h2", null, "New reminder"), remForm),
      h("section", { class: "nb-list" }, h("h3", { class: "coll-title" }, icon("bell", 14), "Coming up"), upcoming));

    // ================================================================== layout
    const tabs = paneTabs([{ id: "notes", label: "Notes" }, { id: "reminders", label: "Reminders", badge: () => reminders.length }], { notes: notesPane, reminders: remPane }, query.get("pane") === "reminders" ? "reminders" : "notes") as HTMLElement & { refreshBadges(): void };
    mount(root, pageHead("notebook", "Notebook", "Private notes and reminders. Also available from Telegram with /note and /remind."), areaNav("notebook"), tabs,
      h("div", { class: "nb-cols" }, notesPane, remPane));
    drawSuggest();
    void loadNotes().catch((e) => toast(e.message, "error"));
    void loadRem().catch((e) => toast(e.message, "error"));
    if (query.get("compose")) queueMicrotask(() => body.focus());

    // countdowns tick without asking the server; the list itself is refreshed once a minute so fired reminders drop off
    const tick = window.setInterval(() => { if (alive) drawRem(); }, 30000);
    const refresh = window.setInterval(() => { if (alive) void loadRem().catch(() => undefined); }, 60000);
    return () => { alive = false; window.clearInterval(tick); window.clearInterval(refresh); };
  },
};
