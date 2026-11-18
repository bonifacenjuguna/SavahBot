/** The page's side of the service worker (1.4.11): everything the installed app does when it is not in front of you.
 *
 *   - App icon badge: the number of moderation requests waiting, on the home-screen / taskbar icon (Badging API).
 *   - A read-only "badge link" is kept for the service worker, so Periodic Background Sync (Chrome, installed app only) can refresh that number
 *     while the app is closed. It can read the waiting count and nothing else, and it is wiped on sign-out.
 *   - Sends writes that were saved offline (see outbox.ts), as soon as the connection is back.
 *   - Tells you when something was kept for later.
 * Every part is optional and silent where the browser has no support (iOS keeps the badge from push messages only). */
import { apiBase, get, getToken } from "./api.js";
import { toast } from "./dom.js";
import { kvGet, kvSet } from "./idb.js";
import { SYNC_TAG, flush, onOutbox, queuedNotice } from "./outbox.js";

type BadgeNav = Navigator & { setAppBadge?: (n?: number) => Promise<void>; clearAppBadge?: () => Promise<void> };
const nav = navigator as BadgeNav;
const BADGE_TOKEN_DAYS = 3;                     // the link lasts 14 days; it is renewed whenever it is older than this
export const PERIODIC_TAG = "savahbot-badge";

/** Puts the number on the app icon (0 clears it). */
export async function setBadge(n: number): Promise<void> {
  const count = Math.max(0, Math.min(9999, Math.floor(n) || 0));
  await kvSet("pending", { n: count, at: Date.now() });
  try { if (count > 0) await nav.setAppBadge?.(count); else await nav.clearAppBadge?.(); } catch { /* no badge support or not installed */ }
}

async function renewBadgeLink(): Promise<void> {
  const base = apiBase();
  const have = await kvGet<{ at: number; base: string }>("badge");
  if (have && have.base === base && Date.now() - have.at < BADGE_TOKEN_DAYS * 86_400_000) return;
  try {
    const r = await get<{ token: string }>("/api/notify/badge-token");
    await kvSet("badge", { token: r.token, base, at: Date.now() });
  } catch { /* offline or not allowed right now: tried again next start */ }
}

async function registerPeriodic(): Promise<void> {
  try {
    const reg = await navigator.serviceWorker?.getRegistration("/");
    const ps = (reg as unknown as { periodicSync?: { register(tag: string, o: { minInterval: number }): Promise<void> } } | undefined)?.periodicSync;
    if (!ps) return;
    const perm = await (navigator.permissions as Permissions | undefined)?.query({ name: "periodic-background-sync" as PermissionName }).catch(() => null);
    if (perm && perm.state === "denied") return;
    await ps.register(PERIODIC_TAG, { minInterval: 15 * 60 * 1000 });
  } catch { /* not an installed Chromium app: the push messages keep the badge up to date instead */ }
}

let flushTimer = 0;
async function sendWaiting(announce: boolean): Promise<void> {
  const token = getToken();
  if (!token) return;
  const r = await flush(apiBase(), token);
  if (announce && r.sent) toast(r.sent === 1 ? "Sent what you saved while offline." : `Sent ${r.sent} things you saved while offline.`);
  for (const d of r.dropped) toast(`Something saved offline could not be sent: ${d.reason}`, "error");
}

/** Start once the signed-in dashboard is up. Returns a stop function. */
export function startBridge(): () => void {
  const offs: (() => void)[] = [];
  void kvSet("config", { base: apiBase() });
  void renewBadgeLink();
  void registerPeriodic();
  void sendWaiting(true);

  const online = () => { window.clearTimeout(flushTimer); flushTimer = window.setTimeout(() => void sendWaiting(true), 1200); };
  window.addEventListener("online", online);
  offs.push(() => window.removeEventListener("online", online));

  const queued = () => {
    toast(navigator.onLine === false ? "Saved on this device. It will be sent when you are back online." : "Could not reach the server. Saved on this device; it will be sent when it is back.");
    if (navigator.onLine !== false) online();      // the server may only be restarting: try again shortly
  };
  queuedNotice.addEventListener("queued", queued);
  offs.push(() => queuedNotice.removeEventListener("queued", queued));

  // the service worker finished sending (Background Sync) or asks the open app to
  const onMsg = (e: MessageEvent) => {
    const d = e.data as { type?: string; sent?: number } | undefined;
    if (d?.type === "outbox-flush") void sendWaiting(true);
    else if (d?.type === "outbox-sent" && d.sent) toast(d.sent === 1 ? "Sent what you saved while offline." : `Sent ${d.sent} things you saved while offline.`);
  };
  navigator.serviceWorker?.addEventListener("message", onMsg);
  offs.push(() => navigator.serviceWorker?.removeEventListener("message", onMsg));
  return () => { offs.forEach((f) => f()); window.clearTimeout(flushTimer); };
}

/** For the sidebar and Settings: how many writes are waiting to be sent. */
export { onOutbox, SYNC_TAG };
