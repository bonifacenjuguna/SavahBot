/** Setup progress shared by the Setup page, the sidebar nudge and the More sheet, so every place shows the same numbers. */
import { get } from "./api.js";
import type { Status } from "./state.js";

export interface SetupInfo {
  requirements: Record<string, { env: string; set: boolean }[]>;
  public_url: string; telegram_webhook_url: string; google_redirect_uri: string;
  youtube_connected: boolean; telegram_owner_bound: boolean; telegram_bot: string | null;
}

export type SetupSection = "overview" | "addresses" | "youtube" | "telegram" | "checks" | "variables";

export interface Step { id: string; section: SetupSection; title: string; text: string; done: boolean }

export function computeSteps(s: SetupInfo, st: Status | null): Step[] {
  const yt = st?.youtube, tg = st?.telegram;
  return [
    { id: "url", section: "addresses", title: "Public address", done: !!s.public_url, text: s.public_url || "Set PUBLIC_BASE_URL in Railway" },
    { id: "token", section: "telegram", title: "Telegram bot token", done: !!tg?.configured, text: tg?.configured ? `Bot @${s.telegram_bot ?? "connected"}` : "Create a bot with @BotFather and set TELEGRAM_BOT_TOKEN" },
    { id: "claim", section: "telegram", title: "Claim the bot", done: !!s.telegram_owner_bound, text: s.telegram_owner_bound ? "Only your account can use it" : "Send /claim and your dashboard password to the bot" },
    { id: "google", section: "youtube", title: "Google account", done: !!s.youtube_connected, text: s.youtube_connected ? (yt?.account?.title || "Connected") : "Press Connect Google account" },
    { id: "target", section: "youtube", title: "Target channel", done: !!yt?.target, text: yt?.target ? (yt.target.title || yt.target.channel_id) : "Choose the channel whose live chat you moderate" },
  ];
}

export function hasProblem(st: Status | null): boolean {
  return !!(st?.youtube.last_error || st?.telegram.last_error);
}

let info: SetupInfo | null = null;
const subs = new Set<(i: SetupInfo) => void>();

export const setupInfo = (): SetupInfo | null => info;
export function setSetup(i: SetupInfo): void { info = i; subs.forEach((f) => f(i)); }
export function onSetup(fn: (i: SetupInfo) => void): () => void { subs.add(fn); if (info) fn(info); return () => subs.delete(fn); }

export async function loadSetup(): Promise<SetupInfo | null> {
  try { setSetup(await get<SetupInfo>("/api/setup")); } catch { /* keep the last known value */ }
  return info;
}
