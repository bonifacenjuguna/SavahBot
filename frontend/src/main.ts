import "./styles.css";
import "./redesign.css";
import "./manage.css";
import "./knowledge.css";
import "./appearance.css";
import "./polish.css";
import "./desktop.css";
import "./moderation.css";
import "./chat-zoom.css";
import "./streams.css";
import { ApiError, apiBase, endSession, get, hasToken, loggedOut, post, setApiBase, setToken } from "./api.js";
import { busy, clear, h, mount, sheet, toast } from "./dom.js";
import * as feed from "./events.js";
import { icon, logo } from "./icons.js";
import { refreshStatus, onStatus, type Status } from "./state.js";
import { resetClock } from "./pages/kit.js";

let resetTimer = 0;
import { installPageNav, trackRecent } from "./nav.js";
import { onNotices, openNotifications, refresh as refreshBell, startNotifications, unreadCount, worstUnread } from "./notifications.js";
import { initAppearance } from "./appearance.js";
import { applyTheme, initTheme, installShortcuts, nextTheme, openPalette, setAppContext, themePref, THEME_ICON, type AppContext, type ThemePref } from "./ui.js";
import { APP_VERSION } from "./version.js";
import { initPWA, mountInstallButton } from "./pwa.js";
import { desk } from "./pages/desk.js";
import { type LoginReply, passkeyFirst, secondStep } from "./login-flow.js";
import { bans } from "./pages/bans.js";
import { backup, restoreForm } from "./pages/backup.js";
import { security } from "./pages/security.js";
import { notifications } from "./pages/notifications.js";
import { weather } from "./pages/weather.js";
import { weatherSettings } from "./pages/weather-settings.js";
import { variables } from "./pages/variables.js";
import { activity } from "./pages/activity.js";
import { streamSettings } from "./pages/stream-settings.js";
import { readerSettings } from "./pages/reader-settings.js";
import { listenForTaps, resumePush } from "./push.js";
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
import { current, navigate, onRoute, startRouter } from "./router.js";

export { APP_VERSION };

const PAGES: Page[] = [desk, moderation, commands, notebook, community, bans, security, notifications, weather, weatherSettings, variables, activity, streamSettings, readerSettings, backup, insights, demo, setup, settings, more];
/** The deliberate 404: an address that is not a page. It is drawn inside the signed-in shell, so nothing is revealed to a signed-out visitor. */
const NOT_FOUND: Page = {
  id: "not-found", title: "Page not found", icon: "alert",
  render(root) {
    mount(root, h("div", { class: "page" }, h("div", { class: "empty" }, icon("alert", 28),
      h("h2", null, "Page not found"),
      h("p", { class: "muted" }, `There is no page at ${location.pathname}.`),
      h("a", { class: "btn primary", href: "/desk" }, "Go to the Desk"))));
  },
};
const NAV_GROUPS: { title: string; ids: string[] }[] = [
  { title: "Operate", ids: ["desk", "moderation", "commands"] },
  { title: "Manage", ids: ["notebook", "community", "bans", "security", "notifications", "weather", "backup", "insights", "demo"] },
  { title: "System", ids: ["setup", "settings"] },
];
const TAB_IDS = ["desk", "moderation", "commands", "insights"];
const root = document.getElementById("app")!;
let statusTimer: number | undefined;
let shellCleanup: (() => void) | null = null;

initTheme();
initAppearance();
initPWA();

/** One address, one page: the router resolves the path; an address that is not a page shows the "not found" page (see render). */
startRouter(PAGES.map((p) => p.id));

function tallyState(s: Status | null): { state: "live" | "demo" | "standby"; title: string; detail: string } {
  if (!s) return { state: "standby", title: "Connecting", detail: "Waiting for the backend" };
  if (s.hub.mode === "demo") return { state: "demo", title: "Demo", detail: "Simulated chat, nothing is sent" };
  if (s.hub.stream_live) return { state: "live", title: "On air", detail: s.hub.stream_title || "YouTube live chat" };
  return { state: "standby", title: "Standby", detail: s.youtube.connected ? "Waiting for a live stream" : "YouTube not connected" };
}

function signOut(): void {
  endSession();       // closes the session on the server too, not just here
  showLogin();
}

// ------------------------------------------------------------------------------------------------ login
/** On a brand-new deployment the server prints a one-time token; this lets you restore a backup before signing in. */
function restoreLink(): HTMLElement | null {
  if (!apiBase()) return null;
  const holder = h("div", null);
  void get<{ available: boolean }>("/api/backup/first-run").then((r) => {
    if (!r.available) return;
    holder.append(h("button", { class: "lc-link", type: "button", onclick: () => { sheet("Restore from a backup", restoreForm({ firstRun: true })); } }, icon("upload", 14), "Restore from a backup"));
  }).catch(() => undefined);
  return holder;
}

function showLogin(): void {
  shellCleanup?.();
  shellCleanup = null;
  feed.stop();
  window.clearInterval(statusTimer);
  const needsBase = !apiBase();
  const pass = h("input", { type: "password", autocomplete: "current-password", required: true, id: "pw", placeholder: "Enter your password", autocapitalize: "off", spellcheck: false });
  // The server address is never printed on this page. It is asked for only when none is set, or after "Connection settings".
  const base = h("input", { type: "url", placeholder: "https://your-server.example", value: "", id: "base", autocomplete: "off", autocapitalize: "off", spellcheck: false, required: needsBase });
  const err = h("p", { class: "lc-err", role: "alert" });
  const eye = h("button", { class: "lc-eye", type: "button", "aria-label": "Show password", "aria-pressed": "false", onclick: () => {
    const show = pass.type === "password";
    pass.type = show ? "text" : "password";
    eye.setAttribute("aria-pressed", String(show));
    eye.setAttribute("aria-label", show ? "Hide password" : "Show password");
    eye.replaceChildren(icon(show ? "eyeOff" : "eye", 18));
    pass.focus();
  } }, icon("eye", 18));
  const btn = h("button", { class: "btn primary lc-btn", type: "submit" }, icon("lock", 16), "Sign in");
  const connBox = h("div", { class: "lc-conn", hidden: !needsBase },
    h("label", { class: "lc-field" }, h("span", null, "Server address"), h("span", { class: "lc-input plain" }, base)),
    needsBase ? null : h("small", null, "Leave empty to keep the current connection."));
  const connLink = needsBase ? null : h("button", { class: "lc-link", type: "button", "aria-expanded": "false", onclick: () => {
    const open = connBox.hidden;
    connBox.hidden = !open;
    connLink!.setAttribute("aria-expanded", String(open));
    if (open) base.focus();
  } }, icon("sliders", 14), "Connection settings");
  const pane = h("div", { class: "login-pane" });
  const finish = (r: LoginReply): void => {
    if (r.token) {
      setToken(r.token);
      navigate(r.lockdown ? "/security" : "/desk");   // a fresh sign-in always starts on the Desk, never on the page you left
      boot();
      if (!r.lockdown && r.setup_needed) window.setTimeout(() => toast("Only your password protects this dashboard. Add a passkey or an authenticator app on the Security page."), 1200);
    } else if (r.step === "more") pane.replaceChildren(secondStep(r, finish, showLogin));
  };
  const setBusy = (on: boolean) => { btn.disabled = on; btn.replaceChildren(...(on ? [h("span", { class: "spin" }), "Signing in"] : [icon("lock", 16), "Sign in"])); };
  const form = h(
    "form",
    {
      class: "login-card",
      novalidate: false,
      onsubmit: (e: Event) => {
        e.preventDefault();
        err.textContent = "";
        if (base.value.trim()) setApiBase(base.value);
        setBusy(true);
        post<LoginReply>("/api/auth/login", { password: pass.value })
          .then((r) => finish(r))
          .catch((ex) => { err.textContent = ex instanceof ApiError && ex.status === 401 ? "That password is not right. Try again." : ex instanceof ApiError ? ex.message : "Could not reach the server. Check your connection."; pass.select(); })
          .finally(() => setBusy(false));
      },
    },
    h("div", { class: "lc-top" },
      h("div", { class: "lc-logo" }, logo(36)),
      h("div", null, h("h1", null, "Welcome back"), h("p", null, "Sign in to your SavahBot dashboard"))),
    h("label", { class: "lc-field" }, h("span", null, "Password"), h("span", { class: "lc-input" }, icon("lock", 18), pass, eye)),
    needsBase ? connBox : null,
    err,
    btn,
    passkeyFirst(finish, (m) => { err.textContent = m; }),
    connLink,
    needsBase ? null : connBox,
    restoreLink(),
    h("p", { class: "lc-foot" }, icon("shield", 13), `Private, owner access only \u00b7 v${APP_VERSION}`),
  );
  const hero = h("aside", { class: "login-hero", "aria-hidden": "false" },
    h("div", { class: "mark" }, logo(36), "SavahBot"),
    h("div", null,
      h("h2", null, "Your chat, under control."),
      h("p", null, "Private moderation for your live chat, with a clear reason behind every decision."),
      h("ul", { class: "login-points" },
        [["shield", "Every moderation decision explains itself"], ["flask", "Practice safely in demo mode"], ["chart", "Live view of chat activity"]]
          .map(([i, t]) => h("li", null, icon(i, 20), h("span", null, t))))),
    h("small", null, "Owner access only"));
  mount(root, h("main", { class: "login" }, h("div", { class: "login-bg", "aria-hidden": "true" }), hero, pane));
  pane.replaceChildren(form);
  pass.focus({ preventScroll: true });
}

// ------------------------------------------------------------------------------------------------ new version
/** The file names of the scripts this page was loaded with, e.g. /assets/index-3f9a.js. A new deployment changes them. */
const scriptsNow = (): string => Array.from(document.querySelectorAll("script[src]")).map((e) => e.getAttribute("src")).filter((x) => x && x.includes("assets/")).sort().join(",");
const loadedWith = scriptsNow();
let checking = false;

/** After an outage, see whether the dashboard itself was updated while you were away. If so the page reloads (your sign-in is kept), instead of you having to refresh. */
async function checkForNewVersion(): Promise<void> {
  if (checking || !loadedWith) return;
  checking = true;
  try {
    const html = await (await fetch(`${location.pathname}?v=${Date.now()}`, { cache: "no-store" })).text();
    const next = Array.from(html.matchAll(/<script[^>]+src="([^"]+)"/g)).map((m) => m[1]).filter((x) => x.includes("assets/")).sort().join(",");
    if (!next || next === loadedWith) return;
    const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (document.hidden || !typing) { toast("Dashboard updated. Reloading…"); window.setTimeout(() => location.reload(), 900); }
    else toast("A new version of the dashboard is ready. Reload when you are done typing.");
  } catch { /* offline again: the next reconnect checks again */ } finally { checking = false; }
}

// ------------------------------------------------------------------------------------------------ shell
function showShell(): void {
  shellCleanup?.();
  const offs: (() => void)[] = [];

  // ----- shared actions
  const ctx: AppContext = {
    pages: PAGES,
    go: (id) => { navigate(`/${id}`); },
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
        const a = h("a", { href: `/${p.id}`, "data-id": p.id, title: p.title }, icon(p.icon, 20), h("span", { class: "label" }, p.title), badge);
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
  const railFoot = h("div", { class: "rail-foot" }, h("div", { class: "stat" }, icon("gauge", 16), quotaText), meter, h("div", { class: "stat" }, connIcon, connText), themeBtn, out);
  offs.push(mountInstallButton(railFoot, themeBtn)); // 1.1.9: "Install app", shown only while installing makes sense
  const rail = h("aside", { class: "rail" },
    h("div", { class: "rail-brand" }, logo(30), h("span", { class: "brand" }, "SavahBot"), verTag),
    tally, nav,
    railFoot);

  // ----- top bar
  const tbIco = h("span", { class: "tb-ico", "aria-hidden": "true" }, icon("power", 13));
  const tbTitle = h("span", null, "Connecting");
  const tbDetail = h("span", { class: "muted t-detail" }, "");
  const tbTally = h("button", { class: "tb-tally", type: "button", "data-state": "standby", "aria-label": "Bot mode and status", onclick: () => openModeSheet() }, tbIco, tbTitle, tbDetail);
  const searchBtn = h("button", { class: "search-btn", type: "button", onclick: () => openPalette(ctx), "aria-label": "Search and jump to" },
    icon("search", 18), h("span", { class: "grow" }, "Search pages and actions"), h("kbd", null, "Ctrl K"));
  const connChip = h("button", { class: "conn-chip down", "data-state": "retry", type: "button", role: "status", title: "The live feed is down. Tap to try again now.", onclick: () => { feed.retryNow(); void refreshStatus(); } }, icon("wifiOff", 16), h("span", { class: "txt" }, "Reconnecting"));
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
      const a = h("a", { class: "tab", href: `/${p.id}`, "data-id": p.id }, icon(p.icon, 22), p.title, id === "moderation" ? tabBadge : null);
      tabLinks.push(a);
      return a;
    }),
    h("a", { class: "tab", href: "/more", id: "tab-more", "data-id": "more" }, icon("menu", 22), "More"));
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
  let cleanupNav: (() => void) | undefined;
  let lastId = "";
  const render = () => {
    cleanup?.();
    const where = current();
    const query = where.query;
    const page = PAGES.find((p) => p.id === where.id) ?? (where.notFound ? NOT_FOUND : PAGES[0]);
    for (const a of navLinks) (a.getAttribute("data-id") === page.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    for (const a of tabLinks) (a.getAttribute("data-id") === page.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    // More stays lit for every page that lives behind it (Notebook, Community, Setup and so on)
    if (TAB_IDS.includes(page.id) || page === NOT_FOUND) moreTab.removeAttribute("aria-current"); else moreTab.setAttribute("aria-current", "page");
    document.title = `${page.title} · SavahBot`;
    clear(content);
    cleanupNav?.();
    if (page !== NOT_FOUND) trackRecent(page.id);
    cleanup = page.render(content, query);
    cleanupNav = installPageNav(content);
    if (lastId && lastId !== page.id) window.scrollTo(0, 0);
    lastId = page.id;
  };
  offs.push(onRoute(render));

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
    const rc = resetClock(q.resets_at, s.timezone);
    meter.title = rc && s.hub.mode !== "demo" ? `YouTube API quota used today. It resets at ${rc.clock} ${rc.place} time, which is midnight Pacific.` : "YouTube API quota used today";
    // Refresh the moment the reset passes, so the number drops to 0 without waiting for the next poll.
    window.clearTimeout(resetTimer);
    if (q.resets_at) resetTimer = window.setTimeout(() => void refreshStatus(), Math.max(1000, (q.resets_at - Date.now() / 1000) * 1000 + 2000));
    meter.classList.toggle("hot", pct >= 75);
    const badge = counts.get("moderation")!;
    badge.hidden = s.pending === 0;
    badge.textContent = String(s.pending);
    tabBadge.hidden = s.pending === 0;
    tabBadge.textContent = s.pending > 99 ? "99+" : String(s.pending);
    // the pages were drawn for the previous mode: draw them again so Demo and Live never show each other's data
    if (shownMode && shownMode !== s.hub.mode) render();
    shownMode = s.hub.mode;
  }));
  /** Says what is wrong in plain words: no internet at all, or the server is not answering (it may be restarting). */
  const paintConn = () => {
    const up = feed.connected;
    const offline = typeof navigator !== "undefined" && navigator.onLine === false;
    const word = up ? "Live" : offline ? "Offline" : feed.attempts > 2 ? `Reconnecting (${feed.attempts})` : "Reconnecting";
    connText.textContent = up ? "Live feed: connected" : offline ? "Live feed: no internet" : "Live feed: reconnecting";
    mount(connIcon, icon(up ? "wifi" : "wifiOff", 16));
    connChip.classList.toggle("down", !up);
    connChip.dataset.state = up ? "live" : offline ? "offline" : "retry";     // the look follows this; the behaviour is unchanged
    mount(connChip, icon(up ? "wifi" : "wifiOff", 16), h("span", { class: "txt" }, word));
    connChip.title = up ? "The live feed is connected." : offline ? "This device has no internet. It reconnects by itself when it is back." : "The server is not answering. It reconnects by itself. Tap to try again now.";
  };
  offs.push(feed.onConnection(() => paintConn()));
  const connTick = window.setInterval(() => { if (!feed.connected) paintConn(); }, 2000);     // the attempt count moves while it is down
  offs.push(() => window.clearInterval(connTick));
  const onNet = () => { paintConn(); if (navigator.onLine) { feed.retryNow(); void refreshStatus(); } };
  window.addEventListener("online", onNet);
  window.addEventListener("offline", onNet);
  offs.push(() => { window.removeEventListener("online", onNet); window.removeEventListener("offline", onNet); });
  // Back after an outage: refresh the status, and redraw the page you are on so it shows what it missed (the Desk catches up by itself, without a redraw).
  offs.push(feed.onReconnect((downMs) => {
    void refreshStatus();
    void refreshBell();
    const busyNow = document.querySelector(".sheet, .popover, .palette") || (document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) && content.contains(document.activeElement));
    if (downMs >= 4000 && current().id !== "desk" && !busyNow) render();
    void checkForNewVersion();
  }));
  for (const t of ["mode", "stream", "mod_pending", "mod_resolved"]) offs.push(feed.on(t, () => void refreshStatus()));
  const syncBell = () => {
    const n = unreadCount();
    bellBadge.hidden = n === 0;
    const text = n > 99 ? "99+" : String(n);
    if (bellBadge.textContent !== text) { bellBadge.textContent = text; bellBadge.classList.remove("pop"); void bellBadge.offsetWidth; bellBadge.classList.add("pop"); }
    bellBadge.dataset.tone = worstUnread();
    bell.setAttribute("aria-label", n ? `Notifications, ${n} unread` : "Notifications");
  };
  offs.push(onNotices(syncBell));
  syncBell();
  offs.push(startNotifications(() => lastStatus));
  offs.push(listenForTaps((route) => { navigate(route); }, () => void refreshBell(), () => void resumePush()));
  void resumePush();
  offs.push(installShortcuts(ctx));

  render();
  void refreshStatus();
  statusTimer = window.setInterval(() => void refreshStatus(), 15000);
  feed.start();

  const stopShell = () => {
    cleanup?.();
    cleanup = undefined;
    offs.forEach((f) => f());
  };
  shellCleanup = stopShell;
}

function boot(): void {
  if (!hasToken()) return showLogin();
  showShell();
}

loggedOut.addEventListener("out", () => {
  if (!shellCleanup) return;      // already on the sign-in screen (several requests can fail at once): one notice, one redraw
  showLogin();                    // first: tears the shell down, so changing the address below does not redraw a page that would only fail again
  navigate("/desk", { replace: true });
  toast("Your session ended. Sign in again.", "error");
});

boot();
