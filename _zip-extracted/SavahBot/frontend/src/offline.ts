/** Offline reading (1.4.11): the last good answer of the read-only API calls the dashboard makes most, kept on this device.
 *
 * When a GET cannot reach the server at all (no internet, the backend is restarting), the api layer asks here for the last copy and the
 * page draws that instead of an error, with a slim "Showing saved data from ..." strip. As soon as any live answer arrives, the strip goes.
 *
 * What is kept, and what is not:
 *   - Only the allow-listed read-only paths below. Never sign-in, security, backup, push devices, keys or settings with secrets.
 *   - Only answers the server really gave (HTTP 200). Nothing is invented.
 *   - It is private to this browser profile, expires after a week, and is wiped on sign-out and when the session ends.
 * Nothing here changes what happens while you are online. */
import { idbAll, idbClear, idbDelete, idbGet, idbPut, kvDelete } from "./idb.js";

export const MAX_AGE_MS = 7 * 86_400_000;
export const MAX_ENTRIES = 80;
export const MAX_BYTES = 600_000;       // one answer; bigger ones (long chat exports) are simply not kept

/** Paths whose last answer is worth showing offline. A path matches by prefix, query included in the key but not in the test. */
const READABLE = [
  "/api/status", "/api/analytics", "/api/notes", "/api/quotes", "/api/regulars", "/api/reminders", "/api/bans", "/api/blacklist",
  "/api/commands", "/api/timers", "/api/triggers", "/api/variables", "/api/moderation/pending", "/api/moderation/history", "/api/moderation/level",
  "/api/notify/inbox", "/api/notify/unread", "/api/notify/categories", "/api/notify/prefs", "/api/notify/stats", "/api/notify/log",
  "/api/live/stats", "/api/live/streams", "/api/history", "/api/streams", "/api/weather/overview", "/api/weather/current", "/api/weather/daily",
  "/api/weather/hourly", "/api/weather/locations", "/api/weather/prefs", "/api/weather/rules", "/api/layouts", "/api/activity", "/api/demo",
];
const NEVER = ["/api/auth", "/api/security", "/api/backup", "/api/notify/devices", "/api/notify/config", "/api/notify/badge", "/api/youtube", "/api/telegram", "/api/settings", "/api/system", "/api/knowledge", "/api/events", "/api/voices"];
const EXPORTS = /\/export(\b|$)|[?&]download=/;

export function isReadable(path: string): boolean {
  const p = path.split("?")[0];
  if (EXPORTS.test(path) || NEVER.some((n) => p === n || p.startsWith(n + "/"))) return false;
  return READABLE.some((r) => p === r || p.startsWith(r + "/"));
}

interface Entry { key: string; ts: number; data: unknown }
let staleSince: number | null = null;
const listeners = new Set<(since: number | null) => void>();
const emit = () => listeners.forEach((f) => { try { f(staleSince); } catch (e) { console.error(e); } });

/** When the data on screen is a saved copy: the time that copy was taken, or null while everything is live. */
export const savedFrom = (): number | null => staleSince;
export function onSaved(fn: (since: number | null) => void): () => void { listeners.add(fn); fn(staleSince); return () => listeners.delete(fn); }

/** Keeps a live answer. Fire and forget: it never slows or fails a request. */
export function remember(path: string, data: unknown): void {
  if (staleSince !== null) { staleSince = null; emit(); }
  if (!isReadable(path)) return;
  try {
    const text = JSON.stringify(data);
    if (!text || text.length > MAX_BYTES) { void idbDelete("cache", path); return; }
    void idbPut("cache", { key: path, ts: Date.now(), data } satisfies Entry).then(() => prune());
  } catch { /* a value that cannot be stored is just not kept */ }
}

/** The last copy of this path, if there is a fresh enough one. Marks the page as showing saved data. */
export async function recall<T>(path: string): Promise<T | null> {
  if (!isReadable(path)) return null;
  const hit = await idbGet<Entry>("cache", path);
  if (!hit || Date.now() - hit.ts > MAX_AGE_MS) return null;
  if (staleSince === null || hit.ts < staleSince) { staleSince = hit.ts; emit(); }
  return hit.data as T;
}

let pruning = false;
async function prune(): Promise<void> {
  if (pruning) return;
  pruning = true;
  try {
    const all = await idbAll<Entry>("cache");
    const old = all.filter((e) => Date.now() - e.ts > MAX_AGE_MS);
    const keep = all.filter((e) => !old.includes(e)).sort((a, b) => b.ts - a.ts);
    const drop = [...old, ...keep.slice(MAX_ENTRIES)];
    await Promise.all(drop.map((e) => idbDelete("cache", e.key)));
  } finally { pruning = false; }
}

/** Sign-out, a lost session and lockdown: nothing from this account stays on the device. */
export async function forgetAll(): Promise<void> {
  staleSince = null;
  emit();
  await idbClear("cache");
  await Promise.all([kvDelete("badge"), kvDelete("pending")]);                              // the read-only badge link for the service worker
  try { await (navigator as Navigator & { clearAppBadge?: () => Promise<void> }).clearAppBadge?.(); } catch { /* no badge support */ }
}
