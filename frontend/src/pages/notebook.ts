import { del, get, patch, post } from "../api.js";
import { busy, h, inUntil, mount, toast } from "../dom.js";
import type { Page } from "./types.js";

interface Note { id: number; body: string; tags: string[] | string; pinned: boolean }
interface Reminder { id: number; body: string; due: number; repeat_kind: string }
const tagList = (n: Note) => (Array.isArray(n.tags) ? n.tags : String(n.tags || "").split(",").filter(Boolean));

export const notebook: Page = {
  id: "notebook",
  title: "Notebook",
  render(root) {
    const notesBox = h("div"), remBox = h("div");
    const loadNotes = async () => {
      const r = await get<{ items: Note[] }>("/api/notes");
      const body = h("textarea", { required: true, maxLength: 5000, placeholder: "Ideas, segment plans, things to remember" });
      const tags = h("input", { type: "text", placeholder: "Tags, comma separated" });
      const add = h("button", { class: "btn primary", type: "submit" }, "Save note");
      mount(notesBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/notes", { body: body.value, tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean) }); await loadNotes(); }); } }, body, h("div", { class: "row" }, h("div", { class: "grow" }, tags), add)),
        r.items.length ? h("ul", { class: "list" }, r.items.map((n) => h("li", null,
          h("div", { style: "white-space:pre-wrap;overflow-wrap:anywhere" }, n.body),
          h("div", { class: "row between" }, h("span", null, tagList(n).map((t) => h("span", { class: "chip" }, t))),
            h("span", { class: "row" }, h("button", { class: "btn small ghost", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await patch(`/api/notes/${n.id}`, { pinned: !n.pinned }); await loadNotes(); }) }, n.pinned ? "Unpin" : "Pin"),
              h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/notes/${n.id}`); await loadNotes(); }) }, "Delete"))))))
          : h("div", { class: "empty" }, "No notes yet."));
    };
    const loadRem = async () => {
      const r = await get<{ items: Reminder[]; timezone: string }>("/api/reminders");
      const when = h("input", { type: "text", required: true, placeholder: "30m, 18:30, tomorrow 09:00, daily 08:00", maxLength: 100 });
      const text = h("input", { type: "text", required: true, maxLength: 500, placeholder: "What to remind you about" });
      const add = h("button", { class: "btn primary", type: "submit" }, "Set reminder");
      mount(remBox, h("form", { class: "body stack", onsubmit: (e: Event) => { e.preventDefault(); busy(add, async () => { await post("/api/reminders", { when: when.value, text: text.value }); when.value = ""; text.value = ""; await loadRem(); }, "Reminder set"); } },
        h("div", { class: "form-grid" }, h("label", { class: "field" }, "When", when), h("label", { class: "field" }, "Reminder", text)),
        h("div", { class: "row" }, add, h("span", { class: "muted small" }, `Times use your timezone (${r.timezone}). Reminders arrive in Telegram and on the Desk.`))),
        r.items.length ? h("ul", { class: "list" }, r.items.map((x) => h("li", { class: "row between" },
          h("span", null, x.body, " ", h("span", { class: "chip" }, inUntil(x.due)), x.repeat_kind !== "none" ? h("span", { class: "chip accent" }, x.repeat_kind) : null),
          h("button", { class: "btn small danger", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await del(`/api/reminders/${x.id}`); await loadRem(); }) }, "Cancel"))))
          : h("div", { class: "empty" }, "No upcoming reminders."));
    };
    mount(root, h("div", { class: "page-head" }, h("h1", null, "Notebook"), h("p", null, "Private notes and reminders. Also available from Telegram with /note and /remind.")),
      h("div", { class: "cols" }, h("section", { class: "block flush" }, h("header", null, h("h2", null, "Notes")), notesBox), h("section", { class: "block flush" }, h("header", null, h("h2", null, "Reminders")), remBox)));
    void loadNotes().catch((e) => toast(e.message, "error"));
    void loadRem().catch((e) => toast(e.message, "error"));
  },
};
