/** Settings panels that live on this page: Appearance, Privacy & data, Device & app, Developer. */
import { get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { ACCENTS, TOAST_SECS, accentPref, densityPref, motionPref, setAccent, setDensity, setMotion, setText, setToastMode, setToastPos, setToastSecs, textPref, toastMode, toastPos, toastSecs, type Accent, type ToastMode, type ToastPos } from "../appearance.js";
import { applyTheme, themePref, type ThemePref } from "../ui.js";
import { getPWAState, installApp, openInstallGuide } from "../pwa.js";
import { card } from "./shared.js";
import { figures, lede, seg } from "./widgets.js";

const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");
const row = (title: string, text: string | null, control: HTMLElement | null) => h("div", { class: "n-row" }, h("div", { class: "n-row-main" }, h("strong", null, title), text ? h("span", { class: "muted small" }, text) : null), control);
const body = (...k: (HTMLElement | null)[]) => h("div", { class: "k-stack", style: "padding:6px 14px 12px" }, k);

// ------------------------------------------------------------------ Appearance
export function renderAppearance(el: HTMLElement): void {
  const theme = seg<ThemePref>("Theme", [{ id: "system", label: "System", icon: "monitor" }, { id: "light", label: "Light", icon: "sun" }, { id: "dark", label: "Dark", icon: "moon" }], themePref(), (v) => applyTheme(v)).el;
  const swatches = h("div", { class: "row wrap", role: "radiogroup", "aria-label": "Accent colour" }, ACCENTS.map((a) => {
    const b = h("button", { type: "button", class: "swatch", role: "radio", "aria-checked": String(a.id === accentPref()), "aria-label": a.label, title: a.label, style: `--sw:${a.swatch}`, onclick: () => {
      setAccent(a.id as Accent); swatches.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    } });
    return b;
  }));
  const density = seg<"comfortable" | "compact">("Density", [{ id: "comfortable", label: "Comfortable" }, { id: "compact", label: "Compact" }], densityPref(), setDensity).el;
  const text = seg<"normal" | "large" | "larger">("Text size", [{ id: "normal", label: "Normal" }, { id: "large", label: "Large" }, { id: "larger", label: "Larger" }], textPref(), setText).el;
  const motion = h("input", { type: "checkbox", class: "switch", checked: motionPref() === "reduce", "aria-label": "Reduce motion", onchange: (e: Event) => setMotion((e.target as HTMLInputElement).checked ? "reduce" : "system") });
  mount(el, card("sparkle", "Look and feel", body(
    lede("These are saved on this device only, so your phone and your computer can look different. They never touch the server."),
    row("Theme", "System follows your device's light or dark setting.", theme), row("Accent colour", "Buttons, links and highlights.", swatches),
    row("Density", "Compact fits more on screen.", density), row("Text size", "Makes everything bigger, not just the text.", text),
    row("Reduce motion", "Also on automatically if your device asks for it.", motion)), ),
    toastCard());
}

/** 1.3.3: the small pop-up messages ("Saved", "Copied", errors): on or off, top or bottom, and how long they stay. Swipe one sideways to dismiss it. */
function toastCard(): HTMLElement {
  const mode = seg<ToastMode>("Pop-up notices", [{ id: "all", label: "All" }, { id: "errors", label: "Errors only" }, { id: "off", label: "Off" }], toastMode(), (v) => { setToastMode(v); if (v === "off") return; toast(v === "errors" ? "Only errors will pop up" : "Pop-up notices are on"); }).el;
  const pos = seg<ToastPos>("Pop-up position", [{ id: "bottom", label: "Bottom" }, { id: "top", label: "Top" }], toastPos(), (v) => { setToastPos(v); toast("Notices will appear here"); }).el;
  const label = h("span", { class: "muted small", style: "min-width:34px;text-align:right" }, `${toastSecs()} s`);
  const slider = h("input", { type: "range", min: TOAST_SECS.min, max: TOAST_SECS.max, step: 1, value: String(toastSecs()), "aria-label": "Seconds a notice stays on screen", style: "flex:1;min-width:110px",
    oninput: (e: Event) => { label.textContent = `${(e.target as HTMLInputElement).value} s`; },
    onchange: (e: Event) => { setToastSecs(Number((e.target as HTMLInputElement).value)); toast("Notices will stay this long"); } });
  const sample = h("button", { class: "btn small", type: "button", onclick: () => { toast("This is a notice. Swipe it left or right to dismiss."); toast("This is what an error looks like.", "error"); } }, "Show a sample");
  return card("bell", "Pop-up notices", body(
    lede("The small messages that slide in over the page. Saved on this device only. Swipe one left or right, or tap it, to dismiss it."),
    row("Show", "Errors only hides \"Saved\" and \"Copied\" but still tells you when something fails. Off hides every pop-up.", mode),
    row("Position", "Put them at the top if the bottom is in your way.", pos),
    row("Stay for", "Errors stay twice as long.", h("div", { class: "row", style: "gap:8px;align-items:center;min-width:170px" }, slider, label)),
    h("div", { class: "row" }, sample)));
}

// ------------------------------------------------------------------ Privacy & data
interface Item { id: string; label: string; text: string; count: number; retention_days: number | null; clearable: boolean; protected: boolean }
export async function renderPrivacy(el: HTMLElement): Promise<void> {
  const d = await get<{ items: Item[]; stored_where: { database: string; cache: string; processors: string[] }; export_note: string; never_collected: string[] }>("/api/system/data");
  const again = () => void renderPrivacy(el).catch(fail);
  const clear = (it: Item) => h("button", { class: "btn small", type: "button", onclick: (e: Event) => {
    if (!confirm(`Clear ${it.label.toLowerCase()}?\n\n${it.count} item${it.count === 1 ? "" : "s"} will be deleted from the server. This cannot be undone. Security records are never touched.`)) return;
    void busy(e.currentTarget as HTMLButtonElement, async () => { const r = await post<{ cleared: number }>("/api/system/data/clear", { target: it.id, confirm: true }); toast(`Cleared ${r.cleared}`); again(); });
  } }, icon("trash", 14), "Clear");
  mount(el, card("database", "What SavahBot stores", h("div", { class: "n-log" }, d.items.map((it) => h("div", { class: "n-log-row n-dev" },
    h("div", { class: "n-row-main" }, h("strong", null, it.label, it.protected ? h("span", { class: "chip" }, icon("lock", 12), "protected") : null), h("span", { class: "muted small" }, it.text),
      it.retention_days ? h("span", { class: "muted small" }, `Kept ${it.retention_days} days, then deleted automatically (change it under All environment settings).`) : null),
    h("span", { class: "chip" }, String(it.count)), it.clearable ? clear(it) : null))), { flush: true }),
    card("shield", "Where it lives", body(h("p", null, `Database: ${d.stored_where.database}. Cache: ${d.stored_where.cache}. The database is the source of truth; the cache can be thrown away.`),
      h("p", { class: "muted" }, "Services that receive some data when you use them:"), h("ul", null, d.stored_where.processors.map((p) => h("li", null, p))),
      h("p", { class: "muted" }, "Never collected or kept: "), h("ul", null, d.never_collected.map((p) => h("li", null, p)))), { flush: true }),
    card("download", "Your data", body(h("p", null, d.export_note), h("a", { class: "btn", href: "#/backup" }, icon("database", 16), "Open Backup")), { flush: true }));
}

// ------------------------------------------------------------------ Device & app
export async function renderDevice(el: HTMLElement): Promise<void> {
  const pwa = getPWAState();
  const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration("/") : undefined;
  const est = await navigator.storage?.estimate?.().catch(() => undefined);
  const perm = "Notification" in window ? Notification.permission : "unsupported";
  const keys = Object.keys(localStorage).filter((k) => k.startsWith("savahbot."));
  const check = h("button", { class: "btn small", type: "button", disabled: !reg }, icon("refresh", 14), "Check for an update") as HTMLButtonElement;
  check.onclick = () => busy(check, async () => { await reg?.update(); toast(reg?.waiting ? "An update is ready. Reload to use it." : "You are on the latest version."); });
  const wipe = h("button", { class: "btn small", type: "button" }, icon("trash", 14), "Clear data on this device") as HTMLButtonElement;
  wipe.onclick = () => {
    if (!confirm("Clear what this browser remembers about SavahBot?\n\nThis removes your look settings, recent searches and collapsed sections on THIS device. Your server data and sign-in session are not touched, and you stay signed in.")) return;
    keys.filter((k) => k !== "savahbot.session" && !k.includes("token") && !k.includes("api")).forEach((k) => localStorage.removeItem(k));
    toast("Cleared. Reloading…"); setTimeout(() => location.reload(), 600);
  };
  const state = (ok: boolean, yes: string, no: string) => h("span", { class: `chip ${ok ? "ok" : ""}` }, ok ? yes : no);
  mount(el, figures([{ value: pwa.installed ? "installed" : "browser", label: "how you are running" }, { value: navigator.onLine ? "online" : "offline", label: "connection", tone: navigator.onLine ? "ok" : "warn" }, { value: String(perm), label: "notification permission", tone: perm === "granted" ? "ok" : perm === "denied" ? "bad" : "" }]),
    card("smartphone", "This device", body(
      row("Installed app", pwa.installed ? "SavahBot is running as an installed app." : "Install for its own window and (on iPhone) for push notifications.", pwa.installed ? state(true, "installed", "") : h("div", { class: "row" }, pwa.canPrompt ? h("button", { class: "btn small primary", type: "button", onclick: () => void installApp() }, icon("download", 14), "Install") : null, h("button", { class: "btn small", type: "button", onclick: () => openInstallGuide() }, "How"))),
      row("Service worker", reg ? `Active${reg.waiting ? ", update waiting" : ""}. It shows push notifications and a friendly offline page. Nothing private is cached.` : "Not registered on this device yet.", h("div", { class: "row" }, state(Boolean(reg?.active), "active", "none"), check)),
      row("Push permission", perm === "granted" ? "Allowed. Turn push on per device under Notifications." : perm === "denied" ? "Blocked. Allow it in your browser's site settings." : "Not asked yet. The browser asks only when you press the button on Notifications.", h("a", { class: "btn small", href: "#/notifications" }, icon("bell", 14), "Notifications")),
      row("Offline", "Offline you see a simple page that says so. The dashboard needs a connection because it controls a live bot.", null),
      row("Storage on this device", est?.usage !== undefined ? `${(est.usage / 1048576).toFixed(1)} MB used by this site, ${keys.length} small preference${keys.length === 1 ? "" : "s"} saved.` : `${keys.length} small preferences saved.`, wipe)), ));
}

// ------------------------------------------------------------------ Developer
interface Health {
  app: { name: string; version: string; env: string; python: string; platform: string; uptime: number; mode: string };
  database: { backend: string; ok: boolean; latency_ms: number; schema_version: number };
  redis: { configured: boolean; mode: string; instance: string; error: string; leader: boolean };
  background: { scheduler_last_tick: number | null; scheduler_seconds_ago: number | null; hooks: number; notifications_listening: boolean };
  events: { subscribers: number | null }; cache: { weather_entries: number; weather_provider: string };
  features: Record<string, boolean>; deployment: { backend_host: string; frontend_host: string };
  config_problems: { level: string; text: string; route: string }[]; secrets: Record<string, boolean>;
}
const dur = (s: number) => (s < 3600 ? `${Math.floor(s / 60)} min` : s < 86400 ? `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min` : `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`);
export async function renderDeveloper(el: HTMLElement): Promise<void> {
  const x = await get<Health>("/api/system/health");
  const ok = (v: boolean, a = "ok", b = "problem") => h("span", { class: `chip ${v ? "ok" : "bad"}` }, v ? a : b);
  const refresh = h("button", { class: "btn small", type: "button" }, icon("refresh", 14), "Re-check") as HTMLButtonElement;
  refresh.onclick = () => busy(refresh, () => renderDeveloper(el));
  mount(el, h("div", { class: "row" }, refresh), card("checklist", "Configuration check", x.config_problems.length ? h("div", { class: "n-log" }, x.config_problems.map((p) => h("a", { class: `n-hist ${p.level}`, href: p.route }, icon(p.level === "info" ? "info" : "alert", 18), h("span", { class: "set-main" }, p.text)))) : h("p", { style: "padding:12px 14px" }, "No configuration problems found."), { flush: true }),
    card("gauge", "Service health", body(
      row("Database", `${x.database.backend}, schema v${x.database.schema_version}, answered in ${x.database.latency_ms} ms`, ok(x.database.ok)),
      row("Redis", x.redis.configured ? `${x.redis.mode}${x.redis.error ? `: ${x.redis.error}` : ""}. This instance ${x.redis.leader ? "is" : "is not"} the leader.` : "Not configured: SavahBot runs in memory.", ok(!x.redis.configured || x.redis.mode === "redis", x.redis.configured ? "connected" : "not used", "unreachable")),
      row("Background work", x.background.scheduler_seconds_ago === null ? "The scheduler has not run on this instance (it runs on the leader)." : `Scheduler last ran ${x.background.scheduler_seconds_ago} s ago, ${x.background.hooks} jobs. Notification listener ${x.background.notifications_listening ? "running" : "stopped"}.`, ok(x.background.scheduler_seconds_ago === null || x.background.scheduler_seconds_ago < 120)),
      row("Live updates", `${x.events.subscribers ?? 0} dashboard stream${x.events.subscribers === 1 ? "" : "s"} connected`, null),
      row("Cache", `${x.cache.weather_entries} weather entries (${x.cache.weather_provider})`, null)), ),
    card("plug", "Features", body(...Object.entries(x.features).map(([k, v]) => row(k.replace(/_/g, " "), null, h("span", { class: `chip ${v ? "ok" : ""}` }, v ? "available" : "not set up")))), { flush: true }),
    card("lock", "Secrets (only whether they are set)", body(h("p", { class: "muted small" }, "Values are never shown anywhere in SavahBot."), ...Object.entries(x.secrets).map(([k, v]) => row(k.replace(/_/g, " "), null, h("span", { class: `chip ${v ? "ok" : ""}` }, v ? "set" : "not set")))), { flush: true }),
    card("cloud", "This deployment", body(row("Version", `${x.app.name} ${x.app.version} · ${x.app.env} · Python ${x.app.python}`, null), row("Running for", dur(x.app.uptime), null), row("Backend address", x.deployment.backend_host || "not set", null), row("Dashboard address", x.deployment.frontend_host || "not set", null),
      h("p", null, h("a", { class: "btn small", href: "#/settings?tab=all" }, icon("sliders", 14), "All environment settings"))), { flush: true }));
}
