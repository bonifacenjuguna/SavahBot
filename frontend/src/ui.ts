/** Cross-page UI: theme, command palette, keyboard shortcuts. */
import { recentPages } from "./nav.js";
import { get, post } from "./api.js";
import { h, mount, sheet, toast } from "./dom.js";
import { icon } from "./icons.js";
import type { Page } from "./pages/types.js";
import { installApp, getPWAState } from "./pwa.js";
import { refreshStatus, status } from "./state.js";
import { navigate } from "./router.js";

// ------------------------------------------------------------------ theme
export type ThemePref = "system" | "light" | "dark";
const THEME_KEY = "savahbot.theme";

export function themePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(pref: ThemePref): void {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
  try {
    if (pref === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch { /* private mode: the choice lasts for this visit only */ }
  window.dispatchEvent(new Event("themechange"));
}

export function initTheme(): void {
  applyTheme(themePref());
}

export const THEME_ICON: Record<ThemePref, string> = { system: "monitor", light: "sun", dark: "moon" };
export function nextTheme(p: ThemePref): ThemePref {
  return p === "system" ? "light" : p === "light" ? "dark" : "system";
}

// ------------------------------------------------------------------ shortcuts
export const SHORTCUT_KEYS: Record<string, string> = { desk: "d", moderation: "m", commands: "c", notebook: "n", community: "u", bans: "b", security: "y", notifications: "a", weather: "w", insights: "i", demo: "x", setup: "s", settings: "t", more: "o" };

export interface AppContext {
  pages: Page[];
  go(id: string): void;
  setMode(mode: "demo" | "live"): Promise<void>;
  signOut(): void;
  cycleTheme(): void;
  setTheme(p: ThemePref): void;
}

function typing(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

let appCtx: AppContext | null = null;
/** The shell registers its actions once, so pages (the More page, for one) can change mode or theme without the shell passing them in. */
export function setAppContext(c: AppContext): void { appCtx = c; }
export function appContext(): AppContext { if (!appCtx) throw new Error("The app is not ready yet."); return appCtx; }

/** Phones and tablets have no keyboard to speak of, so shortcuts are only offered on desktops and laptops. */
export const hasKeyboard = (): boolean => !matchMedia("(max-width: 719px), (pointer: coarse)").matches;

export function installShortcuts(ctx: AppContext): () => void {
  let pendingG = 0;
  const onKey = (e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette(ctx);
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || document.body.classList.contains("no-scroll")) return;
    if (e.key === "?") { e.preventDefault(); openShortcuts(ctx); return; }
    if (e.key === "/") { e.preventDefault(); openPalette(ctx); return; }
    if (e.key.toLowerCase() === "g") { pendingG = Date.now(); return; }
    if (pendingG && Date.now() - pendingG < 1200) {
      const hit = Object.entries(SHORTCUT_KEYS).find(([, k]) => k === e.key.toLowerCase());
      pendingG = 0;
      if (hit) { e.preventDefault(); ctx.go(hit[0]); }
    }
  };
  document.addEventListener("keydown", onKey);
  return () => document.removeEventListener("keydown", onKey);
}

/** The full list of shortcuts as a grid of keys and what they do. Used by the pop-up sheet and by Settings, Shortcuts, so the two never differ. */
export function shortcutList(ctx: AppContext): HTMLElement {
  const rows: [string, string][] = [["Ctrl / Cmd + K", "Search and jump anywhere"], ["/", "Open search"], ["?", "This list"]];
  const goRows = Object.entries(SHORTCUT_KEYS).map(([id, k]) => [`g then ${k}`, `Go to ${ctx.pages.find((p) => p.id === id)?.title ?? id}`] as [string, string]);
  return h("div", { class: "keys" }, [...rows, ...goRows].flatMap(([k, d]) => [h("span", null, k.split(" ").map((p) => (p === "then" || p === "+" ? ` ${p} ` : h("kbd", null, p)))), h("span", { class: "muted" }, d)]));
}

export function openShortcuts(ctx: AppContext): void {
  openModal("Keyboard shortcuts", shortcutList(ctx));
}

function openModal(title: string, body: Node): void { sheet(title, body); }

// ------------------------------------------------------------------ command palette
interface Item { group: string; label: string; hint?: string; icon: string; run: () => void | Promise<void>; keywords?: string }

let paletteOpen = false;

export function openPalette(ctx: AppContext): void {
  if (paletteOpen) return;
  paletteOpen = true;
  const live = status?.hub.mode === "live";
  const recent = recentPages().map((id) => ctx.pages.find((p) => p.id === id)).filter((p): p is NonNullable<typeof p> => !!p).slice(1, 5);
  const items: Item[] = [
    ...recent.map((p): Item => ({ group: "Recent", label: p.title, hint: p.blurb, icon: p.icon, run: () => ctx.go(p.id), keywords: `recent ${p.id}` })),
    { group: "Actions", label: "Pause Telegram for 30 minutes", icon: "bellOff", run: async () => { await post("/api/telegram/control", { pause_minutes: 30 }); toast("Telegram is paused for 30 minutes"); }, keywords: "telegram pause quiet silence mute" },
    { group: "Actions", label: "Resume Telegram", icon: "send", run: async () => { await post("/api/telegram/control", { pause_minutes: 0 }); toast("Telegram is back"); }, keywords: "telegram resume unpause" },
    { group: "Actions", label: "Pause push notifications for 1 hour", icon: "bellOff", run: async () => { await post("/api/notify/pause", { minutes: 60 }); toast("Notifications are paused for an hour"); }, keywords: "notifications pause quiet mute spam" },
    { group: "Go to", label: "Stream source: paste a live link", icon: "link", run: () => { navigate("/setup?step=youtube"); }, keywords: "youtube stream video link id auto search" },
    ...ctx.pages.map((p): Item => ({ group: "Go to", label: p.title, hint: p.blurb, icon: p.icon, run: () => ctx.go(p.id), keywords: p.id })),
    { group: "Actions", label: live ? "Switch to Demo mode" : "Switch to Live mode", icon: live ? "flask" : "zap", run: () => ctx.setMode(live ? "demo" : "live"), keywords: "mode demo live" },
    { group: "Quick add", label: "New note", icon: "notebook", run: () => { navigate("/notebook?compose=1"); }, keywords: "note write checklist" },
    { group: "Quick add", label: "Set a reminder", icon: "bell", run: () => { navigate("/notebook?pane=reminders"); }, keywords: "remind timer" },
    { group: "Quick add", label: "Add a quote", icon: "quote", run: () => { navigate("/community?add=quote"); }, keywords: "quote community" },
    { group: "Quick add", label: "Test a message against the rules", icon: "gauge", run: () => { navigate("/moderation?tab=rules"); }, keywords: "score moderation test try" },
    { group: "Quick add", label: "Check a message against the knowledge", icon: "flask", run: () => { navigate("/settings?tab=knowledge&view=test"); }, keywords: "knowledge test lab scam spam detect try" },
    { group: "Go to", label: "Knowledge: packs, detectors and learning", icon: "sparkle", hint: "What the bot knows", run: () => { navigate("/settings?tab=knowledge"); }, keywords: "knowledge intelligence packs detectors learning feeds scam" },
    { group: "Actions", label: "Review what the bot has learned", icon: "trending", run: () => { navigate("/settings?tab=knowledge&view=learning"); }, keywords: "learning suggestions approve reject teach lesson" },
    { group: "Go to", label: "Knowledge: live threat lists", icon: "radio", run: () => { navigate("/settings?tab=knowledge&view=live"); }, keywords: "feeds phishing malware domains live data" },
    { group: "Actions", label: "Refresh status", icon: "refresh", run: async () => { await refreshStatus(); toast("Status refreshed"); }, keywords: "reload" },
    { group: "Appearance", label: "Theme: follow system", icon: "monitor", run: () => ctx.setTheme("system"), keywords: "theme appearance" },
    { group: "Appearance", label: "Theme: light", icon: "sun", run: () => ctx.setTheme("light"), keywords: "theme appearance" },
    { group: "Appearance", label: "Theme: dark", icon: "moon", run: () => ctx.setTheme("dark"), keywords: "theme appearance" },
    ...(getPWAState().entry ? [{ group: "Actions", label: getPWAState().label, icon: "download", run: () => installApp(), keywords: "install app pwa home screen dock add" } satisfies Item] : []),
    ...(hasKeyboard() ? [{ group: "Help", label: "Keyboard shortcuts", icon: "keyboard", run: () => openShortcuts(ctx), keywords: "keys help" } satisfies Item] : []),
    { group: "Account", label: "Sign out", icon: "logout", run: () => ctx.signOut(), keywords: "logout" },
  ];
  // demo scenarios are loaded in the background and added when they arrive
  let scenariosAdded = false;
  const loadScenarios = async () => {
    if (scenariosAdded || status?.hub.mode !== "demo") return;
    try {
      const d = await get<{ scenarios: { name: string; label?: string; running: boolean }[] }>("/api/demo");
      scenariosAdded = true;
      d.scenarios.forEach((s) => items.push({ group: "Run demo scenario", label: s.label ?? s.name.replace(/_/g, " "), icon: "play", keywords: "scenario demo " + s.name,
        run: async () => { await post("/api/demo/scenario", { name: s.name }); toast("Scenario started. Watch the Desk."); ctx.go("desk"); } }));
      draw();
    } catch { /* optional extra */ }
  };

  const input = h("input", { type: "text", placeholder: "Search pages and actions", "aria-label": "Search pages and actions", autocomplete: "off", spellcheck: false, role: "combobox", "aria-expanded": "true", "aria-controls": "pal-list" });
  const list = h("ul", { class: "pal-list", id: "pal-list", role: "listbox" });
  let shown: Item[] = [];
  let sel = 0;

  const close = () => {
    if (!paletteOpen) return;
    paletteOpen = false;
    overlay.remove();
    document.removeEventListener("keydown", onKey, true);
    if (!document.querySelector(".sheet")) document.body.classList.remove("no-scroll");
  };
  const run = async (it: Item) => {
    close();
    try { await it.run(); } catch (e) { toast((e as Error).message, "error"); }
  };
  function draw(): void {
    const q = input.value.trim().toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    shown = items.filter((it) => { const hay = `${it.label} ${it.group} ${it.keywords ?? ""}`.toLowerCase(); return words.every((w) => hay.includes(w)); });
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    let lastGroup = "";
    mount(list, shown.length ? shown.flatMap((it, i) => {
      const out: Node[] = [];
      if (it.group !== lastGroup) { lastGroup = it.group; out.push(h("li", { class: "pal-group", role: "presentation" }, it.group)); }
      out.push(h("li", { class: "pal-item", role: "option", "aria-selected": String(i === sel), id: `pal-${i}`, onclick: () => void run(it), onmousemove: () => { if (sel !== i) { sel = i; draw(); } } },
        icon(it.icon, 18), h("span", null, it.label), it.hint ? h("span", { class: "hint" }, it.hint) : null));
      return out;
    }) : h("li", { class: "empty" }, "Nothing matches."));
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    input.setAttribute("aria-activedescendant", `pal-${sel}`);
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(shown.length - 1, sel + 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); draw(); }
    else if (e.key === "Enter" && shown[sel]) { e.preventDefault(); void run(shown[sel]); }
  };
  input.addEventListener("input", () => { sel = 0; draw(); });

  const overlay = h("div", { class: "overlay top", onpointerdown: (e: Event) => { if (e.target === overlay) close(); } },
    h("div", { class: "palette", role: "dialog", "aria-modal": "true", "aria-label": "Search" },
      h("div", { class: "pal-top" }, icon("search", 18), input, h("button", { class: "icon-btn", type: "button", "aria-label": "Close", onclick: close }, icon("x", 18))),
      list,
      h("div", { class: "pal-foot" }, h("span", null, h("kbd", null, "Up"), " ", h("kbd", null, "Down"), " move"), h("span", null, h("kbd", null, "Enter"), " open"), h("span", null, h("kbd", null, "Esc"), " close"))));
  document.body.appendChild(overlay);
  document.body.classList.add("no-scroll");
  document.addEventListener("keydown", onKey, true);
  draw();
  input.focus();
  void loadScenarios();
}
