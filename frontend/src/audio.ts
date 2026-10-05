/** Streaming FIR resampler with persistent fractional position across worklet blocks. */
export class Resampler {
  private pending: number[] = Array(32).fill(0);
  private position = 16;
  constructor(
    public sourceRate: number,
    public targetRate = 16000,
  ) {}
  push(input: Float32Array): Int16Array {
    this.pending.push(...input);
    const out: number[] = [],
      ratio = this.sourceRate / this.targetRate;
    const cutoff = Math.min(1, this.targetRate / this.sourceRate) * 0.94;
    while (this.position + 16 < this.pending.length) {
      const center = Math.floor(this.position);
      let sum = 0,
        norm = 0;
      for (let k = center - 15; k <= center + 16; k++) {
        const x = k - this.position;
        const sinc =
          Math.abs(x) < 1e-9
            ? cutoff
            : Math.sin(Math.PI * cutoff * x) / (Math.PI * x);
        const window = 0.5 + 0.5 * Math.cos((Math.PI * x) / 16);
        const weight = sinc * window;
        sum += this.pending[k] * weight;
        norm += weight;
      }
      out.push(Math.round(Math.max(-1, Math.min(1, sum / norm)) * 32767));
      this.position += ratio;
    }
    const discard = Math.max(0, Math.floor(this.position) - 16);
    this.pending.splice(0, discard);
    this.position -= discard;
    return Int16Array.from(out);
  }
}
export const pcmBase64 = (samples: Int16Array) => {
  const bytes = new Uint8Array(samples.length * 2),
    view = new DataView(bytes.buffer);
  samples.forEach((value, index) => view.setInt16(index * 2, value, true));
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text);
};
/** A candidate pauses one turn only; it must never block a replacement turn. */
export class PlaybackInterruption {
  private pending = false;
  private deferred = false;
  reset() {
    this.pending = false;
    this.deferred = false;
  }
  candidate() {
    this.pending = true;
  }
  drained() {
    if (!this.pending) return true;
    this.deferred = true;
    return false;
  }
  reject() {
    const drained = this.deferred;
    this.reset();
    return drained;
  }
}
export class Player {
  context: AudioContext | null = null;
  analyser: AnalyserNode | null = null;
  private epoch = 0;
  private queue: Promise<void> = Promise.resolve();
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private count = 0;
  private done = false;
  muted = false;
  private paused = false;
  onDrained: () => void = () => {};
  onError: (message: string) => void = () => {};
  async activate() {
    if (!this.context) {
      this.context = new AudioContext();
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.connect(this.context.destination);
    }
    if (!this.paused) await this.context.resume();
  }
  async pause() {
    this.paused = true;
    if (this.context?.state === "running") await this.context.suspend();
  }
  async resume() {
    this.paused = false;
    if (this.context?.state === "suspended") await this.context.resume();
  }
  stop() {
    this.epoch++;
    this.paused = false;
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        /* already ended */
      }
      source.disconnect();
    }
    this.sources.clear();
    this.queue = Promise.resolve();
    this.nextTime = 0;
    this.count = 0;
    this.done = false;
  }
  setMuted(value: boolean) {
    this.muted = value;
    if (value) {
      const completed = this.done;
      this.stop();
      if (completed) this.complete();
    }
  }
  push(encoded: string) {
    const epoch = this.epoch;
    this.count++;
    this.queue = this.queue
      .then(async () => {
        if (epoch !== this.epoch) return;
        if (this.muted) {
          this.count--;
          this.drain();
          return;
        }
        await this.activate();
        const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
        const audio = await this.context!.decodeAudioData(bytes.buffer);
        if (epoch !== this.epoch) return;
        const source = this.context!.createBufferSource();
        source.buffer = audio;
        source.connect(this.analyser!);
        this.sources.add(source);
        this.nextTime = Math.max(
          this.context!.currentTime + 0.03,
          this.nextTime,
        );
        source.onended = () => {
          if (epoch !== this.epoch) return;
          this.sources.delete(source);
          source.disconnect();
          this.count--;
          this.drain();
        };
        source.start(this.nextTime);
        this.nextTime += audio.duration + 0.07;
      })
      .catch((error) => {
        if (epoch === this.epoch) {
          this.count--;
          this.onError(
            `Voice playback failed: ${error instanceof Error ? error.message : String(error)}. Check your output device and try the voice preview in Settings.`,
          );
          this.drain();
        }
      });
  }
  complete() {
    this.done = true;
    this.drain();
  }
  private drain() {
    if (this.done && this.count === 0) {
      this.done = false;
      this.onDrained();
    }
  }
}
export class Microphone {
  context: AudioContext | null = null;
  analyser: AnalyserNode | null = null;
  stream: MediaStream | null = null;
  node: AudioWorkletNode | null = null;
  resampler: Resampler | null = null;
  pending: number[] = [];
  onSamples: (samples: Int16Array) => void = () => {};
  onLost: () => void = () => {};
  async start(device: string) {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId: device ? { exact: device } : undefined,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      this.context = new AudioContext();
      await this.context.resume();
      await this.context.audioWorklet.addModule("/capture-worklet.js");
      this.resampler = new Resampler(this.context.sampleRate);
      const source = this.context.createMediaStreamSource(this.stream);
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 256;
      source.connect(this.analyser);
      this.node = new AudioWorkletNode(this.context, "jarvis-capture");
      source.connect(this.node);
      const silent = this.context.createGain();
      silent.gain.value = 0;
      this.node.connect(silent);
      silent.connect(this.context.destination);
      this.node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        if (!this.resampler) return;
        const pcm = this.resampler.push(event.data);
        this.pending.push(...pcm);
        while (this.pending.length >= 1024)
          this.onSamples(Int16Array.from(this.pending.splice(0, 1024)));
      };
      this.stream
        .getAudioTracks()
        .forEach((track) => (track.onended = () => this.onLost()));
      return this.context.sampleRate;
    } catch (error) {
      await this.stop();
      throw error;
    }
  }
  async stop() {
    if (this.node) this.node.port.onmessage = null;
    this.node?.disconnect();
    this.node = null;
    this.resampler = null;
    this.stream?.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    this.stream = null;
    if (this.context && this.context.state !== "closed")
      await this.context.close();
    this.context = null;
    this.analyser = null;
    this.pending = [];
  }
}
