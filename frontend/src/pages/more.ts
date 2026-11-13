import { get } from "../api.js";
import { busy, h, mount } from "../dom.js";
import { icon } from "../icons.js";
import { onStatus, status, type Status } from "../state.js";
import { THEME_ICON, appContext, openShortcuts, themePref, type ThemePref } from "../ui.js";
import { APP_VERSION } from "../version.js";
import { installApp, onPWAState } from "../pwa.js";
import { AREAS, tile } from "./kit.js";
import { setupSteps, type Setup } from "./setup.js";
import type { Page } from "./types.js";

const BLURB: Record<string, string> = {
  notebook: "Private notes and reminders",
  community: "Quotes and trusted regulars",
  bans: "Lift bans and soften the bot's actions",
  security: "Sign-in methods, devices and lockdown",
  notifications: "Push, bell, quiet hours and history",
  weather: "Current weather, forecast and weather alerts",
  backup: "Encrypted export and restore",
  insights: "Charts of chat and moderation",
  demo: "Run simulated chat scenarios",
  setup: "Connect YouTube and Telegram",
  settings: "Every option, and the bot's Intelligence",
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
    // Made of the app's own parts (panel, line, the same segmented control as the chat filters), no gradient or glow. Phones only: from 720px up
    // the sidebar shows the same status and switch.
    const card = h("section", { class: "more-status", "data-state": "standby", "aria-label": "Bot status" });
    const STATE_ICON = { live: "radio", demo: "flask", standby: "power" } as const;
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
        h("div", { class: "ms-main" }, h("span", { class: "ms-ico", "aria-hidden": "true" }, icon(STATE_ICON[t.state], 20)),
          h("div", { class: "ms-text", role: "status" }, h("strong", { class: "ms-title" }, t.title), h("span", { class: "ms-detail" }, t.detail))),
        h("div", { class: "seg-control ms-seg", role: "group", "aria-label": "Bot mode" }, mk("demo", "flask", "Demo"), mk("live", "radio", "Live")),
        s ? h("div", { class: "ms-stats" },
          h("a", { href: "/moderation" }, h("b", null, String(s.pending)), h("span", null, "waiting")),
          h("a", { href: "/desk" }, h("b", null, String(s.hub.lines)), h("span", null, "chat lines")),
          h("a", { href: "/settings" }, h("b", null, s.hub.mod_mode), h("span", null, "moderation"))) : null);
    };

    // ------------------------------------------------------------ sections
    const sections = h("div", { class: "more-sections" });
    mount(sections, Object.values(AREAS).map((area) =>
      h("section", { class: "more-group" }, h("h2", { class: "mg-title" }, area.title),
        h("div", { class: "tiles" }, area.items.map((i) => tile({ icon: i.icon, title: i.title, text: BLURB[i.id], href: `/${i.id}`, meta: metaFor(i.id) }))))));

    // ------------------------------------------------------------ appearance and account
    const themes: ThemePref[] = ["system", "light", "dark"];
    const themeSeg = h("div", { class: "seg-control", role: "group", "aria-label": "Theme" });
    const drawTheme = () => mount(themeSeg, themes.map((t) => h("button", { type: "button", "aria-pressed": String(themePref() === t), onclick: () => { ctx.setTheme(t); drawTheme(); } }, icon(THEME_ICON[t], 16), t === "system" ? "Auto" : t[0].toUpperCase() + t.slice(1))));
    drawTheme();
    const account = h("section", { class: "more-group" }, h("h2", { class: "mg-title" }, "Appearance and account"),
      h("div", { class: "more-card" },
        h("div", { class: "mc-row" }, h("span", null, h("strong", null, "Theme"), h("span", { class: "muted small" }, "Follows your device unless you choose")), themeSeg),
        h("button", { class: "mc-link kb-only", type: "button", onclick: () => openShortcuts(ctx) }, icon("keyboard", 18), h("span", { class: "grow" }, "Keyboard shortcuts"), icon("chevronRight", 16)),
        h("button", { class: "mc-link danger", type: "button", onclick: () => ctx.signOut() }, icon("logout", 18), h("span", { class: "grow" }, "Sign out"), icon("chevronRight", 16))),
      h("p", { class: "muted small centered" }, `SavahBot dashboard v${APP_VERSION}`));

    // 1.1.9: install entry. It stays here after the banner is dismissed, and disappears once the app is installed.
    const installBox = h("section", { class: "more-group", hidden: true });
    const offInstall = onPWAState((s) => {
      installBox.hidden = !s.entry;
      if (s.entry) mount(installBox, h("h2", { class: "mg-title" }, "App"), h("div", { class: "tiles" }, tile({ icon: s.mode === "native" ? "download" : "plusSquare", title: s.label, text: s.hint, onclick: () => void installApp() })));
    });

    mount(root, h("div", { class: "more-page" },
      h("h1", { class: "sr-only" }, "More"),
      card, installBox, sections, account));

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
    return () => { alive = false; off(); offInstall(); };
  },
};
