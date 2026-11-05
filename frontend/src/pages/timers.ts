import { get, patch, post } from "../api.js";
import { ago, busy, confirmDialog, dateTime, debounce, duration, h, inUntil, mount, sheet, toast } from "../dom.js";
import { icon } from "../icons.js";
import { empty } from "./shared.js";

export interface Timer {
  id: number; name: string; message: string; interval_seconds: number; min_lines: number; enabled: boolean; kind: "recurring" | "once";
  trigger_mode: "all" | "any"; run_at: number | null; done: boolean; last_fired: number; fired: number; last_error: string;
  progress: { state: string; lines_since: number; lines_needed: number; next_run_at: number | null };
}
interface Run { id: number; timer_id: number; timer_name: string; ts: number; ok: boolean; error: string; demo: boolean }

/** Plain-language trigger summary. The wording matches what the scheduler really does. */
export function triggerText(t: Timer): string {
  if (t.kind === "once") return t.run_at ? `Once, not before ${dateTime(t.run_at)}` : "Once, as soon as the stream is live";
  const time = t.interval_seconds ? `every ${duration(t.interval_seconds)}` : "";
  const lines = t.min_lines ? `${t.min_lines} new chat lines` : "";
  if (time && lines) return t.trigger_mode === "any" ? `${time} or after ${lines}` : `${time} and after ${lines}`;
  return time ? `Posts ${time}` : `Posts after ${lines}`;
}

const stateChip = (t: Timer): [string, string] => {
  if (t.kind === "once" && t.done) return ["ok", "Sent"];
  if (!t.enabled) return ["", "Off"];
  return t.progress.state === "waiting" ? ["ok", "Waiting for trigger"] : ["warn", "Paused: no live stream"];
};

export function timersPanel(): { el: HTMLElement; load: () => Promise<void> } {
  let items: Timer[] = [];
  let needle = "";
  const picked = new Set<number>();
  const el = h("div");
  const bar = h("div", { class: "bulkbar", hidden: true });
  const listBox = h("div");

  const reload = async () => {
    items = (await get<{ items: Timer[] }>("/api/timers")).items;
    for (const id of Array.from(picked)) if (!items.some((t) => t.id === id)) picked.delete(id);
    draw();
  };
  const bulk = async (action: string) => {
    const ids = Array.from(picked);
    if (action === "delete" && !(await confirmDialog(`Delete ${ids.length} timer${ids.length === 1 ? "" : "s"}?`, "Their settings and run history are removed.", "Delete", "danger"))) return;
    try { await post("/api/timers/bulk", { ids, action }); picked.clear(); await reload(); toast("Done"); } catch (e) { toast((e as Error).message, "error"); }
  };
  const drawBar = () => {
    bar.hidden = picked.size === 0;
    if (picked.size) mount(bar, h("strong", null, `${picked.size} selected`),
      h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("enable") }, "Enable"),
      h("button", { class: "btn small ghost", type: "button", onclick: () => void bulk("disable") }, "Disable"),
      h("button", { class: "btn small danger", type: "button", onclick: () => void bulk("delete") }, icon("trash", 14), "Delete"),
      h("button", { class: "btn small ghost", type: "button", onclick: () => { picked.clear(); draw(); } }, "Clear"));
  };

  const history = async (t: Timer) => {
    const r = await get<{ items: Run[] }>(`/api/timers/runs?timer_id=${t.id}&limit=50`);
    sheet(`History: ${t.name}`, r.items.length
      ? h("ul", { class: "list" }, r.items.map((x) => h("li", { class: "row between nowrap" }, h("span", null, dateTime(x.ts), x.demo ? h("span", { class: "chip", style: "margin-left:8px" }, "demo") : null), h("span", { class: `chip ${x.ok ? "ok" : "bad"}`, title: x.error }, x.ok ? "Posted" : "Failed"))))
      : empty("history", "This timer has not posted yet."));
  };

  const row = (t: Timer) => {
    const [tone, text] = stateChip(t);
    const sw = h("input", { type: "checkbox", class: "switch", checked: t.enabled, "aria-label": `Enable timer ${t.name}`, onchange: (e: Event) => {
      const v = (e.target as HTMLInputElement).checked;
      void patch(`/api/timers/${t.id}`, { enabled: v }).then(reload).catch((x) => { (e.target as HTMLInputElement).checked = !v; toast(x.message, "error"); });
    } });
    const next = t.enabled && !t.done && t.progress.next_run_at ? (t.progress.state === "waiting" ? `Next ${inUntil(t.progress.next_run_at)}` : "Next once the stream is live") : "";
    return h("li", { class: `timer-row${t.enabled ? "" : " off"}` },
      h("input", { type: "checkbox", checked: picked.has(t.id), "aria-label": `Select ${t.name}`, onchange: (e: Event) => { (e.target as HTMLInputElement).checked ? picked.add(t.id) : picked.delete(t.id); drawBar(); } }),
      h("div", { class: "grow" },
        h("div", { class: "row", style: "gap:6px" }, h("strong", null, t.name), h("span", { class: "chip" }, t.kind === "once" ? "One-time" : "Recurring"), h("span", { class: `chip ${tone}` }, text), t.last_error ? h("span", { class: "chip bad", title: t.last_error }, "Last post failed") : null),
        h("div", { class: "muted small" }, triggerText(t)),
        h("div", { class: "appr-msg" }, t.message),
        h("div", { class: "muted small" }, [t.fired ? `Posted ${t.fired} time${t.fired === 1 ? "" : "s"}, last ${ago(t.last_fired)}` : "Not posted yet", t.enabled && t.min_lines && t.progress.state === "waiting" ? `${t.progress.lines_needed} more chat lines needed` : "", next].filter(Boolean).join(" · "))),
      h("div", { class: "timer-actions" }, sw,
        h("button", { class: "icon-btn sm", type: "button", title: "Run history", "aria-label": `History of ${t.name}`, onclick: () => void history(t).catch((e) => toast(e.message, "error")) }, icon("history", 17)),
        h("button", { class: "icon-btn sm", type: "button", title: "Duplicate", "aria-label": `Duplicate ${t.name}`, onclick: (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/timers/${t.id}/duplicate`); await reload(); }, "Duplicated, switched off") }, icon("copy", 17)),
        h("button", { class: "icon-btn sm", type: "button", title: "Edit", "aria-label": `Edit ${t.name}`, onclick: () => editor(t) }, icon("pencil", 17))));
  };

  const draw = () => {
    const rows = items.filter((t) => !needle || `${t.name} ${t.message}`.toLowerCase().includes(needle));
    mount(listBox, rows.length ? h("ul", { class: "list" }, rows.map(row)) : items.length ? empty("search", "No timers match.")
      : h("div", { class: "empty" }, icon("timer", 28), h("span", null, "No timers yet. A timer posts a message by itself, only while a stream is live."), h("button", { class: "btn primary small", type: "button", onclick: () => editor() }, icon("plus", 15), "New timer")));
    drawBar();
  };

  // ----- editor
  const editor = (t?: Timer) => {
    let kind: "recurring" | "once" = t?.kind ?? "recurring";
    const name = h("input", { type: "text", value: t?.name ?? "", required: true, maxLength: 32, placeholder: "social" });
    const msg = h("textarea", { required: true, maxLength: 500, placeholder: "Enjoying the stream? Follow the channel!" }, t?.message ?? "");
    const mins = t?.interval_seconds ? t.interval_seconds / 60 : "";
    const time = h("input", { type: "number", min: 1, step: "any", value: String(mins), placeholder: "none", inputMode: "decimal" });
    const lines = h("input", { type: "number", min: 0, value: t?.min_lines ? String(t.min_lines) : (t ? "" : "10"), placeholder: "none", inputMode: "numeric" });
    const mode = h("select", null, h("option", { value: "all", selected: (t?.trigger_mode ?? "all") === "all" }, "Both are reached (and)"), h("option", { value: "any", selected: t?.trigger_mode === "any" }, "Either is reached (or)"));
    const when = h("input", { type: "datetime-local", value: t?.run_at ? new Date(t.run_at * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "" });
    const kindSeg = h("div", { class: "seg-control", role: "group", "aria-label": "Timer type" });
    const recurringBox = h("div", { class: "stack tight" }), onceBox = h("div", { class: "stack tight" });
    const hint = h("p", { class: "small", role: "alert" });
    const prev = h("div", { class: "reasons", "aria-live": "polite" });
    const save = h("button", { class: "btn primary", type: "submit" }, icon("check", 16), t ? "Save changes" : "Create timer");
    const holder: { close: () => void } = { close: () => undefined };

    const seconds = () => (time.value ? Math.round(Number(time.value) * 60) : 0);
    const problem = (): string => {
      if (kind === "once") return "";
      const s = seconds(), l = Number(lines.value || 0);
      if (!s && !l) return "Set a time, a number of chat lines, or both.";
      if (s && s < 60) return "Time between posts must be at least 1 minute.";
      return "";
    };
    const refresh = () => {
      mount(kindSeg, (["recurring", "once"] as const).map((k) => h("button", { type: "button", "aria-pressed": String(kind === k), onclick: () => { kind = k; refresh(); } }, k === "recurring" ? "Recurring" : "One-time")));
      recurringBox.hidden = kind !== "recurring"; onceBox.hidden = kind !== "once";
      mode.closest("label")!.hidden = !(seconds() && Number(lines.value || 0));
      const p = problem();
      hint.textContent = p; hint.style.color = p ? "var(--bad)" : "";
      save.disabled = !!p;
    };
    [time, lines].forEach((i) => i.addEventListener("input", refresh));
    const doPreview = debounce(async () => {
      if (!msg.value.trim()) return mount(prev, "");
      try { mount(prev, icon("message", 14), " Preview: ", (await post<{ output: string }>("/api/commands/preview", { template: msg.value, user: "Viewer", level: "everyone", args: "" })).output); } catch (e) { mount(prev, (e as Error).message); }
    }, 350);
    msg.addEventListener("input", doPreview);

    mount(recurringBox,
      h("div", { class: "form-grid" }, h("label", { class: "field" }, "Every (minutes)", time), h("label", { class: "field" }, "After this many chat lines", lines), h("label", { class: "field wide" }, "When both are set, post when", mode)),
      h("p", { class: "muted small" }, "Leave one empty to use only the other. After each post both the clock and the line count start again, and a timer never posts more than once a minute."));
    mount(onceBox, h("label", { class: "field" }, "Send at (optional)", when), h("p", { class: "muted small" }, "Posts one time while the stream is live, then switches itself off. Leave the time empty to send as soon as the stream is live."));

    const form = h("form", { class: "stack tight", onsubmit: (e: Event) => {
      e.preventDefault();
      if (problem()) return;
      const body: Record<string, unknown> = { name: name.value, message: msg.value, kind, interval_seconds: kind === "once" ? 0 : seconds(), min_lines: kind === "once" ? 0 : Number(lines.value || 0), trigger_mode: mode.value,
        run_at: kind === "once" && when.value ? new Date(when.value).getTime() / 1000 : null };
      busy(save, async () => { t ? await patch(`/api/timers/${t.id}`, body) : await post("/api/timers", { ...body, enabled: false }); await reload(); holder.close(); }, t ? "Saved" : "Timer created, switched off until you enable it");
    } },
      h("label", { class: "field" }, "Name", name), h("div", null, h("div", { class: "muted small", style: "margin-bottom:6px" }, "Type"), kindSeg),
      recurringBox, onceBox, h("label", { class: "field" }, "Message", msg), prev, hint,
      h("div", { class: "row", style: "justify-content:flex-end" }, h("button", { class: "btn ghost", type: "button", onclick: () => holder.close() }, "Cancel"), save));
    holder.close = sheet(t ? `Edit ${t.name}` : "New timer", form).close;
    refresh();
    if (t) void doPreview();
  };

  const search = h("input", { type: "search", placeholder: "Search timers", "aria-label": "Search timers" });
  search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); draw(); });
  mount(el,
    h("div", { class: "toolbar" }, h("div", { class: "input-icon" }, icon("search", 16), search), h("button", { class: "btn small primary", type: "button", onclick: () => editor() }, icon("plus", 15), "New timer")),
    bar, listBox);
  return { el, load: reload };
}

