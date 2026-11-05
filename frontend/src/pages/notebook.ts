import { del, get, patch, post } from "../api.js";
import { busy, dateTime, h, inUntil, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { areaNav, dateRange, type RangeValue } from "./kit.js";
import { card, empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Note { id: number; body: string; tags: string[] | string; pinned: boolean; created: number; updated: number }
interface Reminder { id: number; body: string; due: number; repeat_kind: string }
const copyBtn = (text: string) => h("button", { class: "btn small ghost", type: "button", "aria-label": "Copy note", onclick: () => { void navigator.clipboard?.writeText(text).then(() => toast("Copied")).catch(() => toast("Could not copy", "error")); } }, icon("copy", 15), "Copy");
const tagList = (n: Note) => (Array.isArray(n.tags) ? n.tags : String(n.tags || "").split(",").filter(Boolean));

export const notebook: Page = {
  id: "notebook",
  title: "Notebook",
  icon: "notebook",
  blurb: "Private notes and reminders",
  render(root) {
    const notesBox = h("div"), remBox = h("div");
    let notes: Note[] = [];
    let needle = "";
    let tagFilter = "";
    let range: RangeValue = { label: "", active: false };
    let sort: "new" | "old" = "new";
    let view: "grid" | "list" = (() => { try { return localStorage.getItem("savahbot.noteview") === "list" ? "list" : "grid"; } catch { return "grid"; } })();
    const dates = dateRange({ presets: ["any", "today", "7d", "30d", "custom"], label: "Notes by date written" }, (v) => { range = v; drawGrid(); });

    const noteForm = h("div");
    const noteList = h("div");
    const search = h("input", { type: "search", placeholder: "Search notes", "aria-label": "Search notes" });
    search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); drawGrid(); });
    const tagBox = h("div", { class: "scroll-x" });
    const viewBtn = h("button", { class: "btn small ghost", type: "button", "aria-label": "Switch between grid and list", onclick: () => { view = view === "grid" ? "list" : "grid"; try { localStorage.setItem("savahbot.noteview", view); } catch { /* private mode */ } paintView(); drawGrid(); } });
    const sortBtn = h("button", { class: "btn small ghost", type: "button", "aria-label": "Change order", onclick: () => { sort = sort === "new" ? "old" : "new"; paintView(); drawGrid(); } });
    const paintView = () => { mount(viewBtn, icon(view === "grid" ? "list" : "grid", 15), view === "grid" ? "List" : "Grid"); mount(sortBtn, icon("clock", 15), sort === "new" ? "Newest" : "Oldest"); };
    paintView();
    const toolbar = h("div", { class: "toolbar", hidden: true }, h("div", { class: "input-icon" }, icon("search", 16), search), tagBox, sortBtn, viewBtn, h("div", { class: "toolbar-dates-inline" }, dates.el));
    const grid = h("div");
    const drawGrid = () => {
      const shown = notes
        .filter((n) => (!needle || `${n.body} ${tagList(n).join(" ")}`.toLowerCase().includes(needle)) && (!tagFilter || tagList(n).includes(tagFilter))
          && (range.since === undefined || n.created >= range.since) && (range.until === undefined || n.created < range.until))
        .sort((a, b) => Number(b.pinned) - Number(a.pinned) || (sort === "new" ? b.created - a.created : a.created - b.created));
      mount(grid, shown.length ? h("div", { class: `notes-grid${view === "list" ? " as-list" : ""}` }, shown.map((n) => h("article", { class: `note-card${n.pinned ? " pinned" : ""}` },
        h("div", { class: "body-text" }, n.body),
        h("div", { class: "muted small" }, dateTime(n.created)),
        h("div", { class: "row between" }, h("span", { class: "row", style: "gap:6px" }, n.pinned ? icon("pin", 14) : null, tagList(n).map((t) => h("span", { class: "chip" }, t))),
          h("span", { class: "row", style: "gap:6px" },
            copyBtn(n.body),
            h("button", { class: "btn small ghost", "aria-label": n.pinned ? "Unpin note" : "Pin note", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await patch(`/api/notes/${n.id}`, { pinned: !n.pinned }); await loadNotes(); }) }, icon("pin", 15), n.pinned ? "Unpin" : "Pin"),
            h("button", { class: "btn small danger", "aria-label": "Delete note", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/notes/${n.id}`); await loadNotes(); }) }, icon("trash", 15), "Delete"))))))
        : empty("notebook", notes.length ? "No notes match." : "No notes yet."));
    };
    const drawNotes = () => {
      const tags = Array.from(new Set(notes.flatMap(tagList)));
      if (tagFilter && !tags.includes(tagFilter)) tagFilter = "";
      toolbar.hidden = notes.length <= 1;
      mount(tagBox, tags.length ? h("div", { class: "seg-control", role: "group", "aria-label": "Tag" },
        [["", "All"], ...tags.slice(0, 8).map((t) => [t, t])].map(([v, l]) => h("button", { type: "button", "aria-pressed": String(tagFilter === v), onclick: () => { tagFilter = v; drawNotes(); } }, l))) : null);
      drawGrid();
    };
    mount(noteList, toolbar, grid);
    const loadNotes = async () => {
      notes = (await get<{ items: Note[] }>("/api/notes")).items;
      drawNotes();
    };
    {
      const body = h("textarea", { required: true, maxLength: 5000, placeholder: "Ideas, segment plans, things to remember", "aria-label": "Note" });
      const tags = h("input", { type: "text", placeholder: "Tags, comma separated", "aria-label": "Tags" });
      const add = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Save note");
      mount(noteForm, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/notes", { body: body.value, tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean) }); body.value = ""; tags.value = ""; await loadNotes(); }); } },
        body, h("div", { class: "row" }, h("div", { class: "grow" }, tags), add)));
    }
    mount(notesBox, noteForm, noteList);

    const loadRem = async () => {
      const r = await get<{ items: Reminder[]; timezone: string }>("/api/reminders");
      const when = h("input", { type: "text", required: true, placeholder: "30m, 18:30, tomorrow 09:00, daily 08:00", maxLength: 100 });
      const text = h("input", { type: "text", required: true, maxLength: 500, placeholder: "What to remind you about" });
      const add = h("button", { class: "btn primary", type: "submit" }, icon("bell", 16), "Set reminder");
      const quick = (v: string) => h("button", { class: "chip", type: "button", style: "cursor:pointer", onclick: () => { when.value = v; when.focus(); } }, v);
      mount(remBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/reminders", { when: when.value, text: text.value }); when.value = ""; text.value = ""; await loadRem(); }, "Reminder set"); } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "When", when), h("label", { class: "field" }, "Reminder", text)),
        h("div", { class: "row", style: "gap:6px" }, h("span", { class: "muted small" }, "Quick:"), ["15m", "1h", "tomorrow 09:00", "daily 08:00"].map(quick)),
        h("div", { class: "row" }, add, h("span", { class: "muted small" }, `Times use your timezone (${r.timezone}). Reminders arrive in Telegram and on the Desk.`))),
        r.items.length ? h("ul", { class: "list" }, r.items.map((x) => h("li", { class: "row between nowrap" },
          h("span", { class: "grow" }, x.body, " ", h("span", { class: "chip" }, icon("clock", 12), inUntil(x.due)), x.repeat_kind !== "none" ? h("span", { class: "chip accent" }, icon("refresh", 12), x.repeat_kind) : null),
          h("button", { class: "btn small danger", "aria-label": "Cancel reminder", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/reminders/${x.id}`); await loadRem(); }) }, icon("x", 15), "Cancel"))))
          : empty("bell", "No upcoming reminders."));
    };
    mount(root, pageHead("notebook", "Notebook", "Private notes and reminders. Also available from Telegram with /note and /remind."), areaNav("notebook"),
      h("div", { class: "cols even" }, card("notebook", "Notes", notesBox, { flush: true }), card("bell", "Reminders", remBox, { flush: true })));
    void loadNotes().catch((e) => toast(e.message, "error"));
    void loadRem().catch((e) => toast(e.message, "error"));
  },
};
