import { get, patch } from "../api.js";
import { h, mount, toast } from "../dom.js";
import { empty, pageHead } from "./shared.js";
import { gesture, setGesture, type Gesture } from "../chat-actions.js";
import type { Page } from "./types.js";

interface Item { name: string; value: string | number | boolean }

/** One place for everything that reacts to what happens on stream: live stats, subscriber alerts, members and Super Chats. Each control saves as you change it. */
async function render(body: HTMLElement): Promise<void> {
  const [snap, live] = await Promise.all([get<{ items: Item[] }>("/api/settings"), get<{ subscribers: { state: string; note: string }; cost_per_hour: number }>("/api/live/stats")]);
  const v = (n: string) => snap.items.find((i) => i.name === n)?.value;
  const save = async (name: string, value: unknown) => { try { await patch("/api/settings", { values: { [name]: value } }); toast("Saved"); } catch (e) { toast(e instanceof Error ? e.message : "Could not save"); } };
  const row = (title: string, hint: string, control: Node) => h("div", { class: "row between", style: "align-items:center;gap:12px;padding:10px 0;border-top:1px solid var(--line)" }, h("div", { style: "min-width:0" }, h("strong", null, title), h("div", { class: "muted small" }, hint)), control);
  const sw = (name: string, label: string) => h("input", { type: "checkbox", class: "switch", checked: Boolean(v(name)), "aria-label": label, onchange: (e: Event) => void save(name, (e.target as HTMLInputElement).checked) });
  const nm = (name: string, min: number, max: number, unit: string) => {
    const i = h("input", { type: "number", min, max, value: String(v(name) ?? ""), style: "width:90px", "aria-label": unit, onchange: () => { const n = Number(i.value); if (!Number.isFinite(n) || n < min || n > max) { toast(`Use a number from ${min} to ${max}`); i.value = String(v(name)); return; } void save(name, n); } }) as HTMLInputElement;
    return h("span", { class: "row", style: "gap:6px;align-items:center" }, i, h("span", { class: "muted small" }, unit));
  };
  const tx = (name: string, label: string) => {
    const i = h("input", { type: "text", value: String(v(name) ?? ""), maxlength: 200, "aria-label": label, style: "width:100%", onchange: () => void save(name, i.value) }) as HTMLInputElement;
    return h("label", { class: "field", style: "margin-top:8px" }, label, i);
  };
  const g = h("select", { "aria-label": "How to open the message actions", onchange: (e: Event) => { setGesture((e.target as HTMLSelectElement).value as Gesture); toast("Saved on this device"); } },
    ...([["longpress", "Press and hold"], ["tap", "Tap once"], ["doubletap", "Double tap"]] as const).map(([k, l]) => h("option", { value: k, selected: gesture() === k }, l)));
  mount(body,
    h("div", { class: "sp-card" }, h("h3", null, "Chat actions"),
      h("p", { class: "muted small" }, "Open the action sheet on a chat line to copy, reply, pin, delete, time out or ban. A right click opens it on a computer too. Pins are only on this device: YouTube has no pin for live chat."),
      row("Open the sheet with", "This is remembered on this device only.", g)),
    h("div", { class: "sp-card" }, h("h3", null, "Live stats"),
      h("p", { class: "muted small" }, "Likes and people watching, on the Desk and in Insights. YouTube decides what it shares: likes can be hidden by the creator, and viewer counts lag."),
      row("Track likes and viewers", "Off: nothing is asked of YouTube.", sw("yt_live_enabled", "Track likes and viewers")),
      row("Refresh every", `Each refresh costs about 1 quota unit. At this setting that is about ${live.cost_per_hour} per hour of stream.`, nm("yt_live_seconds", 30, 600, "seconds")),
      row("Alert on likes", "Notify each time likes pass a multiple of this. 0 is off.", nm("yt_live_likes_step", 0, 100000, "likes")),
      row("Alert on viewers", "Notify the first time viewers pass a multiple of this in a stream. 0 is off.", nm("yt_live_viewers_step", 0, 100000, "viewers")),
      h("p", { class: "muted small" }, "In commands, timers and messages, $(likes), $(viewers) and $(subs) show the latest numbers.")),
    h("div", { class: "sp-card" }, h("h3", null, "Subscriber alerts"),
      h("p", { class: "muted small wrap" }, "While you are live the bot checks YouTube for new subscribers. This is best effort: only people who made their subscription public appear by name, so some are missed. The channel's subscriber count is checked too, for milestones."),
      live.subscribers.note ? h("p", { class: "muted small wrap" }, `Status: ${live.subscribers.note}`) : null,
      row("Look for new subscribers", "Needs your Google sign-in to allow it. If YouTube refuses, the status above says what to do.", sw("yt_subs_enabled", "Look for new subscribers")),
      row("Check every", "About 1 quota unit per check (plus 1 for the count).", nm("yt_subs_minutes", 5, 120, "minutes")),
      row("Subscriber milestones", "Notify each time the count passes a multiple of this. 0 is off.", nm("yt_subs_milestone_step", 0, 1000000, "subscribers")),
      row("Thank them in chat", "Posts the message below for a subscriber seen by name. Costs quota per message.", sw("yt_subs_thank", "Thank new subscribers in chat")),
      tx("yt_subs_msg", "Thank-you message ($(user) is filled in)")),
    h("div", { class: "sp-card" }, h("h3", null, "Members, Super Chats and gifts"),
      h("p", { class: "muted small" }, "New members, Super Chats, Super Stickers and membership gifts are recognised in chat. Only who, what kind and how much is kept, never the message."),
      row("Tell me about them", "A notification for each one. Which channels carry it is set in Notifications, Categories.", sw("yt_events_notify", "Notify about stream events")),
      row("Thank them in chat", "Off by default: every thank-you is a chat message and costs quota.", sw("yt_events_thank", "Thank in chat")),
      tx("yt_events_msg_member", "New member ($(user), $(count))"), tx("yt_events_msg_superchat", "Super Chat or Super Sticker ($(user), $(amount))"), tx("yt_events_msg_gift", "Membership gift ($(user), $(count))")));
}

export const streamSettings: Page = {
  id: "stream-settings", title: "Stream alerts", icon: "radio", blurb: "Live stats, subscribers, members and Super Chats",
  render(root) {
    const body = h("div", { class: "stack" }, h("p", { class: "muted" }, "Loading…"));
    mount(root, h("div", { class: "page" }, pageHead("radio", "Stream alerts", "What the bot watches for while you are live.", h("a", { class: "btn small", href: "#/settings" }, "Back to Settings")), body));
    void render(body).catch(() => mount(body, empty("alert", "Settings could not load.")));
  },
};
