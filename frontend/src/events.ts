import { apiBase, getToken } from "./api.js";

export interface BotEvent {
  type: string;
  data: any;
  ts: number;
}

type Listener = (e: BotEvent) => void;
const listeners = new Map<string, Set<Listener>>();
let controller: AbortController | null = null;
let retry = 1000;
export let connected = false;
const connectionListeners = new Set<(up: boolean) => void>();

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

function setConnected(up: boolean): void {
  if (connected === up) return;
  connected = up;
  connectionListeners.forEach((f) => f(up));
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

/** Live feed over fetch streaming (EventSource cannot send an Authorization header). Reconnects with backoff. */
export function start(): void {
  stop();
  controller = new AbortController();
  void loop(controller);
}

export function stop(): void {
  controller?.abort();
  controller = null;
  setConnected(false);
}

async function loop(ctl: AbortController): Promise<void> {
  while (!ctl.signal.aborted) {
    try {
      const res = await fetch(apiBase() + "/api/events", { headers: { Authorization: `Bearer ${getToken()}` }, signal: ctl.signal });
      if (res.status === 401) return;
      if (!res.ok || !res.body) throw new Error(`status ${res.status}`);
      setConnected(true);
      retry = 1000;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
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
    setConnected(false);
    if (ctl.signal.aborted) return;
    await new Promise((r) => setTimeout(r, retry));
    retry = Math.min(retry * 2, 15000);
  }
}
