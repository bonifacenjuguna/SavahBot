/** Settings > Knowledge: Detectors, Learning and Live data. */
import { get, patch, post } from "../api.js";
import { busy, debounce, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { ago, goKnowledge, kcard, modeSeg, MODE_HELP, type Detector, type Feed, type Mode } from "./knowledge-shared.js";
import { confirmAct, figures, invite, lede, plural } from "./widgets.js";

const enc = encodeURIComponent;
const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");

// ------------------------------------------------------------------------------------------------ detectors
export function renderDetectors(host: HTMLElement): void {
  const load = async () => {
    const { detectors } = await get<{ detectors: Detector[] }>("/api/knowledge/detectors");
    mount(host,
      lede("Detectors are the readers. Each one looks for one kind of trouble in the packs and in the message. Choose Off, Shadow (watch and record, never score) or Live, and how strongly it counts."),
      h("div", { class: "k-grid two" }, detectors.map(detector)),
      h("p", { class: "k-note" }, `${MODE_HELP.shadow} ${MODE_HELP.live} Everything the knowledge layer adds is capped, so on its own it can never ban anyone.`));
  };
  void load().catch((e) => { fail(e); mount(host, invite("alert", "Could not load the detectors", (e as Error).message)); });
}

function detector(d: Detector): HTMLElement {
  const sw = modeSeg(`${d.title} mode`, d.mode, async (m: Mode) => {
    try { await patch(`/api/knowledge/detectors/${enc(d.id)}`, { mode: m }); toast(`${d.title}: ${m}`); } catch (e) { sw.set(d.mode); fail(e); }
  });
  const slider = h("input", { type: "range", min: 0.1, max: 3, step: 0.1, value: String(d.scale), "aria-label": `${d.title} strength` }) as HTMLInputElement;
  const out = h("output", null, `${d.scale.toFixed(1)}x`);
  slider.oninput = () => { out.textContent = `${Number(slider.value).toFixed(1)}x`; };
  slider.onchange = debounce(async () => { try { await patch(`/api/knowledge/detectors/${enc(d.id)}`, { scale: Number(slider.value) }); toast("Saved"); } catch (e) { fail(e); } }, 150);
  return h("section", { class: "k-detector" },
    h("div", null, h("h3", null, d.title), h("p", { class: "k-note" }, d.about)),
    sw.el,
    h("div", { class: "k-slider" }, h("span", { class: "muted small" }, "Strength"), slider, out),
    d.learned_scale !== 1 ? h("p", { class: "k-note" }, `Learning from your decisions has set this to ${d.learned_scale}x on top of the strength above.`) : null,
    h("div", { class: "chip-row tight" }, h("span", { class: "chip ok" }, `${plural(d.live_hits, "message")} scored`), h("span", { class: "chip warn" }, `${plural(d.shadow_hits, "message")} noticed in shadow`),
      d.mode !== d.default_mode ? h("span", { class: "chip" }, `default is ${d.default_mode}`) : null),
    d.packs.length ? h("div", { class: "chip-row tight" }, h("span", { class: "muted small" }, "Reads:"), d.packs.slice(0, 6).map((p) => h("button", { class: "chip pick", type: "button", onclick: () => goKnowledge("packs", { pack: p.id }) }, p.title))) : null,
    h("div", { class: "row" }, h("button", { class: "btn small", type: "button", onclick: () => goKnowledge("test", { text: d.example }) }, icon("flask", 15), "Try an example")));
}

// ------------------------------------------------------------------------------------------------ learning
// ------------------------------------------------------------------------------------------------ live data
export function renderFeeds(host: HTMLElement): void {
  let data: { feeds: Feed[]; summary: { enabled: number; total: number; entries: number; last_ok: number | null; errors: number; auto: boolean } };
  const load = async () => { data = await get(`/api/knowledge/feeds`); draw(); };
  const reload = () => load().catch(fail);

  const tone = (f: Feed): string => (f.error ? "bad" : f.status === "ok" || f.status === "up to date" ? "ok" : f.status === "rolled back" ? "warn" : "");

  const feedRow = (f: Feed): HTMLElement => {
    const sw = h("input", { type: "checkbox", class: "switch", checked: f.enabled, "aria-label": `Use ${f.title}` }) as HTMLInputElement;
    sw.onchange = async () => { try { await patch(`/api/knowledge/feeds/${enc(f.id)}`, { enabled: sw.checked }); toast(sw.checked ? "On" : "Off"); await reload(); } catch (e) { sw.checked = !sw.checked; fail(e); } };
    const refresh = (force: boolean) => (e: Event) => busy(e.currentTarget as HTMLButtonElement, async () => {
      const r = await post<{ ok: boolean; status: string; entries?: number; error?: string }>(`/api/knowledge/feeds/${enc(f.id)}/refresh`, { force });
      if (!r.ok) toast(r.error ?? "The refresh failed", "error"); else toast(r.status === "up to date" ? "Already up to date" : `Loaded ${plural(r.entries ?? 0, "domain")}`);
      await reload();
    });
    return h("div", { class: "k-feed" },
      h("div", { class: "top" }, h("div", null, h("strong", null, f.title), h("div", { class: "k-note" }, f.about)), sw),
      h("div", { class: "chip-row tight" }, h("span", { class: `chip ${tone(f)}` }, f.status), h("span", { class: "chip" }, `${plural(f.entries, f.format === "phrases" ? "phrase" : "domain")}`),
        h("span", { class: "chip" }, `last good ${ago(f.last_ok)}`), h("span", { class: "chip" }, f.license), f.custom ? h("span", { class: "chip ok" }, "yours") : null),
      f.error ? h("div", { class: "k-error" }, f.error) : null,
      h("div", { class: "acts" },
        h("button", { class: "btn small", type: "button", onclick: refresh(false), disabled: !f.enabled }, icon("refresh", 15), "Refresh now"),
        f.error.includes("shrank") ? h("button", { class: "btn small ghost", type: "button", onclick: refresh(true) }, "Accept the smaller list") : null,
        f.can_rollback ? confirmAct({ icon: "undo", label: "Roll back", confirmText: "Go back to the previous version?", text: `Restores ${plural(f.previous_entries, "entry", "entries")} from before the last refresh.`,
          onConfirm: async () => { await post(`/api/knowledge/feeds/${enc(f.id)}/rollback`); await reload(); toast("Rolled back"); } }) : null,
        f.custom ? confirmAct({ icon: "trash", label: "Remove", confirmText: "Remove this feed and its domains?", onConfirm: async () => { await post(`/api/knowledge/feeds/${enc(f.id)}/delete`); await reload(); } }) : null,
        f.homepage ? h("a", { class: "btn small ghost", href: f.homepage, target: "_blank", rel: "noopener noreferrer" }, icon("external", 14), "Source") : null));
  };

  const addCard = (): HTMLElement => {
    const title = h("input", { type: "text", maxlength: 60, placeholder: "Name", "aria-label": "Feed name" }) as HTMLInputElement;
    const url = h("input", { type: "url", placeholder: "https://example.org/list.txt", "aria-label": "Feed address" }) as HTMLInputElement;
    const fmt = h("select", { "aria-label": "Format" }, [["domains", "One domain per line"], ["hosts", "Hosts file (0.0.0.0 domain)"], ["urls", "One web address per line"], ["phrases", "One spam phrase per line"]].map(([v, l]) => h("option", { value: v }, l))) as HTMLSelectElement;
    const btn = h("button", { class: "btn primary", type: "button" }, icon("plus", 16), "Add feed") as HTMLButtonElement;
    btn.onclick = () => busy(btn, async () => { await post("/api/knowledge/feeds", { title: title.value, url: url.value, format: fmt.value }); title.value = ""; url.value = ""; toast("Added. Press Refresh now to load it."); await reload(); });
    return kcard("plus", "Add a list of your own", h("div", { class: "k-add" }, h("p", { class: "k-note" }, "Any public list on the web in a plain-text format. Only addresses on the public internet are accepted, and redirects are not followed."),
      h("label", { class: "field" }, "Name", title), h("label", { class: "field" }, "Address", url), h("label", { class: "field" }, "Format", fmt), h("div", { class: "row" }, btn)));
  };

  const draw = () => {
    const s = data.summary;
    const auto = h("input", { type: "checkbox", class: "switch", checked: s.auto, "aria-label": "Refresh automatically" }) as HTMLInputElement;
    auto.onchange = async () => { try { await patch("/api/settings", { values: { intel_feeds_enabled: auto.checked } }); toast(auto.checked ? "Automatic refresh on" : "Automatic refresh off"); } catch (e) { auto.checked = !auto.checked; fail(e); } };
    mount(host,
      lede("Public lists of known phishing and malware websites, fetched by your bot's own server and kept up to date. A link to a listed site scores as a threat. Well-known sites can never be added, a download that fails or suddenly shrinks is refused, and every refresh can be rolled back."),
      kcard("radio", "Refreshing", h("div", { class: "k-stack" },
        figures([{ value: `${s.enabled}/${s.total}`, label: "lists on" }, { value: s.entries.toLocaleString(), label: "domains known", tone: s.entries ? "ok" : "" }, { value: ago(s.last_ok), label: "last good refresh", tone: s.errors ? "warn" : "" }]),
        h("div", { class: "row between" }, h("span", { class: "muted" }, "Refresh automatically (about once a day, politely)"), auto),
        h("p", { class: "k-note" }, "Only the list is downloaded. Nothing about your chat is ever sent. How often is set by “intel_feed_interval_hours” under All settings."))),
      kcard("database", "Lists", h("div", null, data.feeds.map(feedRow)), { flush: true }),
      addCard());
  };
  void load().catch((e) => { fail(e); mount(host, invite("alert", "Could not load the live data", (e as Error).message)); });
}
