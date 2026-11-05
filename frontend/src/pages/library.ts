/** Moderation library: blocked words and phrases as collections you can search, select, import, export and bulk edit. */
import { get, patch, post } from "../api.js";
import { busy, confirmDialog, downloadCsv, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { empty } from "./shared.js";

export interface Phrase { id: number; phrase: string; is_regex: boolean; weight: number; enabled: boolean; hits: number; category: string }

export const CATEGORIES: { id: string; label: string; hint: string }[] = [
  { id: "blocked_words", label: "Words", hint: "Single offensive or banned words" },
  { id: "blocked_phrases", label: "Phrases", hint: "Longer expressions and sentences" },
  { id: "spam", label: "Spam", hint: "Scam, promotion and follower-selling wording" },
  { id: "links", label: "Links", hint: "Domains and URL patterns" },
  { id: "suspicious", label: "Suspicious", hint: "Wording that deserves a closer look" },
  { id: "custom", label: "Custom", hint: "Your own collection" },
];
const label = (id: string) => CATEGORIES.find((c) => c.id === id)?.label ?? id;
const PAGE = 60;

const categorySelect = (value: string, withAll = false) =>
  h("select", { "aria-label": "Category" }, [withAll ? h("option", { value: "" }, "Keep each entry's category") : null, ...CATEGORIES.map((c) => h("option", { value: c.id, selected: c.id === value }, c.label))]);

export function libraryPanel(onChange: () => void): { el: HTMLElement; load: () => Promise<void> } {
  let items: Phrase[] = [];
  let cat = "all";
  let state = "all";
  let needle = "";
  let shown = PAGE;
  const picked = new Set<number>();

  const el = h("div");
  const chips = h("div", { class: "scroll-x" });
  const bar = h("div", { class: "bulkbar", hidden: true });
  const listBox = h("div");
  const more = h("button", { class: "btn ghost small", type: "button", onclick: () => { shown += PAGE; draw(); } }, "");

  const visible = () => items.filter((p) => (cat === "all" || p.category === cat) && (state === "all" || (state === "on") === p.enabled) && (!needle || p.phrase.toLowerCase().includes(needle)));

  // ----- bulk actions on the selection
  const bulk = async (action: string, category?: string, ok?: string) => {
    const ids = Array.from(picked);
    if (action === "delete" && !(await confirmDialog(`Delete ${ids.length} ${ids.length === 1 ? "entry" : "entries"}?`, "They are removed from the library and the bot stops matching them. This cannot be undone.", "Delete", "danger"))) return;
    try {
      await post("/api/blacklist/bulk", { ids, action, category });
      picked.clear();
      await load();
      onChange();
      toast(ok ?? "Done");
    } catch (e) { toast((e as Error).message, "error"); }
  };
  const drawBar = () => {
    bar.hidden = picked.size === 0;
    if (!picked.size) return;
    const move = categorySelect("custom");
    mount(bar,
      h("strong", null, `${picked.size} selected`),
      h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("enable", undefined, "Enabled") }, "Enable"),
      h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("disable", undefined, "Disabled") }, "Disable"),
      h("span", { class: "row nowrap", style: "gap:6px" }, h("div", { style: "min-width:120px" }, move), h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("move", move.value, "Moved") }, "Move")),
      h("button", { class: "btn small danger", type: "button", onclick: () => void bulk("delete") }, icon("trash", 14), "Delete"),
      h("button", { class: "btn small ghost", type: "button", onclick: () => { picked.clear(); draw(); } }, "Clear"));
  };

  // ----- list
  const row = (p: Phrase) => {
    const box = h("input", { type: "checkbox", checked: picked.has(p.id), "aria-label": `Select ${p.phrase}`, onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? picked.add(p.id) : picked.delete(p.id); drawBar(); } });
    const sw = h("input", { type: "checkbox", class: "switch", checked: p.enabled, "aria-label": `Enable ${p.phrase}`, onchange: (e: Event) => {
      const on = (e.target as HTMLInputElement).checked;
      void patch(`/api/blacklist/${p.id}`, { enabled: on }).then(() => { p.enabled = on; onChange(); draw(); }).catch((x) => { (e.target as HTMLInputElement).checked = !on; toast(x.message, "error"); });
    } });
    return h("li", { class: `lib-row${p.enabled ? "" : " off"}` }, box,
      h("button", { class: "lib-main", type: "button", onclick: () => editor(p), "aria-label": `Edit ${p.phrase}` },
        h("span", { class: "mono lib-phrase" }, p.phrase),
        h("span", { class: "lib-meta" }, cat === "all" ? h("span", { class: "chip" }, label(p.category)) : null, p.is_regex ? h("span", { class: "chip" }, "regex") : null, p.weight ? h("span", { class: "chip" }, `+${p.weight}`) : null, p.hits ? h("span", { class: "chip" }, `${p.hits} hit${p.hits === 1 ? "" : "s"}`) : null)),
      sw);
  };
  const drawChips = () => mount(chips, h("div", { class: "seg-control", role: "group", "aria-label": "Collection" },
    [{ id: "all", label: "All" }, ...CATEGORIES].map((c) => {
      const n = c.id === "all" ? items.length : items.filter((p) => p.category === c.id).length;
      return h("button", { type: "button", "aria-pressed": String(cat === c.id), onclick: () => { cat = c.id; shown = PAGE; draw(); } }, c.label, h("span", { class: "n alt" }, String(n)));
    })));
  const draw = () => {
    drawChips();
    const rows = visible();
    const allBox = h("input", { type: "checkbox", "aria-label": "Select all shown", checked: rows.length > 0 && rows.every((p) => picked.has(p.id)), onchange: (e: Event) => { rows.forEach((p) => ((e.target as HTMLInputElement).checked ? picked.add(p.id) : picked.delete(p.id))); draw(); } });
    mount(listBox, rows.length
      ? h("div", null, h("div", { class: "lib-head" }, allBox, h("span", { class: "muted small" }, `${rows.length} ${rows.length === 1 ? "entry" : "entries"}${cat !== "all" ? ` in ${label(cat)}` : ""}`)), h("ul", { class: "list lib-list" }, rows.slice(0, shown).map(row)))
      : items.length ? empty("search", "Nothing matches these filters.")
        : h("div", { class: "empty" }, icon("layers", 28), h("span", null, "The library is empty. Add one entry, or import a whole list at once."), h("button", { class: "btn primary small", type: "button", onclick: () => importer() }, icon("upload", 15), "Import a list")));
    const rest = rows.length - shown;
    more.hidden = rest <= 0;
    more.textContent = `Show ${Math.min(rest, PAGE)} more (${rest} left)`;
    drawBar();
  };

  // ----- single entry editor (add and edit)
  const editor = (p?: Phrase) => {
    const phrase = h("input", { type: "text", value: p?.phrase ?? "", required: true, maxLength: 200, placeholder: "Word, phrase or regex" });
    const regex = h("input", { type: "checkbox", checked: p?.is_regex ?? false });
    const weight = h("input", { type: "number", min: 0, max: 100, value: String(p?.weight ?? 0) });
    const catSel = categorySelect(p?.category ?? (cat !== "all" ? cat : "blocked_phrases"));
    const on = h("input", { type: "checkbox", class: "switch", checked: p?.enabled ?? true, "aria-label": "Enabled" });
    const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), p ? "Save changes" : "Add entry");
    const holder: { close: () => void } = { close: () => undefined };
    const form = h("form", { class: "stack tight", onsubmit: (e: Event) => {
      e.preventDefault();
      const body = { phrase: phrase.value, is_regex: regex.checked, weight: Number(weight.value), category: catSel.value, enabled: on.checked };
      busy(save, async () => { p ? await patch(`/api/blacklist/${p.id}`, body) : await post("/api/blacklist", body); await load(); onChange(); holder.close(); }, "Saved");
    } },
      h("label", { class: "field" }, "Phrase", phrase),
      h("div", { class: "form-grid" }, h("label", { class: "field" }, "Collection", catSel), h("label", { class: "field" }, "Score added (0 = default)", weight)),
      h("div", { class: "row between" }, h("label", { class: "check" }, regex, "Regular expression"), h("label", { class: "check" }, on, "Enabled")),
      h("p", { class: "muted small" }, "Matching ignores spacing, symbols and look-alike letters, so one entry also catches disguised versions."),
      h("div", { class: "row", style: "justify-content:flex-end" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save));
    holder.close = sheet(p ? "Edit entry" : "Add entry", form).close;
  };

  // ----- bulk import with a preview before anything is written
  const importer = () => {
    const text = h("textarea", { placeholder: "One entry per line.\nAdd a score after a bar to set it: free robux | 80", rows: 7, "aria-label": "Entries to import" });
    const catSel = categorySelect(cat !== "all" ? cat : "blocked_phrases");
    const regex = h("input", { type: "checkbox" });
    const on = h("input", { type: "checkbox", class: "switch", checked: true, "aria-label": "Start enabled" });
    const file = h("input", { type: "file", accept: ".txt,.csv,text/plain,text/csv", "aria-label": "Choose a file" });
    const result = h("div", { class: "stack tight", "aria-live": "polite" });
    const go = h("button", { class: "btn primary", type: "button", disabled: true }, icon("upload", 16), "Import");
    const check = h("button", { class: "btn ghost", type: "button" }, icon("search", 16), "Check list");
    const holder: { close: () => void } = { close: () => undefined };
    file.addEventListener("change", async () => { const f = file.files?.[0]; if (f) { text.value = (await f.text()).slice(0, 400_000); go.disabled = true; mount(result); } });
    text.addEventListener("input", () => { go.disabled = true; });
    const parse = () => text.value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).slice(0, 5000).map((line) => {
      const [phrase, w] = line.split("|").map((x) => x.trim());
      return { phrase, weight: /^\d+$/.test(w ?? "") ? Number(w) : 0, is_regex: regex.checked, category: catSel.value };
    });
    const request = (dry: boolean) => post<any>("/api/blacklist/import", { items: parse(), enabled: on.checked, dry_run: dry });
    check.onclick = () => busy(check, async () => {
      if (!text.value.trim()) throw new Error("Paste a list or choose a file first.");
      const r = await request(true);
      go.disabled = r.new === 0;
      go.lastChild!.textContent = r.new ? `Import ${r.new} new` : "Nothing to import";
      mount(result,
        h("div", { class: "row" }, h("span", { class: "chip ok" }, `${r.new} new`), h("span", { class: "chip" }, `${r.duplicates} already in the library or repeated`), r.invalid.length ? h("span", { class: "chip bad" }, `${r.invalid.length} invalid`) : null),
        r.sample.length ? h("div", { class: "muted small" }, "First entries: ", r.sample.slice(0, 6).map((s: any) => s.phrase).join(", "), r.new > 6 ? "…" : "") : null,
        r.invalid.length ? h("ul", { class: "reasons" }, r.invalid.slice(0, 5).map((i: any) => h("li", null, `"${i.phrase}": ${i.reason}`))) : null);
    });
    go.onclick = () => busy(go, async () => { const r = await request(false); await load(); onChange(); holder.close(); toast(`Added ${r.added}. Skipped ${r.duplicates} duplicates${r.invalid.length ? ` and ${r.invalid.length} invalid` : ""}.`); });
    holder.close = sheet("Import entries", h("div", { class: "stack tight" },
      h("label", { class: "field" }, "Paste a list", text), h("label", { class: "field" }, "Or choose a .txt or .csv file", file),
      h("div", { class: "form-grid" }, h("label", { class: "field" }, "Collection", catSel)),
      h("div", { class: "row between" }, h("label", { class: "check" }, regex, "Entries are regular expressions"), h("label", { class: "check" }, on, "Start enabled")),
      h("p", { class: "muted small" }, "Check the list first. Duplicates, empty lines and broken patterns are skipped, and nothing is saved until you press Import."),
      result, h("div", { class: "row", style: "justify-content:flex-end" }, check, go))).close;
  };

  const exportCsv = () => downloadCsv("savahbot-library.csv", [["phrase", "regex", "weight", "collection", "enabled", "hits"], ...visible().map((p) => [p.phrase, p.is_regex ? "yes" : "no", p.weight, p.category, p.enabled ? "yes" : "no", p.hits])]);

  const search = h("input", { type: "search", placeholder: "Search the library", "aria-label": "Search the library" });
  search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); shown = PAGE; draw(); });
  const stateSel = h("select", { "aria-label": "Show", onchange: (e: Event) => { state = (e.target as HTMLSelectElement).value; shown = PAGE; draw(); } }, h("option", { value: "all" }, "All"), h("option", { value: "on" }, "Enabled"), h("option", { value: "off" }, "Disabled"));

  mount(el,
    h("div", { class: "toolbar" },
      h("div", { class: "input-icon" }, icon("search", 16), search), h("div", { style: "width:120px" }, stateSel),
      h("span", { class: "row", style: "gap:6px" },
        h("button", { class: "btn small primary", type: "button", onclick: () => editor() }, icon("plus", 15), "Add"),
        h("button", { class: "btn small ghost", type: "button", onclick: () => importer() }, icon("upload", 15), "Import"),
        h("button", { class: "btn small ghost", type: "button", onclick: exportCsv }, icon("download", 15), "Export"))),
    h("div", { class: "body tight-y" }, chips), bar, listBox, h("div", { class: "body", style: "text-align:center" }, more));

  const load = async () => {
    items = (await get<{ items: Phrase[] }>("/api/blacklist")).items.map((p) => ({ ...p, category: p.category ?? "blocked_phrases", hits: p.hits ?? 0 }));
    for (const id of Array.from(picked)) if (!items.some((p) => p.id === id)) picked.delete(id);
    draw();
  };
  return { el, load };
}
