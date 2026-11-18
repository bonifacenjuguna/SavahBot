/** Settings > Knowledge > Knowledge: every pack by category, and each pack's own page (settings, entries, add, export). */
import { get, patch, post } from "../api.js";
import { busy, debounce, h, mount, toast, toastAction } from "../dom.js";
import { icon } from "../icons.js";
import { KIND_NAME, LANG_NAME, goKnowledge, kcard, modeSeg, signalName, type Category, type Entry, type PackInfo } from "./knowledge-shared.js";
import { empty } from "./shared.js";
import { invite, lede, plural, seg } from "./widgets.js";

const enc = encodeURIComponent;

export function renderPacks(host: HTMLElement, query: URLSearchParams): void {
  const id = query.get("pack");
  if (id) { renderPack(host, id); return; }
  const open = query.get("cat");
  const load = async () => {
    const { categories } = await get<{ categories: Category[] }>("/api/knowledge/categories");
    mount(host,
      lede("Everything the bot knows, split into packs by topic. Switch a pack Off, Shadow (watch only) or Live, open it to see and change its entries, or add your own."),
      categories.map((c) => h("details", { class: "k-cat", open: c.id === open },
        h("summary", null, icon("chevronRight", 16), h("div", { class: "grow" }, h("strong", null, c.title), h("span", { class: "k-note" }, c.about)),
          h("span", { class: "chip" }, `${c.active}/${c.packs.length} on`)),
        c.packs.map((p) => packRow(p)))));
  };
  void load().catch((e) => { toast((e as Error).message, "error"); mount(host, invite("alert", "Could not load the packs", (e as Error).message)); });
}

function packChips(p: PackInfo): HTMLElement {
  return h("div", { class: "chip-row tight" },
    h("span", { class: "chip" }, KIND_NAME[p.kind] ?? p.kind), h("span", { class: "chip" }, plural(p.entries, "entry", "entries")),
    p.lang !== "en" ? h("span", { class: "chip" }, LANG_NAME[p.lang] ?? p.lang) : null,
    p.signal ? h("span", { class: "chip" }, `counts as: ${signalName(p.signal)}`) : null,
    p.entries_added ? h("span", { class: "chip ok" }, `${p.entries_added} added`) : null,
    p.language_off ? h("span", { class: "chip warn" }, "language is switched off") : null);
}

function packRow(p: PackInfo): HTMLElement {
  const note = h("span", { class: "muted small" }, p.overridden ? `Default is ${p.default_mode}` : "");
  const sw = p.kind === "maps" ? null : modeSeg(`${p.title} mode`, p.mode, async (m) => {
    try { const r = await patch<{ pack: PackInfo }>(`/api/knowledge/packs/${enc(p.id)}`, { mode: m }); note.textContent = r.pack.overridden ? `Default is ${r.pack.default_mode}` : ""; toast(`${p.title}: ${m}`); }
    catch (e) { sw?.set(p.mode); toast((e as Error).message, "error"); }
  });
  return h("div", { class: "k-pack" },
    h("div", { class: "k-pack-head" }, h("div", null, h("button", { class: "title", type: "button", onclick: () => goKnowledge("packs", { pack: p.id }) }, p.title), h("div", { class: "k-note" }, p.description)),
      h("button", { class: "btn small ghost", type: "button", onclick: () => goKnowledge("packs", { pack: p.id }), "aria-label": `Open ${p.title}` }, icon("chevronRight", 16))),
    packChips(p), h("div", { class: "k-pack-ctl" }, sw ? sw.el : h("span", { class: "muted small" }, "Always used"), note));
}

// ------------------------------------------------------------------------------------------------ one pack
interface PackPage { pack: PackInfo; total: number; offset: number; items: Entry[]; payload?: Record<string, unknown> }
type Filter = "all" | "added" | "off" | "edited";

function renderPack(host: HTMLElement, id: string): void {
  let pack: PackInfo;
  let items: Entry[] = [];
  let total = 0;
  let q = "";
  let only: Filter = "all";
  const list = h("div", { class: "k-entries" });
  const moreBtn = h("button", { class: "btn small", type: "button" }, "Show more") as HTMLButtonElement;
  const count = h("span", { class: "muted small" }, "");
  const url = (offset: number) => `/api/knowledge/packs/${enc(id)}?limit=60&offset=${offset}&q=${enc(q)}&only=${only === "all" ? "" : only}`;

  const entryRow = (e: Entry): HTMLElement => {
    const onFeed = e.source.startsWith("feed:");
    const sw = h("input", { type: "checkbox", class: "switch", checked: e.enabled, "aria-label": `Use ${e.phrase}` }) as HTMLInputElement;
    sw.onchange = async () => {
      try { await patch(`/api/knowledge/packs/${enc(id)}/entries`, { phrase: e.phrase, enabled: sw.checked }); e.enabled = sw.checked; row.classList.toggle("off", !sw.checked); }
      catch (err) { sw.checked = !sw.checked; toast((err as Error).message, "error"); }
    };
    const w = h("input", { type: "number", class: "k-weight", min: 0, max: 100, value: String(e.weight), "aria-label": `Weight of ${e.phrase}`, title: "How much score this adds, 1 to 100. Back to the default value resets it." }) as HTMLInputElement;
    w.onchange = async () => {
      const v = Math.max(0, Math.min(100, Math.round(Number(w.value) || 0)));
      try { await patch(`/api/knowledge/packs/${enc(id)}/entries`, { phrase: e.phrase, weight: v === e.default_weight ? 0 : v }); e.weight = v || e.default_weight; w.value = String(e.weight); toast("Saved"); }
      catch (err) { w.value = String(e.weight); toast((err as Error).message, "error"); }
    };
    const act = e.builtin
      ? (e.edited ? h("button", { class: "btn small ghost", type: "button", title: "Back to the built-in setting", onclick: async () => { await post(`/api/knowledge/packs/${enc(id)}/entries/remove`, { phrase: e.phrase }); await reload(); } }, icon("undo", 14), "Reset") : null)
      : onFeed ? null
        : h("button", { class: "btn small ghost", type: "button", "aria-label": `Remove ${e.phrase}`, onclick: async () => {
          await post(`/api/knowledge/packs/${enc(id)}/entries/remove`, { phrase: e.phrase });
          await reload();
          toastAction(`Removed “${e.phrase.slice(0, 30)}”`, "Undo", async () => { await post(`/api/knowledge/packs/${enc(id)}/entries`, { phrases: [(e.regex ? "re:" : "") + e.phrase], weight: e.weight === pack.weight ? 0 : e.weight }); await reload(); });
        } }, icon("trash", 14));
    const row: HTMLElement = h("div", { class: `k-entry${e.enabled ? "" : " off"}` },
      h("span", { class: "k-phrase" }, e.phrase),
      h("div", { class: "ctl" }, w, sw, act),
      h("div", { class: "meta" }, e.regex ? h("span", { class: "chip" }, "pattern") : null,
        h("span", { class: `chip${e.builtin ? "" : " ok"}` }, e.builtin ? "built in" : onFeed ? `from ${e.source.slice(5)}` : e.source === "learned" ? "learned" : "added by you"),
        e.edited ? h("span", { class: "chip warn" }, "changed") : null));
    return row;
  };
  const paint = () => {
    mount(list, items.length ? items.map(entryRow) : empty("search", q || only !== "all" ? "No entries match." : "This pack has no entries yet."));
    count.textContent = total ? `Showing ${items.length} of ${total.toLocaleString()}` : "";
    moreBtn.hidden = items.length >= total;
  };
  const reload = async () => {
    const r = await get<PackPage>(url(0));
    items = r.items; total = r.total; pack = r.pack; paint();
  };
  moreBtn.onclick = () => busy(moreBtn, async () => { const r = await get<PackPage>(url(items.length)); items = [...items, ...r.items]; total = r.total; paint(); });

  const search = h("input", { type: "search", placeholder: "Search this pack", "aria-label": "Search this pack" }) as HTMLInputElement;
  search.oninput = debounce(() => { q = search.value.trim(); void reload().catch((e) => toast((e as Error).message, "error")); }, 250);
  const filter = seg<Filter>("Show", [{ id: "all", label: "All" }, { id: "added", label: "Added" }, { id: "off", label: "Off" }, { id: "edited", label: "Changed" }], "all", (v) => { only = v; void reload(); });

  const add = (): HTMLElement => {
    const hint: Record<string, string> = {
      phrases: "One phrase per line. Start a line with re: to use a pattern. Typos and disguises are handled for you.",
      domains: "One domain per line, for example shady-deals.example. Sub-domains are included.", tlds: "Domain endings such as xyz or top, one per line.",
      words: "One word per line.", domain_regex: "One pattern per line, matched against the address.",
    };
    const ta = h("textarea", { rows: 4, placeholder: pack.kind === "domains" ? "example.com" : "type here, one per line", "aria-label": "Entries to add" }) as HTMLTextAreaElement;
    const wt = h("input", { type: "number", min: 0, max: 100, placeholder: `${pack.weight}`, class: "k-weight", "aria-label": "Weight for the new entries (optional)" }) as HTMLInputElement;
    const btn = h("button", { class: "btn primary", type: "button" }, icon("plus", 16), "Add") as HTMLButtonElement;
    btn.onclick = () => busy(btn, async () => {
      const phrases = ta.value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (!phrases.length) throw new Error("Type at least one entry.");
      const r = await post<{ added: number; skipped: number; problems: string[] }>(`/api/knowledge/packs/${enc(id)}/entries`, { phrases, weight: Math.round(Number(wt.value) || 0) });
      ta.value = "";
      toast(`Added ${r.added}${r.skipped ? `, ${r.skipped} already there` : ""}${r.problems.length ? `, ${r.problems.length} not valid` : ""}`);
      await reload();
    });
    return kcard("plus", "Add your own", h("div", { class: "k-add" }, h("p", { class: "k-note" }, hint[pack.kind] ?? ""), ta,
      h("div", { class: "row" }, h("label", { class: "field" }, "Weight (optional)", wt), btn)));
  };

  const exportAll = async (b: HTMLButtonElement) => busy(b, async () => {
    const lines: string[] = [`# ${pack.title} (${pack.id}, v${pack.version})`, ""];
    let off = 0;
    for (let i = 0; i < 100 && off < 100000; i++) {
      const r = await get<PackPage>(`/api/knowledge/packs/${enc(id)}?limit=200&offset=${off}`);
      r.items.forEach((e) => lines.push(`${e.regex ? "re:" : ""}${e.phrase}${e.weight !== pack.weight ? `\t${e.weight}` : ""}`));
      off += r.items.length;
      if (!r.items.length || off >= r.total) break;
    }
    const a = h("a", { href: URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/plain" })), download: `${pack.id}.txt` });
    document.body.appendChild(a); a.click(); a.remove();
    toast("Exported");
  });

  const draw = (p: PackPage) => {
    pack = p.pack;
    const slider = h("input", { type: "range", min: 0.1, max: 3, step: 0.1, value: String(pack.scale), "aria-label": "Pack strength" }) as HTMLInputElement;
    const out = h("output", null, `${pack.scale.toFixed(1)}x`);
    slider.oninput = () => { out.textContent = `${Number(slider.value).toFixed(1)}x`; };
    slider.onchange = async () => { try { await patch(`/api/knowledge/packs/${enc(id)}`, { scale: Number(slider.value) }); toast("Saved"); } catch (e) { toast((e as Error).message, "error"); } };
    const sw = pack.kind === "maps" ? null : modeSeg("Pack mode", pack.mode, async (m) => { try { await patch(`/api/knowledge/packs/${enc(id)}`, { mode: m }); toast(`${pack.title}: ${m}`); } catch (e) { sw?.set(pack.mode); toast((e as Error).message, "error"); } });
    const exportBtn = h("button", { class: "btn small", type: "button" }, icon("download", 15), "Export") as HTMLButtonElement;
    exportBtn.onclick = () => void exportAll(exportBtn);
    mount(host,
      h("div", null, h("button", { class: "k-back", type: "button", onclick: () => goKnowledge("packs", { cat: pack.category }) }, icon("arrowLeft", 16), "All packs")),
      kcard("database", pack.title, h("div", { class: "k-stack" }, h("p", { class: "k-note" }, pack.description), packChips(pack),
        h("div", { class: "chip-row tight" }, h("span", { class: "chip" }, `version ${pack.version}`), h("span", { class: "chip" }, pack.source), pack.license ? h("span", { class: "chip" }, pack.license) : null),
        sw ? h("div", { class: "k-stack" }, h("div", { class: "k-pack-ctl" }, sw.el, h("span", { class: "muted small" }, pack.overridden ? `Default is ${pack.default_mode}` : "Default setting")),
          pack.kind === "corpus" ? null : h("div", { class: "k-slider" }, h("span", { class: "muted small" }, "Strength"), slider, out)) : null,
        pack.needs_target ? h("p", { class: "k-note" }, "Scored higher when the message talks to someone ('you', 'u', 'wewe') and lower when it does not.") : null,
        pack.signal ? h("p", { class: "k-note" }, `A match counts as “${signalName(pack.signal)}” and the matching detector's mode also applies (see Detectors). Entries default to a weight of ${pack.weight}.`) : null)),
      pack.editable ? [add(), kcard("list", "Entries", h("div", { class: "k-stack" }, h("div", { class: "input-icon" }, icon("search", 16), search), h("div", { class: "row between" }, filter.el, count), list, h("div", { class: "row" }, moreBtn, exportBtn)), { scroll: true })] : payload(p));
    paint();
  };
  void get<PackPage>(url(0)).then((r) => { items = r.items; total = r.total; draw(r); }).catch((e) => { toast((e as Error).message, "error"); mount(host, invite("alert", "Could not open this pack", (e as Error).message, h("button", { class: "btn", type: "button", onclick: () => goKnowledge("packs") }, "Back"))); });
}

function payload(p: PackPage): HTMLElement {
  const d = (p.payload ?? {}) as Record<string, any>;
  if (p.pack.kind === "facets") {
    return kcard("target", "Word groups", h("div", { class: "k-stack" },
      h("p", { class: "k-note" }, `A message scores when ${d.min_groups ?? 2} or more groups are present together, and at least one of ${(d.anchors ?? []).join(", ")}. Words are matched whole, so common words are left out on purpose. Entries starting with re: are patterns.`),
      Object.entries(d.facets ?? {}).map(([name, words]) => h("div", null, h("strong", null, name), h("div", { class: "k-chips", style: "margin-top:6px" }, (words as string[]).map((w) => h("span", { class: "chip" }, w)))))));
  }
  if (p.pack.kind === "corpus") {
    return kcard("list", `${(d.examples ?? []).length} examples (${d.label})`, h("div", { class: "k-stack" },
      h("p", { class: "k-note" }, d.label === "spam" ? "Example spam. The word-statistics model learns what spam looks like from these, and new messages are compared against them." : "Everyday chat. Teaches the model that words like 'link' or 'free' are normal in ordinary sentences."),
      h("ul", { class: "list" }, (d.examples ?? []).slice(0, 200).map((t: string) => h("li", null, h("q", null, t))))));
  }
  if (p.pack.kind === "maps") {
    return kcard("textSize", "Look-alikes and tricks", h("div", { class: "k-stack" },
      h("p", { class: "k-note" }, "Before matching, these letters are turned back into plain ones, so 'ᴀ' or a Cyrillic 'о' cannot hide a word. Symbol sequences like |< also become letters."),
      h("div", { class: "k-chips" }, Object.entries(d.letters ?? {}).map(([k, v]) => h("span", { class: "chip" }, `${k} → ${v}`))),
      h("div", { class: "k-chips" }, (d.sequences ?? []).map((s: string[]) => h("span", { class: "chip" }, `${s[0]} → ${s[1]}`)))));
  }
  return empty("info", "Nothing to show.");
}
