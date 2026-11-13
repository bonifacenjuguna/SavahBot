import { tabRail } from "../nav.js";
import { post } from "../api.js";
import { busy, dateTime, duration, h, type Child } from "../dom.js";
import { icon } from "../icons.js";

export interface Action {
  id: number; ts: number; author_name: string; action: string; duration: number | null; score: number; reasons: string[];
  status: string; body: string; error: string; demo: boolean;
}

export function actionLabel(a: Action): string {
  return a.action === "timeout" && a.duration ? `timeout ${duration(a.duration)}` : a.action;
}

/** Standard page heading: icon tile, title, optional description and right-aligned actions. */
/** The page's own heading is for screen readers and the "On this page" list only: the top bar and the menu already say where you are, so it takes no room. Only a page's action buttons are drawn. */
export function pageHead(_iconName: string, title: string, _description?: string, actions?: Child): HTMLElement {
  return h("div", { class: actions ? "page-head" : "page-head bare" },
    h("h1", { class: "sr-only" }, title),
    actions ? h("div", { class: "ph-actions" }, actions) : null);
}

/** A short, stable id made from a title ("Waiting for you" becomes "waiting-for-you"). Cards use it so a saved layout can find them again. */
export const cardSlug = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30) || "card";

/** A titled card. `body` goes under the header; use `flush` when the body supplies its own padding. */
export function card(iconName: string | null, title: string, body: Child, opts: { flush?: boolean; actions?: Child; cls?: string; id?: string } = {}): HTMLElement {
  return h("section", { class: `block${opts.flush ? " flush" : ""}${opts.cls ? " " + opts.cls : ""}`, "data-card": opts.id ?? cardSlug(title) },
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
  tabRail(wrap, "pane-tabs");
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

export function approvalList(items: Action[], reload: () => Promise<void> | void): HTMLElement {
  if (!items.length) return h("div", { class: "empty" }, icon("check", 28), h("span", null, "Nothing is waiting. Requests appear here when the bot wants to delete, time out or ban someone."));
  const decide = (id: number, verb: "approve" | "reject") => (e: Event) =>
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${id}/${verb}`); await reload(); });
  const all = (verb: "approve" | "reject") => (e: Event) =>
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${verb}-all`); await reload(); });
  return h("ul", { class: "list" },
    items.length > 1 ? h("li", { class: "row ap-bulk" }, h("button", { class: "btn small primary", onclick: all("approve") }, icon("check", 15), "Approve all"), h("button", { class: "btn small ghost", onclick: all("reject") }, icon("x", 15), "Reject all")) : null,
    items.map((a) => {
      const why = a.reasons.join(", ");
      const reasons = h("div", { class: "reasons", title: why, tabindex: 0, role: "button", "aria-expanded": "false" }, why);
      const flip = () => { const open = reasons.classList.toggle("open"); reasons.setAttribute("aria-expanded", String(open)); };
      reasons.addEventListener("click", flip);
      reasons.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(); } });
      return h("li", { class: "approval" },
        h("div", { class: "ap-head" }, h("strong", null, a.author_name), h("span", { class: `chip ${a.action === "ban" ? "bad" : "warn"}` }, `${actionLabel(a)} · score ${a.score}`), h("span", { class: "ap-time muted small" }, dateTime(a.ts))),
        a.body ? h("q", null, a.body) : null,
        why ? reasons : null,
        h("div", { class: "ap-actions" }, h("button", { class: "btn small primary", onclick: decide(a.id, "approve") }, icon("check", 15), "Approve"),
          h("button", { class: "btn small ghost", onclick: decide(a.id, "reject") }, icon("x", 15), "Reject")));
    }),
  );
}
