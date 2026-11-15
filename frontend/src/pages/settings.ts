import { del, get, patch } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus } from "../state.js";
import { areaNav } from "./kit.js";
import { renderKnowledge } from "./knowledge.js";
import { card, empty, pageHead } from "./shared.js";
import { settingsTabs } from "./settings-tabs.js";
import { renderAttention, settingsSearch } from "./settings-overview.js";
import { renderAppearance, renderDeveloper, renderDevice, renderPrivacy, renderShortcuts } from "./settings-panels.js";
import type { Page } from "./types.js";
import { hasKeyboard } from "../ui.js";

interface Setting {
  name: string; env: string; group: string; description: string; type: string; default: unknown; value: unknown;
  is_set: boolean; secret: boolean; source: string; editable: boolean; options: string[] | null; reserved: boolean;
}

/** Developer: every environment option, searchable, editable, with reset to default. (Until 1.4.4 this was its own "All settings" tab.) */
function renderEnvSettings(host: HTMLElement, query: URLSearchParams): void {
    const box = h("div", { class: "block flush" });
    const search = h("input", { type: "search", placeholder: "Search settings", "aria-label": "Search settings" });
    const changedOnly = h("input", { type: "checkbox", class: "switch", "aria-label": "Only settings changed from the default" });
    const summary = h("span", { class: "muted small" }, "");
    let items: Setting[] = [];
    const openGroups = new Set<string>();

    const control = (s: Setting): HTMLElement => {
      const save = async (value: string | number | boolean) => {
        try { await patch("/api/settings", { values: { [s.name]: value } }); toast("Saved"); void refreshStatus(); }
        catch (e) { toast((e as Error).message, "error"); }
      };
      if (!s.editable) return h("span", { class: "muted small" }, s.secret ? (s.is_set ? "Set in environment" : "Not set") : `Set with ${s.env} in Railway`, s.secret ? null : h("div", { class: "mono" }, String(s.value ?? "")));
      if (s.secret) { const i = h("input", { type: "password", placeholder: s.is_set ? "Set (type to replace)" : "Not set", autocomplete: "off", "aria-label": s.env }); i.onchange = () => { if (i.value) void save(i.value); }; return i; }
      if (s.type === "bool") return h("input", { type: "checkbox", class: "switch", checked: Boolean(s.value), "aria-label": s.name, onchange: (e: Event) => void save((e.target as HTMLInputElement).checked) });
      if (s.options) { const sel = h("select", { "aria-label": s.env }, s.options.map((o) => h("option", { value: o, selected: s.value === o }, o))); sel.onchange = () => void save(sel.value); return sel; }
      const num = s.type === "int" || s.type === "float";
      const i = h("input", { type: num ? "number" : "text", value: String(s.value ?? ""), step: s.type === "float" ? "any" : undefined, "aria-label": s.env });
      i.onchange = () => void save(num ? Number(i.value) : i.value);
      return i;
    };

    const draw = () => {
      const q = search.value.trim().toLowerCase();
      const shown = items.filter((s) => (!q || s.name.includes(q) || s.env.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)) && (!changedOnly.checked || s.source === "dashboard"));
      summary.textContent = `${shown.length} of ${items.length} settings${items.some((s) => s.source === "dashboard") ? `, ${items.filter((s) => s.source === "dashboard").length} changed here` : ""}`;
      const groups = new Map<string, Setting[]>();
      shown.forEach((s) => groups.set(s.group, [...(groups.get(s.group) ?? []), s]));
      mount(box, [...groups].map(([g, list]) => h("details", { class: "group", open: Boolean(q) || changedOnly.checked || openGroups.has(g), ontoggle: (e: Event) => { const d = e.target as HTMLDetailsElement; if (d.open) openGroups.add(g); else openGroups.delete(g); } },
        h("summary", null, h("span", { class: "row nowrap", style: "gap:8px" }, icon("chevronRight", 16), g), h("span", { class: "chip" }, `${list.length}`)),
        list.map((s) => h("div", { class: "setting" },
          h("div", null, h("div", { class: "mono" }, s.env), h("div", { class: "muted small" }, s.description),
            s.source === "dashboard" ? h("button", { class: "btn small ghost", style: "margin-top:6px", onclick: async () => { await del(`/api/settings/${s.name}`); await load(); } }, icon("refresh", 14), "Reset to default") : null),
          h("div", null, control(s), h("div", { class: "muted small" }, s.reserved ? "Reserved for a future feature" : `Source: ${s.source}`)))))),
        shown.length ? null : empty("search", "No settings match."));
    };
    const load = async () => { items = (await get<{ items: Setting[] }>("/api/settings")).items; draw(); };
    search.oninput = draw;
    changedOnly.onchange = draw;
    search.value = query.get("q") ?? "";
    mount(host, card("sliders", "All environment settings", h("div", { class: "k-stack" },
      h("p", { class: "muted small" }, "Changes made here apply immediately and override the environment until you reset them. Secrets are never shown."),
      h("div", { class: "row between", style: "margin-bottom:6px" },
        h("div", { class: "input-icon", style: "flex:1 1 280px;max-width:420px" }, icon("search", 16), search),
        h("label", { class: "check small" }, changedOnly, "Changed from default only"), summary),
      box), { id: "env-settings" }));
    if (query.get("q")) host.querySelector("#env-settings")?.scrollIntoView({ block: "start" });
    void load().catch((e) => toast(e.message, "error"));
}

export const settings: Page = {
  id: "settings",
  title: "Settings",
  icon: "sliders",
  blurb: "Every option, searchable",
  render(root, query) {
    // 1.2.0: Settings is a hub. The address says which view is open (?tab=), so links, search results and the back button all work.
    const INLINE = ["appearance", "privacy", "device", "shortcuts", "knowledge", "developer"] as const;
    type Tab = (typeof INLINE)[number];
    // 1.4.3: this view is called Intelligence (its first section is still Knowledge). ?tab=knowledge keeps working, and so does ?tab=intelligence.
    const asked = query.get("tab") === "intelligence" ? "knowledge" : query.get("tab") === "all" ? "developer" : query.get("tab");   // 1.4.4: ?tab=all (All settings) now lives inside Developer
    const tab = (INLINE.find((t) => t === asked && (t !== "shortcuts" || hasKeyboard())) ?? "appearance") as Tab;
    // 1.4.7: Chat reader, Stream alerts, Activity log, Variables and Setup sit in this same strip; they open as their own pages under the same strip.
    const views = settingsTabs(tab);
    const host = h("div", { class: "k-stack" });
    const shell = (title: string, blurb: string) => mount(root, pageHead("sliders", title, blurb), areaNav("settings"), settingsSearch(host), h("div", { class: "tab-row" }, views.el), host);
    const fail = (e: unknown) => mount(host, empty("alert", e instanceof Error ? e.message : "This section could not load."));
    if (tab === "knowledge") {
      shell("Intelligence", "How the bot spots spam, scams and abuse: what it knows (packs of patterns), the detectors that read them, what it learns from you, and live threat lists.");
      return renderKnowledge(host, query);
    }
    if (tab === "appearance") { shell("Appearance", "How the dashboard looks on this device."); renderAppearance(host); return undefined; }
    if (tab === "privacy") { shell("Privacy & data", "What is stored, for how long, and what you can clear."); void renderPrivacy(host).catch(fail); return undefined; }
    if (tab === "device") { shell("Device & app", "Install, offline use and this browser."); void renderDevice(host).catch(fail); return undefined; }
    if (tab === "shortcuts") { shell("Keyboard shortcuts", "Every key that jumps somewhere or opens something."); renderShortcuts(host); return undefined; }
    if (tab === "developer") {
      shell("Developer & advanced", "Service health, configuration checks and every environment option. Secrets are never shown.");
      const att = h("div", { class: "k-stack" }), top = h("div", { class: "k-stack" }), env = h("div", { class: "k-stack" });
      mount(host, att, top, env);
      void renderAttention(att).catch(() => undefined);
      renderEnvSettings(env, query);
      void renderDeveloper(top).catch((e) => mount(top, empty("alert", e instanceof Error ? e.message : "This section could not load.")));
      return undefined;
    }
    return undefined;
  },
};
