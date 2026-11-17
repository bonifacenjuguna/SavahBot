/** Pages that load the first time you open them (1.4.11).
 *
 * The dashboard used to ship every page in one file, so the first screen waited for code it might never use. A lazy page keeps its name, icon and blurb
 * in the main file (the sidebar and the palette need them at once) and fetches the page's code on first visit; after that it opens instantly. While the
 * rest of the app is idle, `preloadPages` fetches them one by one in the background, so they are already saved for offline use and instant to open.
 *
 * A page that was navigated away from before its code arrived is not drawn late, and a failed load (offline, a page not yet saved) says so with a Retry. */
import { clear, h, mount } from "../dom.js";
import { icon } from "../icons.js";
import type { Page } from "./types.js";

export type LazyPage = Page & { preload(): Promise<void> };
export type PageMeta = Omit<Page, "render">;

export function lazyPage(meta: PageMeta, load: () => Promise<Page>): LazyPage {
  let loaded: Page | null = null;
  let pending: Promise<Page> | null = null;
  const fetchPage = (): Promise<Page> => {
    if (loaded) return Promise.resolve(loaded);
    pending ??= load().then((p) => {
      if (p.id !== meta.id) console.warn(`Lazy page "${meta.id}" loaded a page called "${p.id}"`);
      return (loaded = p);
    }).catch((e: unknown) => { pending = null; throw e; });
    return pending;
  };
  return {
    ...meta,
    preload: () => fetchPage().then(() => undefined, () => undefined),
    render(root, query) {
      if (loaded) return loaded.render(root, query);
      let dead = false;
      let cleanup: (() => void) | void;
      const draw = () => {
        mount(root, h("div", { class: "page", "aria-busy": "true" }, h("p", { class: "muted", role: "status" }, `Opening ${meta.title}…`)));
        fetchPage().then((p) => {
          if (dead) return;
          clear(root);
          cleanup = p.render(root, query);
        }).catch(() => {
          if (dead) return;
          mount(root, h("div", { class: "page" }, h("div", { class: "empty" }, icon("wifiOff", 28),
            h("h2", null, `${meta.title} could not be opened`),
            h("p", { class: "muted" }, navigator.onLine === false ? "This page has not been saved on this device yet. Connect once and open it, and it will work offline from then on." : "The page could not be loaded. Check the connection and try again."),
            h("button", { class: "btn primary", type: "button", onclick: draw }, icon("refresh", 16), "Try again"))));
        });
      };
      draw();
      return () => { dead = true; cleanup?.(); };
    },
  };
}

/** Fetches the code of every lazy page, one at a time, when the browser is idle. Skipped on a metered or slow connection. */
export function preloadPages(pages: readonly Page[]): () => void {
  const lazy = pages.filter((p): p is LazyPage => "preload" in p);
  const conn = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection;
  if (conn?.saveData || /(^|-)2g$/.test(conn?.effectiveType ?? "")) return () => undefined;
  let stopped = false;
  let timer = 0;
  const idle = (fn: () => void): void => { if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(fn, { timeout: 4000 }); else window.setTimeout(fn, 600); };
  const next = (i: number) => {
    if (stopped || i >= lazy.length) return;
    idle(() => { if (stopped) return; void lazy[i].preload().then(() => { timer = window.setTimeout(() => next(i + 1), 250); }); });
  };
  timer = window.setTimeout(() => next(0), 4000);                  // let the first screen settle first
  return () => { stopped = true; window.clearTimeout(timer); };
}
