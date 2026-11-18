/** Settings > Knowledge > Overview > Tools: pack health, detector hits, and moving all your Knowledge between installs. */
import { get, post } from "../api.js";
import { busy, h, mount, toast } from "../dom.js";
import { icon } from "../icons.js";
import { kcard } from "./knowledge-shared.js";
import { figures, plural } from "./widgets.js";

interface Finding { kind: string; pack: string; phrase: string; why: string }
interface Health { checked: number; total: number; findings: Finding[]; by_kind: Record<string, number> }
interface Hits { total: number; detectors: { name: string; hits: number }[] }
interface ImportReport { dry_run: boolean; pack_settings: number; unknown_packs: string[]; entries: number; lessons: number; entries_added?: number; entries_skipped?: number; lessons_added?: number }

const KIND: Record<string, string> = { "ham-hit": "Appears in normal chat", short: "Very short trigger", duplicate: "Listed twice", overlap: "In more than one pack" };
const fail = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error");

function save(name: string, data: unknown): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
  const a = h("a", { href: url, download: name }) as HTMLAnchorElement;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function healthView(r: Health): HTMLElement {
  if (!r.total) return h("p", { class: "k-note" }, `Checked ${plural(r.checked, "pack")}. Nothing to fix.`);
  return h("div", { class: "k-stack" },
    h("p", { class: "k-note" }, `Checked ${plural(r.checked, "pack")} and found ${plural(r.total, "thing")} worth a look. The first group is the most important: those phrases would flag messages that are known to be normal.`),
    h("ul", { class: "list" }, r.findings.slice(0, 40).map((f) => h("li", null, h("span", { class: "chip" }, KIND[f.kind] ?? f.kind), " ", h("b", null, f.phrase),
      h("span", { class: "muted small" }, ` in ${f.pack}`), h("div", { class: "muted small" }, f.why)))),
    r.total > 40 ? h("p", { class: "k-note" }, `Showing 40 of ${r.total}.`) : null);
}

function importView(r: ImportReport): HTMLElement {
  return h("div", { class: "k-stack" }, figures(r.dry_run
    ? [{ value: String(r.entries), label: "entries to add" }, { value: String(r.pack_settings), label: "pack settings" }, { value: String(r.lessons), label: "lessons" }]
    : [{ value: String(r.entries_added ?? 0), label: "entries added", tone: "ok" }, { value: String(r.entries_skipped ?? 0), label: "already here" }, { value: String(r.lessons_added ?? 0), label: "lessons added" }]),
    r.unknown_packs.length ? h("p", { class: "k-note" }, `Skipped settings for packs this version does not have: ${r.unknown_packs.join(", ")}.`) : null);
}

export function toolsCard(): HTMLElement {
  const out = h("div", { class: "k-stack" });
  const btn = (label: string, ic: string, run: () => Promise<void>) => {
    const b = h("button", { class: "btn small", type: "button" }, icon(ic as any, 15), label) as HTMLButtonElement;
    b.onclick = () => busy(b, async () => { try { await run(); } catch (e) { fail(e); } });
    return b;
  };
  const file = h("input", { type: "file", accept: "application/json,.json", hidden: true }) as HTMLInputElement;
  file.onchange = async () => {
    const f = file.files?.[0]; file.value = "";
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      const preview = await post<ImportReport>("/api/knowledge/bundle/import?dry=1", data);
      const go = h("button", { class: "btn primary small", type: "button" }, icon("upload", 15), "Import now") as HTMLButtonElement;
      go.onclick = () => busy(go, async () => {
        try { mount(out, importView(await post<ImportReport>("/api/knowledge/bundle/import", data))); toast("Knowledge imported", "ok"); } catch (e) { fail(e); }
      });
      mount(out, h("div", { class: "k-stack" }, h("p", { class: "k-note" }, "This is what the file would add. Nothing has changed yet. Your lessons are snapshotted first, and entries already here are skipped."),
        importView(preview), h("div", { class: "row" }, go)));
    } catch (e) { fail(e); }
  };
  return kcard("sliders", "Tools", h("div", { class: "k-stack" },
    h("p", { class: "k-note" }, "Check your packs for trouble, see which detectors really fire, or carry all your own Knowledge (added phrases, pack settings, lessons) to another install."),
    h("div", { class: "row wrap" },
      btn("Check pack health", "shield", async () => mount(out, healthView(await get<Health>("/api/knowledge/health")))),
      btn("Detector hits", "chart", async () => {
        const r = await get<Hits>("/api/knowledge/hits");
        mount(out, r.total ? h("ul", { class: "list" }, r.detectors.map((d) => h("li", null, h("b", null, d.name), h("span", { class: "muted small" }, ` ${d.hits.toLocaleString()} hits`))))
          : h("p", { class: "k-note" }, "No detector has fired yet."));
      }),
      btn("Export bundle", "download", async () => { save("savahbot-knowledge.json", await get("/api/knowledge/bundle")); toast("Bundle saved", "ok"); }),
      btn("Import bundle", "upload", async () => { file.click(); })), file, out));
}
