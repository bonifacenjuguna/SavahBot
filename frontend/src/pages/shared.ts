import { post } from "../api.js";
import { append, busy, confirmDialog, dateTime, duration, h, mount, type Child } from "../dom.js";
import { icon } from "../icons.js";

export interface Action {
  id: number; ts: number; author_name: string; action: string; duration: number | null; score: number; reasons: string[];
  status: string; body: string; error: string; demo: boolean;
}

export function actionLabel(a: Action): string {
  return a.action === "timeout" && a.duration ? `timeout ${duration(a.duration)}` : a.action;
}

/** Standard page heading: icon tile, title, optional description and right-aligned actions. */
export function pageHead(iconName: string, title: string, description?: string, actions?: Child): HTMLElement {
  return h("div", { class: "page-head" },
    h("div", { class: "ph-main" }, h("span", { class: "ph-icon" }, icon(iconName, 22)), h("div", null, h("h1", null, title), description ? h("p", null, description) : null)),
    actions ? h("div", { class: "ph-actions" }, actions) : null);
}

/** A titled card. `body` goes under the header; use `flush` when the body supplies its own padding. */
export function card(iconName: string | null, title: string, body: Child, opts: { flush?: boolean; actions?: Child; cls?: string } = {}): HTMLElement {
  return h("section", { class: `block${opts.flush ? " flush" : ""}${opts.cls ? " " + opts.cls : ""}` },
    h("header", null, h("h2", null, iconName ? icon(iconName, 18) : null, title), opts.actions ?? null), body);
}

export function empty(iconName: string, text: string): HTMLElement {
  return h("div", { class: "empty" }, icon(iconName, 28), h("span", null, text));
}

export function chipFor(status: string): string {
  return status === "executed" || status === "approved" ? "ok" : status === "failed" || status === "rejected" ? "bad" : status === "pending" ? "warn" : "";
}

/** Two-pane switcher for narrow screens. Panes stay visible side by side on wide screens (CSS). */
export function paneTabs(labels: { id: string; label: string; badge?: () => number }[], panes: Record<string, HTMLElement>, initial: string): HTMLElement {
  let current = initial;
  const wrap = h("div", { class: "seg-control pane-tabs", role: "tablist" });
  const apply = () => {
    for (const [id, el] of Object.entries(panes)) { el.classList.add("pane"); el.setAttribute("data-hidden", String(id !== current)); }
    for (const b of Array.from(wrap.children)) b.setAttribute("aria-selected", String(b.getAttribute("data-id") === current));
  };
  for (const l of labels) {
    const n = h("span", { class: "n", hidden: true }, "");
    const b = h("button", { type: "button", role: "tab", "data-id": l.id, onclick: () => { current = l.id; apply(); } }, l.label, n);
    (b as any).__n = n;
    wrap.appendChild(b);
  }
  apply();
  (wrap as any).refreshBadges = () => {
    labels.forEach((l, i) => {
      const n = (wrap.children[i] as any).__n as HTMLElement;
      const v = l.badge?.() ?? 0;
      n.hidden = v <= 0;
      n.textContent = String(v);
    });
  };
  return wrap;
}

/** Compact "Waiting for you" list: one line per request, tap a row to read the whole message, quick approve and reject,
 *  search when the queue is long and progressive loading so a raid of 200 requests never makes the page 200 cards tall. */
export function approvalList(items: Action[], reload: () => Promise<void> | void, opts: { pageSize?: number } = {}): HTMLElement {
  if (!items.length) return h("div", { class: "empty" }, icon("check", 28), h("span", null, "Nothing is waiting. Requests appear here when the bot wants to delete, time out or ban someone."));
  const size = opts.pageSize ?? 8;
  let shownCount = size;
  let needle = "";
  const decide = (id: number, verb: "approve" | "reject") => (e: Event) => {
    e.stopPropagation();
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${id}/${verb}`); await reload(); });
  };
  const all = (verb: "approve" | "reject") => async (e: Event) => {
    const btn = e.currentTarget as HTMLButtonElement;
    if (!(await confirmDialog(`${verb === "approve" ? "Approve" : "Reject"} all ${items.length}?`, verb === "approve" ? "Every waiting request runs now: messages are deleted and people are timed out or banned as listed." : "Every waiting request is dismissed and nothing is done.", verb === "approve" ? "Approve all" : "Reject all", verb === "approve" ? "primary" : "danger"))) return;
    busy(btn, async () => { await post(`/api/moderation/${verb}-all`); await reload(); });
  };
  const row = (a: Action): HTMLElement => {
    const li = h("li", { class: "appr", tabindex: 0, role: "button", "aria-expanded": "false" });
    const toggle = () => { const open = li.classList.toggle("open"); li.setAttribute("aria-expanded", String(open)); };
    li.addEventListener("click", toggle);
    li.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === li) { e.preventDefault(); toggle(); } });
    append(li, [
      h("div", { class: "appr-top" },
        h("strong", { class: "appr-who" }, a.author_name),
        h("span", { class: "chip warn" }, actionLabel(a)),
        h("span", { class: "chip" }, `score ${a.score}`),
        h("span", { class: "grow" }),
        h("button", { class: "icon-btn sm ok", type: "button", "aria-label": `Approve ${actionLabel(a)} for ${a.author_name}`, title: "Approve", onclick: decide(a.id, "approve") }, icon("check", 18)),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": `Reject request for ${a.author_name}`, title: "Reject", onclick: decide(a.id, "reject") }, icon("x", 18))),
      a.body ? h("div", { class: "appr-msg" }, a.body) : null,
      h("div", { class: "appr-more" }, a.reasons.length ? h("div", { class: "reasons" }, "Why: " + a.reasons.join(", ")) : null, h("div", { class: "reasons" }, dateTime(a.ts) + (a.demo ? " · demo" : "")))]);
    return li;
  };
  const listEl = h("ul", { class: "list appr-list" });
  const moreBtn = h("button", { class: "btn ghost small", type: "button", onclick: () => { shownCount += size; draw(); } }, "");
  const countEl = h("span", { class: "muted small" }, "");
  const draw = () => {
    const rows = items.filter((a) => !needle || `${a.author_name} ${a.body} ${a.reasons.join(" ")}`.toLowerCase().includes(needle));
    mount(listEl, rows.slice(0, shownCount).map(row));
    if (!rows.length) listEl.append(h("li", { class: "muted small" }, "No requests match."));
    const rest = rows.length - shownCount;
    moreBtn.hidden = rest <= 0;
    moreBtn.textContent = `Show ${Math.min(rest, size)} more (${rest} left)`;
    countEl.textContent = `${rows.length} waiting`;
  };
  draw();
  const search = h("input", { type: "search", placeholder: "Search waiting requests", "aria-label": "Search waiting requests" });
  search.addEventListener("input", () => { needle = search.value.trim().toLowerCase(); shownCount = size; draw(); });
  return h("div", null,
    h("div", { class: "toolbar" },
      items.length > size ? h("div", { class: "input-icon" }, icon("search", 16), search) : countEl,
      items.length > 1 ? h("span", { class: "row", style: "gap:6px;margin-left:auto" }, h("button", { class: "btn small primary", type: "button", onclick: all("approve") }, icon("check", 15), "Approve all"), h("button", { class: "btn small ghost", type: "button", onclick: all("reject") }, icon("x", 15), "Reject all")) : null),
    listEl,
    h("div", { class: "body", style: "text-align:center" }, moreBtn));
}
