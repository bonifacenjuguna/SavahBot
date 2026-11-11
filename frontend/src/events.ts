import { apiBase, getToken } from "./api.js";

export interface BotEvent {
  type: string;
  data: any;
  ts: number;
}

type Listener = (e: BotEvent) => void;
const listeners = new Map<string, Set<Listener>>();
let controller: AbortController | null = null;
export let connected = false;
/** How many connection attempts in a row have failed (0 while connected). Shown next to "Reconnecting". */
export let attempts = 0;
const connectionListeners = new Set<(up: boolean) => void>();
const reconnectListeners = new Set<(downForMs: number) => void>();

/** The server sends a ping comment every 15 seconds. If nothing at all arrives for this long, the connection is dead even though the browser has not noticed
 * (a phone that slept, a proxy that dropped the stream, a server that was restarted). It is closed and opened again. */
const SILENCE_MS = 40_000;
const BACKOFF = [500, 1000, 2000, 4000, 8000, 10000];

let wake: (() => void) | null = null;
let downSince = 0;

export function on(type: string, fn: Listener): () => void {
  let set = listeners.get(type);
  if (!set) listeners.set(type, (set = new Set()));
  set.add(fn);
  return () => set!.delete(fn);
}

export function onConnection(fn: (up: boolean) => void): () => void {
  connectionListeners.add(fn);
  return () => connectionListeners.delete(fn);
}

/** Called each time the feed comes back after having been down, with how long it was down. Use it to catch up on what was missed. */
export function onReconnect(fn: (downForMs: number) => void): () => void {
  reconnectListeners.add(fn);
  return () => reconnectListeners.delete(fn);
}

/** Try again right now instead of waiting out the back-off. Safe to call at any time. */
export function retryNow(): void {
  wake?.();
}

function setConnected(up: boolean): void {
  if (connected === up) return;
  connected = up;
  if (up) {
    attempts = 0;
    const was = downSince ? Date.now() - downSince : 0;
    downSince = 0;
    connectionListeners.forEach((f) => f(true));
    if (was > 0) reconnectListeners.forEach((f) => { try { f(was); } catch (e) { console.error(e); } });
  } else {
    downSince = Date.now();
    connectionListeners.forEach((f) => f(false));
  }
}

function dispatch(raw: string): void {
  for (const line of raw.split("\n")) {
    if (!line.startsWith("data:")) continue;
    try {
      const e = JSON.parse(line.slice(5)) as BotEvent;
      listeners.get(e.type)?.forEach((f) => f(e));
      listeners.get("*")?.forEach((f) => f(e));
    } catch {
      /* ignore malformed frame */
    }
  }
}

/** The browser told us something changed: the tab came back, the network came back. A stalled connection is not trusted; a fresh one is opened now. */
function onWake(): void {
  if (!controller) return;
  if (!connected) { retryNow(); return; }
  stale?.();     // connected on paper: make the silence check run straight away
}
let stale: (() => void) | null = null;
const onVisible = () => { if (document.visibilityState === "visible") onWake(); };

/** Live feed over fetch streaming (EventSource cannot send an Authorization header). Reconnects by itself, quickly, and whenever the tab or the network wakes up. */
export function start(): void {
  stop();
  controller = new AbortController();
  window.addEventListener("online", onWake);
  document.addEventListener("visibilitychange", onVisible);
  void loop(controller);
}

export function stop(): void {
  controller?.abort();
  controller = null;
  window.removeEventListener("online", onWake);
  document.removeEventListener("visibilitychange", onVisible);
  wake?.();
  downSince = 0;
  setConnected(false);
  downSince = 0;
}

/** Waits `ms`, or less if retryNow() / a wake-up event asks to try again. */
function pause(ms: number, ctl: AbortController): Promise<void> {
  return new Promise((resolve) => {
    const done = () => { clearTimeout(t); wake = null; ctl.signal.removeEventListener("abort", done); resolve(); };
    const t = window.setTimeout(done, ms);
    wake = done;
    ctl.signal.addEventListener("abort", done);
  });
}

async function loop(ctl: AbortController): Promise<void> {
  while (!ctl.signal.aborted) {
    const conn = new AbortController();
    const abortConn = () => conn.abort();
    ctl.signal.addEventListener("abort", abortConn);
    let lastByte = Date.now();
    const check = () => { if (Date.now() - lastByte > SILENCE_MS) conn.abort(); };
    const watchdog = window.setInterval(check, 5000);
    stale = check;
    try {
      const res = await fetch(apiBase() + "/api/events", { headers: { Authorization: `Bearer ${getToken()}` }, signal: conn.signal, cache: "no-store" });
      if (res.status === 401) { window.clearInterval(watchdog); ctl.signal.removeEventListener("abort", abortConn); return; }
      if (!res.ok || !res.body) throw new Error(`status ${res.status}`);
      lastByte = Date.now();
      setConnected(true);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        lastByte = Date.now();
        buf += decoder.decode(value, { stream: true });
        let i: number;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          dispatch(buf.slice(0, i));
          buf = buf.slice(i + 2);
        }
      }
    } catch {
      /* fall through to reconnect */
    }
    window.clearInterval(watchdog);
    ctl.signal.removeEventListener("abort", abortConn);
    stale = null;
    setConnected(false);
    if (ctl.signal.aborted) return;
    attempts++;
    const base = BACKOFF[Math.min(attempts - 1, BACKOFF.length - 1)];
    await pause(base + Math.random() * 300, ctl);
  }
}
