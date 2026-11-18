/**
 * 1.3.2: the neural voice (Kokoro) runs here, in a Web Worker, never on the page's own thread.
 * Loading the model and turning text into sound is heavy WebAssembly work; done on the page it froze scrolling, taps and the live chat.
 * The page now only sends text and gets finished audio back.
 *
 * 1.3.3: optional GPU (WebGPU) with an automatic fall back to the CPU, and the quiet stretches at the start and end of each clip are trimmed,
 *        so lines follow each other without a half-second gap.
 *
 * Messages in:  { type: "load", base, gpu }                 download and start the model (base = optional own host for the files; gpu = try WebGPU first)
 *               { type: "speak", id, text, voice }         make audio for one line
 * Messages out: { type: "progress", text } | { type: "ready" } | { type: "audio", id, wav } | { type: "fail", id?, message }
 */
import { KOKORO_MODEL, rewriteModelUrl } from "./reader-core.js";

const KOKORO_URL = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.0/+esm";     // pinned: a new release never changes behaviour under you

type Out = { type: "progress"; text: string } | { type: "device"; text: string } | { type: "ready" } | { type: "audio"; id: number; wav: ArrayBuffer } | { type: "fail"; id?: number; message: string };
interface Tts { generate(text: string, o: { voice: string }): Promise<{ toBlob?: () => Blob; audio?: Float32Array; sampling_rate?: number }> }
interface Progress { status?: string; progress?: number; file?: string }

const scope = self as unknown as { postMessage(m: Out, t?: Transferable[]): void; onmessage: ((e: MessageEvent) => void) | null; fetch: typeof fetch };
const say = (m: Out, t?: Transferable[]) => scope.postMessage(m, t);

let tts: Tts | null = null;
let loading: Promise<void> | null = null;

function wav(samples: Float32Array, rate: number): ArrayBuffer {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
  return buf;
}

/** Cuts the near-silent start and end of a clip, keeping a short natural edge. */
function trim(a: Float32Array, rate: number): Float32Array {
  const quiet = 0.008;
  let s = 0, e = a.length;
  while (s < e && Math.abs(a[s]) < quiet) s++;
  while (e > s && Math.abs(a[e - 1]) < quiet) e--;
  if (e - s < rate * 0.1) return a;                                                     // nearly all quiet: leave it alone
  return a.subarray(Math.max(0, s - Math.round(rate * 0.03)), Math.min(a.length, e + Math.round(rate * 0.08)));
}

function load(base: string, gpu = false): Promise<void> {
  if (tts) return Promise.resolve();
  if (loading) return loading;
  const realFetch = scope.fetch.bind(self);
  if (base) scope.fetch = ((input: RequestInfo | URL, init?: RequestInit) => realFetch(typeof input === "string" ? rewriteModelUrl(input, base) : input instanceof URL ? rewriteModelUrl(input.href, base) : input, init)) as typeof fetch;
  let lastPct = -1;
  loading = (async () => {
    try {
      say({ type: "progress", text: "Starting the voice…" });
      const mod = (await import(/* @vite-ignore */ KOKORO_URL)) as { KokoroTTS: { from_pretrained(id: string, o: { dtype: string; device: string; progress_callback?: (p: Progress) => void }): Promise<Tts> } };
      const progress_callback = (p: Progress) => {
        if (p.status !== "progress" || typeof p.progress !== "number") return;
        const pct = Math.floor(p.progress / 5) * 5;                                    // a message every 5 %, not hundreds per second
        if (pct !== lastPct) { lastPct = pct; say({ type: "progress", text: `Downloading the voice (one time): ${Math.round(p.progress)}%` }); }
      };
      const tries = gpu && "gpu" in self.navigator ? [{ dtype: "fp32", device: "webgpu" }, { dtype: "q8", device: "wasm" }] : [{ dtype: "q8", device: "wasm" }];
      let last: unknown = null;
      for (const t of tries) {
        try { lastPct = -1; tts = await mod.KokoroTTS.from_pretrained(KOKORO_MODEL, { ...t, progress_callback }); say({ type: "device", text: t.device }); last = null; break; }
        catch (err) { last = err; if (t.device === "webgpu") say({ type: "progress", text: "The GPU could not be used, using the processor instead…" }); }
      }
      if (last || !tts) throw last instanceof Error ? last : new Error("the voice could not load");
      say({ type: "ready" });
    } finally { scope.fetch = realFetch; loading = null; }
  })();
  return loading;
}

scope.onmessage = (e: MessageEvent) => {
  const m = e.data as { type: string; base?: string; gpu?: boolean; id?: number; text?: string; voice?: string };
  if (m.type === "load") {
    load(m.base ?? "", Boolean(m.gpu)).catch((err) => say({ type: "fail", message: err instanceof Error ? err.message : "the voice could not load" }));
  } else if (m.type === "speak" && typeof m.id === "number") {
    const id = m.id;
    (async () => {
      await load("");
      const out = await (tts as Tts).generate(m.text ?? "", { voice: m.voice || "af_heart" });
      const buffer = out.audio instanceof Float32Array ? wav(trim(out.audio, out.sampling_rate ?? 24000), out.sampling_rate ?? 24000) : await (out.toBlob as () => Blob)().arrayBuffer();
      say({ type: "audio", id, wav: buffer }, [buffer]);
    })().catch((err) => say({ type: "fail", id, message: err instanceof Error ? err.message : "the voice could not speak" }));
  }
};
