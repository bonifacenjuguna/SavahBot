/**
 * Progressive Web App support (1.1.9): install detection, the install banner, iOS guidance, dismissal memory and service worker registration.
 *
 * Call `initPWA()` once at start-up. It registers every listener exactly once and returns a cleanup function; calling it again is harmless.
 *
 * Rules this module keeps:
 *  - The browser's own install prompt is only ever shown after the person presses an Install button. It is never triggered automatically.
 *  - Nothing is shown on the sign-in screen, while a dialog is open, or while the tab is in the background.
 *  - "Not now" is remembered with a growing cooldown (3, 14, then 60 days). It never switches the offer off for good, and the install
 *    entries (sidebar button, More page, command palette) stay available.
 *  - Nothing sensitive is stored here: only the dismissal count and time, under one localStorage key.
 */
import "./pwa.css";
import { hasToken } from "./api.js";
import { copyButton, h, sheet, toast } from "./dom.js";
import { icon } from "./icons.js";

// ------------------------------------------------------------------------------------------------ types
/** Chromium's install event. It is not in TypeScript's DOM types. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

/**
 * How this browser can install the app right now.
 *  native      the browser gave us its install prompt and we are holding it until the person asks
 *  ios         iPhone or iPad: no prompt exists, so we show Share menu steps
 *  safari-mac  Safari 17+ on a Mac: File, Add to Dock
 *  manual      a browser that can install but has no prompt to give us (the person used the menu, or the event was already used)
 *  none        this browser cannot install web apps, or the app is already installed
 */
export type InstallMode = "native" | "ios" | "safari-mac" | "manual" | "none";

export interface PWAState {
  /** Running as an installed app (own window, no browser bars). */
  standalone: boolean;
  /** Standalone, or the browser reported that it installed the app. */
  installed: boolean;
  mode: InstallMode;
  /** The native prompt is in hand and can be opened with one press. */
  canPrompt: boolean;
  /** An install entry (sidebar button, More tile, palette action) should be offered. */
  entry: boolean;
  /** Short label for that entry. */
  label: string;
  /** One line that says what pressing it does. */
  hint: string;
  /** The install banner is on screen. */
  banner: boolean;
  /** The browser accepted the install and is finishing it. */
  installing: boolean;
}

type GuideKind = "ios-safari" | "ios-browser" | "ios-open-safari" | "safari-mac" | "chromium" | "android-menu";

interface Env {
  ios: boolean;
  iosThirdPartyOk: boolean;
  iosBrowser: string;
  inApp: boolean;
  android: boolean;
  safariMac: boolean;
  edge: boolean;
  coarse: boolean;
}

interface Saved {
  /** When the banner or the native prompt was last dismissed (ms), and how many times in total. */
  dismissedAt: number;
  dismissals: number;
  /** When the browser accepted the install, the app reported itself installed, or the person said they added it (ms). */
  installedAt: number;
}

// ------------------------------------------------------------------------------------------------ constants
const KEY = "savahbot.pwa";
const SHOWN_KEY = "savahbot.pwa.shown";
const DAY = 86_400_000;
const COOLDOWN_DAYS = [3, 14, 60];
/** Wait this long after the dashboard appears before offering anything, so the person can get their bearings first. */
const FIRST_OFFER_DELAY = 6000;
const RETRY_MS = 4000;
const INSTALL_SETTLE_MS = 15000;
const STANDALONE_QUERIES = ["(display-mode: standalone)", "(display-mode: minimal-ui)", "(display-mode: window-controls-overlay)"];

// ------------------------------------------------------------------------------------------------ environment
let envCache: Env | null = null;

function detectEnv(): Env {
  if (envCache) return envCache;
  const ua = navigator.userAgent || "";
  // iPadOS 13+ reports itself as a Mac; a Mac with a touch screen is an iPad.
  const ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const android = /Android/i.test(ua);
  const ver = /OS (\d+)[_.](\d+)/.exec(ua);
  const major = ver ? Number(ver[1]) : 0;
  const minor = ver ? Number(ver[2]) : 0;
  // Other iOS browsers can add to the Home Screen from iOS 16.4. An unknown version (iPad reporting as a Mac) is treated as recent.
  const iosThirdPartyOk = !ver || major > 16 || (major === 16 && minor >= 4);
  let iosBrowser = "Safari";
  if (/CriOS/.test(ua)) iosBrowser = "Chrome";
  else if (/FxiOS/.test(ua)) iosBrowser = "Firefox";
  else if (/EdgiOS/.test(ua)) iosBrowser = "Edge";
  else if (/OPiOS|OPT\//.test(ua)) iosBrowser = "Opera";
  else if (/DuckDuckGo/.test(ua)) iosBrowser = "DuckDuckGo";
  else if (!/Safari\//.test(ua)) iosBrowser = "";
  const webview = (ios && iosBrowser === "") || (android && /; wv\)/.test(ua));
  const inApp = webview || /FBAN|FBAV|FB_IAB|Instagram|Line\/|MicroMessenger|Snapchat|TikTok|musical_ly|Twitter|LinkedInApp|Pinterest|GSA\//.test(ua);
  const v = /Version\/(\d+)/.exec(ua);
  const safariMac = !ios && !android && /Safari\//.test(ua) && !/Chrome|Chromium|Edg|OPR|Firefox|FxiOS/.test(ua) && !!v && Number(v[1]) >= 17;
  envCache = {
    ios, iosThirdPartyOk, iosBrowser, inApp, android, safariMac,
    edge: /Edg\//.test(ua),
    coarse: typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches,
  };
  return envCache;
}

/** True when the browser fires `beforeinstallprompt` at all (Chrome, Edge, Samsung Internet, Opera and other Chromium browsers). */
function promptCapable(): boolean {
  return "onbeforeinstallprompt" in window;
}

/** Standalone detection: the display-mode media queries, iOS's navigator.standalone, and an Android TWA launch. */
function detectStandalone(): boolean {
  try {
    if (typeof matchMedia === "function" && STANDALONE_QUERIES.some((q) => matchMedia(q).matches)) return true;
  } catch { /* an old engine without display-mode */ }
  if ((navigator as Navigator & { standalone?: boolean }).standalone === true) return true;
  return document.referrer.startsWith("android-app://");
}

// ------------------------------------------------------------------------------------------------ persistence
let memory: Saved = { dismissedAt: 0, dismissals: 0, installedAt: 0 };

function clean(raw: unknown): Saved {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const num = (v: unknown, max: number) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.min(v, max) : 0);
  return { dismissedAt: num(o.dismissedAt, 8.64e15), dismissals: Math.floor(num(o.dismissals, 99)), installedAt: num(o.installedAt, 8.64e15) };
}

function load(): Saved {
  try {
    const raw = localStorage.getItem(KEY);
    memory = clean(raw ? JSON.parse(raw) : null);
  } catch { /* private mode or damaged value: keep what we have in memory */ }
  return memory;
}

function save(patch: Partial<Saved>): Saved {
  memory = { ...memory, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(memory)); } catch { /* private mode: the choice lasts for this visit only */ }
  return memory;
}

let shownMemory = false;
function shownThisSession(): boolean {
  try { return sessionStorage.getItem(SHOWN_KEY) === "1" || shownMemory; } catch { return shownMemory; }
}
function markShown(): void {
  shownMemory = true;
  try { sessionStorage.setItem(SHOWN_KEY, "1"); } catch { /* memory flag covers it */ }
}

function cooldownOver(): boolean {
  if (!memory.dismissals) return true;
  const days = COOLDOWN_DAYS[Math.min(memory.dismissals, COOLDOWN_DAYS.length) - 1];
  const since = Date.now() - memory.dismissedAt;
  if (since < -DAY) return true; // a clock that was set far ahead must not silence the offer for years
  return since >= days * DAY;
}

// ------------------------------------------------------------------------------------------------ live state
let deferred: BeforeInstallPromptEvent | null = null;
let standalone = false;
let shellUp = false;
let shellSince = 0;
let prompting = false;
let installing = false;
let banner: HTMLElement | null = null;
let guide: { close: () => void } | null = null;
let offerTimer = 0;
let settleTimer = 0;
const subs = new Set<(s: PWAState) => void>();

const BANNER_MODES: ReadonlySet<InstallMode> = new Set<InstallMode>(["native", "ios", "safari-mac"]);

function mode(): InstallMode {
  if (standalone) return "none";
  const env = detectEnv();
  if (deferred) return "native";
  if (env.ios) return "ios";
  if (env.safariMac) return "safari-mac";
  if (env.inApp) return "none";
  // A browser with a prompt that has none for us right now: offer the menu steps only after we know the app can be installed here
  // (the person turned the offer down, or already used the event), and not when it has been installed.
  if (promptCapable()) return memory.dismissals > 0 && !memory.installedAt ? "manual" : "none";
  // Android browsers without the event (Firefox, for one) still install from their menu.
  if (env.android) return "manual";
  return "none";
}

function guideKind(): GuideKind | null {
  const env = detectEnv();
  if (env.ios) {
    if (env.inApp) return "ios-open-safari";
    if (env.iosBrowser === "Safari") return "ios-safari";
    return env.iosThirdPartyOk ? "ios-browser" : "ios-open-safari";
  }
  if (env.safariMac) return "safari-mac";
  if (env.android) return "android-menu";
  return promptCapable() ? "chromium" : null;
}

export function getPWAState(): PWAState {
  const m = mode();
  const entry = m !== "none";
  const label = m === "ios" ? "Add to Home Screen" : m === "safari-mac" ? "Add to Dock" : "Install app";
  const hint = m === "native" ? "Open SavahBot in its own window, one tap away" : m === "none" ? "" : "Step by step instructions for this browser";
  return { standalone, installed: standalone || (memory.installedAt > 0 && !deferred), mode: m, canPrompt: !!deferred, entry, label, hint, banner: !!banner, installing };
}

function emit(): void {
  const s = getPWAState();
  document.documentElement.dataset.display = s.standalone ? "standalone" : "browser";
  subs.forEach((f) => f(s));
}

/** Subscribe to install state changes. The callback runs once straight away. Returns an unsubscribe function. */
export function onPWAState(fn: (s: PWAState) => void): () => void {
  subs.add(fn);
  fn(getPWAState());
  return () => { subs.delete(fn); };
}

// ------------------------------------------------------------------------------------------------ when to offer
function modalOpen(): boolean {
  return document.body.classList.contains("no-scroll") || !!document.querySelector(".overlay");
}

function wantBanner(): boolean {
  const m = mode();
  return shellUp && !standalone && !installing && BANNER_MODES.has(m) && !(m === "ios" && detectEnv().inApp)
    && !memory.installedAt && cooldownOver() && !shownThisSession();
}

/** Decides whether the banner should appear, and when. Safe to call as often as needed: there is only ever one timer. */
function schedule(): void {
  window.clearTimeout(offerTimer);
  offerTimer = 0;
  if (banner || !wantBanner()) return;
  const wait = Math.max(0, FIRST_OFFER_DELAY - (Date.now() - shellSince));
  offerTimer = window.setTimeout(() => {
    offerTimer = 0;
    if (banner || !wantBanner()) return;
    // not while a dialog is open or the tab is in the background: try again shortly
    if (document.visibilityState !== "visible" || modalOpen()) { offerTimer = window.setTimeout(schedule, RETRY_MS); return; }
    showBanner();
  }, wait);
}

// ------------------------------------------------------------------------------------------------ banner
function liftToasts(on: boolean): void {
  const root = document.documentElement;
  if (!on || !banner) { root.style.removeProperty("--pwa-offset"); return; }
  root.style.setProperty("--pwa-offset", `${Math.ceil(banner.getBoundingClientRect().height) + 12}px`);
}

function removeBanner(animate = true): void {
  const el = banner;
  banner = null;
  liftToasts(false);
  if (!el) return;
  if (animate && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.classList.add("leaving");
    window.setTimeout(() => el.remove(), 220);
  } else el.remove();
  emit();
}

function showBanner(): void {
  // never two at once, even if a hot reload left an old one behind
  document.querySelectorAll("[data-pwa-banner]").forEach((n) => n.remove());
  const s = getPWAState();
  const env = detectEnv();
  const native = s.mode === "native";
  const where = env.coarse ? "your home screen" : "your desktop";
  const title = s.mode === "ios" ? "Add SavahBot to your Home Screen" : s.mode === "safari-mac" ? "Add SavahBot to your Dock" : "Install SavahBot";
  const text = native
    ? `Open the dashboard from ${where} in its own window, with no browser bars in the way.`
    : s.mode === "safari-mac" ? "Keep the dashboard one click away in its own window." : "Open the dashboard full screen from your Home Screen, like any other app.";
  const perks: [string, string][] = [["zap", "One tap to open"], ["sidebar", "Its own window"], ["eye", "No browser clutter"]];

  const go = h("button", { class: "btn primary", type: "button", onclick: () => void installApp() },
    icon(native ? "download" : "arrowRight", 16), native ? "Install" : "Show me how");
  const later = h("button", { class: "btn ghost", type: "button", onclick: () => dismissBanner() }, "Not now");
  const titleId = "pwa-title";
  const el = h("aside", { class: "pwa-card", "data-pwa-banner": "", "data-mode": s.mode, role: "region", "aria-labelledby": titleId, onkeydown: (e: KeyboardEvent) => { if (e.key === "Escape") dismissBanner(); } },
    h("img", { class: "pwa-icon", src: "/icon-192.png", alt: "", width: 48, height: 48, decoding: "async" }),
    h("div", { class: "pwa-body" },
      h("strong", { class: "pwa-title", id: titleId }, title),
      h("p", { class: "pwa-text" }, text),
      h("ul", { class: "pwa-perks" }, perks.map(([i, t]) => h("li", null, icon(i, 14), t)))),
    h("div", { class: "pwa-actions" }, go, later));
  banner = el;
  document.body.appendChild(el);
  markShown();
  liftToasts(true);
  emit();
}

function dismissBanner(): void {
  recordDismissal();
  removeBanner();
  const where = matchMedia("(max-width: 719px)").matches ? "the More page" : "the sidebar";
  if (getPWAState().entry) toast(`No problem. You can install SavahBot any time from ${where}.`);
}

function recordDismissal(): void {
  save({ dismissedAt: Date.now(), dismissals: Math.min(99, memory.dismissals + 1) });
}

// ------------------------------------------------------------------------------------------------ installing
/** Opens the install flow. Must be called from a click or key press. Uses the native prompt when we hold it, the steps otherwise. */
export async function installApp(): Promise<void> {
  if (standalone || prompting) return;
  const event = deferred;
  if (!event) { openInstallGuide(); return; }
  prompting = true;
  deferred = null; // the event can be used once; a fresh one arrives later if the person says no
  emit();
  try {
    await event.prompt();
    const choice = await event.userChoice;
    if (choice.outcome === "accepted") {
      installing = true;
      save({ installedAt: Date.now() });
      removeBanner();
      toast("Installing SavahBot…");
      window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(() => { installing = false; emit(); }, INSTALL_SETTLE_MS);
    } else {
      recordDismissal();
      removeBanner();
      toast("No problem. The install option stays in the sidebar and on the More page.");
    }
  } catch {
    // the browser refused to open the prompt (for example it was already used): show the steps instead
    removeBanner();
    openInstallGuide();
  } finally {
    prompting = false;
    emit();
  }
}

// ------------------------------------------------------------------------------------------------ guides
function step(n: number, title: string, text: string, glyph?: string): HTMLElement {
  return h("li", { class: "pwa-step" },
    h("span", { class: "pwa-num", "aria-hidden": "true" }, String(n)),
    h("div", { class: "pwa-step-text" }, h("strong", null, title), h("span", null, text)),
    glyph ? h("span", { class: "pwa-glyph", "aria-hidden": "true" }, icon(glyph, 22)) : null);
}

function guideBody(kind: GuideKind, done: () => void): HTMLElement {
  const env = detectEnv();
  const steps: HTMLElement[] = [];
  let lead = "";
  const extra: Node[] = [];
  switch (kind) {
    case "ios-safari":
      lead = "iPhone and iPad install web apps from Safari's Share menu. It takes three taps.";
      steps.push(
        step(1, "Tap the Share button", "It is the square with an arrow, in Safari's toolbar. On iPad it is at the top right. If you do not see it, open the ••• menu first.", "share"),
        step(2, "Choose Add to Home Screen", "Scroll down in the Share menu if you cannot see it. If you see Open as Web App, leave it on.", "plusSquare"),
        step(3, "Tap Add", "SavahBot appears on your Home Screen. Open it from there for the full screen app.", "check"));
      break;
    case "ios-browser":
      lead = `${env.iosBrowser} can add web apps to the Home Screen on iOS 16.4 and later.`;
      steps.push(
        step(1, "Open the Share menu", `Tap the Share button in ${env.iosBrowser}'s address bar or menu. It looks like a square with an arrow.`, "share"),
        step(2, "Choose Add to Home Screen", "Scroll down in the list if you cannot see it.", "plusSquare"),
        step(3, "Tap Add", "SavahBot appears on your Home Screen. If the option is missing, open this page in Safari and use its Share menu.", "check"));
      break;
    case "ios-open-safari":
      lead = env.inApp ? "This page is open inside another app, which cannot add it to your Home Screen." : "This version of iOS can only add web apps from Safari.";
      steps.push(
        step(1, "Open this page in Safari", "Copy the link, then paste it into Safari. Many apps also have an Open in Browser option in their menu.", "external"),
        step(2, "Use Safari's Share menu", "Tap Share, then Add to Home Screen, then Add.", "share"));
      extra.push(h("div", { class: "pwa-extra" }, copyButton(location.href, "Copy link")));
      break;
    case "safari-mac":
      lead = "Safari 17 and later can keep a web app in your Dock.";
      steps.push(
        step(1, "Open the File menu", "In the menu bar at the top of your screen, or use the Share button in the toolbar.", "menu"),
        step(2, "Choose Add to Dock", "Name it SavahBot if asked, then click Add.", "plusSquare"));
      break;
    case "android-menu":
      lead = "Your browser installs web apps from its menu.";
      steps.push(
        step(1, "Open the browser menu", "Tap the menu button (three dots or lines) at the top or bottom of the browser.", "more"),
        step(2, "Choose Install app", "It may be called Add to Home screen. Confirm when asked.", "download"),
        step(3, "Open SavahBot from your apps", "It runs in its own window, without browser bars.", "check"));
      break;
    default:
      lead = env.edge ? "Microsoft Edge installs web apps from its menu." : "Your browser installs web apps from its menu or address bar.";
      steps.push(
        step(1, env.edge ? "Open the Apps menu" : "Look for the install icon", env.edge ? "Click the three dots at the top right, then Apps." : "At the right end of the address bar there may be an install icon. Otherwise open the three dot menu.", env.edge ? "menu" : "download"),
        step(2, env.edge ? "Choose Install this site as an app" : "Choose Install SavahBot", env.edge ? "Confirm with Install." : "It can sit under Cast, save and share, as Install page as app. Confirm with Install.", "plusSquare"),
        step(3, "Open SavahBot from your apps", "It opens in its own window and can be pinned to your taskbar or Dock.", "check"));
  }
  const ios = kind.startsWith("ios");
  return h("div", { class: "pwa-guide stack tight" },
    h("p", { class: "pwa-lead" }, lead),
    h("ol", { class: "pwa-steps" }, steps),
    ...extra,
    h("p", { class: "muted small" }, ios ? "Apple does not let websites open an install prompt, which is why these steps are needed." : "If SavahBot is already installed, open it from your apps or Start menu instead."),
    h("div", { class: "pwa-guide-actions" },
      h("button", { class: "btn primary", type: "button", onclick: done }, "Got it"),
      ios ? h("button", { class: "btn ghost", type: "button", onclick: () => { save({ installedAt: Date.now() }); done(); removeBanner(false); toast("Great. Open SavahBot from your Home Screen."); emit(); } }, icon("check", 16), "I've added it") : null));
}

/** Shows the steps for this browser. Only one copy can be open. */
export function openInstallGuide(): void {
  const kind = guideKind();
  if (!kind || standalone) return;
  if (guide) return;
  const title = kind.startsWith("ios") ? "Add to Home Screen" : kind === "safari-mac" ? "Add to Dock" : "Install SavahBot";
  const holder: { close: () => void } = { close: () => undefined };
  const body = guideBody(kind, () => holder.close());
  const handle = sheet(title, body, () => { guide = null; });
  holder.close = handle.close;
  guide = handle;
  removeBanner();
}

// ------------------------------------------------------------------------------------------------ entries
/**
 * Adds a small "Install app" button to `host` (the sidebar footer). It shows only while installing makes sense, and removes itself from the
 * subscriber list when the returned cleanup runs.
 */
export function mountInstallButton(host: HTMLElement, before: Node | null = null): () => void {
  const txt = h("span", { class: "txt" }, "Install app");
  const btn = h("button", { class: "rail-btn pwa-entry", type: "button", hidden: true, onclick: () => void installApp() }, icon("download", 18), txt);
  host.insertBefore(btn, before);
  const off = onPWAState((s) => {
    btn.hidden = !s.entry;
    txt.textContent = s.label;
    btn.title = s.hint ? `${s.label}. ${s.hint}` : s.label;
  });
  return () => { off(); btn.remove(); };
}

// ------------------------------------------------------------------------------------------------ service worker
async function registerWorker(): Promise<void> {
  if (!("serviceWorker" in navigator)) return;
  try {
    if (import.meta.env?.MODE !== "production") {
      // development: make sure an old worker from a production preview never serves stale files
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
      return;
    }
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch {
    /* an insecure origin or a blocked worker: the app works the same without it */
  }
}

// ------------------------------------------------------------------------------------------------ lifecycle
let teardown: (() => void) | null = null;

/** Starts install detection. Call once, early. Calling it again returns the same cleanup and registers nothing twice. */
export function initPWA(): () => void {
  if (teardown) return teardown;
  const offs: (() => void)[] = [];
  const on = <T extends EventTarget>(target: T, type: string, fn: EventListener, opts?: AddEventListenerOptions) => {
    target.addEventListener(type, fn, opts);
    offs.push(() => target.removeEventListener(type, fn, opts));
  };

  load();
  standalone = detectStandalone();
  if (standalone && !memory.installedAt) save({ installedAt: Date.now() });

  // 1. The browser says the app can be installed. Hold the event; showing the prompt waits for a click.
  on(window, "beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e as BeforeInstallPromptEvent;
    // the browser only offers installation when the app is not installed, so any earlier "installed" note is stale (the app was removed)
    if (memory.installedAt) save({ installedAt: 0 });
    installing = false;
    emit();
    schedule();
  });

  // 2. The app was installed, from our button or from the browser's own menu.
  on(window, "appinstalled", () => {
    deferred = null;
    installing = false;
    window.clearTimeout(settleTimer);
    save({ installedAt: Date.now() });
    guide?.close();
    removeBanner(false);
    emit();
    toast("SavahBot is installed. Open it from your apps.");
  });

  // 3. The display mode changes (the app was opened in a window, or moved back to a tab).
  for (const q of STANDALONE_QUERIES) {
    try {
      const mq = matchMedia(q);
      const fn: EventListener = () => {
        const now = detectStandalone();
        if (now === standalone) return;
        standalone = now;
        if (now) { save({ installedAt: memory.installedAt || Date.now() }); guide?.close(); removeBanner(false); }
        emit();
        schedule();
      };
      if (typeof mq.addEventListener === "function") on(mq, "change", fn);
      else {
        const legacy = mq as unknown as { addListener(f: EventListener): void; removeListener(f: EventListener): void };
        legacy.addListener(fn);
        offs.push(() => legacy.removeListener(fn));
      }
    } catch { /* no display-mode support */ }
  }

  // 4. Another tab dismissed or installed: follow it, so the offer is not repeated here.
  on(window, "storage", ((e: StorageEvent) => {
    if (e.key !== KEY) return;
    load();
    if (memory.installedAt || !cooldownOver()) removeBanner();
    emit();
    schedule();
  }) as EventListener);

  // 5. Coming back to the tab, or closing a dialog, is a chance to show a banner that was waiting.
  on(document, "visibilitychange", () => { if (document.visibilityState === "visible") schedule(); });

  // 6. The signed in dashboard appears and goes away without this module touching the app's own code: watch the app root.
  const root = document.getElementById("app");
  const syncShell = () => {
    const up = hasToken() && !!root?.querySelector(":scope > .app");
    if (up === shellUp) return;
    shellUp = up;
    if (up) { shellSince = Date.now(); schedule(); }
    else { window.clearTimeout(offerTimer); removeBanner(false); }
  };
  if (root) {
    const mo = new MutationObserver(syncShell);
    mo.observe(root, { childList: true });
    offs.push(() => mo.disconnect());
  }
  syncShell();

  void registerWorker();
  emit();

  // keep hot reload in development from leaving a second set of listeners behind
  (import.meta as unknown as { hot?: { dispose(cb: () => void): void } }).hot?.dispose(() => teardown?.());

  teardown = () => {
    offs.splice(0).forEach((f) => f());
    window.clearTimeout(offerTimer);
    window.clearTimeout(settleTimer);
    removeBanner(false);
    guide?.close();
    deferred = null;
    shellUp = false;
    teardown = null;
  };
  return teardown;
}
