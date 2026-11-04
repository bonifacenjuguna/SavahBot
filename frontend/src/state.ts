import { get } from "./api.js";

export interface Status {
  app: string;
  version: string;
  timezone: string;
  hub: {
    mode: "demo" | "live";
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
  };
  demo: { state: string; ambient: boolean; scenarios_running: string[]; channel: string };
  pending: number;
  database: string;
  uptime: number;
  sse_clients: number;
}

export let status: Status | null = null;
const subs = new Set<(s: Status) => void>();

export function onStatus(fn: (s: Status) => void): () => void {
  subs.add(fn);
  if (status) fn(status);
  return () => subs.delete(fn);
}

export async function refreshStatus(): Promise<Status | null> {
  try {
    status = await get<Status>("/api/status");
    subs.forEach((f) => f(status!));
  } catch {
    /* the shell shows the connection state; a failed refresh keeps the last known status */
  }
  return status;
}
