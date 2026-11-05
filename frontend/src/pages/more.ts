import { get } from "../api.js";
import { busy, h, mount } from "../dom.js";
import { icon, logo } from "../icons.js";
import { onStatus, status, type Status } from "../state.js";
import { THEME_ICON, appContext, openPalette, openShortcuts, themePref, type ThemePref } from "../ui.js";
import { APP_VERSION } from "../version.js";
import { AREAS, tile } from "./kit.js";
import { empty } from "./shared.js";
import { setupSteps, type Setup } from "./setup.js";
import type { Page } from "./types.js";

const BLURB: Record<string, string> = {
  notebook: "Private notes and reminders",
  community: "Quotes and trusted regulars",
  insights: "Charts of chat and moderation",
  demo: "Run simulated chat scenarios",
  setup: "Connect YouTube and Telegram",
  settings: "Every option, searchable",
};

function hero(s: Status | null): { state: "live" | "demo" | "standby"; title: string; detail: string } {
  if (!s) return { state: "standby", title: "Connecting", detail: "Waiting for the backend" };
  if (s.hub.mode === "demo") return { state: "demo", title: "Demo mode", detail: "Simulated chat, nothing is sent" };
  if (s.hub.stream_live) return { state: "live", title: "On air", detail: s.hub.stream_title || "YouTube live chat" };
  return { state: "standby", title: "Standby", detail: s.youtube.connected ? "Waiting for a live stream" : "YouTube not connected" };
}

export const more: Page = {
  id: "more",
  title: "More",
  icon: "menu",
  blurb: "Manage, system, appearance and account",
  render(root) {
    const ctx = appContext();
    const meta = new Map<string, HTMLElement>();
    const metaFor = (id: string): HTMLElement => { let el = meta.get(id); if (!el) { el = h("span", { class: "tile-count", hidden: true }, ""); meta.set(id, el); } return el; };
    const setMeta = (id: string, text: string | null, tone = "") => { const el = metaFor(id); el.hidden = !text; el.textContent = text ?? ""; el.className = `tile-count ${tone}`; };

    // ------------------------------------------------------------ status card with the mode switch
    const card = h("section", { class: "more-hero", "data-state": "standby" });
    const drawHero = (s: Status | null) => {
      const t = hero(s);
      card.setAttribute("data-state", t.state);
      const mode = s?.hub.mode ?? "demo";
      const mk = (m: "demo" | "live", ic: string, label: string) => {
        const b = h("button", { type: "button", "aria-pressed": String(mode === m) }, icon(ic, 16), label);
        b.onclick = () => { if (mode !== m) busy(b, () => ctx.setMode(m)); };
        return b;
      };
      mount(card,
        h("div", { class: "mh-top" }, h("span", { class: "mh-logo" }, logo(34)),
          h("div", { class: "grow" }, h("div", { class: "mh-title" }, h("strong", null, t.title), h("span", { class: "mh-dot", "aria-hidden": "true" })), h("div", { class: "mh-detail" }, t.detail))),
        h("div", { class: "mc-switch wide", role: "group", "aria-label": "Bot mode" }, mk("demo", "flask", "Demo"), mk("live", "radio", "Live")),
        s ? h("div", { class: "mh-stats" },
          h("a", { href: "#/moderation" }, h("b", null, String(s.pending)), h("span", null, "waiting")),
          h("a", { href: "#/desk" }, h("b", null, String(s.hub.lines)), h("span", null, "chat lines")),
          h("a", { href: "#/settings" }, h("b", null, s.hub.mod_mode), h("span", null, "moderation"))) : null);
    };

    // ------------------------------------------------------------ searchable sections
    const find = h("input", { type: "search", placeholder: "Search sections and actions", "aria-label": "Search sections", autocomplete: "off" });
    const sections = h("div", { class: "more-sections" });
    const drawSections = () => {
      const q = find.value.trim().toLowerCase();
      const hit = (t: string, b: string) => !q || `${t} ${b}`.toLowerCase().includes(q);
      const blocks = Object.entries(AREAS).map(([key, area]) => {
        const items = area.items.filter((i) => hit(i.title, BLURB[i.id] ?? ""));
        if (!items.length) return null;
        return h("section", { class: "more-group" }, h("h2", { class: "mg-title" }, area.title),
          h("div", { class: "tiles" }, items.map((i) => tile({ icon: i.icon, title: i.title, text: BLURB[i.id], href: `#/${i.id}`, meta: metaFor(i.id) }))));
      }).filter(Boolean);
      mount(sections, blocks.length ? blocks : empty("search", "Nothing matches. Try the command palette for actions."));
    };
    find.addEventListener("input", drawSections);
    drawSections();

    // ------------------------------------------------------------ appearance and account
    const themes: ThemePref[] = ["system", "light", "dark"];
    const themeSeg = h("div", { class: "seg-control", role: "group", "aria-label": "Theme" });
    const drawTheme = () => mount(themeSeg, themes.map((t) => h("button", { type: "button", "aria-pressed": String(themePref() === t), onclick: () => { ctx.setTheme(t); drawTheme(); } }, icon(THEME_ICON[t], 16), t === "system" ? "Auto" : t[0].toUpperCase() + t.slice(1))));
    drawTheme();
    const account = h("section", { class: "more-group" }, h("h2", { class: "mg-title" }, "Appearance and account"),
      h("div", { class: "more-card" },
        h("div", { class: "mc-row" }, h("span", null, h("strong", null, "Theme"), h("span", { class: "muted small" }, "Follows your device unless you choose")), themeSeg),
        h("button", { class: "mc-link", type: "button", onclick: () => openPalette(ctx) }, icon("search", 18), h("span", { class: "grow" }, "Search pages and actions"), h("kbd", null, "Ctrl K")),
        h("button", { class: "mc-link", type: "button", onclick: () => openShortcuts(ctx) }, icon("keyboard", 18), h("span", { class: "grow" }, "Keyboard shortcuts"), icon("chevronRight", 16)),
        h("button", { class: "mc-link danger", type: "button", onclick: () => ctx.signOut() }, icon("logout", 18), h("span", { class: "grow" }, "Sign out"), icon("chevronRight", 16))),
      h("p", { class: "muted small centered" }, `SavahBot dashboard v${APP_VERSION}`));

    mount(root, h("div", { class: "more-page" },
      h("div", { class: "more-head" }, h("h1", null, "More"), h("p", { class: "muted" }, "Everything beyond the daily desk, in one place.")),
      card, h("div", { class: "input-icon more-find" }, icon("search", 16), find), sections, account));

    // ------------------------------------------------------------ live bits: status, counts, setup progress
    drawHero(status);
    const off = onStatus((s) => drawHero(s));
    let alive = true;
    const count = (path: string) => get<{ items: unknown[] }>(path).then((r) => r.items.length, () => null);
    void Promise.all([count("/api/notes"), count("/api/reminders"), count("/api/quotes"), count("/api/regulars")]).then(([n, r, q, g]) => {
      if (!alive) return;
      setMeta("notebook", n === null ? null : `${n} note${n === 1 ? "" : "s"}${r ? ` · ${r} reminder${r === 1 ? "" : "s"}` : ""}`);
      setMeta("community", q === null && g === null ? null : `${q ?? 0} quote${q === 1 ? "" : "s"} · ${g ?? 0} regular${g === 1 ? "" : "s"}`);
    });
    void get<Setup>("/api/setup").then((s) => {
      if (!alive) return;
      const steps = setupSteps(s, status);
      const done = steps.filter((x) => x.done).length;
      setMeta("setup", done === steps.length ? "All set" : `${done} of ${steps.length} done`, done === steps.length ? "ok" : "warn");
    }, () => undefined);
    return () => { alive = false; off(); };
  },
};
