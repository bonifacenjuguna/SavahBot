import { get, post } from "./api.js";
import { h, mount, sheet, toast, toastAction } from "./dom.js";
import { icon } from "./icons.js";

/** What the sheet needs to know about one chat line. */
export interface ChatLine { id?: number; author_id?: string; platform?: string; author_name: string; text: string; level: string; ts: number; verdict: string | null; demo?: boolean; reasons?: string[] }
export interface ActionCtx {
  /** Puts "@name " in the message box so the owner can answer as the bot. */
  reply(name: string): void;
  /** Items other features add to the sheet (the chat reader adds Read aloud here). */
  extra?(m: ChatLine, close: () => void): HTMLElement[];
  /** Starts multi-select with this line ticked. */
  select(m: ChatLine): void;
  /** Called after a pin change so the strip above the chat can redraw. */
  pinsChanged(): void;
}

export type Gesture = "longpress" | "tap" | "doubletap";
const GESTURE_KEY = "savah.chat.gesture", PIN_KEY = "savah.chat.pins";
export const gesture = (): Gesture => { try { const v = localStorage.getItem(GESTURE_KEY); return v === "tap" || v === "doubletap" ? v : "longpress"; } catch { return "longpress"; } };
export const setGesture = (g: Gesture): void => { try { localStorage.setItem(GESTURE_KEY, g); } catch { /* private mode */ } };

/** Pins live on this device only: YouTube has no pin for live chat, so this is the dashboard's own sticky list, never shown to viewers. */
export interface Pin { author_name: string; text: string; ts: number }
export const pins = (): Pin[] => { try { return JSON.parse(localStorage.getItem(PIN_KEY) || "[]") as Pin[]; } catch { return []; } };
const savePins = (p: Pin[]) => { try { localStorage.setItem(PIN_KEY, JSON.stringify(p.slice(0, 20))); } catch { /* private mode */ } };
const isPinned = (m: ChatLine) => pins().some((p) => p.ts === m.ts && p.author_name === m.author_name);

const buzz = (ms = 12) => { try { navigator.vibrate?.(ms); } catch { /* not supported */ } };
const copy = async (text: string, what: string) => { try { await navigator.clipboard.writeText(text); toast(`${what} copied`); } catch { toast("Your browser blocked copying", "error"); } };
const TIMEOUTS: [string, number][] = [["1 min", 60], ["5 min", 300], ["10 min", 600], ["1 hour", 3600], ["24 hours", 86400]];

/** Wires one chat line: long press (default), tap or double tap opens the sheet, and a right click does too. Text selection still works on desktop. */
export function wireLine(el: HTMLElement, m: ChatLine, ctx: ActionCtx): void {
  let timer = 0, sx = 0, sy = 0, last = 0;
  const open = () => { buzz(); openSheet(m, ctx); };
  el.addEventListener("contextmenu", (e) => { e.preventDefault(); open(); });
  el.addEventListener("pointerdown", (e) => {
    if (gesture() !== "longpress" || (e.pointerType === "mouse" && e.button !== 0)) return;
    sx = e.clientX; sy = e.clientY;
    timer = window.setTimeout(open, 480);
  });
  const cancel = () => clearTimeout(timer);
  el.addEventListener("pointermove", (e) => { if (Math.abs(e.clientX - sx) > 8 || Math.abs(e.clientY - sy) > 8) cancel(); });
  ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, cancel));
  el.addEventListener("click", () => {
    const g = gesture();
    if (el.closest(".chat-main")?.querySelector(".sel-bar:not([hidden])")) return;   // picking several lines: a tap just ticks the line
    if (window.getSelection()?.toString()) return;          // someone is selecting text: do not interrupt
    if (g === "tap") open();
    else if (g === "doubletap") { const now = Date.now(); if (now - last < 350) open(); last = now; }
  });
}

async function act(m: ChatLine, action: "delete" | "timeout" | "ban", seconds = 300, done?: () => void): Promise<void> {
  if (m.id === undefined) { toast("This line cannot be acted on yet. Try again in a moment.", "error"); return; }
  try {
    const r = await post<{ ban_id: number | null; simulated: boolean }>("/api/chat/act", { id: m.id, action, seconds });
    buzz(20); done?.();
    const what = action === "delete" ? "Message deleted" : action === "ban" ? `${m.author_name} banned` : `${m.author_name} timed out`;
    if (r.ban_id) toastAction(`${what}${r.simulated ? " (demo)" : ""}`, "Undo", async () => { await post(`/api/bans/${r.ban_id}/lift`); toast("Undone"); }, 10_000);
    else toast(`${what}${r.simulated ? " (demo)" : ""}`);
  } catch (e) { toast(e instanceof Error ? e.message : "That did not work", "error"); }
}

/** Delete, timeout and ban ask first, and say what they cost in YouTube quota. */
async function confirmAction(m: ChatLine, action: "delete" | "timeout" | "ban", seconds: number, label: string, run: () => void): Promise<void> {
  let cost = "";
  try { const k = await get<{ delete: number; timeout: number; ban: number; remaining: number }>("/api/chat/costs"); cost = m.demo ? "Demo: nothing is sent to YouTube." : `Costs about ${k[action]} YouTube quota units (${k.remaining.toLocaleString()} left today).`; } catch { /* the cost line is optional */ }
  const go = h("button", { class: "btn primary danger", type: "button" }, label);
  const no = h("button", { class: "btn ghost", type: "button" }, "Cancel");
  const box = sheet(label, h("div", { class: "stack" }, h("p", { class: "wrap" }, action === "delete" ? `Delete ${m.author_name}'s message?` : `${label} ${m.author_name}?`), cost ? h("p", { class: "muted small" }, cost) : null, h("div", { class: "row", style: "gap:8px" }, go, no)));
  go.onclick = () => { box.close(); run(); }; no.onclick = () => box.close();
}

async function personCard(m: ChatLine): Promise<void> {
  const body = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
  sheet(m.author_name, body);
  try {
    const p = await get<{ messages: number; first_seen: number | null; recent: { ts: number; body: string; verdict: string }[]; actions: { ts: number; kind: string; status: string }[]; notes: { body: string }[]; regular: boolean }>(`/api/chat/person?author_id=${encodeURIComponent(m.author_id ?? "")}&platform=${m.platform ?? "youtube"}`);
    const when = (t: number) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    mount(body,
      h("p", null, `${p.messages.toLocaleString()} message${p.messages === 1 ? "" : "s"} stored`, p.first_seen ? ` · first seen ${when(p.first_seen)}` : "", p.regular ? " · regular" : ""),
      p.actions.length ? h("div", null, h("strong", null, "Bans and timeouts"), ...p.actions.map((a) => h("div", { class: "muted small" }, `${when(a.ts)}: ${a.kind}, ${a.status}`))) : h("p", { class: "muted small" }, "Never banned or timed out."),
      p.notes.length ? h("div", null, h("strong", null, "Notes"), ...p.notes.map((n) => h("div", { class: "muted small wrap" }, n.body))) : null,
      h("div", null, h("strong", null, "Recent messages"), ...(p.recent.length ? p.recent.map((r) => h("div", { class: "muted small wrap" }, `${when(r.ts)}: ${r.body}${r.verdict !== "allow" ? ` (${r.verdict})` : ""}`)) : [h("div", { class: "muted small" }, "None stored.")])));
  } catch (e) { mount(body, h("p", { class: "muted" }, e instanceof Error ? e.message : "Could not load")); }
}

export function openSheet(m: ChatLine, ctx: ActionCtx): void {
  const it = (ic: string, label: string, run: () => void, tone = "") => {
    const b = h("button", { class: `sheet-item ${tone}`.trim(), type: "button", style: "display:flex;gap:10px;align-items:center;width:100%;text-align:left;padding:12px 4px;background:none;border:0;border-top:1px solid var(--line);color:inherit;font:inherit;cursor:pointer" }, icon(ic, 18), h("span", null, label));
    b.onclick = () => { box.close(); run(); };
    return b;
  };
  const group = (title: string, ...items: (HTMLElement | null)[]) => h("div", null, h("div", { class: "muted small", style: "margin:12px 0 2px" }, title), ...items.filter(Boolean) as HTMLElement[]);
  const flagged = m.verdict && m.verdict !== "allow";
  const canAct = m.level !== "owner" && m.level !== "bot";
  const body = h("div", null,
    h("div", { class: "wrap", style: "padding:4px 0 8px" }, h("strong", null, m.author_name), h("div", { class: "muted small wrap" }, m.text)),
    group("Copy", it("copy", "Copy text", () => void copy(m.text, "Text")), it("user", "Copy username", () => void copy(m.author_name, "Username")), it("message", "Copy as quote", () => void copy(`> ${m.author_name}: ${m.text}`, "Quote"))),
    group("Chat", it("send", `Reply as the bot to ${m.author_name}`, () => ctx.reply(m.author_name)),
      it("pin", isPinned(m) ? "Unpin from my dashboard" : "Pin on my dashboard (only you see it)", () => { const all = pins(); savePins(isPinned(m) ? all.filter((p) => !(p.ts === m.ts && p.author_name === m.author_name)) : [{ author_name: m.author_name, text: m.text, ts: m.ts }, ...all]); ctx.pinsChanged(); }),
      it("check", "Select several messages", () => ctx.select(m)), ...(ctx.extra?.(m, () => box.close()) ?? [])),
    group("This person", it("user", `About ${m.author_name}`, () => void personCard(m)),
      it("edit", "Add a note to the Notebook", () => void post("/api/notes", { body: `@${m.author_name}: ${m.text}`.slice(0, 1000), tags: ["chat"], pinned: false }).then(() => toast("Added to the Notebook")).catch((e) => toast(e.message, "error")))),
    flagged ? group("Moderation", it("flag", "Why it was flagged", () => toast(m.reasons?.length ? `Flagged for: ${m.reasons.join(", ")}` : "The bot flagged this message; details are on the Moderation page.")),
      it("shield", "Teach the bot: this is spam", () => void post("/api/knowledge/lessons", { label: "spam", text: m.text, author: m.author_name }).then(() => toast("Learned as spam")).catch((e) => toast(e.message, "error"))),
      it("check", "Teach the bot: this is fine", () => void post("/api/knowledge/lessons", { label: "ham", text: m.text, author: m.author_name }).then(() => toast("Learned as fine")).catch((e) => toast(e.message, "error")))) : group("Moderation",
      it("shield", "Teach the bot: this is spam", () => void post("/api/knowledge/lessons", { label: "spam", text: m.text, author: m.author_name }).then(() => toast("Learned as spam")).catch((e) => toast(e.message, "error")))),
    group("Block this phrase", it("ban", "Add this message to the blocked phrases", () => void post("/api/blacklist", { phrase: m.text.slice(0, 200), is_regex: false, weight: 0, enabled: true }).then(() => toast("Added to blocked phrases")).catch((e) => toast(e.message, "error")))),
    canAct ? group("Act on the channel", it("trash", "Delete message", () => void confirmAction(m, "delete", 0, "Delete", () => void act(m, "delete")), "danger"),
      ...TIMEOUTS.map(([l, s]) => it("timer", `Time out ${l}`, () => void confirmAction(m, "timeout", s, `Time out ${l}`, () => void act(m, "timeout", s)), "danger")),
      it("ban", `Ban ${m.author_name}`, () => void confirmAction(m, "ban", 0, "Ban", () => void act(m, "ban")), "danger")) : null);
  const box = sheet("Message", body);
}
