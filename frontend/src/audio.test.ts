import { describe, it, expect, vi } from "vitest";
import { Resampler, pcmBase64, Player, PlaybackInterruption } from "./audio";

describe("interruption recovery", () => {
  it("does not leave a replacement turn stuck speaking after a cancelled candidate", () => {
    const gate = new PlaybackInterruption();
    gate.candidate();
    expect(gate.drained()).toBe(false);
    gate.reset(); // text submission, Stop, or a new capture supersedes the candidate
    expect(gate.drained()).toBe(true);
    expect(gate.reject()).toBe(false);
  });
  it("releases a drained turn exactly once when a candidate is rejected as echo", () => {
    const gate = new PlaybackInterruption();
    gate.candidate();
    expect(gate.drained()).toBe(false);
    expect(gate.reject()).toBe(true);
    expect(gate.reject()).toBe(false);
    expect(gate.drained()).toBe(true);
  });
});

describe("browser audio contract", () => {
  it.each([44100, 48000, 96000])(
    "resamples native %i Hz without losing chunk continuity",
    (rate) => {
      const input = Float32Array.from(
        { length: rate },
        (_, i) => 0.5 * Math.sin((2 * Math.PI * 440 * i) / rate),
      );
      const whole = new Resampler(rate).push(input);
      const streaming = new Resampler(rate);
      const pieces: number[] = [];
      for (let i = 0; i < input.length; i += 2048)
        pieces.push(...streaming.push(input.slice(i, i + 2048)));
      expect(pieces.length).toBe(whole.length);
      expect(pieces.length).toBeGreaterThan(15980);
      expect(pieces.length).toBeLessThanOrEqual(16001);
      for (let i = 0; i < pieces.length; i++)
        expect(Math.abs(pieces[i] - whole[i])).toBeLessThanOrEqual(1);
    },
  );
  it("encodes little-endian PCM rather than recording-container bytes", () => {
    expect(pcmBase64(new Int16Array([1, -2, 32767]))).toBe("AQD+//9/");
  });
  it("anti-aliases frequencies above the target Nyquist rate", () => {
    const rate = 48000;
    const input = Float32Array.from(
      { length: rate },
      (_, i) => 0.8 * Math.sin((2 * Math.PI * 12000 * i) / rate),
    );
    const samples = new Resampler(rate).push(input).slice(40);
    const rms = Math.sqrt(
      Array.from(samples).reduce((sum, v) => sum + (v / 32768) ** 2, 0) /
        samples.length,
    );
    expect(rms).toBeLessThan(0.025);
  });
  it("drops decoded audio that arrives after interruption", async () => {
    let resolve!: (value: unknown) => void;
    const start = vi.fn();
    const context = {
      resume: vi.fn(),
      currentTime: 0,
      createAnalyser: () => ({ fftSize: 0, connect: vi.fn() }),
      destination: {},
      decodeAudioData: () =>
        new Promise((r) => {
          resolve = r;
        }),
      createBufferSource: () => ({
        connect: vi.fn(),
        start,
        disconnect: vi.fn(),
      }),
    };
    vi.stubGlobal(
      "AudioContext",
      class {
        constructor() {
          return context;
        }
      },
    );
    const player = new Player();
    await player.activate();
    player.push("AAAA");
    await new Promise((r) => setTimeout(r, 0));
    player.stop();
    resolve({ duration: 1 });
    await new Promise((r) => setTimeout(r, 0));
    expect(start).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("playback mute recovery", () => {
  it("waits for every queued buffer to end even when generation completes before decoding", async () => {
    const sources: {
      onended: null | (() => void);
      start: ReturnType<typeof vi.fn>;
    }[] = [];
    vi.stubGlobal(
      "AudioContext",
      class {
        currentTime = 0;
        destination = {};
        resume = vi.fn();
        createAnalyser = () => ({ connect: vi.fn(), fftSize: 0 });
        decodeAudioData = async () => ({ duration: 2 });
        createBufferSource = () => {
          const source = {
            connect: vi.fn(),
            disconnect: vi.fn(),
            stop: vi.fn(),
            start: vi.fn(),
            onended: null,
          };
          sources.push(source);
          return source;
        };
      },
    );
    const player = new Player();
    player.onDrained = vi.fn();
    player.push("AAAA");
    player.push("AAAA");
    player.push("AAAA");
    player.complete();
    expect(player.onDrained).not.toHaveBeenCalled();
    await new Promise((r) => setTimeout(r, 0));
    expect(sources).toHaveLength(3);
    expect(sources[0].start.mock.calls[0][0]).toBeCloseTo(0.03);
    expect(sources[2].start.mock.calls[0][0]).toBeCloseTo(4.17);
    sources[0].onended!();
    sources[1].onended!();
    expect(player.onDrained).not.toHaveBeenCalled();
    sources[2].onended!();
    expect(player.onDrained).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });

  it("drains a completed turn when muted while audio is still playing", async () => {
    const stop = vi.fn();
    vi.stubGlobal(
      "AudioContext",
      class {
        currentTime = 0;
        destination = {};
        resume = vi.fn();
        createAnalyser = () => ({ connect: vi.fn(), fftSize: 0 });
        decodeAudioData = async () => ({ duration: 10 });
        createBufferSource = () => ({
          connect: vi.fn(),
          disconnect: vi.fn(),
          start: vi.fn(),
          stop,
          onended: null,
        });
      },
    );
    const player = new Player();
    player.onDrained = vi.fn();
    player.push("AAAA");
    await new Promise((r) => setTimeout(r, 0));
    player.complete();
    expect(player.onDrained).not.toHaveBeenCalled();
    player.setMuted(true);
    expect(stop).toHaveBeenCalledOnce();
    expect(player.onDrained).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});

it("does not resume suspended playback when queued audio arrives during an interruption candidate", async () => {
  const resume = vi.fn();
  const suspend = vi.fn();
  vi.stubGlobal(
    "AudioContext",
    class {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = resume;
      suspend = suspend;
      createAnalyser = () => ({ connect: vi.fn(), fftSize: 0 });
      decodeAudioData = async () => ({ duration: 10 });
      createBufferSource = () => ({
        connect: vi.fn(),
        disconnect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      });
    },
  );
  const player = new Player();
  await player.activate();
  await player.pause();
  player.push("AAAA");
  await new Promise((r) => setTimeout(r, 0));
  expect(resume).toHaveBeenCalledTimes(1);
  expect(suspend).toHaveBeenCalledOnce();
  player.stop();
  vi.unstubAllGlobals();
});
