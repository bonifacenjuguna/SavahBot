import { DEFAULT_RULES, KOKORO_VOICES, prepare, shouldRead, voiceFor, type Msg, type Rules } from "./reader-core.js";

/** Chat reader. Two voices: the ones built into the browser (always there, free) and a neural voice (Kokoro, free and open source) that the browser downloads once.
 *  If the neural voice cannot load or fails mid-stream, reading carries on with the built-in voice and says why. Reading only ever starts from a tap. */
export interface DevicePrefs { engine: "builtin" | "kokoro"; voice: string; rate: number; volume: number; source: string }
const KEY = "savah.reader.device";
export const DEFAULT_DEVICE: DevicePrefs = { engine: "builtin", voice: "", rate: 1, volume: 1, source: "" };
export const devicePrefs = (): DevicePrefs => { try { return { ...DEFAULT_DEVICE, ...(JSON.parse(localStorage.getItem(KEY) || "{}") as Partial<DevicePrefs>) }; } catch { return { ...DEFAULT_DEVICE }; } };
export const saveDevicePrefs = (p: DevicePrefs): void => { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private mode */ } };

export const builtinSupported = (): boolean => typeof speechSynthesis !== "undefined";
export const builtinVoices = (): SpeechSynthesisVoice[] => (builtinSupported() ? speechSynthesis.getVoices() : []);
const SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

/** The neural voice lives in a Web Worker (reader-worker.ts) so loading and speaking never block the page. */
class Neural {
  private worker: Worker | null = null;
  private ready: Promise<void> | null = null;
  private seq = 0;
  private waiting = new Map<number, { ok: (b: ArrayBuffer) => void; fail: (e: Error) => void }>();
  private onReady: (() => void) | null = null;
  private onFail: ((e: Error) => void) | null = null;
  constructor(private progress: (text: string) => void) {}
  get loaded(): boolean { return this.ready !== null; }
  load(base: string): Promise<void> {
    if (this.ready) return this.ready;
    if (typeof Worker === "undefined") return Promise.reject(new Error("this browser cannot run background workers"));
    this.ready = new Promise<void>((ok, fail) => {
      this.onReady = ok; this.onFail = fail;
      let w: Worker;
      try { w = new Worker(new URL("./reader-worker.ts", import.meta.url), { type: "module" }); } catch (e) { fail(e instanceof Error ? e : new Error("the voice worker could not start")); return; }
      this.worker = w;
      w.onmessage = (e: MessageEvent) => {
        const m = e.data as { type: string; text?: string; id?: number; wav?: ArrayBuffer; message?: string };
        if (m.type === "progress") this.progress(m.text ?? "");
        else if (m.type === "ready") this.onReady?.();
        else if (m.type === "audio" && m.id !== undefined) { this.waiting.get(m.id)?.ok(m.wav as ArrayBuffer); this.waiting.delete(m.id); }
        else if (m.type === "fail") {
          const err = new Error(m.message || "the voice failed");
          if (m.id !== undefined) { this.waiting.get(m.id)?.fail(err); this.waiting.delete(m.id); } else this.onFail?.(err);
        }
      };
      w.onerror = (e) => { const err = new Error(e.message || "the voice worker crashed"); this.onFail?.(err); this.waiting.forEach((p) => p.fail(err)); this.waiting.clear(); };
      w.postMessage({ type: "load", base });
    });
    this.ready.catch(() => this.dispose());          // a failed load leaves nothing half-started; the next try begins clean
    return this.ready;
  }
  speak(text: string, voice: string): Promise<ArrayBuffer> {
    const w = this.worker;
    if (!w) return Promise.reject(new Error("the voice is not loaded"));
    const id = ++this.seq;
    return new Promise((ok, fail) => { this.waiting.set(id, { ok, fail }); w.postMessage({ type: "speak", id, text, voice }); });
  }
  dispose(): void { this.worker?.terminate(); this.worker = null; this.ready = null; this.waiting.forEach((p) => p.fail(new Error("the voice was stopped"))); this.waiting.clear(); }
}
export interface ReaderState { running: boolean; loading: string; engine: "builtin" | "kokoro"; note: string; queued: number; spoken: number }

class Reader {
  rules: Rules = DEFAULT_RULES;
  private q: { text: string; voice: string }[] = [];
  private busy = false;
  private neural = new Neural((text) => this.set({ loading: text }));
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
    const cap = devicePrefs().engine === "kokoro" && !this.fell ? 4 : 25;   // a neural voice is slower than chat: keep only the newest few so it never falls minutes behind
    while (this.q.length > cap) this.q.shift();                 // a flood is trimmed, newest kept
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
          try { await this.loadNeural(dev); if (!this.state.running) break; await this.speakNeural(item.text, item.voice || dev.voice || "af_heart", dev); this.set({ spoken: this.state.spoken + 1 }); continue; }
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

  private async loadNeural(dev: DevicePrefs): Promise<void> {
    if (!this.neural.loaded) this.set({ loading: "Starting the voice…" });
    try { await this.neural.load(dev.source); } finally { this.set({ loading: "" }); }
  }

  private async speakNeural(text: string, voice: string, dev: DevicePrefs): Promise<void> {
    const wav = await this.neural.speak(text, voice);                  // made off the page's thread
    if (!this.state.running) return;                                   // Read chat was switched off while this was being made
    const url = URL.createObjectURL(new Blob([wav], { type: "audio/wav" }));
    await new Promise<void>((done, fail) => {
      const a = new Audio(url);
      this.current = a;
      a.volume = dev.volume; a.playbackRate = dev.rate;
      a.onended = () => done();
      a.onpause = () => { if (!this.state.running) done(); };           // stop() pauses the clip: finish the wait instead of hanging
      a.onerror = () => fail(new Error("the audio could not be played"));
      a.play().catch((e) => fail(e instanceof Error ? e : new Error("the browser blocked sound")));
    }).finally(() => URL.revokeObjectURL(url));
  }
}

export const reader = new Reader();
export { KOKORO_VOICES };
