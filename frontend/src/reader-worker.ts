/**
 * 1.3.2: the neural voice (Kokoro) runs here, in a Web Worker, never on the page's own thread.
 * Loading the model and turning text into sound is heavy WebAssembly work; done on the page it froze scrolling, taps and the live chat.
 * The page now only sends text and gets finished audio back.
 *
 * Messages in:  { type: "load", base }                     download and start the model (base = optional own host for the files)
 *               { type: "speak", id, text, voice }         make audio for one line
 * Messages out: { type: "progress", text } | { type: "ready" } | { type: "audio", id, wav } | { type: "fail", id?, message }
 */
import { KOKORO_MODEL, rewriteModelUrl } from "./reader-core.js";

const KOKORO_URL = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.0/+esm";     // pinned: a new release never changes behaviour under you

type Out = { type: "progress"; text: string } | { type: "ready" } | { type: "audio"; id: number; wav: ArrayBuffer } | { type: "fail"; id?: number; message: string };
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

function load(base: string): Promise<void> {
  if (tts) return Promise.resolve();
  if (loading) return loading;
  const realFetch = scope.fetch.bind(self);
  if (base) scope.fetch = ((input: RequestInfo | URL, init?: RequestInit) => realFetch(typeof input === "string" ? rewriteModelUrl(input, base) : input instanceof URL ? rewriteModelUrl(input.href, base) : input, init)) as typeof fetch;
  let lastPct = -1;
  loading = (async () => {
    try {
      say({ type: "progress", text: "Starting the voice…" });
      const mod = (await import(/* @vite-ignore */ KOKORO_URL)) as { KokoroTTS: { from_pretrained(id: string, o: { dtype: string; device: string; progress_callback?: (p: Progress) => void }): Promise<Tts> } };
      tts = await mod.KokoroTTS.from_pretrained(KOKORO_MODEL, {
        dtype: "q8", device: "wasm",
        progress_callback: (p) => {
          if (p.status !== "progress" || typeof p.progress !== "number") return;
          const pct = Math.floor(p.progress / 5) * 5;                                    // a message every 5 %, not hundreds per second
          if (pct !== lastPct) { lastPct = pct; say({ type: "progress", text: `Downloading the voice (one time): ${Math.round(p.progress)}%` }); }
        },
      });
      say({ type: "ready" });
    } finally { scope.fetch = realFetch; loading = null; }
  })();
  return loading;
}

scope.onmessage = (e: MessageEvent) => {
  const m = e.data as { type: string; base?: string; id?: number; text?: string; voice?: string };
  if (m.type === "load") {
    load(m.base ?? "").catch((err) => say({ type: "fail", message: err instanceof Error ? err.message : "the voice could not load" }));
  } else if (m.type === "speak" && typeof m.id === "number") {
    const id = m.id;
    (async () => {
      await load("");
      const out = await (tts as Tts).generate(m.text ?? "", { voice: m.voice || "af_heart" });
      const buffer = out.toBlob ? await out.toBlob().arrayBuffer() : wav(out.audio as Float32Array, out.sampling_rate ?? 24000);
      say({ type: "audio", id, wav: buffer }, [buffer]);
    })().catch((err) => say({ type: "fail", id, message: err instanceof Error ? err.message : "the voice could not speak" }));
  }
};
