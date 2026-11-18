/** Writes made while offline (1.4.11): notes, quotes and clock-time reminders are kept on this device and sent when the connection is back.
 *
 * Only these three, because they are safe to send late and twice is impossible (an entry is taken out before it is sent). Anything that
 * acts on live chat (a ban, an approval, a command) is never queued: it would be wrong an hour later, so it still says "cannot reach the backend".
 * Where it can, the browser's Background Sync wakes the service worker to send them even if the app is closed; otherwise the open app sends them
 * as soon as the connection returns. While anything is waiting, the service worker is given the sign-in token (and nothing else) so it can send
 * them; the copy is removed the moment the box is empty or you sign out. */
import { idbAll, idbDelete, idbPut, kvDelete, kvSet } from "./idb.js";

export interface Queued { id: string; method: "POST"; path: string; body: unknown; created: number; tries: number }
export const SYNC_TAG = "savahbot-outbox";
/** Fires when a write was kept for later, so the shell can say so (the api layer does not draw anything itself). */
export const queuedNotice = new EventTarget();

/** A relative time ("30m", "in 2 hours") would be wrong by the time it is sent, so only clock times and dates may wait. */
const RELATIVE = /^\s*(in\s+)?\d+(\.\d+)?\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\s*$/i;
export const isRelativeReminder = (when: string): boolean => RELATIVE.test(when);

export function canQueue(method: string, path: string, body: unknown): boolean {
  if (method !== "POST") return false;
  const p = path.split("?")[0];
  if (p === "/api/notes" || p === "/api/quotes") return true;
  if (p === "/api/reminders") {
    const when = body && typeof body === "object" ? String((body as { when?: unknown }).when ?? "") : "";
    return when !== "" && !isRelativeReminder(when);
  }
  return false;
}

const listeners = new Set<(n: number) => void>();
export function onOutbox(fn: (n: number) => void): () => void { listeners.add(fn); void count().then(fn); return () => listeners.delete(fn); }
const tell = async () => { const n = await count(); listeners.forEach((f) => { try { f(n); } catch (e) { console.error(e); } }); };

export const list = (): Promise<Queued[]> => idbAll<Queued>("outbox").then((l) => l.sort((a, b) => a.created - b.created));
export const count = async (): Promise<number> => (await list()).length;

export async function enqueue(path: string, body: unknown, token: string, base: string): Promise<void> {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  await idbPut("outbox", { id, method: "POST", path, body, created: Date.now(), tries: 0 } satisfies Queued);
  await kvSet("replay", { token, base });                     // only while something is waiting
  await registerSync();
  void tell();
}

async function registerSync(): Promise<void> {
  try {
    const reg = await navigator.serviceWorker?.getRegistration("/");
    const sync = (reg as unknown as { sync?: { register(tag: string): Promise<void> } } | undefined)?.sync;
    if (sync) await sync.register(SYNC_TAG);
  } catch { /* no Background Sync here (Safari, Firefox): the open app sends them instead */ }
}

let flushing = false;
export interface FlushResult { sent: number; dropped: { path: string; reason: string }[]; left: number }

/** Sends what is waiting, oldest first. Stops at the first sign that the server cannot be reached or the session is gone, keeping the rest. */
export async function flush(base: string, token: string): Promise<FlushResult> {
  const out: FlushResult = { sent: 0, dropped: [], left: 0 };
  if (flushing || !token) { out.left = await count(); return out; }
  flushing = true;
  const run = async () => {
    for (const item of await list()) {
      await idbDelete("outbox", item.id);                      // taken out first: it can never be sent twice
      let res: Response | null = null;
      try {
        res = await fetch(base + item.path, { method: item.method, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify(item.body) });
      } catch { res = null; }
      if (!res || res.status >= 500 || res.status === 401 || res.status === 429) {
        await idbPut("outbox", { ...item, tries: item.tries + 1 });   // not delivered: back in the queue, in its place (created is unchanged)
        break;
      }
      if (res.ok) out.sent++;
      else {
        let reason = `Request failed (${res.status}).`;
        try { reason = ((await res.json()) as { error?: string }).error ?? reason; } catch { /* keep the generic reason */ }
        out.dropped.push({ path: item.path, reason });
      }
    }
  };
  try {
    const locks = (navigator as Navigator & { locks?: LockManager }).locks;
    if (locks) await locks.request("savahbot-outbox-flush", run); else await run();
  } finally { flushing = false; }
  out.left = await count();
  if (out.left === 0) await kvDelete("replay");
  void tell();
  return out;
}

/** Sign-out and a lost session: the service worker keeps no way to act for this account. Queued writes stay and are sent at the next sign-in. */
export const revokeReplay = (): Promise<void> => kvDelete("replay");
