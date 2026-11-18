import { DEFAULT_RULES, KOKORO_VOICES, prepare, shouldRead, voiceFor, type Msg, type Rules } from "./reader-core.js";

/** Chat reader. Two voices: the ones built into the browser (always there, free) and a neural voice (Kokoro, free and open source) that the browser downloads once.
 *  If the neural voice cannot load or fails mid-stream, reading carries on with the built-in voice and says why. Reading only ever starts from a tap. */
export interface DevicePrefs { engine: "builtin" | "kokoro"; voice: string; rate: number; volume: number; source: string; /** 1.3.3: try the GPU (WebGPU) for the neural voice; falls back to the CPU by itself */ gpu: boolean }
const KEY = "savah.reader.device";
export const DEFAULT_DEVICE: DevicePrefs = { engine: "builtin", voice: "", rate: 1, volume: 1, source: "", gpu: false };
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
  /** "webgpu" or "wasm": what the worker ended up running on */
  device = "";
  constructor(private progress: (text: string) => void) {}
  get loaded(): boolean { return this.ready !== null; }
  load(base: string, gpu = false): Promise<void> {
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
        else if (m.type === "device") this.device = m.text ?? "";
        else if (m.type === "ready") this.onReady?.();
        else if (m.type === "audio" && m.id !== undefined) { this.waiting.get(m.id)?.ok(m.wav as ArrayBuffer); this.waiting.delete(m.id); }
        else if (m.type === "fail") {
          const err = new Error(m.message || "the voice failed");
          if (m.id !== undefined) { this.waiting.get(m.id)?.fail(err); this.waiting.delete(m.id); } else this.onFail?.(err);
        }
      };
      w.onerror = (e) => { const err = new Error(e.message || "the voice worker crashed"); this.onFail?.(err); this.waiting.forEach((p) => p.fail(err)); this.waiting.clear(); };
      w.postMessage({ type: "load", base, gpu });
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
interface Line { text: string; voice: string }
interface Clip { url: string; lines: Line[] }

/** Neural voice speed (1.3.3). Before, one line went through "make the sound, then play it, then start the next", so the processor sat idle during every
 *  playback and a slow phone managed about one line a minute. Now two loops run side by side: one keeps making clips ahead (up to AHEAD of them) while
 *  the other plays them back to back. Lines that pile up are also joined into one clip (up to JOIN lines, JOIN_CHARS letters, same voice), which saves the
 *  fixed cost of each run, and when the queue is long playback speeds up a little to catch up. */
const AHEAD = 2, JOIN = 3, JOIN_CHARS = 300, KEEP_NEURAL = 12, KEEP_BUILTIN = 25;

class Reader {
  rules: Rules = DEFAULT_RULES;
  private q: Line[] = [];                       // waiting to be made into sound
  private clips: Clip[] = [];                   // made and waiting to be played
  private busy = false;                         // built-in voice loop
  private making = false;                       // neural: clip-making loop
  private playing = false;                      // neural: playback loop
  private epoch = 0;                            // bumped by stop/clear so clips still being made are thrown away
  private waiters = new Set<() => void>();
  private neural = new Neural((text) => this.set({ loading: text }));
  private loadedKey = "";
  private fell = false;
  private endCurrent: (() => void) | null = null;   // finishes the clip that is playing, so stop/clear never leave the player waiting
  private listeners = new Set<() => void>();
  state: ReaderState = { running: false, loading: "", engine: "builtin", note: "", queued: 0, spoken: 0 };

  onChange(fn: () => void): () => void { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  private set(p: Partial<ReaderState>): void { this.state = { ...this.state, ...p, queued: this.q.length + this.clips.reduce((n, c) => n + c.lines.length, 0) }; this.listeners.forEach((f) => f()); }
  private poke(): void { const w = [...this.waiters]; this.waiters.clear(); w.forEach((f) => f()); }
  private sleep(): Promise<void> { return new Promise((ok) => { this.waiters.add(ok); }); }
  private drop(): void { this.epoch++; this.q = []; this.clips.forEach((c) => URL.revokeObjectURL(c.url)); this.clips = []; this.endCurrent?.(); if (builtinSupported()) speechSynthesis.cancel(); this.poke(); }

  /** Must be called from a tap: browsers refuse to make sound until the person has interacted with the page. */
  async start(): Promise<void> {
    const dev = devicePrefs();
    try { const a = new Audio(SILENT); await a.play(); } catch { /* the tap still counts for speech */ }
    if (builtinSupported()) speechSynthesis.speak(new SpeechSynthesisUtterance(""));
    this.fell = false;
    this.set({ running: true, engine: dev.engine, note: "" });
    if (dev.engine === "kokoro") void this.loadNeural(dev).catch(() => { /* reported when the first line is made */ });
  }
  stop(): void { this.drop(); this.set({ running: false, loading: "" }); }
  clear(): void { this.drop(); this.set({}); }

  /** Offer a chat line. Whether it is read, and what is said, comes from the rules. */
  offer(m: Msg): void {
    if (!this.state.running || !shouldRead(m, this.rules)) return;
    const text = prepare(m, this.rules);
    if (!text) return;
    this.q.push({ text, voice: voiceFor(m, this.rules) });
    const cap = this.neuralOn() ? KEEP_NEURAL : KEEP_BUILTIN;    // a flood is trimmed, newest kept, so the reader never falls minutes behind
    while (this.q.length > cap) this.q.shift();
    this.set({});
    this.kick();
  }

  private neuralOn(): boolean { return devicePrefs().engine === "kokoro" && !this.fell; }
  private kick(): void {
    if (this.neuralOn()) { void this.make(); void this.play(); this.poke(); } else void this.pump();
  }

  /** The next thing to make: one line, or several short ones from the same voice joined into a single clip. */
  private take(): Line[] {
    const first = this.q.shift();
    if (!first) return [];
    const got = [first];
    let chars = first.text.length;
    while (this.q.length && got.length < JOIN && this.q[0].voice === first.voice && chars + this.q[0].text.length <= JOIN_CHARS) { const n = this.q.shift() as Line; got.push(n); chars += n.text.length; }
    return got;
  }

  /** Neural, loop 1: keep a couple of clips made ahead of the one being played. */
  private async make(): Promise<void> {
    if (this.making) return;
    this.making = true;
    const mine = this.epoch;
    try {
      while (this.state.running && mine === this.epoch && !this.fell) {
        if (!this.q.length || this.clips.length >= AHEAD) { await this.sleep(); continue; }
        const lines = this.take();
        const dev = devicePrefs();
        this.set({});
        try {
          await this.loadNeural(dev);
          const voice = lines[0].voice || dev.voice || "af_heart";
          const wav = await this.neural.speak(lines.map((l) => l.text.replace(/[.!?…]+\s*$/u, "")).join(". "), voice);
          if (mine !== this.epoch || !this.state.running) break;                         // Read chat was switched off or cleared while this was being made
          this.clips.push({ url: URL.createObjectURL(new Blob([wav], { type: "audio/wav" })), lines });
          this.set({}); this.poke();
        } catch (e) {
          if (mine !== this.epoch) break;
          this.fell = true;                                                               // the neural voice is not working: hand everything to the built-in voice
          this.q.unshift(...this.clips.flatMap((c) => c.lines), ...lines);
          this.clips.forEach((c) => URL.revokeObjectURL(c.url)); this.clips = [];
          this.set({ note: `The neural voice did not work (${e instanceof Error ? e.message : "unknown error"}), so the built-in voice is reading instead.`, engine: "builtin" });
          this.poke(); void this.pump();
          break;
        }
      }
    } finally { this.making = false; if (this.state.running && this.neuralOn() && this.q.length && mine !== this.epoch) this.kick(); }
  }

  /** Neural, loop 2: play clips back to back. */
  private async play(): Promise<void> {
    if (this.playing) return;
    this.playing = true;
    try {
      while (this.state.running) {
        const clip = this.clips.shift();
        if (!clip) { await this.sleep(); continue; }
        this.set({}); this.poke();                                                       // a slot is free: the maker can start the next clip
        const dev = devicePrefs();
        const behind = this.q.length + this.clips.length;
        await this.playClip(clip.url, dev, behind >= 3 ? 1.2 : behind >= 2 ? 1.1 : 1);   // a little quicker while there is a queue
        this.set({ spoken: this.state.spoken + clip.lines.length });
      }
    } finally { this.playing = false; }
  }

  private playClip(url: string, dev: DevicePrefs, boost: number): Promise<void> {
    return new Promise<void>((done) => {
      const a = new Audio(url);
      a.volume = dev.volume; a.playbackRate = Math.min(2, dev.rate * boost);
      const end = () => { a.pause(); this.endCurrent = null; URL.revokeObjectURL(url); done(); };
      this.endCurrent = end;
      a.onended = end;
      a.onerror = () => end();                                                           // an unplayable clip is skipped, not allowed to stall the queue
      a.play().catch(() => end());
    });
  }

  /** Built-in voice (and the fallback): one line at a time, the browser queues its own speech. */
  private async pump(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      while (this.q.length && this.state.running && !this.neuralOn()) {
        const item = this.q.shift() as Line;
        this.set({});
        await this.speakBuiltin(item.text, item.voice, devicePrefs());
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
    const key = `${dev.source}|${dev.gpu}`;
    if (this.neural.loaded && key !== this.loadedKey) this.neural.dispose();             // the source or the GPU choice changed: start the voice again
    this.loadedKey = key;
    if (!this.neural.loaded) this.set({ loading: "Starting the voice…" });
    try { await this.neural.load(dev.source, dev.gpu); } finally { this.set({ loading: "" }); }
  }
}

export const reader = new Reader();
export { KOKORO_VOICES };
