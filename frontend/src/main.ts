import "./styles.css";
import { ApiError, apiBase, hasToken, loggedOut, post, setApiBase, setToken } from "./api.js";
import { clear, h, mount, sheet, toast } from "./dom.js";
import * as feed from "./events.js";
import { icon, logo } from "./icons.js";
import { refreshStatus, onStatus, onModeChange, resetState, type Status } from "./state.js";
import { describeState, modeControl } from "./modeswitch.js";
import { THEME_ICON, applyTheme, initTheme, installShortcuts, nextTheme, openPalette, themePref, type AppContext, type ThemePref } from "./ui.js";
import { desk } from "./pages/desk.js";
import { moderation } from "./pages/moderation.js";
import { commands } from "./pages/commands.js";
import { notebook } from "./pages/notebook.js";
import { community } from "./pages/community.js";
import { insights } from "./pages/insights.js";
import { demo } from "./pages/demo.js";
import { setup } from "./pages/setup.js";
import { settings } from "./pages/settings.js";
import { notifications } from "./pages/notifications.js";
import type { Page } from "./pages/types.js";

export const APP_VERSION = "1.1.1";

const PAGES: Page[] = [desk, moderation, commands, notifications, notebook, community, insights, demo, setup, settings];
if ("scrollRestoration" in history) history.scrollRestoration = "manual";   // the browser must not restore a scroll offset into a freshly drawn page
const NAV_GROUPS: { title: string; ids: string[] }[] = [
  { title: "Operate", ids: ["desk", "moderation", "commands", "notifications"] },
  { title: "Manage", ids: ["notebook", "community", "insights", "demo"] },
  { title: "System", ids: ["setup", "settings"] },
];
const TAB_IDS = ["desk", "moderation", "commands", "insights"];
const root = document.getElementById("app")!;
let statusTimer: number | undefined;
let shellCleanup: (() => void) | null = null;

initTheme();

function route(): { id: string; query: URLSearchParams } {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  return { id: path || "desk", query: new URLSearchParams(qs ?? "") };
}

function signOut(): void {
  setToken("");
  resetState();
  showLogin();
}

// ------------------------------------------------------------------------------------------------ login
function showLogin(): void {
  shellCleanup?.();
  shellCleanup = null;
  feed.stop();
  window.clearInterval(statusTimer);
  const needsBase = !apiBase();
  const pass = h("input", { type: "password", autocomplete: "current-password", required: true, id: "pw" });
  const base = h("input", { type: "url", placeholder: "https://your-app.up.railway.app", value: apiBase(), id: "base" });
  const err = h("p", { class: "small", style: "color:var(--bad)", role: "alert" });
  const btn = h("button", { class: "btn primary", type: "submit" }, icon("lock", 16), "Sign in");
  const form = h(
    "form",
    {
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
    h("div", { class: "mobile-logo" }, logo(44)),
    h("div", { class: "head" }, h("h1", null, "Sign in")),
    h("p", { class: "muted" }, "Owner sign-in. The password is the OWNER_PASSWORD variable, or the one printed once in the Railway logs on first start."),
    h("label", { class: "field" }, "Password", pass),
    needsBase
      ? h("label", { class: "field" }, "Backend address", base)
      : h("details", null, h("summary", { class: "small muted" }, "Backend address"), h("label", { class: "field" }, "Address", base)),
    err,
    btn,
    h("p", { class: "muted small" }, `SavahBot dashboard v${APP_VERSION}`),
  );
  const brand = h("aside", { class: "login-brand" },
    h("div", { class: "row nowrap mark" }, logo(40), h("span", { class: "brand", style: "font-size:1.3rem" }, "SavahBot")),
    h("div", { class: "stack" },
      h("h2", null, "Your chat, under control."),
      h("p", null, "A private moderation and utility bot for YouTube live chat, run from this dashboard and from Telegram."),
      h("ul", { class: "login-points" },
        [["shield", "Explainable moderation: every score shows its signals."], ["flask", "Demo mode: simulated chat, nothing sent, no quota used."], ["chart", "Live charts of chat activity and moderation."]]
          .map(([i, t]) => h("li", null, icon(i, 20), h("span", null, t))))),
    h("span", { class: "small" }, `v${APP_VERSION}`));
  mount(root, h("main", { class: "login" }, brand, h("div", { class: "login-pane" }, form)));
  pass.focus();
}

// ------------------------------------------------------------------------------------------------ shell
function showShell(): void {
  shellCleanup?.();
  const offs: (() => void)[] = [];

  // ----- shared actions
  const ctx: AppContext = {
    pages: PAGES,
    go: (id) => { location.hash = `#/${id}`; },
    setMode: async (mode) => { await post("/api/mode", { mode }); await refreshStatus(); },
    signOut,
    cycleTheme: () => ctx.setTheme(nextTheme(themePref())),
    setTheme: (p: ThemePref) => { applyTheme(p); syncTheme(); },
  };

  // ----- sidebar (desktop and tablet)
  const railMode = modeControl((m) => ctx.setMode(m), "rail");

  const counts = new Map<string, HTMLElement>();
  const navLinks: HTMLAnchorElement[] = [];
  const nav = h("nav", { class: "nav", "aria-label": "Sections" },
    NAV_GROUPS.flatMap((g) => [
      h("div", { class: "nav-title" }, g.title),
      ...g.ids.map((id) => {
        const p = PAGES.find((x) => x.id === id)!;
        const badge = h("span", { class: "count", hidden: true }, "");
        counts.set(p.id, badge);
        const a = h("a", { href: `#/${p.id}`, "data-id": p.id, title: p.title }, icon(p.icon, 20), h("span", { class: "label" }, p.title), badge);
        navLinks.push(a);
        return a;
      }),
    ]));

  const quotaText = h("span", { class: "txt" }, "");
  const meterBar = h("i", null);
  const meter = h("div", { class: "meter", title: "YouTube API quota used today" }, meterBar);
  const connText = h("span", { class: "txt" }, "Live feed: connecting");
  const connIcon = h("span", { class: "ico-slot" }, icon("wifiOff", 16));
  const themeIcon = h("span", { class: "ico-slot" });
  const themeText = h("span", { class: "txt" }, "");
  const themeBtn = h("button", { class: "rail-btn", type: "button", onclick: () => ctx.cycleTheme(), title: "Change theme" }, themeIcon, themeText);
  const out = h("button", { class: "rail-btn", type: "button", onclick: signOut, title: "Sign out" }, icon("logout", 18), h("span", { class: "txt" }, "Sign out"));
  const verTag = h("span", { class: "ver", title: "Dashboard version" }, `v${APP_VERSION}`);
  const rail = h("aside", { class: "rail" },
    h("div", { class: "rail-brand" }, logo(30), h("span", { class: "brand" }, "SavahBot"), verTag),
    railMode.el, nav,
    h("div", { class: "rail-foot" }, h("div", { class: "stat" }, icon("gauge", 16), quotaText), meter, h("div", { class: "stat" }, connIcon, connText), themeBtn, out));

  // ----- top bar
  const tbDot = h("span", { class: "dot" });
  const tbTitle = h("span", null, "Connecting");
  const tbDetail = h("span", { class: "muted t-detail" }, "");
  const tbTally = h("button", { class: "tb-tally", type: "button", "data-state": "standby", "aria-label": "Bot mode and status", onclick: () => openModeSheet() }, tbDot, tbTitle, tbDetail);
  const searchBtn = h("button", { class: "search-btn", type: "button", onclick: () => openPalette(ctx), "aria-label": "Search and jump to" },
    icon("search", 18), h("span", { class: "grow" }, "Search pages and actions"), h("kbd", null, "Ctrl K"));
  const connChip = h("span", { class: "conn-chip down", role: "status" }, icon("wifiOff", 16), h("span", { class: "txt" }, "Reconnecting"));
  const bellBadge = h("span", { class: "badge", hidden: true }, "0");
  const bell = h("a", { class: "icon-btn", href: "#/notifications", "aria-label": "Notifications", title: "Notifications" }, icon("bell", 20), bellBadge);
  const topbar = h("header", { class: "topbar" },
    h("span", { class: "tb-brand" }, logo(26)), tbTally, searchBtn, h("span", { class: "tb-spacer" }), connChip, bell);

  // ----- phone tab bar
  const tabLinks: HTMLElement[] = [];
  const tabBadge = h("span", { class: "badge", hidden: true }, "0");
  const tabbar = h("nav", { class: "tabbar", "aria-label": "Main" },
    TAB_IDS.map((id) => {
      const p = PAGES.find((x) => x.id === id)!;
      const a = h("a", { class: "tab", href: `#/${p.id}`, "data-id": p.id }, icon(p.icon, 22), p.title, id === "moderation" ? tabBadge : null);
      tabLinks.push(a);
      return a;
    }),
    h("button", { class: "tab", type: "button", id: "tab-more", onclick: () => openMore() }, icon("menu", 22), "More"));
  const moreTab = tabbar.querySelector("#tab-more") as HTMLElement;

  const content = h("main", { class: "main", id: "content", tabindex: -1 });
  const skip = h("a", { class: "skip", href: "#content", onclick: (e: Event) => { e.preventDefault(); content.focus(); } }, "Skip to content");
  mount(root, skip, h("div", { class: "app" }, rail, h("div", { class: "stage" }, topbar, content)), tabbar);

  // ----- sheets (every open mode control is updated from the same status)
  const sheetModes = new Set<ReturnType<typeof modeControl>>();
  function openModeSheet(): void {
    const holder: { close: () => void } = { close: () => undefined };
    const ctl = modeControl((m) => ctx.setMode(m), "sheet", () => holder.close());
    if (lastStatus) ctl.update(lastStatus);
    sheetModes.add(ctl);
    holder.close = sheet("Bot mode", ctl.el, () => sheetModes.delete(ctl)).close;
  }
  function openMore(): void {
    const holder: { close: () => void } = { close: () => undefined };
    const rest = PAGES.filter((p) => !TAB_IDS.includes(p.id));
    const cur = route().id;
    const themes: ThemePref[] = ["system", "light", "dark"];
    const themeSeg = h("div", { class: "seg-control", role: "group", "aria-label": "Theme" }, themes.map((t) =>
      h("button", { type: "button", "aria-pressed": String(themePref() === t), onclick: () => { ctx.setTheme(t); holder.close(); } }, icon(THEME_ICON[t], 16), t === "system" ? "Auto" : t[0].toUpperCase() + t.slice(1))));
    const moreMode = modeControl((m) => ctx.setMode(m), "sheet", () => holder.close());
    if (lastStatus) moreMode.update(lastStatus);
    sheetModes.add(moreMode);
    const body = h("div", null,
      h("div", { class: "more-grid" }, rest.map((p) => h("a", { class: "more-item", href: `#/${p.id}`, "aria-current": cur === p.id ? "page" : undefined, onclick: () => holder.close() }, icon(p.icon, 24), p.title))),
      h("div", { class: "more-section" }, h("h3", null, "Bot mode"), moreMode.el),
      h("div", { class: "more-section" }, h("h3", null, "Theme"), themeSeg),
      h("div", { class: "more-section" },
        h("button", { class: "btn ghost block-btn", type: "button", onclick: () => { holder.close(); openPalette(ctx); } }, icon("search", 16), "Search pages and actions"),
        h("button", { class: "btn ghost block-btn", type: "button", onclick: () => { holder.close(); signOut(); } }, icon("logout", 16), "Sign out"),
        h("p", { class: "muted small", style: "text-align:center" }, `SavahBot dashboard v${APP_VERSION}`)));
    holder.close = sheet("More", body, () => sheetModes.delete(moreMode)).close;
  }

  // ----- routing
  let cleanup: (() => void) | void;
  let lastId = "";
  const render = () => {
    cleanup?.();
    const { id, query } = route();
    const page = PAGES.find((p) => p.id === id) ?? PAGES[0];
    for (const a of navLinks) (a.getAttribute("data-id") === page.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    for (const a of tabLinks) (a.getAttribute("data-id") === page.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    if (TAB_IDS.includes(page.id)) moreTab.removeAttribute("aria-current"); else moreTab.setAttribute("aria-current", "page");
    document.title = `${page.title} · SavahBot`;
    clear(content);
    cleanup = page.render(content, query);
    if (lastId !== page.id) window.scrollTo(0, 0);     // a new page always opens at the top
    lastId = page.id;
  };
  window.onhashchange = render;

  // ----- theme icon sync (the one theme control lives in the sidebar and the More sheet)
  function syncTheme(): void {
    const p = themePref();
    mount(themeIcon, icon(THEME_ICON[p], 18));
    themeText.textContent = `Theme: ${p === "system" ? "auto" : p}`;
  }
  syncTheme();

  // ----- live status
  let lastStatus: Status | null = null;
  offs.push(onStatus((s) => {
    lastStatus = s;
    const t = describeState(s);
    railMode.update(s);
    sheetModes.forEach((c) => c.update(s));
    tbTally.setAttribute("data-state", t.state);
    tbTitle.textContent = t.title;
    tbDetail.textContent = t.state === "demo" ? "simulated" : t.state === "live" ? "on air" : "waiting for stream";
    const q = s.youtube.quota;
    const pct = Math.min(100, Math.round(q.fraction * 100));
    quotaText.textContent = s.hub.mode === "demo" ? "YouTube quota: untouched in demo" : `YouTube quota: ${pct}% used today`;
    meterBar.style.width = `${s.hub.mode === "demo" ? 0 : pct}%`;
    meter.classList.toggle("hot", pct >= 75);
    const badge = counts.get("moderation")!;
    badge.hidden = s.pending === 0;
    badge.textContent = String(s.pending);
    tabBadge.hidden = s.pending === 0;
    tabBadge.textContent = String(s.pending);
    const unread = s.notifications_unread ?? 0;           // notifications are their own count, separate from moderation
    bellBadge.hidden = unread === 0;
    bellBadge.textContent = unread > 99 ? "99+" : String(unread);
    const nb = counts.get("notifications");
    if (nb) { nb.hidden = unread === 0; nb.textContent = String(unread); }
  }));
  // The active mode changed (here, on another device, or from the Demo page): redraw the current page from scratch
  // so nothing from the previous mode stays on screen.
  offs.push(onModeChange(() => render()));
  offs.push(feed.onConnection((up) => {
    connText.textContent = up ? "Live feed: connected" : "Live feed: reconnecting";
    mount(connIcon, icon(up ? "wifi" : "wifiOff", 16));
    connChip.classList.toggle("down", !up);
    mount(connChip, icon(up ? "wifi" : "wifiOff", 16), h("span", { class: "txt" }, up ? "Live" : "Reconnecting"));
  }));
  for (const t of ["mode", "stream", "mod_pending", "mod_resolved", "notification"]) offs.push(feed.on(t, () => void refreshStatus()));
  offs.push(installShortcuts(ctx));

  render();
  void refreshStatus();
  statusTimer = window.setInterval(() => void refreshStatus(), 15000);
  feed.start();

  const stopShell = () => {
    cleanup?.();
    cleanup = undefined;
    offs.forEach((f) => f());
    window.onhashchange = null;
  };
  shellCleanup = stopShell;
}

function boot(): void {
  if (!hasToken()) return showLogin();
  showShell();
}

loggedOut.addEventListener("out", () => {
  toast("Your session ended. Sign in again.", "error");
  showLogin();
});

boot();
