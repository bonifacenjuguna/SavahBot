import { get } from "../api.js";
import { busy, dateTime, h, mount, toast } from "../dom.js";
import { icon, statusIcon } from "../icons.js";
import { empty, pageHead } from "./shared.js";
import type { Page } from "./types.js";

interface Item { id: number; ts: number; area: string; importance: "sensitive" | "notable" | "routine"; action: string; summary: string; before_v: string; after_v: string; actor: string }
interface Res { items: Item[]; more: boolean; areas: Record<string, string> }

const TONE: Record<Item["importance"], [string, string]> = { sensitive: ["bad", "Sensitive"], notable: ["warn", "Notable"], routine: ["ok", "Routine"] };
const RANGES: [string, number][] = [["Any time", 0], ["Last 24 hours", 86400], ["Last 7 days", 7 * 86400], ["Last 30 days", 30 * 86400]];

function entry(i: Item): HTMLElement {
  const [tone, label] = TONE[i.importance];
  const change = i.before_v || i.after_v ? h("div", { class: "muted small wrap" }, i.before_v ? `Before: ${i.before_v}` : "", i.before_v && i.after_v ? "  →  " : "", i.after_v ? `After: ${i.after_v}` : "") : null;
  return h("div", { style: "display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--line)" }, statusIcon(tone === "bad" ? "bad" : tone === "warn" ? "warn" : "ok", 18),
    h("div", { style: "min-width:0" }, h("div", { class: "wrap" }, h("strong", null, i.summary)), change, h("div", { class: "muted small" }, `${label} · ${dateTime(i.ts)}${i.actor ? ` · ${i.actor}` : ""}`)));
}

export const activity: Page = {
  id: "activity", title: "Activity log", icon: "checklist", blurb: "What changed, by area and importance",
  render(root) {
    let items: Item[] = [], more = false, areas: Record<string, string> = {};
    const f = { area: "", importance: "", q: "", range: 0 };
    const list = h("div", null);
    const area = h("select", { "aria-label": "Area" }) as HTMLSelectElement;
    const imp = h("select", { "aria-label": "Importance" }, h("option", { value: "" }, "All importance"), ...(["sensitive", "notable", "routine"] as const).map((k) => h("option", { value: k }, TONE[k][1]))) as HTMLSelectElement;
    const rng = h("select", { "aria-label": "Dates" }, ...RANGES.map(([l, v]) => h("option", { value: String(v) }, l))) as HTMLSelectElement;
    const search = h("input", { type: "search", placeholder: "Search the log", "aria-label": "Search the log" }) as HTMLInputElement;
    const qs = (before = 0) => {
      const p = new URLSearchParams({ limit: "30" });
      if (f.area) p.set("area", f.area); if (f.importance) p.set("importance", f.importance); if (f.q) p.set("q", f.q);
      if (f.range) p.set("since", String(Date.now() / 1000 - f.range)); if (before) p.set("before", String(before));
      return p;
    };
    const draw = () => {
      const btn = h("button", { class: "btn ghost", type: "button" }, "Show more");
      btn.onclick = () => void busy(btn, async () => {
        const r = await get<Res>(`/api/activity?${qs(items[items.length - 1].id)}`);
        items = items.concat(r.items); more = r.more; draw();
      });
      mount(list, items.length ? h("div", null, ...items.map(entry)) : empty("checklist", "Nothing logged for this filter."), more ? h("div", { style: "text-align:center;padding:12px" }, btn) : null);
    };
    const load = async () => {
      try {
        const r = await get<Res>(`/api/activity?${qs()}`);
        items = r.items; more = r.more; areas = r.areas;
        if (area.options.length < 2) mount(area, h("option", { value: "" }, "All areas"), ...Object.entries(areas).map(([k, v]) => h("option", { value: k }, v)));
        draw();
      } catch (e) { toast(e instanceof Error ? e.message : "Could not load the log"); }
    };
    area.onchange = () => { f.area = area.value; void load(); };
    imp.onchange = () => { f.importance = imp.value; void load(); };
    rng.onchange = () => { f.range = Number(rng.value); void load(); };
    let t = 0;
    search.oninput = () => { clearTimeout(t); t = window.setTimeout(() => { f.q = search.value.trim(); void load(); }, 300); };
    const exp = h("a", { class: "btn small", href: "#", onclick: (e: Event) => {
      e.preventDefault();
      void fetch(`/api/activity/export?${qs()}`, { credentials: "include" }).then((r) => r.blob()).then((b) => { const a = h("a", { href: URL.createObjectURL(b), download: "savahbot-activity.csv" }) as HTMLAnchorElement; a.click(); }).catch(() => toast("Export failed"));
    } }, icon("download", 15), "Export");
    mount(root, h("div", { class: "page" }, pageHead("checklist", "Activity log", "What changed, newest first. Secrets, tokens, passwords and message text are never recorded. Sensitive entries cannot be deleted here; they leave when the retention period ends.", h("div", { class: "row", style: "gap:8px" }, h("a", { class: "btn small", href: "#/settings" }, "Back to Settings"), exp)),
      h("div", { class: "sp-card" }, h("div", { class: "row wrap", style: "gap:8px" }, search, area, imp, rng), list),
      h("p", { class: "muted small" }, "Retention and the optional notification for sensitive entries are in Settings, Developer & advanced: activity_retention_days and activity_notify_sensitive.")));
    void load();
  },
};
