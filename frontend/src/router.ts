/**
 * The router: clean URLs on the browser History API (`/moderation?tab=rules`), no libraries.
 *
 * - The address bar, the back and forward buttons, refresh and deep links all work on real paths.
 * - `navigate()` is the only way the app changes page. It accepts the clean form, the old `#/route` form (which the backend still stores in
 *   notifications) and a bare id, and it refuses anything that is not a page of this app, so nothing can send the user to another site.
 * - Old bookmarks (`/#/security`) are converted to clean URLs on load and whenever a hash route appears while the app is open.
 * - Links written as `<a href="/security">` are caught here and navigate without reloading; with Ctrl/Cmd/Shift/middle-click or a target
 *   they behave like any link (new tab, new window).
 * Who may see a page is decided by the backend on every API call. This file only decides which page is drawn; signing in is handled in main.ts.
 */
import { fromLegacyHash, normalize, queryString, resolvePath, type Resolved } from "./route-utils.js";

export interface Where {
  /** The registered page this address shows, or null for an address that is not a page (the 404 page). */
  id: string | null;
  /** The pathname exactly as typed, for the 404 page. */
  path: string;
  query: URLSearchParams;
  notFound: boolean;
}

type Listener = () => void;
const listeners = new Set<Listener>();
let ids: string[] = [];
let started = false;

const here = (): string => location.pathname + location.search;
/** The path and query of the page that is drawn now. A back or forward step that only moves the `#fragment` leaves it unchanged and must not redraw the page. */
let shown = "";

export function current(): Where {
  const r: Resolved = resolvePath(location.pathname, ids);
  return { id: r.kind === "page" ? r.id : null, path: location.pathname, query: new URLSearchParams(location.search), notFound: r.kind === "notfound" };
}

/** Subscribe to page changes (navigate, back, forward, an old hash link). Returns the unsubscribe function. */
export function onRoute(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const notify = () => { shown = here(); listeners.forEach((f) => { try { f(); } catch (e) { console.error(e); } }); };

/**
 * Go to a page. Returns false (and does nothing) when `to` is not a route of this app.
 * Going to the address you are already on does nothing, so a double tap never stacks history entries or redraws the page.
 */
export function navigate(to: string, opts: { replace?: boolean } = {}): boolean {
  const url = normalize(to, ids);
  if (!url) return false;
  if (url === here()) return true;
  if (opts.replace) history.replaceState(null, "", url);
  else history.pushState(null, "", url);
  notify();
  return true;
}

/** Updates the query string of the current page (a selected tab, a wizard step) without a redraw and without a new history entry. */
export function replaceQuery(q: string | URLSearchParams): void {
  const url = location.pathname + queryString(q);
  if (url !== here()) { history.replaceState(null, "", url); shown = here(); }   // the page already shows this state: nothing to redraw
}

/** The clean address for a route, for `href` attributes: `href("settings?tab=x")` is `/settings?tab=x`. Falls back to the Desk for a non-route. */
export function href(route: string): string {
  return normalize(route, ids) ?? "/desk";
}

/** Old-style address in the bar (`/#/security`): rewrite it to the clean one without adding a history entry. */
function adoptLegacyHash(): boolean {
  const clean = fromLegacyHash(location.hash, location.search, ids);
  if (!clean) return false;
  history.replaceState(null, "", clean);
  return true;
}

/** The path `/` and unusual spellings (`/Desk`, `/dashboard`, `/desk/`) are rewritten to the one canonical form, keeping the query. */
function canonicalize(): void {
  const r = resolvePath(location.pathname, ids);
  if (r.kind === "page" && !r.canonical) history.replaceState(null, "", `/${r.id}${location.search}${location.hash}`);   // the #fragment is kept
}

function onClick(e: MouseEvent): void {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
  if (!a || (a.target && a.target !== "_self") || a.hasAttribute("download")) return;
  const raw = a.getAttribute("href") ?? "";
  if (!(raw.startsWith("/") || raw.startsWith("#/"))) return;     // external links, mailto:, "#" and anchors on the page are left to the browser
  const url = normalize(raw, ids);
  if (!url) return;
  const r = resolvePath(url.split("?")[0], ids);
  if (r.kind !== "page") return;                                  // a path that is not one of our pages (a static file, say) is a normal link
  e.preventDefault();
  navigate(url);
}

/** Call once, before the first page is drawn. `pageIds` are the registered pages; they are the only addresses that are pages. */
export function startRouter(pageIds: readonly string[]): void {
  ids = [...pageIds];
  if (started) return;
  started = true;
  if (!adoptLegacyHash()) canonicalize();
  shown = here();
  window.addEventListener("popstate", () => { if (here() !== shown) notify(); });
  // An old bookmark clicked while the app is already open only changes the hash, so nothing reloads: convert it here.
  window.addEventListener("hashchange", () => { if (adoptLegacyHash()) notify(); });
  document.addEventListener("click", onClick);
}

/** Test hook: lets a test run the same setup again with another page list. */
export function _reset(): void { ids = []; started = false; shown = ""; listeners.clear(); }
