import "./styles.css";
import { ApiError, apiBase, hasToken, loggedOut, post, setApiBase, setToken } from "./api.js";
import { busy, clear, h, mount, toast } from "./dom.js";
import * as feed from "./events.js";
import { icon, logo, type IconName } from "./icons.js";
import { closePalette, openPalette, type PaletteItem } from "./palette.js";
import { refreshStatus, onStatus, type Status } from "./state.js";
import { applyTheme, getTheme, nextTheme, setTheme, themeLabel } from "./theme.js";
import { overview } from "./pages/overview.js";
import { desk } from "./pages/desk.js";
import { moderation } from "./pages/moderation.js";
import { commands } from "./pages/commands.js";
import { notebook } from "./pages/notebook.js";
import { community } from "./pages/community.js";
import { insights } from "./pages/insights.js";
import { demo } from "./pages/demo.js";
import { setup } from "./pages/setup.js";
import { settings } from "./pages/settings.js";
import type { Page } from "./pages/types.js";

const PAGES: Page[] = [overview, desk, moderation, commands, notebook, community, insights, demo, setup, settings];
const PAGE_ICONS: Record<string, IconName> = {
  overview: "overview", desk: "desk", moderation: "shield", commands: "commands", notebook: "notebook", community: "users",
  insights: "chart", demo: "flask", setup: "plug", settings: "sliders",
};
/** Pages that get a tab on phones. Everything else lives behind "More". */
const TABS = ["overview", "desk", "moderation", "insights"];
const DEFAULT_PAGE = "overview";
const root = document.getElementById("app")!;
let statusTimer: number | undefined;
let shellUp = false;

applyTheme();

function route(): { id: string; query: URLSearchParams } {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  return { id: path || DEFAULT_PAGE, query: new URLSearchParams(qs ?? "") };
}

function tallyState(s: Status | null): { state: "live" | "demo" | "standby"; title: string; detail: string } {
  if (!s) return { state: "standby", title: "Connecting", detail: "Waiting for the backend" };
  if (s.hub.mode === "demo") return { state: "demo", title: "Demo", detail: "Simulated chat, nothing is sent" };
  if (s.hub.stream_live) return { state: "live", title: "On air", detail: s.hub.stream_title || "YouTube live chat" };
  return { state: "standby", title: "Standby", detail: s.youtube.connected ? "Waiting for a live stream" : "YouTube not connected" };
}

// ------------------------------------------------------------------------------------------------ login
function showLogin(): void {
  shellUp = false;
  closePalette();
  feed.stop();
  window.clearInterval(statusTimer);
  const needsBase = !apiBase();
  const pass = h("input", { type: "password", autocomplete: "current-password", required: true, id: "pw" });
  const base = h("input", { type: "url", placeholder: "https://your-app.up.railway.app", value: apiBase(), id: "base" });
  const err = h("p", { class: "small", style: "color:var(--bad)", role: "alert" });
  const btn = h("button", { class: "btn primary block-btn", type: "submit" }, icon("lock", 16), "Sign in");
  const form = h(
    "form",
    {
      class: "login-card",
      onsubmit: (e: Event) => {
        e.preventDefault();
        err.textContent = "";
        setApiBase(base.value);
        btn.disabled = true;
        post<{ token: string }>("/api/auth/login", { password: pass.value })
          .then((r) => { setToken(r.token); boot(); })
          .catch((ex) => { err.textContent = ex instanceof ApiError ? ex.message : "Could not sign in."; })
          .finally(() => (btn.disabled = false));
      },
    },
    h("div", { class: "login-mark" }, logo(40), h("h1", null, "SavahBot")),
    h("p", { class: "muted" }, "Owner sign-in. The password is the OWNER_PASSWORD variable, or the one printed once in the Railway logs on first start."),
    h("label", { class: "field" }, "Password", pass),
    needsBase
      ? h("label", { class: "field" }, "Backend address", base)
      : h("details", null, h("summary", { class: "small muted" }, "Backend address"), h("label", { class: "field" }, "Address", base)),
    err,
    btn,
  );
  const points: [IconName, string, string][] = [
    ["shield", "Moderation you control", "Suggest, approve or let it act on its own."],
    ["chart", "Live insights", "Chat activity, triggers and quota at a glance."],
    ["smartphone", "Works on every screen", "Phone, tablet and desktop, with an installable app."],
  ];
  const side = h("aside", { class: "login-side" },
    h("div", { class: "login-mark" }, logo(56)),
    h("h2", null, "Calm, accountable chat moderation."),
    h("ul", null, points.map(([ic, title, text]) => h("li", null, icon(ic, 22), h("div", null, h("strong", null, title), h("p", null, text))))));
  mount(root, h("main", { class: "login" }, side, form));
  pass.focus();
}

// ------------------------------------------------------------------------------------------------ shell
function showShell(): void {
  shellUp = true;
  const updaters: ((s: Status) => void)[] = [];
  const themePainters: (() => void)[] = [];
  const cycleTheme = () => { setTheme(nextTheme()); themePainters.forEach((f) => f()); };

  // Tally: the lamp and the one-line state. Built twice (side rail, phone top bar) and kept in step.
  const makeTally = (withDetail: boolean) => {
    const lamp = h("div", { class: "lamp", "aria-hidden": "true" });
    const title = h("strong", null, "Connecting");
    const detail = h("span", { class: "detail" }, "");
    const el = h("div", { class: "tally", "data-state": "standby", role: "status" }, lamp, title, withDetail ? detail : null);
    updaters.push((s) => {
      const t = tallyState(s);
      el.setAttribute("data-state", t.state);
      el.title = `${t.title}: ${t.detail}`;
      title.textContent = t.title;
      detail.textContent = t.detail;
    });
    return el;
  };

  const makeSegment = () => {
    const demoBtn = h("button", { type: "button", "aria-pressed": "false", title: "Demo mode" }, icon("flask", 16), h("span", { class: "label" }, "Demo"));
    const liveBtn = h("button", { type: "button", "aria-pressed": "false", title: "Live mode" }, icon("broadcast", 16), h("span", { class: "label" }, "Live"));
    const setMode = (mode: "demo" | "live") => () => busy(mode === "demo" ? demoBtn : liveBtn, async () => { await post("/api/mode", { mode }); await refreshStatus(); });
    demoBtn.onclick = setMode("demo");
    liveBtn.onclick = setMode("live");
    updaters.push((s) => {
      demoBtn.setAttribute("aria-pressed", String(s.hub.mode === "demo"));
      liveBtn.setAttribute("aria-pressed", String(s.hub.mode === "live"));
    });
    return h("div", { class: "segment", role: "group", "aria-label": "Bot mode" }, demoBtn, liveBtn);
  };

  const makeThemeButton = (withLabel = false) => {
    const b = h("button", { class: "icon-btn", type: "button" });
    const paint = () => {
      const t = getTheme();
      mount(b, icon(t === "system" ? "monitor" : t === "light" ? "sun" : "moon", 18), withLabel ? h("span", { class: "label" }, themeLabel(t)) : null);
      b.title = themeLabel(t);
      b.setAttribute("aria-label", themeLabel(t));
    };
    b.onclick = cycleTheme;
    themePainters.push(paint);
    paint();
    return b;
  };

  const signOut = () => { setToken(""); showLogin(); };
  const goTo = (id: string) => () => { location.hash = `#/${id}`; };
  const quickSearch = () => openPalette(paletteItems());

  const badges: HTMLElement[] = [];
  const badge = () => { const b = h("span", { class: "count", hidden: true }, ""); badges.push(b); return b; };

  // --- side rail (tablet and desktop)
  const nav = h("nav", { class: "nav", "aria-label": "Sections" },
    PAGES.map((p) => h("a", { href: `#/${p.id}`, "data-id": p.id, title: p.title }, icon(PAGE_ICONS[p.id], 20), h("span", { class: "label" }, p.title), p.id === "moderation" ? badge() : null)));
  const quotaText = h("span", { class: "label" }, "");
  const meterBar = h("i", null);
  const meter = h("div", { class: "meter", title: "YouTube API quota used today" }, meterBar);
  const connText = h("span", { class: "label" }, "Live feed: connecting");
  const connDot = h("i", { class: "dot" });
  const version = h("span", { class: "ver" }, "");
  const rail = h("aside", { class: "rail" },
    h("div", { class: "brand" }, logo(30), h("span", { class: "label" }, "SavahBot"), version),
    makeTally(true), makeSegment(),
    h("button", { class: "searchbtn", type: "button", onclick: quickSearch, "aria-label": "Search pages and actions" }, icon("search", 18), h("span", { class: "label" }, "Search"), h("kbd", { class: "label" }, "Ctrl K")),
    nav,
    h("div", { class: "rail-foot" }, quotaText, meter, h("div", { class: "row tight" }, connDot, connText),
      h("div", { class: "foot-actions" }, makeThemeButton(true),
        h("button", { class: "icon-btn", type: "button", onclick: signOut, title: "Sign out", "aria-label": "Sign out" }, icon("logout", 18), h("span", { class: "label" }, "Sign out")))));

  // --- phone top bar
  const topbar = h("header", { class: "topbar" },
    h("a", { class: "topbrand", href: `#/${DEFAULT_PAGE}`, "aria-label": "SavahBot home" }, logo(26)),
    makeTally(false), h("div", { class: "grow" }), makeSegment(),
    h("button", { class: "icon-btn", type: "button", onclick: quickSearch, title: "Search", "aria-label": "Search pages and actions" }, icon("search", 20)));

  // --- phone bottom tabs and the More sheet
  const sheet = h("div", { class: "sheet", hidden: true });
  const moreBtn = h("button", { type: "button", class: "tab", "aria-expanded": "false", "aria-controls": "more-sheet", "data-more": "1" }, icon("more", 22), h("span", null, "More"));
  const closeSheet = () => { sheet.hidden = true; moreBtn.setAttribute("aria-expanded", "false"); };
  const openSheet = () => { sheet.hidden = false; moreBtn.setAttribute("aria-expanded", "true"); };
  moreBtn.onclick = () => (sheet.hidden ? openSheet() : closeSheet());
  const tabbar = h("nav", { class: "tabbar", "aria-label": "Main sections" },
    TABS.map((id) => { const p = PAGES.find((x) => x.id === id)!; return h("a", { class: "tab", href: `#/${id}`, "data-id": id }, icon(PAGE_ICONS[id], 22), h("span", null, p.title), id === "moderation" ? badge() : null); }),
    moreBtn);
  const sheetQuota = h("p", { class: "muted small" }, "");
  const sheetPanel = h("div", { class: "sheet-panel", id: "more-sheet", role: "dialog", "aria-label": "More sections" },
    h("div", { class: "sheet-grip", "aria-hidden": "true" }),
    h("div", { class: "sheet-grid" }, PAGES.filter((p) => !TABS.includes(p.id)).map((p) => h("a", { href: `#/${p.id}`, "data-id": p.id, onclick: closeSheet }, icon(PAGE_ICONS[p.id], 22), h("span", null, p.title)))),
    sheetQuota,
    h("div", { class: "row between" }, makeThemeButton(true), h("button", { class: "btn ghost", type: "button", onclick: signOut }, icon("logout", 16), "Sign out")));
  mount(sheet, h("div", { class: "sheet-scrim", onclick: closeSheet }), sheetPanel);

  const content = h("main", { class: "main", id: "content", tabindex: -1 });
  mount(root, h("div", { class: "shell" }, rail, topbar, content, tabbar, sheet));

  function paletteItems(): PaletteItem[] {
    return [
      ...PAGES.map((p) => ({ id: `go-${p.id}`, label: p.title, hint: "Go to page", icon: PAGE_ICONS[p.id], run: goTo(p.id) })),
      { id: "demo", label: "Switch to demo mode", hint: "Simulated chat", icon: "flask" as IconName, run: () => void post("/api/mode", { mode: "demo" }).then(refreshStatus).catch((e) => toast(e.message, "error")) },
      { id: "live", label: "Switch to live mode", hint: "YouTube", icon: "broadcast" as IconName, run: () => void post("/api/mode", { mode: "live" }).then(refreshStatus).catch((e) => toast(e.message, "error")) },
      { id: "theme", label: "Change theme", hint: themeLabel(), icon: "sun" as IconName, run: cycleTheme },
      { id: "refresh", label: "Refresh status", icon: "refresh" as IconName, run: () => void refreshStatus() },
      { id: "out", label: "Sign out", icon: "logout" as IconName, run: signOut },
    ];
  }

  let cleanup: (() => void) | void;
  const render = () => {
    cleanup?.();
    closeSheet();
    const { id, query } = route();
    const page = PAGES.find((p) => p.id === id) ?? PAGES[0];
    root.querySelectorAll("[data-id]").forEach((a) => (a.getAttribute("data-id") === page.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    moreBtn.classList.toggle("on", !TABS.includes(page.id));
    document.title = `${page.title} · SavahBot`;
    clear(content);
    window.scrollTo(0, 0);
    cleanup = page.render(content, query);
  };
  window.onhashchange = render;

  const offStatus = onStatus((s) => {
    updaters.forEach((f) => f(s));
    const q = s.youtube.quota;
    const pct = Math.min(100, Math.round(q.fraction * 100));
    const text = s.hub.mode === "demo" ? "YouTube quota: untouched in demo" : `YouTube quota: ${pct}% used today`;
    quotaText.textContent = text;
    sheetQuota.textContent = text;
    meterBar.style.width = `${s.hub.mode === "demo" ? 0 : pct}%`;
    meter.classList.toggle("hot", pct >= 75);
    version.textContent = `v${s.version}`;
    badges.forEach((b) => { b.hidden = s.pending === 0; b.textContent = String(s.pending); });
  });
  const offConn = feed.onConnection((up) => { connText.textContent = up ? "Live feed: connected" : "Live feed: reconnecting"; connDot.className = up ? "dot up" : "dot"; });
  const offEvents = ["mode", "stream", "mod_pending", "mod_resolved"].map((t) => feed.on(t, () => void refreshStatus()));

  render();
  void refreshStatus();
  statusTimer = window.setInterval(() => void refreshStatus(), 15000);
  feed.start();
  loggedOut.addEventListener("out", () => { offStatus(); offConn(); offEvents.forEach((f) => f()); }, { once: true });
}

// Ctrl/Cmd+K (or "/" outside a text field) opens the palette. Ignored on the sign-in screen.
document.addEventListener("keydown", (e) => {
  if (!shellUp) return;
  const typing = (e.target as HTMLElement | null)?.closest("input, textarea, select, [contenteditable]");
  if ((e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey)) {
    e.preventDefault();
    document.querySelector<HTMLButtonElement>(".searchbtn")?.click();
  } else if (e.key === "Escape") {
    document.querySelector<HTMLElement>(".sheet:not([hidden]) .sheet-scrim")?.click();
  }
});

function boot(): void {
  if (!hasToken()) return showLogin();
  showShell();
}

loggedOut.addEventListener("out", () => {
  toast("Your session ended. Sign in again.", "error");
  showLogin();
});

boot();
