/** Share to SavahBot (1.4.11): the page the phone's Share menu opens (the manifest's share_target) and the page `web+savahbot:` links land on.
 *
 * Share a line, a link or a screenshot caption from any app and choose SavahBot: it arrives here, shows what was received, and you decide whether it
 * becomes a note or a quote. Nothing is saved until you press a button, and the shared text is only ever shown as plain text. */
import { post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { navigate } from "../router.js";
import { fromProtocol, sharedText } from "../route-utils.js";
import type { Page } from "./types.js";

export const share: Page = {
  id: "share",
  title: "Share to SavahBot",
  icon: "send",
  blurb: "Save something shared from another app",
  hidden: true,
  render(root, query) {
    const text = sharedText(query.get("title") ?? "", query.get("text") ?? "", query.get("url") ?? "");
    if (!text) {
      mount(root, h("div", { class: "page" }, h("div", { class: "empty" }, icon("send", 28), h("h2", null, "Nothing was shared"),
        h("p", { class: "muted" }, "Use the Share button in another app and choose SavahBot to save a line or a link here."),
        h("a", { class: "btn primary", href: "/notebook" }, "Open the Notebook"))));
      return;
    }
    const body = h("textarea", { class: "share-text", rows: 6, maxlength: 5000, "aria-label": "Shared text" }) as HTMLTextAreaElement;
    body.value = text;
    const asNote = h("button", { class: "btn primary", type: "button" }, icon("notebook", 16), "Save as a note");
    const asQuote = h("button", { class: "btn", type: "button" }, icon("quote", 16), "Save as a quote");
    const skip = h("button", { class: "btn ghost", type: "button", onclick: () => { navigate("/desk", { replace: true }); } }, "Not now");
    asNote.onclick = () => busy(asNote, async () => {
      const v = body.value.trim();
      if (!v) throw new Error("There is nothing to save.");
      await post("/api/notes", { body: v.slice(0, 5000), tags: ["shared"] });
      navigate("/notebook", { replace: true });
    }, "Saved to your Notebook");
    asQuote.onclick = () => busy(asQuote, async () => {
      const v = body.value.trim();
      if (!v) throw new Error("There is nothing to save.");
      if (v.length > 500) { toast("A quote can be up to 500 characters. Shorten it first.", "error"); return; }
      await post("/api/quotes", { body: v, author: "" });
      navigate("/community", { replace: true });
    }, "Saved as a quote");
    mount(root, h("div", { class: "page" }, h("section", { class: "block", "data-card": "shared-with-you" },
      h("header", null, h("h2", null, icon("send", 18), "Shared with SavahBot")),
      h("div", { class: "body stack tight" },
        h("p", { class: "muted" }, "Check it, change it if you like, then choose where it goes. Nothing is saved until you press a button."),
        body, h("div", { class: "row wrap", style: "gap:8px" }, asNote, asQuote, skip)))));
  },
};

/** The landing page for a registered `web+savahbot:` link: it only ever leads to a page of this app. */
export const open: Page = {
  id: "open",
  title: "Open link",
  icon: "external",
  blurb: "Opens a web+savahbot: link",
  hidden: true,
  render(root, query) {
    const to = fromProtocol(query.get("u") ?? "");
    if (to) { queueMicrotask(() => { navigate(to, { replace: true }); }); mount(root, h("div", { class: "page" }, h("p", { class: "muted" }, "Opening…"))); return; }
    mount(root, h("div", { class: "page" }, h("div", { class: "empty" }, icon("external", 28), h("h2", null, "That link is not one SavahBot understands"),
      h("p", { class: "muted" }, "SavahBot links look like web+savahbot:moderation or web+savahbot:notebook."), h("a", { class: "btn primary", href: "/desk" }, "Go to the Desk"))));
  },
};
