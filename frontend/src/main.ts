import "./styles.css";
import "./redesign.css";
import "./manage.css";
import "./knowledge.css";
import "./appearance.css";
import "./polish.css";
import "./desktop.css";
import "./layout.css";
import "./moderation.css";
import "./chat-zoom.css";
import "./streams.css";
import "./fixed.css";
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
import { initPWA, mountInstallButton, nudgeInstall } from "./pwa.js";
import { onSaved } from "./offline.js";
import { onOutbox } from "./outbox.js";
import { setBadge, startBridge } from "./swbridge.js";
import { desk } from "./pages/desk.js";
import { type LoginReply, passkeyFirst, secondStep } from "./login-flow.js";
import { variables } from "./pages/variables.js";
import { listenForTaps, resumePush } from "./push.js";
import { loadLayouts } from "./layout.js";
import { more } from "./pages/more.js";
import { open as openLink, share } from "./pages/share.js";
import { setup } from "./pages/setup.js";
import { lazyPage, preloadPages } from "./pages/lazy.js";
import type { Page } from "./pages/types.js";
import { current, navigate, onRoute, startRouter } from "./router.js";

export { APP_VERSION };

/** 1.4.11: these pages load the first time they are opened (and are fetched quietly in the background once the app is idle). Their name, icon and blurb stay here. */
const bans = lazyPage({ id: "bans", title: "Enforcement", icon: "ban", blurb: "Lift bans and soften the bot's actions" }, () => import("./pages/bans.js").then((m) => m.bans));
const security = lazyPage({ id: "security", title: "Security", icon: "shield", blurb: "Sign-in methods, devices and lockdown" }, () => import("./pages/security.js").then((m) => m.security));
const notifications = lazyPage({ id: "notifications", title: "Notifications", icon: "bell", blurb: "Push, bell, Telegram, quiet hours and history" }, () => import("./pages/notifications.js").then((m) => m.notifications));
const weather = lazyPage({ id: "weather", title: "Weather", icon: "cloudSun", blurb: "Current weather, hourly and daily forecast" }, () => import("./pages/weather.js").then((m) => m.weather));
const savahlive = lazyPage({ id: "savahlive", title: "SavahLive", icon: "smartphone", blurb: "Pair the Android overlay and choose what it shows" }, () => import("./pages/savahlive.js").then((m) => m.savahlive));
const weatherSettings = lazyPage({ id: "weather-settings", title: "Weather settings", icon: "sliders", blurb: "Places, units, refresh and alerts" }, () => import("./pages/weather-settings.js").then((m) => m.weatherSettings));
const activity = lazyPage({ id: "activity", title: "Activity log", icon: "checklist", blurb: "What changed, by area and importance" }, () => import("./pages/activity.js").then((m) => m.activity));
const streamSettings = lazyPage({ id: "stream-settings", title: "Stream alerts", icon: "radio", blurb: "Live stats, subscribers, members and Super Chats" }, () => import("./pages/stream-settings.js").then((m) => m.streamSettings));
const readerSettings = lazyPage({ id: "reader", title: "Chat reader", icon: "volume", blurb: "Read chat aloud with built-in or neural voices" }, () => import("./pages/reader-settings.js").then((m) => m.readerSettings));
const moderation = lazyPage({ id: "moderation", title: "Moderation", icon: "shield", blurb: "Approvals, history and blocked phrases" }, () => import("./pages/moderation.js").then((m) => m.moderation));
const commands = lazyPage({ id: "commands", title: "Commands", icon: "terminal", blurb: "Commands, auto-replies and timers" }, () => import("./pages/commands.js").then((m) => m.commands));
const notebook = lazyPage({ id: "notebook", title: "Notebook", icon: "notebook", blurb: "Private notes and reminders" }, () => import("./pages/notebook.js").then((m) => m.notebook));
const community = lazyPage({ id: "community", title: "Community", icon: "users", blurb: "Quotes and trusted regulars" }, () => import("./pages/community.js").then((m) => m.community));
const insights = lazyPage({ id: "insights", title: "Insights", icon: "chart", blurb: "Charts of chat and moderation" }, () => import("./pages/insights.js").then((m) => m.insights));
const demo = lazyPage({ id: "demo", title: "Demo", icon: "flask", blurb: "Run simulated chat scenarios" }, () => import("./pages/demo.js").then((m) => m.demo));
const settings = lazyPage({ id: "settings", title: "Settings", icon: "sliders", blurb: "Every option, searchable" }, () => import("./pages/settings.js").then((m) => m.settings));
const backup = lazyPage({ id: "backup", title: "Backup & Recovery", icon: "database", blurb: "Encrypted export and restore" }, () => import("./pages/backup.js").then((m) => m.backup));

const PAGES: Page[] = [desk, moderation, commands, notebook, community, bans, security, notifications, weather, weatherSettings, savahlive, variables, activity, streamSettings, readerSettings, backup, insights, demo, setup, settings, more, share, openLink];
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
  { title: "Studio", ids: ["desk", "moderation", "commands", "insights"] },
  { title: "Manage", ids: ["notebook", "community", "bans", "weather", "savahlive", "demo"] },
  { title: "System", ids: ["notifications", "security", "settings", "backup"] },
];
/** Pages that live under another sidebar item light that item up instead (they are tabs of Settings, or part of Weather). */
const NAV_PARENT: Record<string, string> = { setup: "settings", reader: "settings", "stream-settings": "settings", activity: "settings", variables: "settings", "weather-settings": "weather" };
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
    holder.append(h("button", { class: "lc-link", type: "button", onclick: () => { void import("./pages/backup.js").then((m) => { sheet("Restore from a backup", m.restoreForm({ firstRun: true })); }); } }, icon("upload", 14), "Restore from a backup"));
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

  // ----- 1.4.11: "showing saved data" and "waiting to send" (offline reading and the outbox)
  const ssText = h("span", { class: "ss-text" });
  const ssRetry = h("button", { class: "btn small", type: "button", onclick: () => { feed.retryNow(); void refreshStatus(); } }, icon("refresh", 14), "Try now");
  const strip = h("div", { class: "saved-strip", role: "status", "aria-live": "polite", hidden: true }, icon("wifiOff", 16), ssText, ssRetry);
  let savedAt: number | null = null;
  let waitingToSend = 0;
  const paintStrip = () => {
    const parts: Node[] = [];
    if (savedAt !== null) parts.push(h("strong", null, `Showing saved data from ${new Date(savedAt).toLocaleString([], { hour: "2-digit", minute: "2-digit", month: "short", day: "numeric" })}`), h("span", null, " The server cannot be reached; it reconnects by itself."));
    if (waitingToSend) parts.push(h("span", { style: savedAt !== null ? "display:block" : "" }, waitingToSend === 1 ? "1 thing saved on this device will be sent when you are back online." : `${waitingToSend} things saved on this device will be sent when you are back online.`));
    strip.hidden = parts.length === 0;
    ssRetry.hidden = savedAt === null && !waitingToSend;
    mount(ssText, ...parts);
  };
  offs.push(onSaved((since) => { savedAt = since; paintStrip(); }));
  offs.push(onOutbox((n) => { waitingToSend = n; paintStrip(); }));
  const skip = h("a", { class: "skip", href: "#content", onclick: (e: Event) => { e.preventDefault(); content.focus(); } }, "Skip to content");
  mount(root, skip, h("div", { class: "app" }, rail, h("div", { class: "stage" }, topbar, strip, content)), tabbar);

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
  /** A page that has the Edit layout button opens scrolled just past its button row, so the cards start right under the top bar. Scroll up to reach the button. */
  function tuckHead(el: HTMLElement): void {
    el.classList.remove("peek");
    let tries = 0;
    const attempt = (): void => {
      if (!el.isConnected) return;
      const head = el.querySelector<HTMLElement>(".page-head:not(.bare)");
      const btn = head?.querySelector<HTMLElement>(".layout-btn") ?? null;
      if (head && btn && !btn.hidden) {
        const next = head.nextElementSibling as HTMLElement | null;
        if (next && window.scrollY < 2 && !document.body.classList.contains("arranging")) {
          // scroll until the whole button row is behind the top bar (nothing of the button peeks out), then the cards start right under it
          const bar = document.querySelector<HTMLElement>(".topbar")?.getBoundingClientRect().bottom ?? 0;
          const p = Math.ceil(head.getBoundingClientRect().bottom - bar);
          if (p > 0) { el.style.setProperty("--peek", `${p}px`); el.classList.add("peek"); window.scrollTo(0, p); }
        }
        return;
      }
      if (++tries < 12) window.setTimeout(attempt, 150);
    };
    window.requestAnimationFrame(attempt);
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
    for (const a of navLinks) (a.getAttribute("data-id") === (NAV_PARENT[page.id] ?? page.id) ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
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
    tuckHead(content);
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
    void setBadge(s.pending);                       // 1.4.11: the same number on the app icon
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
  // 1.4.11: the first time a request is decided is the moment the app has proved itself: offer to install it then (once, and only if it makes sense)
  offs.push(feed.on("mod_resolved", (e) => { if (["approved", "executed", "rejected"].includes(String(e.data?.status))) nudgeInstall(); }));
  offs.push(startBridge());
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
  void loadLayouts();                    // so a page can show your arrangement the moment it opens
  offs.push(installShortcuts(ctx));

  render();
  offs.push(preloadPages(PAGES));          // 1.4.11: the other pages are fetched while the app is idle
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
