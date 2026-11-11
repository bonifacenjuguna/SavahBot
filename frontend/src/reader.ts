import { DEFAULT_RULES, KOKORO_MODEL, KOKORO_VOICES, prepare, rewriteModelUrl, shouldRead, voiceFor, type Msg, type Rules } from "./reader-core.js";

/** Chat reader. Two voices: the ones built into the browser (always there, free) and a neural voice (Kokoro, free and open source) that the browser downloads once.
 *  If the neural voice cannot load or fails mid-stream, reading carries on with the built-in voice and says why. Reading only ever starts from a tap. */
export interface DevicePrefs { engine: "builtin" | "kokoro"; voice: string; rate: number; volume: number; source: string }
const KEY = "savah.reader.device";
export const DEFAULT_DEVICE: DevicePrefs = { engine: "builtin", voice: "", rate: 1, volume: 1, source: "" };
export const devicePrefs = (): DevicePrefs => { try { return { ...DEFAULT_DEVICE, ...(JSON.parse(localStorage.getItem(KEY) || "{}") as Partial<DevicePrefs>) }; } catch { return { ...DEFAULT_DEVICE }; } };
export const saveDevicePrefs = (p: DevicePrefs): void => { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private mode */ } };

const KOKORO_URL = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.0/+esm";   // pinned: a new release never changes behaviour under you
export const builtinSupported = (): boolean => typeof speechSynthesis !== "undefined";
export const builtinVoices = (): SpeechSynthesisVoice[] => (builtinSupported() ? speechSynthesis.getVoices() : []);
const SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

type Tts = { generate(text: string, o: { voice: string }): Promise<{ toBlob?: () => Blob; audio?: Float32Array; sampling_rate?: number }> };
export interface ReaderState { running: boolean; loading: string; engine: "builtin" | "kokoro"; note: string; queued: number; spoken: number }

class Reader {
  rules: Rules = DEFAULT_RULES;
  private q: { text: string; voice: string }[] = [];
  private busy = false;
  private tts: Tts | null = null;
  private loadingNeural: Promise<void> | null = null;
  private fell = false;
  private current: HTMLAudioElement | null = null;
  private listeners = new Set<() => void>();
  state: ReaderState = { running: false, loading: "", engine: "builtin", note: "", queued: 0, spoken: 0 };

  onChange(fn: () => void): () => void { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  private set(p: Partial<ReaderState>): void { this.state = { ...this.state, ...p, queued: this.q.length }; this.listeners.forEach((f) => f()); }

  /** Must be called from a tap: browsers refuse to make sound until the person has interacted with the page. */
  async start(): Promise<void> {
    const dev = devicePrefs();
    try { const a = new Audio(SILENT); await a.play(); } catch { /* the tap still counts for speech */ }
    if (builtinSupported()) speechSynthesis.speak(new SpeechSynthesisUtterance(""));
    this.fell = false;
    this.set({ running: true, engine: dev.engine, note: "" });
    if (dev.engine === "kokoro") void this.loadNeural(dev);
  }
  stop(): void { this.q = []; this.current?.pause(); if (builtinSupported()) speechSynthesis.cancel(); this.set({ running: false, loading: "" }); }
  clear(): void { this.q = []; this.current?.pause(); if (builtinSupported()) speechSynthesis.cancel(); this.set({}); }

  /** Offer a chat line. Whether it is read, and what is said, comes from the rules. */
  offer(m: Msg): void {
    if (!this.state.running || !shouldRead(m, this.rules)) return;
    const text = prepare(m, this.rules);
    if (!text) return;
    this.q.push({ text, voice: voiceFor(m, this.rules) });
    while (this.q.length > 25) this.q.shift();                 // a flood is trimmed, newest kept
    this.set({});
    void this.pump();
  }

  private async pump(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      while (this.q.length && this.state.running) {
        const item = this.q.shift() as { text: string; voice: string };
        this.set({});
        const dev = devicePrefs();
        if (dev.engine === "kokoro" && !this.fell) {
          try { await this.loadNeural(dev); await this.speakNeural(item.text, item.voice || dev.voice || "af_heart", dev); this.set({ spoken: this.state.spoken + 1 }); continue; }
          catch (e) { this.fell = true; this.set({ note: `The neural voice did not work (${e instanceof Error ? e.message : "unknown error"}), so the built-in voice is reading instead.`, engine: "builtin" }); }
        }
        await this.speakBuiltin(item.text, item.voice, dev);
        this.set({ spoken: this.state.spoken + 1 });
      }
    } finally { this.busy = false; }
  }

  private speakBuiltin(text: string, voiceName: string, dev: DevicePrefs): Promise<void> {
    return new Promise((done) => {
      if (!builtinSupported()) { this.set({ note: "This browser has no built-in voices, so nothing can be read aloud here." }); done(); return; }
      const u = new SpeechSynthesisUtterance(text);
      const v = builtinVoices().find((x) => x.voiceURI === (voiceName || dev.voice) || x.name === (voiceName || dev.voice));
      if (v) u.voice = v;
      u.rate = dev.rate; u.volume = dev.volume;
      u.onend = u.onerror = () => done();
      speechSynthesis.speak(u);
    });
  }

  private loadNeural(dev: DevicePrefs): Promise<void> {
    if (this.tts) return Promise.resolve();
    if (this.loadingNeural) return this.loadingNeural;
    this.set({ loading: "Downloading the voice (one time, about 90 MB)…" });
    const realFetch = window.fetch;
    const base = dev.source;
    if (base) window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => realFetch(typeof input === "string" ? rewriteModelUrl(input, base) : input instanceof URL ? rewriteModelUrl(input.href, base) : input, init)) as typeof fetch;
    this.loadingNeural = (async () => {
      try {
        const mod = (await import(/* @vite-ignore */ KOKORO_URL)) as { KokoroTTS: { from_pretrained(id: string, o: { dtype: string; device: string }): Promise<Tts> } };
        this.tts = await mod.KokoroTTS.from_pretrained(KOKORO_MODEL, { dtype: "q8", device: "wasm" });
        this.set({ loading: "" });
      } catch (e) { this.set({ loading: "" }); throw e; }
      finally { window.fetch = realFetch; this.loadingNeural = null; }
    })();
    return this.loadingNeural;
  }

  private async speakNeural(text: string, voice: string, dev: DevicePrefs): Promise<void> {
    const out = await (this.tts as Tts).generate(text, { voice });
    const blob = out.toBlob ? out.toBlob() : wav(out.audio as Float32Array, out.sampling_rate ?? 24000);
    const url = URL.createObjectURL(blob);
    await new Promise<void>((done, fail) => {
      const a = new Audio(url);
      this.current = a;
      a.volume = dev.volume; a.playbackRate = dev.rate;
      a.onended = () => done();
      a.onerror = () => fail(new Error("the audio could not be played"));
      a.play().catch((e) => fail(e instanceof Error ? e : new Error("the browser blocked sound")));
    }).finally(() => URL.revokeObjectURL(url));
  }
}

function wav(samples: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([buf], { type: "audio/wav" });
}

export const reader = new Reader();
export { KOKORO_VOICES };
