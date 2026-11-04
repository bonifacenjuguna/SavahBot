import "./styles.css";
import { ApiError, apiBase, hasToken, loggedOut, post, setApiBase, setToken } from "./api.js";
import { busy, clear, h, mount, toast } from "./dom.js";
import * as feed from "./events.js";
import { refreshStatus, onStatus, type Status } from "./state.js";
import { desk } from "./pages/desk.js";
import { moderation } from "./pages/moderation.js";
import { commands } from "./pages/commands.js";
import { notebook } from "./pages/notebook.js";
import { community } from "./pages/community.js";
import { insights } from "./pages/insights.js";
import { demo } from "./pages/demo.js";
import { setup } from "./pages/setup.js";
import { settings } from "./pages/settings.js";
import type { Page } from "./pages/types.js";

const PAGES: Page[] = [desk, moderation, commands, notebook, community, insights, demo, setup, settings];
const root = document.getElementById("app")!;
let statusTimer: number | undefined;

function route(): { id: string; query: URLSearchParams } {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  return { id: path || "desk", query: new URLSearchParams(qs ?? "") };
}

function tallyState(s: Status | null): { state: "live" | "demo" | "standby"; title: string; detail: string } {
  if (!s) return { state: "standby", title: "Connecting", detail: "Waiting for the backend" };
  if (s.hub.mode === "demo") return { state: "demo", title: "Demo", detail: "Simulated chat, nothing is sent" };
  if (s.hub.stream_live) return { state: "live", title: "On air", detail: s.hub.stream_title || "YouTube live chat" };
  return { state: "standby", title: "Standby", detail: s.youtube.connected ? "Waiting for a live stream" : "YouTube not connected" };
}

// ------------------------------------------------------------------------------------------------ login
function showLogin(): void {
  feed.stop();
  window.clearInterval(statusTimer);
  const needsBase = !apiBase();
  const pass = h("input", { type: "password", autocomplete: "current-password", required: true, id: "pw" });
  const base = h("input", { type: "url", placeholder: "https://your-app.up.railway.app", value: apiBase(), id: "base" });
  const err = h("p", { class: "small", style: "color:var(--bad)", role: "alert" });
  const btn = h("button", { class: "btn primary", type: "submit" }, "Sign in");
  const form = h(
    "form",
    {
      onsubmit: (e: Event) => {
        e.preventDefault();
        err.textContent = "";
        setApiBase(base.value);
        btn.disabled = true;
        post<{ token: string }>("/api/auth/login", { password: pass.value })
          .then((r) => { setToken(r.token); boot(); })
          .catch((ex) => { err.textContent = ex instanceof ApiError ? ex.message : "Could not sign in."; })
          .finally(() => (btn.disabled = false));
      },
    },
    h("h1", null, h("span", { class: "lamp-sm" }), "SavahBot"),
    h("p", { class: "muted" }, "Owner sign-in. The password is the OWNER_PASSWORD variable, or the one printed once in the Railway logs on first start."),
    h("label", { class: "field" }, "Password", pass),
    needsBase
      ? h("label", { class: "field" }, "Backend address", base)
      : h("details", null, h("summary", { class: "small muted" }, "Backend address"), h("label", { class: "field" }, "Address", base)),
    err,
    btn,
  );
  mount(root, h("main", { class: "login" }, form));
  pass.focus();
}

// ------------------------------------------------------------------------------------------------ shell
function showShell(): void {
  const lamp = h("div", { class: "lamp", "aria-hidden": "true" });
  const tTitle = h("strong", null, "Connecting");
  const tDetail = h("span", null, "");
  const tally = h("div", { class: "tally", "data-state": "standby", role: "status" }, lamp, tTitle, tDetail);
  const demoBtn = h("button", { type: "button", "aria-pressed": "false" }, "Demo");
  const liveBtn = h("button", { type: "button", "aria-pressed": "false" }, "Live");
  const setMode = (mode: "demo" | "live") => () => busy(mode === "demo" ? demoBtn : liveBtn, async () => {
    await post("/api/mode", { mode });
    await refreshStatus();
  });
  demoBtn.onclick = setMode("demo");
  liveBtn.onclick = setMode("live");
  const segment = h("div", { class: "segment", role: "group", "aria-label": "Bot mode" }, demoBtn, liveBtn);

  const counts = new Map<string, HTMLElement>();
  const nav = h("nav", { class: "nav", "aria-label": "Sections" },
    PAGES.map((p) => {
      const badge = h("span", { class: "count", hidden: true }, "");
      counts.set(p.id, badge);
      return h("a", { href: `#/${p.id}`, "data-id": p.id }, p.title, badge);
    }));

  const quotaText = h("span", null, "");
  const meterBar = h("i", null);
  const meter = h("div", { class: "meter", title: "YouTube API quota used today" }, meterBar);
  const connText = h("span", null, "Live feed: connecting");
  const out = h("button", { class: "link-btn", type: "button", onclick: () => { setToken(""); showLogin(); } }, "Sign out");
  const rail = h("aside", { class: "rail" }, h("div", { class: "brand" }, "SavahBot"), tally, segment, nav,
    h("div", { class: "rail-foot" }, quotaText, meter, connText, out));

  const content = h("main", { class: "main", id: "content", tabindex: -1 });
  mount(root, h("div", { class: "shell" }, rail, content));

  let cleanup: (() => void) | void;
  const render = () => {
    cleanup?.();
    const { id, query } = route();
    const page = PAGES.find((p) => p.id === id) ?? PAGES[0];
    nav.querySelectorAll("a").forEach((a) => (a.getAttribute("data-id") === page.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    document.title = `${page.title} · SavahBot`;
    clear(content);
    cleanup = page.render(content, query);
  };
  window.onhashchange = render;

  const offStatus = onStatus((s) => {
    const t = tallyState(s);
    tally.setAttribute("data-state", t.state);
    tTitle.textContent = t.title;
    tDetail.textContent = t.detail;
    demoBtn.setAttribute("aria-pressed", String(s.hub.mode === "demo"));
    liveBtn.setAttribute("aria-pressed", String(s.hub.mode === "live"));
    const q = s.youtube.quota;
    const pct = Math.min(100, Math.round(q.fraction * 100));
    quotaText.textContent = s.hub.mode === "demo" ? "YouTube quota: untouched in demo" : `YouTube quota: ${pct}% used today`;
    meterBar.style.width = `${s.hub.mode === "demo" ? 0 : pct}%`;
    meter.classList.toggle("hot", pct >= 75);
    const badge = counts.get("moderation")!;
    badge.hidden = s.pending === 0;
    badge.textContent = String(s.pending);
  });
  const offConn = feed.onConnection((up) => (connText.textContent = up ? "Live feed: connected" : "Live feed: reconnecting"));
  const offEvents = ["mode", "stream", "mod_pending", "mod_resolved"].map((t) => feed.on(t, () => void refreshStatus()));

  render();
  void refreshStatus();
  statusTimer = window.setInterval(() => void refreshStatus(), 15000);
  feed.start();
  loggedOut.addEventListener("out", () => { offStatus(); offConn(); offEvents.forEach((f) => f()); }, { once: true });
}

function boot(): void {
  if (!hasToken()) return showLogin();
  showShell();
}

loggedOut.addEventListener("out", () => {
  toast("Your session ended. Sign in again.", "error");
  showLogin();
});

boot();
