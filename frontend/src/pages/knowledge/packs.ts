import { del, get, post } from "../../api.js";
import { busy, h, mount, toast, toastAction } from "../../dom.js";
import { icon } from "../../icons.js";
import { empty } from "../shared.js";
import { iconAct, invite, plural, seg } from "../widgets.js";
import { hrefFor, n0 } from "./common.js";

interface PackSummary {
  id: string; title: string; description: string; category: string; kind: string; kind_help: string; language: string; version: string; updated: string;
  sources: { title: string; url: string }[]; enabled: boolean; entries: number; yours: number; muted: number; editable: boolean; user_supplied: boolean;
}
interface PackRow { value: string; weight: number; tags: string[]; user: boolean; muted: boolean; note: string }
interface PackList { items: PackSummary[]; categories: Record<string, string>; kinds: Record<string, string>; problems: string[] }

const KIND_NAME: Record<string, string> = { phrases: "Phrases", templates: "Scam shapes", linkrisk: "Link risk", confusables: "Disguise map", identity: "Name words", corpus: "Training set" };
const CAT_ICON: Record<string, string> = { spam: "inbox", scams: "alert", links: "external", evasion: "eyeOff", identity: "user", learning: "sparkle", custom: "edit" };
const STRENGTHS = [{ id: "25", label: "Light" }, { id: "50", label: "Medium" }, { id: "75", label: "Strong" }];

export function renderPacks(root: HTMLElement, query: URLSearchParams): void {
  const open = query.get("pack");
  if (open) renderDetail(root, open); else renderList(root);
}

// ====================================================================================================== list
function renderList(root: HTMLElement): void {
  let data: PackList | null = null;
  let cat = "all";
  let needle = "";
  const grid = h("div", { class: "pack-grid" });
  const chips = h("div", { class: "scroll-x" });
  const find = h("input", { type: "search", placeholder: "Search packs", "aria-label": "Search packs", autocomplete: "off" });
  find.addEventListener("input", () => { needle = find.value.trim().toLowerCase(); draw(); });

  const draw = () => {
    if (!data) return;
    const d = data;
    const cats = ["all", ...Object.keys(d.categories).filter((c) => d.items.some((p) => p.category === c))];
    mount(chips, h("div", { class: "chip-row nowrap" }, cats.map((c) => h("button", { type: "button", class: `chip pick${cat === c ? " on" : ""}`, "aria-pressed": String(cat === c), onclick: () => { cat = c; draw(); } },
      c === "all" ? "All" : d.categories[c], h("span", { class: "muted" }, ` ${d.items.filter((p) => c === "all" || p.category === c).length}`)))));
    const shown = d.items.filter((p) => (cat === "all" || p.category === cat) && (!needle || `${p.title} ${p.description} ${p.language}`.toLowerCase().includes(needle)));
    mount(grid, shown.length ? shown.map((p) => packCard(p, d)) : empty("search", "No packs match."));
  };
  const packCard = (p: PackSummary, d: PackList): HTMLElement => {
    const sw = h("input", { type: "checkbox", class: "switch", checked: p.enabled, "aria-label": `${p.title} on or off` });
    sw.addEventListener("change", () => {
      const on = sw.checked;
      post(`/api/intel/packs/${p.id}/enable`, { enabled: on }).then(() => { p.enabled = on; toast(`${p.title}: ${on ? "on" : "off"}`); draw(); }).catch((e: Error) => { sw.checked = !on; toast(e.message, "error"); });
    });
    return h("article", { class: `pack-card${p.enabled ? "" : " is-off"}` },
      h("div", { class: "pk-top" }, h("span", { class: "scn-ico" }, icon(CAT_ICON[p.category] ?? "package", 22)),
        h("div", { class: "scn-title" }, h("strong", null, p.title), h("span", { class: "muted small" }, `${d.categories[p.category] ?? p.category} · ${KIND_NAME[p.kind] ?? p.kind}`)), sw),
      h("p", { class: "scn-what" }, p.description),
      h("div", { class: "chip-row tight" }, h("span", { class: "chip" }, plural(p.entries, "entry", "entries")), p.language ? h("span", { class: "chip" }, p.language) : null,
        p.yours ? h("span", { class: "chip accent" }, `${p.yours} yours`) : null, p.muted ? h("span", { class: "chip" }, `${p.muted} muted`) : null, p.user_supplied ? h("span", { class: "chip warn" }, "Yours to fill") : null),
      h("div", { class: "pk-foot" }, h("span", { class: "muted small" }, p.version ? `v${p.version}` : "", p.updated ? ` · ${p.updated}` : ""), h("a", { class: "btn small ghost", href: hrefFor("packs", { pack: p.id }) }, p.editable ? "Browse and edit" : "Browse", icon("chevronRight", 15))));
  };
  mount(root, h("div", { class: "stack" },
    h("p", { class: "lede" }, "Knowledge is split by category, one file per pack, so each can be switched on or off on its own. Packs that hold phrases let you add your own entries or mute ones you do not want."),
    h("div", { class: "toolbar-solo" }, h("div", { class: "input-icon grow" }, icon("search", 16), find)), chips, grid));
  void get<PackList>("/api/intel/packs").then((r) => { data = r; draw(); }).catch((e) => toast(e.message, "error"));
}

// ====================================================================================================== one pack
function renderDetail(root: HTMLElement, id: string): void {
  let pack: PackSummary | null = null;
  let rows: PackRow[] = [];
  let total = 0;
  let filter: "all" | "yours" | "muted" = "all";
  let needle = "";
  let limit = 60;
  const head = h("div");
  const listBox = h("div");
  const more = h("div", { class: "row center" });
  const find = h("input", { type: "search", placeholder: "Search this pack", "aria-label": "Search this pack", autocomplete: "off" });
  let timer = 0;
  find.addEventListener("input", () => { window.clearTimeout(timer); timer = window.setTimeout(() => { needle = find.value.trim(); limit = 60; void loadRows(); }, 250); });
  const filterSeg = seg("Show", [{ id: "all" as const, label: "All" }, { id: "yours" as const, label: "Yours" }, { id: "muted" as const, label: "Muted" }], filter, (v) => { filter = v; limit = 60; void loadRows(); });

  const entryUrl = (value: string) => `/api/intel/packs/${id}/entries?value=${encodeURIComponent(value)}`;
  const reload = async () => { await Promise.all([loadPack(), loadRows()]); };

  const addValue = h("input", { type: "text", maxLength: 200, placeholder: "Add your own phrase", "aria-label": "New entry", autocomplete: "off" }) as HTMLInputElement;
  let strength = "50";
  const strengthSeg = seg("How strong", STRENGTHS, strength, (v) => { strength = v; });
  const addBtn = h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add");
  const addForm = h("form", { class: "mt-add", onsubmit: (e: Event) => {
    e.preventDefault();
    const value = addValue.value.trim();
    if (value.length < 2) { toast("Type at least two characters.", "error"); return; }
    busy(addBtn, async () => { await post(`/api/intel/packs/${id}/entries`, { value, weight: Number(strength) }); addValue.value = ""; await reload(); }, "Added");
  } }, h("div", { class: "mt-add-row" }, h("div", { class: "grow" }, addValue), addBtn),
    h("div", { class: "mt-opt" }, h("span", { class: "mt-opt-label" }, "How strongly it counts"), strengthSeg.el));

  const drawRows = () => {
    if (!pack) return;
    const p = pack;
    if (!rows.length) { mount(listBox, filter === "all" && !needle ? invite("package", "This pack is empty", p.user_supplied ? "Add the words and phrases you want blocked in your community. Nothing is shipped here." : "Nothing in this pack.") : empty("search", "Nothing matches.")); mount(more, null); return; }
    mount(listBox, h("ul", { class: "pk-rows" }, rows.map((r) => h("li", { class: r.muted ? "muted-row" : "" },
      h("div", { class: "pr-main" }, h("code", { class: "ph-text" }, r.value),
        h("div", { class: "chip-row tight" }, r.weight ? h("span", { class: "chip" }, `strength ${r.weight}`) : null, r.tags.filter((t) => t !== "yours").slice(0, 3).map((t) => h("span", { class: "chip" }, t)), r.user ? h("span", { class: "chip accent" }, "yours") : null, r.muted ? h("span", { class: "chip" }, icon("eyeOff", 12), "muted") : null),
        r.note ? h("span", { class: "muted small wrap" }, r.note) : null),
      p.editable ? h("div", { class: "acts" },
        iconAct(r.muted ? "eye" : "eyeOff", r.muted ? "Use this entry again" : "Mute this entry", (e) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/intel/packs/${id}/mute`, { value: r.value, muted: !r.muted }); await reload(); })),
        r.user ? iconAct("trash", "Remove your entry", (e) => busy(e.currentTarget as HTMLButtonElement, async () => {
          await del(entryUrl(r.value)); await reload();
          toastAction("Entry removed", "Undo", async () => { await post(`/api/intel/packs/${id}/entries`, { value: r.value, weight: r.weight }); await reload(); });
        }), "danger") : null) : null))));
    mount(more, total > rows.length ? h("button", { class: "btn ghost", type: "button", onclick: () => { limit += 60; void loadRows(); } }, `Show more (${n0(total - rows.length)} left)`) : h("span", { class: "muted small" }, `${plural(total, "entry", "entries")}`));
  };
  const drawHead = () => {
    if (!pack) return;
    const p = pack;
    const sw = h("input", { type: "checkbox", class: "switch", checked: p.enabled, "aria-label": `${p.title} on or off`, onchange: (e: Event) => {
      const on = (e.target as HTMLInputElement).checked;
      post(`/api/intel/packs/${id}/enable`, { enabled: on }).then(() => { toast(on ? "Pack on" : "Pack off"); void loadPack(); }).catch((x: Error) => toast(x.message, "error"));
    } });
    mount(head, h("section", { class: "wb" },
      h("a", { class: "link-quiet", href: hrefFor("packs") }, icon("chevronRight", 14, "flip"), "All packs"),
      h("div", { class: "mind-top" }, h("div", null, h("h2", null, p.title), h("p", { class: "lede" }, p.description)), h("label", { class: "ambient compact" }, h("span", { class: "muted small" }, p.enabled ? "On" : "Off"), sw)),
      h("div", { class: "chip-row" }, h("span", { class: "chip" }, KIND_NAME[p.kind] ?? p.kind), h("span", { class: "chip" }, plural(p.entries, "entry", "entries")), p.language ? h("span", { class: "chip" }, p.language) : null, p.version ? h("span", { class: "chip" }, `v${p.version}`) : null, p.updated ? h("span", { class: "chip" }, `updated ${p.updated}`) : null),
      h("p", { class: "muted small" }, icon("info", 13), " ", p.kind_help),
      p.sources.length ? h("details", { class: "sources" }, h("summary", null, `Where this came from (${p.sources.length})`),
        h("ul", null, p.sources.map((s) => h("li", null, h("a", { href: s.url, target: "_blank", rel: "noopener noreferrer" }, s.title || s.url))))) : null,
      p.editable ? addForm : h("p", { class: "muted small" }, "This pack is read-only. Switch it off if you do not want it, or add your own phrases in a phrase pack.")));
  };
  const loadPack = async () => {
    const all = await get<PackList>("/api/intel/packs");
    pack = all.items.find((x) => x.id === id) ?? null;
    if (!pack) { mount(root, empty("alert", "That pack no longer exists.")); return; }
    drawHead(); drawRows();
  };
  const loadRows = async () => {
    const q = new URLSearchParams({ limit: String(limit), filter });
    if (needle) q.set("q", needle);
    const r = await get<{ items: PackRow[]; total: number }>(`/api/intel/packs/${id}/entries?${q.toString()}`);
    rows = r.items; total = r.total; drawRows();
  };
  mount(root, h("div", { class: "stack" }, head,
    h("section", { class: "nb-list" }, h("div", { class: "nb-tools" }, h("div", { class: "input-icon grow" }, icon("search", 16), find)), filterSeg.el, listBox, more)));
  void reload().catch((e) => toast(e.message, "error"));
}
