import "./styles.css";
import "./redesign.css";
import { ApiError, apiBase, hasToken, loggedOut, post, setApiBase, setToken } from "./api.js";
import { busy, clear, h, mount, sheet, toast } from "./dom.js";
import * as feed from "./events.js";
import { icon, logo } from "./icons.js";
import { refreshStatus, onStatus, type Status } from "./state.js";
import { onNotices, openNotifications, startNotifications, unreadCount } from "./notifications.js";
import { applyTheme, initTheme, installShortcuts, nextTheme, openPalette, setAppContext, themePref, THEME_ICON, type AppContext, type ThemePref } from "./ui.js";
import { APP_VERSION } from "./version.js";
import { desk } from "./pages/desk.js";
import { moderation } from "./pages/moderation.js";
import { commands } from "./pages/commands.js";
import { notebook } from "./pages/notebook.js";
import { community } from "./pages/community.js";
import { insights } from "./pages/insights.js";
import { demo } from "./pages/demo.js";
import { more } from "./pages/more.js";
import { setup } from "./pages/setup.js";
import { settings } from "./pages/settings.js";
import type { Page } from "./pages/types.js";

export { APP_VERSION };

const PAGES: Page[] = [desk, moderation, commands, notebook, community, insights, demo, setup, settings, more];
const NAV_GROUPS: { title: string; ids: string[] }[] = [
  { title: "Operate", ids: ["desk", "moderation", "commands"] },
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

function tallyState(s: Status | null): { state: "live" | "demo" | "standby"; title: string; detail: string } {
  if (!s) return { state: "standby", title: "Connecting", detail: "Waiting for the backend" };
  if (s.hub.mode === "demo") return { state: "demo", title: "Demo", detail: "Simulated chat, nothing is sent" };
  if (s.hub.stream_live) return { state: "live", title: "On air", detail: s.hub.stream_title || "YouTube live chat" };
  return { state: "standby", title: "Standby", detail: s.youtube.connected ? "Waiting for a live stream" : "YouTube not connected" };
}

function signOut(): void {
  setToken("");
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
    setMode: async (mode) => { await post("/api/mode", { mode }); await refreshStatus(); toast(`Switched to ${mode === "demo" ? "Demo" : "Live"} mode`); },
    signOut,
    cycleTheme: () => ctx.setTheme(nextTheme(themePref())),
    setTheme: (p: ThemePref) => { applyTheme(p); syncTheme(); },
  };
  setAppContext(ctx);

  // ----- sidebar (desktop and tablet)
  const STATE_ICON = { demo: "flask", live: "radio", standby: "power" } as const;
  const STATE_TAG = { demo: "Simulated", live: "On air", standby: "Idle" } as const;
  const mcBadge = h("div", { class: "mc-badge", "aria-hidden": "true" }, icon("power", 22));
  const tTitle = h("strong", null, "Connecting");
  const mcTag = h("span", { class: "mc-tag" }, "Idle");
  const tDetail = h("span", { class: "mc-detail" }, "");
  const demoBtn = h("button", { type: "button", "aria-pressed": "false" }, icon("flask", 15), h("span", null, "Demo"));
  const liveBtn = h("button", { type: "button", "aria-pressed": "false" }, icon("radio", 15), h("span", null, "Live"));
  const setMode = (mode: "demo" | "live") => () => busy(mode === "demo" ? demoBtn : liveBtn, () => ctx.setMode(mode));
  demoBtn.onclick = setMode("demo");
  liveBtn.onclick = setMode("live");
  const segment = h("div", { class: "mc-switch", role: "group", "aria-label": "Bot mode" }, demoBtn, liveBtn);
  const tally = h("div", { class: "modecard", "data-state": "standby", role: "status", title: "Bot status" },
    h("div", { class: "mc-head" }, mcBadge, h("div", { class: "mc-text" }, h("div", { class: "mc-title" }, tTitle, mcTag), tDetail)), segment);

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
    tally, nav,
    h("div", { class: "rail-foot" }, h("div", { class: "stat" }, icon("gauge", 16), quotaText), meter, h("div", { class: "stat" }, connIcon, connText), themeBtn, out));

  // ----- top bar
  const tbIco = h("span", { class: "tb-ico", "aria-hidden": "true" }, icon("power", 13));
  const tbTitle = h("span", null, "Connecting");
  const tbDetail = h("span", { class: "muted t-detail" }, "");
  const tbTally = h("button", { class: "tb-tally", type: "button", "data-state": "standby", "aria-label": "Bot mode and status", onclick: () => openModeSheet() }, tbIco, tbTitle, tbDetail);
  const searchBtn = h("button", { class: "search-btn", type: "button", onclick: () => openPalette(ctx), "aria-label": "Search and jump to" },
    icon("search", 18), h("span", { class: "grow" }, "Search pages and actions"), h("kbd", null, "Ctrl K"));
  const connChip = h("span", { class: "conn-chip down", role: "status" }, icon("wifiOff", 16), h("span", { class: "txt" }, "Reconnecting"));
  const bellBadge = h("span", { class: "badge accent", hidden: true }, "0");
  const bell = h("button", { class: "icon-btn", type: "button", "aria-label": "Notifications", "aria-haspopup": "dialog", "aria-expanded": "false", title: "Notifications", onclick: () => openNotifications(bell) }, icon("bell", 20), bellBadge);
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
    h("a", { class: "tab", href: "#/more", id: "tab-more", "data-id": "more" }, icon("menu", 22), "More"));
  const moreTab = tabbar.querySelector("#tab-more") as HTMLElement;

  const content = h("main", { class: "main", id: "content", tabindex: -1 });
  const skip = h("a", { class: "skip", href: "#content", onclick: (e: Event) => { e.preventDefault(); content.focus(); } }, "Skip to content");
  mount(root, skip, h("div", { class: "app" }, rail, h("div", { class: "stage" }, topbar, content)), tabbar);

  // ----- sheets
  function modeCards(close: () => void): HTMLElement {
    const mk = (mode: "demo" | "live", ic: string, title: string, text: string) => {
      const b = h("button", { class: "mode-card", type: "button", "aria-pressed": String(currentMode() === mode) }, icon(ic, 22), h("strong", null, title), h("span", null, text));
      b.onclick = () => busy(b as HTMLButtonElement, async () => { await ctx.setMode(mode); close(); });
      return b;
    };
    return h("div", { class: "mode-cards", style: "grid-template-columns:1fr" },
      mk("demo", "flask", "Demo", "Simulated chat. Nothing is sent to YouTube or Telegram and no quota is used."),
      mk("live", "zap", "Live", "Real YouTube chat. The bot attaches when your stream starts."));
  }
  function openModeSheet(): void {
    const holder: { close: () => void } = { close: () => undefined };
    const t = tallyState(lastStatus);
    holder.close = sheet("Bot mode", h("div", { class: "stack" }, h("div", { class: "banner" }, icon("info", 18), h("span", null, `${t.title}: ${t.detail}`)), modeCards(() => holder.close()))).close;
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
    // More stays lit for every page that lives behind it (Notebook, Community, Setup and so on)
    if (TAB_IDS.includes(page.id)) moreTab.removeAttribute("aria-current"); else moreTab.setAttribute("aria-current", "page");
    document.title = `${page.title} · SavahBot`;
    clear(content);
    cleanup = page.render(content, query);
    if (lastId && lastId !== page.id) window.scrollTo(0, 0);
    lastId = page.id;
  };
  window.onhashchange = render;

  // ----- theme icon sync
  function syncTheme(): void {
    const p = themePref();
    mount(themeIcon, icon(THEME_ICON[p], 18));
    themeText.textContent = `Theme: ${p === "system" ? "auto" : p}`;
  }
  syncTheme();

  // ----- live status
  let lastStatus: Status | null = null;
  let shownMode: string | null = null;
  const currentMode = () => lastStatus?.hub.mode ?? "demo";
  offs.push(onStatus((s) => {
    lastStatus = s;
    const t = tallyState(s);
    tally.setAttribute("data-state", t.state);
    tbTally.setAttribute("data-state", t.state);
    mount(mcBadge, icon(STATE_ICON[t.state], 22));
    mount(tbIco, icon(STATE_ICON[t.state], 13));
    mcTag.textContent = STATE_TAG[t.state];
    tTitle.textContent = t.title;
    tDetail.textContent = t.detail;
    tbTitle.textContent = t.title;
    tbDetail.textContent = t.detail;
    demoBtn.setAttribute("aria-pressed", String(s.hub.mode === "demo"));
    liveBtn.setAttribute("aria-pressed", String(s.hub.mode === "live"));
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
    // the pages were drawn for the previous mode: draw them again so Demo and Live never show each other's data
    if (shownMode && shownMode !== s.hub.mode) render();
    shownMode = s.hub.mode;
  }));
  offs.push(feed.onConnection((up) => {
    connText.textContent = up ? "Live feed: connected" : "Live feed: reconnecting";
    mount(connIcon, icon(up ? "wifi" : "wifiOff", 16));
    connChip.classList.toggle("down", !up);
    mount(connChip, icon(up ? "wifi" : "wifiOff", 16), h("span", { class: "txt" }, up ? "Live" : "Reconnecting"));
  }));
  for (const t of ["mode", "stream", "mod_pending", "mod_resolved"]) offs.push(feed.on(t, () => void refreshStatus()));
  const syncBell = () => {
    const n = unreadCount();
    bellBadge.hidden = n === 0;
    bellBadge.textContent = n > 9 ? "9+" : String(n);
    bell.setAttribute("aria-label", n ? `Notifications, ${n} unread` : "Notifications");
  };
  offs.push(onNotices(syncBell));
  syncBell();
  offs.push(startNotifications(() => lastStatus));
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
