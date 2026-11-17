/** Updates of the installed app (1.4.11): a new version is downloaded in the background and waits; you choose when to switch.
 *
 * The service worker (public/sw.js) no longer replaces itself in the middle of your session. When a new copy is ready this shows a slim bar
 * with "Reload"; pressing it tells the waiting worker to take over and the page reloads once. Nothing reloads by itself while you are typing.
 * The first ever install (no worker yet) just starts working, with no bar. */
import { h } from "./dom.js";
import { icon } from "./icons.js";

const CHECK_EVERY_MS = 60 * 60 * 1000;
let bar: HTMLElement | null = null;
let dismissed = false;
let reloading = false;

function show(waiting: ServiceWorker): void {
  if (bar || dismissed) return;
  const go = h("button", { class: "btn primary small", type: "button", onclick: () => {
    go.disabled = true;
    reloading = true;
    waiting.postMessage({ type: "skip-waiting" });
    window.setTimeout(() => location.reload(), 4000);          // if the worker never answers, reload anyway
  } }, icon("refresh", 14), "Reload");
  const later = h("button", { class: "btn ghost small", type: "button", onclick: () => { dismissed = true; bar?.remove(); bar = null; } }, "Later");
  bar = h("div", { class: "update-bar", role: "status", "aria-live": "polite" },
    h("span", { class: "ub-ico", "aria-hidden": "true" }, icon("download", 16)),
    h("span", { class: "ub-text" }, h("strong", null, "A new version is ready"), h("span", null, "Reload to use it. Your sign-in is kept.")),
    h("span", { class: "ub-actions" }, go, later));
  document.body.appendChild(bar);
}

function track(reg: ServiceWorkerRegistration): void {
  const check = () => { if (reg.waiting && navigator.serviceWorker.controller) show(reg.waiting); };
  check();
  reg.addEventListener("updatefound", () => {
    const worker = reg.installing;
    worker?.addEventListener("statechange", () => { if (worker.state === "installed") check(); });
  });
}

/** Call once with the registration. Safe where service workers are missing. */
export function watchForUpdates(reg: ServiceWorkerRegistration): void {
  track(reg);
  // the new worker took over (after "Reload"): load the new files once. Not on the very first install.
  let had = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!had) { had = true; return; }
    if (reloading) location.reload();
  });
  const ask = () => { if (document.visibilityState === "visible") void reg.update().catch(() => undefined); };
  window.setInterval(ask, CHECK_EVERY_MS);
  document.addEventListener("visibilitychange", ask);
}

/** On the very first visit the page's own files were fetched before the worker took control, so the worker never saw them. Once it is ready, ask for each
 * of them again (they come from the browser's HTTP cache, so this costs nothing); the worker keeps them, and the app can open offline from then on. */
export function warmAssets(): void {
  const run = () => {
    const urls = performance.getEntriesByType("resource").map((e) => e.name).filter((n) => { try { const u = new URL(n); return u.origin === location.origin && u.pathname.startsWith("/assets/"); } catch { return false; } });
    for (const u of new Set(urls)) void fetch(u, { cache: "force-cache" }).catch(() => undefined);
  };
  void navigator.serviceWorker.ready.then(() => window.setTimeout(run, 1500));
}
