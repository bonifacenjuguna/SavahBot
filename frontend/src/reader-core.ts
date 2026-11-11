/** The chat reader's decisions, with no browser parts, so they can be tested on their own: who gets read, and what is said. */
export interface UserRule { mode: "always" | "never" | "voice"; voice: string; name: string }
export interface Rules {
  who: "everyone" | "mods" | "members" | "owner" | "chosen" | "prefix";
  prefix: string; say_name: boolean; skip_links: boolean; skip_emoji: boolean; shorten: number; collapse_repeats: boolean; drop_backlog: number;
  users: Record<string, UserRule>; dictionary: { from: string; to: string }[];
}
export interface Msg { author_id?: string; author_name: string; text: string; level: string; verdict: string | null; ts: number; /** when the dashboard received the line (ms); age is judged from this, not from `ts`, which is YouTube's publish time on another clock */ arrived?: number }

export const DEFAULT_RULES: Rules = { who: "everyone", prefix: "!say", say_name: true, skip_links: true, skip_emoji: true, shorten: 160, collapse_repeats: true, drop_backlog: 15, users: {}, dictionary: [] };

const MOD = new Set(["mod", "owner"]), MEMBER = new Set(["member", "mod", "owner"]);

/** Never reads a message the bot held, blocked or flagged: they are not "clean" yet, and reading them out would repeat exactly what moderation is keeping off the stream. */
export function shouldRead(m: Msg, r: Rules, now = Date.now() / 1000): boolean {
  if (m.level === "bot") return false;
  if (m.verdict && m.verdict !== "allow") return false;
  const u = m.author_id ? r.users[m.author_id] : undefined;
  if (u?.mode === "never") return false;
  // Age is counted from when this dashboard received the line. YouTube's own publish time runs behind by the polling gap and by any
  // difference between the server clock and this phone's clock, which made nearly every real line look "too old" and silently skipped.
  const age = m.arrived !== undefined ? now - m.arrived / 1000 : now - m.ts;
  if (r.drop_backlog > 0 && age > r.drop_backlog) return false;
  if (u?.mode === "always" || u?.mode === "voice") return true;
  switch (r.who) {
    case "mods": return MOD.has(m.level);
    case "members": return MEMBER.has(m.level);
    case "owner": return m.level === "owner";
    case "chosen": return false;                                   // only people marked "always read"
    case "prefix": return r.prefix !== "" && m.text.trimStart().toLowerCase().startsWith(r.prefix.toLowerCase());
    default: return true;
  }
}

const URL_RE = /\b(?:https?:\/\/|www\.)\S+/gi;
const EMOJI_RE = /[\p{Extended_Pictographic}‍️]/gu;
const ESC = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** What is actually spoken for a message, or "" when nothing is left to say. */
export function prepare(m: Msg, r: Rules): string {
  let t = m.text;
  if (r.who === "prefix" && r.prefix && !r.users[m.author_id ?? ""]) t = t.trimStart().slice(r.prefix.length);
  if (r.skip_links) t = t.replace(URL_RE, " link ");
  if (r.skip_emoji) t = t.replace(EMOJI_RE, "");
  for (const d of r.dictionary) if (d.from) t = t.replace(new RegExp(`(^|\\W)${ESC(d.from)}(?=$|\\W)`, "gi"), (_, pre: string) => `${pre}${d.to}`);
  if (r.collapse_repeats) t = t.replace(/(.)\1{3,}/gu, "$1$1$1").replace(/\b(\w+)(\s+\1\b){2,}/gi, "$1");
  t = t.replace(/\s+/g, " ").trim();
  if (!/[\p{L}\p{N}]/u.test(t)) return "";
  if (t.length > r.shorten) t = t.slice(0, r.shorten).replace(/\s+\S*$/, "") + " and more";
  return r.say_name ? `${m.author_name} says ${t}` : t;
}

/** The voice to use for this author, if their rule picks one. */
export const voiceFor = (m: Msg, r: Rules): string => (m.author_id ? r.users[m.author_id] : undefined)?.mode === "voice" ? r.users[m.author_id as string].voice : "";

export const KOKORO_MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
export const KOKORO_ORIGIN = `https://huggingface.co/${KOKORO_MODEL}/resolve/main/`;
/** Where a model file should really come from: your own pack or host when one is chosen, otherwise the public one. Anything else is left alone. */
export function rewriteModelUrl(url: string, base: string): string {
  return base && url.startsWith(KOKORO_ORIGIN) ? `${base.replace(/\/+$/, "")}/${url.slice(KOKORO_ORIGIN.length)}` : url;
}
export const KOKORO_VOICES: [string, string][] = [["af_heart", "Heart (US, female)"], ["af_bella", "Bella (US, female)"], ["af_nicole", "Nicole (US, female)"], ["am_adam", "Adam (US, male)"], ["am_michael", "Michael (US, male)"], ["bf_emma", "Emma (UK, female)"], ["bm_george", "George (UK, male)"]];
