import { get } from "./api.js";

export type OpState = "demo" | "standby" | "live";

export interface Status {
  app: string;
  version: string;
  timezone: string;
  hub: {
    mode: "demo" | "live";
    /** The single operating state the whole UI shows. demo = simulated, live = real chat with a stream, standby = live mode waiting for a stream. */
    state: OpState;
    source: string | null;
    source_status: Record<string, any>;
    stream_live: boolean;
    stream_title: string;
    uptime: number;
    mod_mode: "off" | "suggest" | "auto";
    lines: number;
    blacklist_size: number;
  };
  telegram: { configured: boolean; mode: string; bot_username: string | null; owner_bound: boolean; webhook_url: string; polling: boolean; last_error: string; last_update: number | null };
  youtube: {
    state: string;
    connected: boolean;
    chat_attached: boolean;
    video_id: string | null;
    title: string | null;
    last_error: string;
    last_poll: number | null;
    polls: number;
    quota: { used: number; daily: number; remaining: number; fraction: number; day: string; reset_tz: string };
    redirect_uri: string;
    account: { channel_id: string; title: string; handle: string } | null;
    target: { channel_id: string; title: string } | null;
    video_channel_id: string;
    last_action_error: string;
  };
  demo: { state: string; ambient: boolean; scenarios_running: string[]; channel: string };
  pending: number;
  notifications_unread: number;
  database: string;
  uptime: number;
  sse_clients: number;
}

export let status: Status | null = null;
const subs = new Set<(s: Status) => void>();
const modeSubs = new Set<(mode: "demo" | "live", previous: "demo" | "live" | null) => void>();
let lastMode: "demo" | "live" | null = null;

/** Fires when the active mode (demo or live) changes. Every page re-renders from it, so no page can keep showing the other mode's data. */
export function onModeChange(fn: (mode: "demo" | "live", previous: "demo" | "live" | null) => void): () => void {
  modeSubs.add(fn);
  return () => modeSubs.delete(fn);
}

/** Always read the mode from here, never from a local copy. */
export const currentMode = (): "demo" | "live" => status?.hub.mode ?? "demo";
export const opState = (): OpState | null => status?.hub.state ?? null;

export function onStatus(fn: (s: Status) => void): () => void {
  subs.add(fn);
  if (status) fn(status);
  return () => subs.delete(fn);
}

export async function refreshStatus(): Promise<Status | null> {
  try {
    const next = await get<Status>("/api/status");
    // an older backend does not send `state`: derive the same value so the UI never disagrees with itself
    next.hub.state ??= next.hub.mode === "demo" ? "demo" : next.hub.stream_live ? "live" : "standby";
    status = next;
    const previous = lastMode;
    lastMode = next.hub.mode;
    subs.forEach((f) => f(next));
    if (previous !== null && previous !== next.hub.mode) modeSubs.forEach((f) => f(next.hub.mode, previous));
  } catch {
    /* the shell shows the connection state; a failed refresh keeps the last known status */
  }
  return status;
}

/** Forget everything about the session (sign-out), so a new sign-in never starts from the previous mode. */
export function resetState(): void {
  status = null;
  lastMode = null;
}
