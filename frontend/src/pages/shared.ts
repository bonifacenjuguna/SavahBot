import { post } from "../api.js";
import { busy, dateTime, duration, h } from "../dom.js";

export interface Action {
  id: number; ts: number; author_name: string; action: string; duration: number | null; score: number; reasons: string[];
  status: string; body: string; error: string; demo: boolean;
}

export function actionLabel(a: Action): string {
  return a.action === "timeout" && a.duration ? `timeout ${duration(a.duration)}` : a.action;
}

export function approvalList(items: Action[], reload: () => Promise<void> | void): HTMLElement {
  if (!items.length) return h("div", { class: "empty" }, "Nothing is waiting. Requests appear here when the bot wants to delete, time out or ban someone.");
  const decide = (id: number, verb: "approve" | "reject") => (e: Event) =>
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${id}/${verb}`); await reload(); });
  const all = (verb: "approve" | "reject") => (e: Event) =>
    busy(e.currentTarget as HTMLButtonElement, async () => { await post(`/api/moderation/${verb}-all`); await reload(); });
  return h("ul", { class: "list" },
    items.length > 1 ? h("li", { class: "row" }, h("button", { class: "btn small primary", onclick: all("approve") }, "Approve all"), h("button", { class: "btn small ghost", onclick: all("reject") }, "Reject all")) : null,
    items.map((a) =>
      h("li", { class: "approval" },
        h("div", { class: "row between" }, h("strong", null, a.author_name), h("span", { class: "chip warn" }, `${actionLabel(a)} · score ${a.score}`)),
        a.body ? h("q", null, a.body) : null,
        h("div", { class: "reasons" }, a.reasons.join(", ")),
        h("div", { class: "row" }, h("button", { class: "btn small primary", onclick: decide(a.id, "approve") }, "Approve"),
          h("button", { class: "btn small ghost", onclick: decide(a.id, "reject") }, "Reject"), h("span", { class: "muted small" }, dateTime(a.ts))))),
  );
}
