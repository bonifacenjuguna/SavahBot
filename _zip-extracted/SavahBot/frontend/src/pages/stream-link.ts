import { post } from "../api.js";
import { busy, h, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { refreshStatus, status, type Status } from "../state.js";

/** The same reading the server does: a bare 11-character ID, or a watch / youtu.be / live / shorts / embed link. Empty string when it is neither. */
export function videoIdOf(raw: string): string {
  const v = raw.trim();
  const m = /(?:v=|youtu\.be\/|\/live\/|\/shorts\/|\/embed\/)([0-9A-Za-z_-]{11})/.exec(v);
  if (m) return m[1];
  return /^[0-9A-Za-z_-]{11}$/.test(v) ? v : "";
}

type Source = NonNullable<Status["youtube"]["source"]>;

/**
 * A shortcut to "Where the stream comes from" (it lives in Setup > YouTube), so the link can be pasted from the Desk, mid-stream, in two taps.
 * It saves through the same endpoint as Setup, so the two can never disagree.
 */
export function openStreamLink(): { close: () => void } {
  const body = h("div", { class: "stack stream-link" });
  const box: { close: () => void } = { close: () => undefined };

  const draw = () => {
    const yt = status?.youtube;
    const src: Source = yt?.source ?? { auto_detect: true, video: "", video_raw: "", mode: "auto" };
    const attached = yt?.chat_attached ? (yt.title || yt.video_id || "a live stream") : "";
    const demo = status?.hub.mode === "demo";

    const field = h("input", { type: "text", class: "input", inputMode: "url", value: src.video_raw, placeholder: "https://www.youtube.com/watch?v=…  or the 11-character ID",
      autocomplete: "off", autocapitalize: "off", spellcheck: false, "aria-label": "Live video link or ID" }) as HTMLInputElement;
    const hint = h("p", { class: "muted small sl-hint", role: "status" });
    const paint = () => {
      const raw = field.value.trim();
      const id = videoIdOf(raw);
      hint.className = `small sl-hint ${!raw ? "muted" : id ? "ok" : "bad"}`;
      mount(hint, !raw ? "Paste the link of the stream you are about to start, or its ID." : id ? [icon("checkCircle", 14), ` Video ID ${id}`] : [icon("alert", 14), " That does not look like a YouTube video link or ID."]);
      use.disabled = !id;
    };
    const save = async (payload: Record<string, unknown>, done: string) => {
      try {
        const r = await post<{ title?: string; live?: boolean }>("/api/youtube/source", payload);
        toast(r.title ? `${done}: ${r.title}${r.live === false ? " (not live yet)" : ""}` : done);
        await refreshStatus();
        draw();
      } catch (e) { toast(e instanceof Error ? e.message : "Could not save", "error"); }
    };
    const use = h("button", { class: "btn primary", type: "button", disabled: true, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, () => save({ video: field.value }, "Linked")) }, icon("link", 16), "Use this video");
    const pasteBtn = h("button", { class: "btn", type: "button", onclick: async () => {
      try { field.value = (await navigator.clipboard.readText()).trim(); paint(); field.focus({ preventScroll: true }); if (videoIdOf(field.value)) use.focus(); }
      catch { toast("Your browser did not allow reading the clipboard. Paste into the box by hand.", "error"); }
    } }, icon("copy", 16), "Paste");
    field.addEventListener("input", paint);
    field.addEventListener("keydown", (e) => { if (e.key === "Enter" && !use.disabled) { e.preventDefault(); use.click(); } });

    const modeText = demo ? "Demo mode is on, so nothing is attached to YouTube. Switch to Live to use a link."
      : src.mode === "link" ? "Using your link. When that video is not live it goes back to searching, if auto-search is on."
      : src.mode === "auto" ? "Searching your channel for a live stream automatically."
      : "Nothing to attach to: auto-search is off and no link is set.";
    const watchId = yt?.video_id || src.video;
    mount(body,
      h("div", { class: `banner${attached ? " demo" : ""}`, style: "display:flex;align-items:center;gap:10px" }, icon(attached ? "radio" : "youtube", 18),
        h("span", { class: "grow" }, attached ? h("span", null, h("strong", null, "Attached now: "), attached) : modeText),
        watchId ? h("a", { class: "btn small ghost", href: `https://www.youtube.com/watch?v=${watchId}`, target: "_blank", rel: "noopener noreferrer" }, icon("external", 14), "Open") : null),
      attached ? h("p", { class: "muted small" }, modeText) : null,
      h("label", { class: "stack", style: "gap:6px" }, h("strong", null, "Stream link or ID"), field),
      hint,
      h("div", { class: "row wrap", style: "gap:8px" }, use, pasteBtn,
        src.video ? h("button", { class: "btn ghost", type: "button", onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, () => save({ video: "" }, "Link cleared")) }, "Clear link") : null),
      h("label", { class: "row between", style: "align-items:center;gap:12px" },
        h("span", null, h("strong", null, "Search for the live stream automatically"), h("span", { class: "muted small", style: "display:block" }, "Costs YouTube quota. Turn it off if you always paste a link.")),
        h("input", { type: "checkbox", class: "switch", checked: src.auto_detect, "aria-label": "Search automatically",
          onchange: (e: Event) => { const on = (e.target as HTMLInputElement).checked; void save({ auto_detect: on }, on ? "Auto-search is on" : "Auto-search is off"); } })),
      h("p", { class: "muted small" }, "It must be a live video of the channel you moderate. A link from another channel is refused. The full setup is in ", h("a", { href: "/setup", onclick: () => box.close() }, "Setup"), "."));
    paint();
  };
  draw();
  Object.assign(box, sheet("Stream link", body));
  return box;
}
