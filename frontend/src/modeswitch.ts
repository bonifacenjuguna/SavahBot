/** The application-level mode control: Demo, Standby and Live in one component, driven only by the central status. */
import { confirmDialog, h, mount, toast } from "./dom.js";
import { icon } from "./icons.js";
import { refreshStatus, type OpState, type Status } from "./state.js";

const SEGMENTS: { state: OpState; label: string; icon: string; target: "demo" | "live" }[] = [
  { state: "demo", label: "Demo", icon: "flask", target: "demo" },
  { state: "standby", label: "Standby", icon: "clock", target: "live" },
  { state: "live", label: "Live", icon: "zap", target: "live" },
];

export function describeState(s: Status | null): { state: OpState; title: string; detail: string } {
  if (!s) return { state: "standby", title: "Connecting", detail: "Waiting for the backend" };
  const state = s.hub.state;
  if (state === "demo") return { state, title: "Demo", detail: "Simulated chat. Nothing is sent to YouTube or Telegram." };
  if (state === "live") return { state, title: "Live", detail: s.hub.stream_title ? `On air: ${s.hub.stream_title}` : "On air. Reading the YouTube live chat." };
  return { state, title: "Standby", detail: s.youtube.connected ? "Live mode is on. Waiting for your stream to start." : "Live mode is on, but YouTube is not connected. Open Setup." };
}

export interface ModeControl { el: HTMLElement; update(s: Status): void }

/** `setMode` posts the change; the control then waits for the real status instead of assuming the change worked. */
export function modeControl(setMode: (m: "demo" | "live") => Promise<void>, variant: "rail" | "sheet", onDone?: () => void): ModeControl {
  const buttons = SEGMENTS.map((seg) => h("button", { type: "button", "data-s": seg.state, "aria-pressed": "false", title: seg.label }, icon(seg.icon, 15), h("span", { class: "lbl" }, seg.label)));
  const seg = h("div", { class: "mode-seg", role: "group", "aria-label": "Bot mode" }, buttons);
  const caption = h("p", { class: "mode-cap", role: "status" }, "");
  const el = h("div", { class: `modebox ${variant}` }, seg, caption);
  let current: Status | null = null;
  let working = false;

  const choose = async (target: "demo" | "live") => {
    if (working || !current) return;
    if (current.hub.mode === target) return;
    if (target === "live") {
      const auto = current.hub.mod_mode === "auto";
      const ok = await confirmDialog("Switch to Live?",
        `The bot will read your real YouTube chat. ${auto ? "Moderation is on Auto, so it can delete messages and time out viewers without asking." : current.hub.mod_mode === "suggest" ? "Moderation is on Suggest, so it will ask you before acting." : "Moderation is Off, so it will only log."} Demo data stays separate and is hidden while Live is on.`,
        "Switch to Live");
      if (!ok) return;
    }
    working = true;
    buttons.forEach((b) => (b.disabled = true));
    try {
      await setMode(target);
      onDone?.();
    } catch (e) {
      toast((e as Error).message, "error");
      await refreshStatus();
    } finally {
      working = false;
      buttons.forEach((b) => (b.disabled = false));
    }
  };
  buttons.forEach((b, i) => b.addEventListener("click", () => void choose(SEGMENTS[i].target)));

  return {
    el,
    update(s) {
      current = s;
      const d = describeState(s);
      buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-s") === d.state)));
      mount(caption, d.detail);
      el.setAttribute("data-state", d.state);
    },
  };
}
