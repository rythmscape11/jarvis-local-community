import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Globe,
  Mic,
  Square,
  Volume2,
  VolumeX,
  ArrowUp,
  Settings2,
  ShieldCheck,
  ArrowUpRight,
  Maximize2,
  Minimize2,
  BookOpen,
  Brain,
  Clock,
  Activity,
  Plus,
  X,
  Power,
  Check,
  RotateCcw,
} from "lucide-react";
import { Microphone, Player, PlaybackInterruption, pcmBase64 } from "./audio";
import { Visualizer } from "./Visualizer";
import { Automations } from "./Automations";
import { responseError } from "./http";

type State =
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "executing"
  | "speaking"
  | "interrupted"
  | "error";
type Message = { role: string; content: string; turn: string };
type Row = Record<string, string>;
type Records = {
  notes: Row[];
  memory: Row[];
  reminders: Row[];
  jobs: Row[];
  executions: Row[];
  directories: Row[];
  control_requests: Row[];
  generated_documents: Row[];
};
type Config = {
  model: string;
  workflow_model: string;
  voice: string;
  language: string;
  timezone: string;
  context_tokens: number;
  voice_pace: number;
  online_voice_enabled: boolean;
  online_voice_fallback: string;
  update_checks: boolean;
  conversation_recall: boolean;
  child_mode: boolean;
  long_speech_sentences: number;
  groq_voice_rpm: number;
  response_tokens: number;
  provider: string;
  api_base: string;
  computer_control: boolean;
  news_enabled: boolean;
  news_priority: string;
};
type Health = {
  backend: boolean;
  ollama: {
    ok: boolean;
    models: string[];
    selected_available: boolean;
    message?: string;
  };
  stt: boolean;
  tts: { ok: boolean; voices: string[] };
  vad: boolean;
  calendar: { connected: boolean; writable_connected: boolean; configured: boolean };
  settings: Config;
  applications: string[];
};
const initial: Records = {
  notes: [],
  memory: [],
  reminders: [],
  jobs: [],
  executions: [],
  directories: [],
  control_requests: [],
  generated_documents: [],
};
declare global {
  interface Window {
    jarvisDesktop?: {
      startup: () => Promise<{ enabled: boolean; supported: boolean }>;
      setStartup: (enabled: boolean) => Promise<boolean>;
      microphoneStatus: () => Promise<string>;
      fullscreen: () => Promise<boolean>;
      setFullscreen: (enabled: boolean) => Promise<boolean>;
      onPause: (callback: () => void) => () => void;
      onFullscreen: (callback: (enabled: boolean) => void) => () => void;
    };
  }
}
const uuid = () => crypto.randomUUID();
const voiceNames: Record<string, string> = {
  "kokoro-am_michael": "Michael · American",
  "kokoro-af_heart": "Heart · American",
  "kokoro-af_bella": "Bella · American",
  "kokoro-af_nicole": "Nicole · American",
  "kokoro-af_sarah": "Sarah · American",
  "kokoro-bf_emma": "Emma · British",
  "kokoro-bf_isabella": "Isabella · British",
  "kokoro-bm_george": "George · British",
  "kokoro-af_aoede": "Aoede · American · local",
  "kokoro-af_kore": "Kore · American · local",
  "kokoro-af_nova": "Nova · American · local",
  "kokoro-am_fenrir": "Fenrir · American · local",
  "kokoro-am_puck": "Puck · American · local",
  "kokoro-bm_fable": "Fable · British · local",
  "mac-Rishi": "Rishi · Indian male · local",
  "mac-Tara": "Tara · Indian female · local",
  "mac-Aman": "Aman · Indian male · local",
  "groq-hannah": "Hannah · female · Groq online",
  "groq-diana": "Diana · female · Groq online",
  "groq-autumn": "Autumn · female · Groq online",
  "groq-austin": "Austin · male · Groq online",
  "groq-daniel": "Daniel · male · Groq online",
  "groq-troy": "Troy · male · Groq online",
};
const caption = (value: string) =>
  value
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[*_`#]/g, "")
    .split(/\n\s*\n/)[0]
    .slice(0, 330);
const labels: Record<State, string> = {
  idle: "Ready when you are",
  listening: "Listening to you",
  transcribing: "Turning speech into text",
  thinking: "Thinking locally",
  executing: "Working on your request",
  speaking: "Speaking to you",
  interrupted: "Stopped",
  error: "Needs your attention",
};
async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await responseError(response);
  return response.json();
}
export default function App() {
  const [focused, setFocused] = useState(true);
  const [updates, setUpdates] = useState<{ id: string; title: string }[]>([]);
  const [automationSection, setAutomationSection] = useState("workflows");
  const [calendarPath, setCalendarPath] = useState("");
  const [voicePicker, setVoicePicker] = useState(false);
  const [previewingVoice, setPreviewingVoice] = useState("");
  const [providerStatus, setProviderStatus] = useState("");
  const [providerKey, setProviderKey] = useState(""),
    [newsItems, setNewsItems] = useState<Row[]>([]),
    [newsAge, setNewsAge] = useState("Not refreshed"),
    [newsCategory, setNewsCategory] = useState("all"),
    [snapshot, setSnapshot] = useState("");
  const [state, setState] = useState<State>("idle"),
    [health, setHealth] = useState<Health | null>(null),
    [records, setRecords] = useState<Records>(initial);
  const [messages, setMessages] = useState<Message[]>([]),
    [text, setText] = useState(""),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(false),
    [locked, setLocked] = useState(false),
    [token, setToken] = useState("");
  const [tab, setTab] = useState("conversation"),
    [settings, setSettings] = useState(false),
    [config, setConfig] = useState<Config | null>(null);
  const [muted, setMuted] = useState(false),
    [handsfree, setHandsfree] = useState(false),
    [capturing, setCapturing] = useState(false),
    [micHealth, setMicHealth] = useState("Not requested"),
    [sourceRate, setSourceRate] = useState(0),
    [devices, setDevices] = useState<MediaDeviceInfo[]>([]),
    [device, setDevice] = useState("");
  const [wake, setWake] = useState(
      localStorage.getItem("jarvis.wake") === "true",
    ),
    [startup, setStartup] = useState(false),
    [desktopSupported, setDesktopSupported] = useState(false);
  const wakeMode = useRef(localStorage.getItem("jarvis.wake") === "true"),
    wakeAwaiting = useRef(false),
    wakeTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    captureEpoch = useRef(0);
  const [wakeActive, setWakeActive] = useState(false);
  const [expanded, setExpanded] = useState(false),
    [activity, setActivity] = useState<string[]>([]),
    [metrics, setMetrics] = useState<Record<string, number>>({}),
    [editingId, setEditingId] = useState<string | null>(null),
    [form, setForm] = useState(false),
    [title, setTitle] = useState(""),
    [content, setContent] = useState(""),
    [path, setPath] = useState(""),
    [results, setResults] = useState<unknown[]>([]),
    [calendarEvents, setCalendarEvents] = useState<Row[]>([]);
  const [softwareUpdate, setSoftwareUpdate] = useState<{available: boolean; current_version: string; latest_version?: string; url: string; status: string} | null>(null);
  useEffect(() => {
    if (!connected) return;
    let closed = false;
    const check = async () => { try { const result = await api<NonNullable<typeof softwareUpdate>>("/updates"); if (!closed) setSoftwareUpdate(result); } catch { /* Update service does not block local conversations. */ } };
    void check(); const interval = setInterval(() => void check(), 6 * 60 * 60 * 1000);
    return () => { closed = true; clearInterval(interval); };
  }, [connected]);
  const [archive, setArchive] = useState<Row[]>([]);
  const [archiveQuery, setArchiveQuery] = useState("");
  const [archiveLoaded, setArchiveLoaded] = useState(false);
  const [micSignal, setMicSignal] = useState<AnalyserNode | null>(null),
    [speakerSignal, setSpeakerSignal] = useState<AnalyserNode | null>(null);
  const ws = useRef<WebSocket | null>(null),
    turn = useRef<string | null>(null),
    seq = useRef(0),
    audioSeq = useRef(0),
    session = useRef(localStorage.getItem("jarvis.session") || "");
  const bargeEnabled = useRef(false),
    bargeSeq = useRef(0),
    interruption = useRef(new PlaybackInterruption());
  const player = useRef(new Player()),
    microphone = useRef(new Microphone()),
    mode = useRef(false),
    gate = useRef(false),
    disposed = useRef(false),
    reconnect = useRef<ReturnType<typeof setTimeout> | null>(null),
    captureTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    end = useRef<HTMLDivElement>(null);
  const notify = (message: string) => {
    setError(message);
    setState("error");
  };
  const send = (message: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN)
      ws.current.send(JSON.stringify(message));
    else throw new Error("Backend connection unavailable");
  };
  async function refresh() {
    const [h, r] = await Promise.all([
      api<Health>("/health"),
      api<Records>("/records"),
    ]);
    setHealth(h);
    setRecords(r);
    setConfig((current) => current || h.settings);
    setLocked(false);
    return r;
  }
  async function safe(action: () => Promise<unknown>) {
    try {
      await action();
      setError("");
    } catch (error) {
      notify((error as Error).message);
    }
  }
  async function toggleFullscreen() {
    if (!expanded) {
      setFocused(true);
      setTab("conversation");
      setSettings(false);
      setVoicePicker(false);
    }
    if (window.jarvisDesktop?.setFullscreen) {
      setExpanded(
        await window.jarvisDesktop.setFullscreen(
          !(await window.jarvisDesktop.fullscreen()),
        ),
      );
    } else if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await document.documentElement.requestFullscreen();
    }
  }
  async function stopMic() {
    bargeEnabled.current = false;
    gate.current = false;
    setCapturing(false);
    setMicSignal(null);
    if (captureTimer.current) clearTimeout(captureTimer.current);
    await microphone.current.stop();
  }
  function stop(resumeListening = false) {
    const keepListening = resumeListening && mode.current;
    if (!keepListening) localStorage.setItem("jarvis.voicePaused", "true");
    if (wakeTimer.current) clearTimeout(wakeTimer.current);
    wakeAwaiting.current = false;
    setWakeActive(false);
    captureEpoch.current++;
    mode.current = keepListening;
    setHandsfree(keepListening);
    interruption.current.reset();
    player.current.stop();
    bargeEnabled.current = false;
    gate.current = false;
    turn.current = null;
    if (!keepListening) void stopMic();
    else setCapturing(false);
    setState("interrupted");
    try {
      send({ type: "interrupt" });
    } catch {
      /* already disconnected */
    }
    if (keepListening)
      void startCapture(true).catch((error) => {
        stop();
        notify(error.message);
      });
  }
  async function startCapture(auto: boolean) {
    if (ws.current?.readyState !== WebSocket.OPEN)
      throw new Error("Connect to the local backend first");
    const epoch = ++captureEpoch.current;
    interruption.current.reset();
    gate.current = false;
    player.current.stop();
    setError("");
    if (!auto || !microphone.current.stream) await stopMic();
    bargeEnabled.current = false;
    bargeSeq.current = 0;
    await player.current.activate();
    setSpeakerSignal(player.current.analyser);
    // Ignore the speaker echo tail before admitting any microphone samples.
    await new Promise((resolve) => setTimeout(resolve, 650));
    if (epoch !== captureEpoch.current) return;
    const id = uuid();
    turn.current = id;
    seq.current = 0;
    audioSeq.current = 0;
    const rate =
      auto && microphone.current.stream
        ? microphone.current.context!.sampleRate
        : await microphone.current.start(device);
    if (epoch !== captureEpoch.current) {
      await stopMic();
      return;
    }
    setSourceRate(rate);
    setMicHealth("Allowed");
    setMicSignal(microphone.current.analyser);
    const deviceList = await navigator.mediaDevices.enumerateDevices();
    setDevices(deviceList.filter((d) => d.kind === "audioinput"));
    microphone.current.onLost = () => {
      stop();
      notify(
        "Microphone disconnected. Select an available device and start again.",
      );
      setMicHealth("Device lost");
    };
    send({
      type: "capture_start",
      turn_id: id,
      mode: auto ? (wakeMode.current ? "wake" : "handsfree") : "ptt",
      sample_rate: 16000,
      source_sample_rate: rate,
      encoding: "pcm_s16le",
    });
    gate.current = true;
    setCapturing(true);
    setState("listening");
    microphone.current.onSamples = (samples) => {
      if (gate.current && turn.current === id) {
        send({
          type: "audio",
          turn_id: id,
          seq: seq.current++,
          audio: pcmBase64(samples),
          voice: !player.current.muted,
        });
      } else if (mode.current && bargeEnabled.current && turn.current) {
        send({
          type: "barge_audio",
          turn_id: turn.current,
          seq: bargeSeq.current++,
          audio: pcmBase64(samples),
        });
      }
    };
    if (!auto)
      captureTimer.current = setTimeout(() => void finishCapture(), 59000);
  }
  async function finishCapture() {
    const id = turn.current;
    gate.current = false;
    await stopMic();
    if (id) {
      send({ type: "capture_stop", turn_id: id, voice: !player.current.muted });
      setState("transcribing");
    }
  }
  async function talk() {
    if (capturing) {
      await finishCapture();
      return;
    }
    mode.current = false;
    localStorage.removeItem("jarvis.voicePaused");
    wakeMode.current = false;
    setHandsfree(false);
    try {
      await startCapture(false);
    } catch (error) {
      setMicHealth(
        (error as Error).name === "NotAllowedError" ? "Denied" : "Unavailable",
      );
      await stopMic();
      notify((error as Error).message);
    }
  }
  async function activateHandsfree() {
    if (mode.current) {
      stop();
      return;
    }
    if (!health?.vad) {
      notify("Download the Silero ONNX model before using hands-free");
      return;
    }
    wakeMode.current = false;
    mode.current = true;
    localStorage.removeItem("jarvis.voicePaused");
    setHandsfree(true);
    try {
      await startCapture(true);
    } catch (error) {
      mode.current = false;
      setHandsfree(false);
      setMicHealth("Unavailable");
      await stopMic();
      notify((error as Error).message);
    }
  }
  async function submit(value = text) {
    if (!value.trim()) return;
    if (ws.current?.readyState !== WebSocket.OPEN)
      throw new Error("Backend connection unavailable. Wait for reconnection.");
    const epoch = ++captureEpoch.current;
    interruption.current.reset();
    turn.current = null;
    gate.current = false;
    bargeEnabled.current = false;
    bargeSeq.current = 0;
    setCapturing(false);
    if (captureTimer.current) clearTimeout(captureTimer.current);
    if (!mode.current) await stopMic();
    player.current.stop();
    await player.current.activate();
    if (epoch !== captureEpoch.current) return;
    setSpeakerSignal(player.current.analyser);
    const id = uuid();
    turn.current = id;
    audioSeq.current = 0;
    setMetrics({});
    setText("");
    setError("");
    setState("thinking");
    setMessages((old) => [...old, { role: "user", content: value, turn: id }]);
    send({
      type: "text",
      turn_id: id,
      text: value,
      voice: !player.current.muted,
    });
  }
  function connect() {
    if (disposed.current) return;
    ws.current = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`,
    );
    ws.current.onopen = () => {
      setConnected(true);
      if (session.current)
        send({ type: "resume", session_id: session.current });
      if (
        localStorage.getItem("jarvis.wake") === "true" &&
        localStorage.getItem("jarvis.voicePaused") !== "true"
      ) {
        wakeMode.current = true;
        mode.current = true;
        setHandsfree(true);
        void startCapture(true).catch((error) => {
          stop();
          notify(
            "Wake listening needs microphone permission: " + error.message,
          );
        });
      }
    };
    ws.current.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "hello") {
        if (session.current && session.current !== message.session_id) return;
        session.current = message.session_id;
        localStorage.setItem("jarvis.session", session.current);
        void api<{ role: string; content: string; turn: string }[]>(
          "/history/" + session.current,
        )
          .then((rows) => {
            if (!turn.current) setMessages(rows);
          })
          .catch(() => {});
        return;
      }
      if (message.turn_id && message.turn_id !== turn.current) return;
      if (message.type === "interrupted") {
        if (message.cancelled_turn === turn.current) {
          player.current.stop();
          gate.current = false;
          setState("interrupted");
        }
        if (message.records) setRecords(message.records);
        return;
      }
      if (message.type === "barge_candidate") {
        interruption.current.candidate();
        void player.current.pause();
        setState("interrupted");
        return;
      }
      if (message.type === "barge_rejected") {
        if (interruption.current.reject()) {
          send({ type: "playback_done", turn_id: turn.current });
        }
        void player.current.resume();
        setState("speaking");
        return;
      }
      if (message.type === "barge_in") {
        interruption.current.reset();
        player.current.stop();
        bargeEnabled.current = false;
        bargeSeq.current = 0;
        turn.current = message.new_turn;
        audioSeq.current = 0;
        setState("interrupted");
        if (message.stopped) stop();
        return;
      }
      if (message.type === "stop_detected") {
        stop();
        return;
      }
      if (message.type === "state") {
        if (message.state === "speaking") bargeEnabled.current = mode.current;
        setState(message.state);
        if (message.state === "idle" && mode.current) {
          void startCapture(true).catch((error) => {
            stop();
            notify(error.message);
          });
        }
      }
      if (message.type === "transcript" && message.text)
        setMessages((old) => [
          ...old,
          { role: "user", content: message.text, turn: message.turn_id },
        ]);
      if (message.type === "delta")
        setMessages((old) => {
          const last = old.at(-1);
          if (last?.role === "assistant" && last.turn === message.turn_id)
            return [
              ...old.slice(0, -1),
              { ...last, content: last.content + message.text },
            ];
          return [
            ...old,
            { role: "assistant", content: message.text, turn: message.turn_id },
          ];
        });
      if (message.type === "wake_detected") {
        setActivity((old) => ["Wake phrase recognized locally", ...old]);
      }
      if (message.type === "wake_session") {
        if (wakeTimer.current) clearTimeout(wakeTimer.current);
        wakeAwaiting.current = message.active === true;
        setWakeActive(message.active === true);
        if (message.active === true)
          wakeTimer.current = setTimeout(
            () => {
              wakeAwaiting.current = false;
              setWakeActive(false);
            },
            Math.min(60000, Math.max(0, message.timeout_ms)),
          );
      }
      if (message.type === "capture_ended") {
        gate.current = false;
        setCapturing(false);
        // Keep the echo-cancelled stream available for spoken interruptions.
        if (!mode.current) void stopMic();
      }
      if (message.type === "audio") {
        if (message.seq !== audioSeq.current) {
          stop();
          notify("Audio sequence mismatch. Playback stopped.");
          return;
        }
        audioSeq.current++;
        gate.current = false;
        player.current.push(message.audio);
      }
      if (message.type === "tool") {
        if (message.name === "set_voice" && message.result?.ok) {
          setConfig((current) =>
            current
              ? { ...current, voice: message.result.data.voice }
              : current,
          );
        }
        setActivity((old) =>
          [`${message.name} · ${message.status}`, ...old].slice(0, 20),
        );
        void refresh().catch(() => {});
      }
      if (message.type === "metrics" || message.type === "done")
        setMetrics((old) => ({ ...old, ...message.metrics }));
      if (message.type === "done") {
        player.current.complete();
        void refresh().catch(() => {});
      }
      if (message.type === "warning") setError(message.message);
      if (message.type === "error") {
        interruption.current.reset();
        gate.current = false;
        mode.current = false;
        setHandsfree(false);
        player.current.stop();
        void stopMic();
        notify(message.message);
      }
    };
    ws.current.onclose = () => {
      if (wakeTimer.current) clearTimeout(wakeTimer.current);
      wakeAwaiting.current = false;
      setWakeActive(false);
      interruption.current.reset();
      setConnected(false);
      player.current.stop();
      turn.current = null;
      mode.current = false;
      setHandsfree(false);
      void stopMic();
      if (!disposed.current) {
        setError("Disconnected. Reconnecting to the local backend…");
        reconnect.current = setTimeout(
          () =>
            void api("/records")
              .then(() => {
                setError("");
                connect();
              })
              .catch(() => setLocked(true)),
          2000,
        );
      }
    };
  }
  useEffect(() => {
    disposed.current = false;
    const unbindFullscreen = window.jarvisDesktop?.onFullscreen?.(setExpanded);
    player.current.onDrained = () => {
      if (!interruption.current.drained()) return;
      const id = turn.current;
      if (id && ws.current?.readyState === WebSocket.OPEN)
        send({ type: "playback_done", turn_id: id });
      else setState("idle");
    };
    player.current.onError = (message) => {
      setError(message);
    };
    async function boot() {
      try {
        const token = new URLSearchParams(location.hash.slice(1)).get("token");
        history.replaceState(null, "", location.pathname);
        if (token) await api("/session", "POST", { token });
        await refresh();
        if (disposed.current) return;
        connect();
      } catch {
        if (!disposed.current) setLocked(true);
      }
    }
    void boot();
    if (window.jarvisDesktop)
      void window.jarvisDesktop.startup().then((result) => {
        setStartup(result.enabled);
        setDesktopSupported(result.supported);
      });
    if (window.jarvisDesktop?.fullscreen)
      void window.jarvisDesktop.fullscreen().then(setExpanded);
    const poll = setInterval(() => {
      if (!disposed.current)
        void api<{ id: string; title: string }[]>("/automation-notifications")
          .then((rows) => {
            if (!disposed.current) setUpdates(rows);
          })
          .catch(() => {});
      if (!disposed.current)
        void refresh()
          .then((r) => {
            let seen: string[] = [];
            try {
              seen = JSON.parse(
                localStorage.getItem("jarvis.notified") || "[]",
              );
            } catch {
              /* invalid user storage */
            }
            for (const reminder of r.reminders.filter(
              (row) =>
                row.state === "pending" &&
                new Date(row.due).getTime() <= Date.now(),
            )) {
              if (!seen.includes(reminder.id)) {
                setActivity((old) => [`Reminder: ${reminder.title}`, ...old]);
                setError(`Reminder due: ${reminder.title}`);
                seen.push(reminder.id);
                localStorage.setItem(
                  "jarvis.notified",
                  JSON.stringify(seen.slice(-1000)),
                );
              }
              void api("/reminders/" + reminder.id + "/ack", "POST").catch(
                () => {},
              );
            }
          })
          .catch(() => {});
    }, 5000);
    const changed = () => {
      const track = microphone.current.stream?.getAudioTracks()[0];
      const activeDevice = track?.getSettings().deviceId;
      void navigator.mediaDevices
        .enumerateDevices()
        .then((d) => {
          const inputs = d.filter((x) => x.kind === "audioinput");
          setDevices(inputs);
          // Permission grants can change labels and emit devicechange. They are
          // not a disconnection; cancelling here discarded the first request.
          if (
            track &&
            (track.readyState === "ended" ||
              (activeDevice &&
                !inputs.some((input) => input.deviceId === activeDevice)))
          ) {
            stop();
            setError(
              "Microphone disconnected. Select an available input in Settings.",
            );
          }
        })
        .catch(() => {});
    };
    navigator.mediaDevices?.addEventListener("devicechange", changed);
    const full = () => setExpanded(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", full);
    return () => {
      disposed.current = true;
      unbindFullscreen?.();
      clearInterval(poll);
      if (wakeTimer.current) clearTimeout(wakeTimer.current);
      if (reconnect.current) clearTimeout(reconnect.current);
      ws.current?.close();
      player.current.stop();
      void stopMic();
      navigator.mediaDevices?.removeEventListener("devicechange", changed);
      document.removeEventListener("fullscreenchange", full);
    };
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "nearest",
    });
  }, [messages]);
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.code === "Escape") stop();
      if (event.code === "Space" && event.altKey) {
        event.preventDefault();
        void talk();
      }
    };
    window.addEventListener("keydown", keyboard);
    const unbindPause = window.jarvisDesktop?.onPause?.(() => stop());
    return () => {
      window.removeEventListener("keydown", keyboard);
      unbindPause?.();
    };
  });
  async function tool(name: string, args: unknown) {
    const result = await api<{ ok: boolean; data: unknown; error?: string }>(
      "/tools",
      "POST",
      { name, arguments: args, key: uuid() },
    );
    if (!result.ok) throw new Error(result.error);
    await refresh();
    return result.data;
  }
  async function previewVoice(voice: string) {
    setPreviewingVoice(voice);
    try {
      stop();
      await player.current.activate();
      setSpeakerSignal(player.current.analyser);
      const response = await fetch("/api/voice-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice }),
      });
      if (!response.ok) throw await responseError(response);
      let bytes = "";
      for (const byte of new Uint8Array(await response.arrayBuffer()))
        bytes += String.fromCharCode(byte);
      setState("speaking");
      player.current.push(btoa(bytes));
      player.current.complete();
    } finally {
      setPreviewingVoice("");
    }
  }
  async function saveForm() {
    if (tab === "notes") await tool("create_note", { title, content });
    if (tab === "memory") {
      if (editingId) {
        await api("/memory/" + editingId, "PUT", {
          key: title,
          value: content,
        });
        setMessages([]);
        await refresh();
      } else await tool("remember_this", { key: title, value: content });
    }
    setEditingId(null);
    if (tab === "reminders")
      await tool("create_reminder", { title, datetime: content });
    setTitle("");
    setContent("");
    setForm(false);
  }
  async function loadNews(category = newsCategory) {
    const result = await api<{ items: Row[]; last_refresh: string | null }>(
      "/news?category=" + encodeURIComponent(category),
    );
    setNewsItems(result.items);
    setNewsAge(result.last_refresh || "Not refreshed");
  }
  const healthItems = [
    ["Backend", connected],
    ["Ollama", health?.ollama.selected_available],
    ["Whisper", health?.stt],
    ["Voice", health?.tts.ok],
    ["Silero", health?.vad],
  ];
  if (locked)
    return (
      <main className="lock">
        <ShieldCheck size={36} />
        <p className="eyebrow">PRIVATE BY DESIGN</p>
        <h1>Jarvis Local</h1>
        <p>
          Launch with <code>./start</code> to unlock your local session.
          <br />
          Or enter the access token from <code>data/auth.token</code>.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void safe(async () => {
              await api("/session", "POST", { token });
              setToken("");
              setLocked(false);
              await refresh();
              connect();
            });
          }}
        >
          <label>
            Local access token
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="off"
            />
          </label>
          <button type="submit">
            Unlock Jarvis <ArrowUpRight size={16} />
          </button>
        </form>
        <p role="alert">{error}</p>
      </main>
    );
  return (
    <div
      className={`app ${focused && tab === "conversation" ? "focus-mode" : tab === "conversation" ? "workspace-conversation" : ""} `}
    >
      {softwareUpdate?.available && <div className="software-update" role="status"><span>Jarvis {softwareUpdate.latest_version} is available.</span><a href={softwareUpdate.url} target="_blank" rel="noreferrer">Review & download</a><button aria-label="Dismiss update notice" onClick={() => setSoftwareUpdate({...softwareUpdate,available:false})}><X size={14}/></button></div>}
      <div className="quiet-toolbar">
        <button
          className="quiet-brand"
          onClick={() => {
            setFocused(true);
            setTab("conversation");
          }}
        >
          JARVIS
        </button>
        <div>
          {updates.length > 0 && (
            <button
              onClick={() => {
                setFocused(false);
                setTab("automations");
                setAutomationSection("activity");
              }}
              aria-label={`Read ${updates.length} updates`}
              title={updates[0].title}
            >
              Updates · {updates.length}
            </button>
          )}
          <span
            className={connected ? "dot" : "dot off"}
            title={connected ? "Backend connected" : "Backend disconnected"}
          />
          <button
            onClick={() => {
              stop();
              setVoicePicker(true);
            }}
            aria-label="Choose voice"
            title="Choose voice"
          >
            <Volume2 size={18} />
          </button>
          <button
            onClick={() => {
              setFocused(!focused);
              setTab("conversation");
            }}
            aria-label={focused ? "Open workspace" : "Return to voice screen"}
          >
            {focused ? <BookOpen size={18} /> : <Mic size={18} />}
          </button>
          <button onClick={() => setSettings(true)} aria-label="Settings">
            <Settings2 size={18} />
          </button>
          <button
            className="fullscreen-control"
            aria-label={expanded ? "Exit fullscreen" : "Enter fullscreen"}
            onClick={() =>
              void safe(async () => {
                await toggleFullscreen();
              })
            }
          >
            {expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            <span>{expanded ? "Exit fullscreen" : "Fullscreen"}</span>
          </button>
        </div>
      </div>
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(e) => e.preventDefault()}>
          <span className="brand-mark">J</span>
          <span>
            Jarvis<span className="brand-local"> LOCAL</span>
          </span>
        </a>
        <div className="workspace-label">YOUR PRIVATE WORKSPACE</div>
        <nav aria-label="Workspace">
          {[
            ["conversation", Activity, "Conversation"],
            ["notes", BookOpen, "Notes & documents"],
            ["memory", Brain, "Memory"],
            ["reminders", Clock, "Reminders"],
            ["jobs", RotateCcw, "Background jobs"],
            ["automations", ShieldCheck, "Automations"],
            ["news", Globe, "Daily news"],
          ].map(([id, Icon, label]) => {
            const I = Icon as typeof Mic;
            return (
              <button
                key={String(id)}
                className={tab === id ? "active" : ""}
                onClick={() => {
                  setTab(String(id));
                  setForm(false);
                  setResults([]);
                  if (id === "news") void loadNews();
                }}
              >
                <I size={18} />
                {String(label)}
                {id === "reminders" && (
                  <span className="count">
                    {
                      records.reminders.filter((r) => r.state === "pending")
                        .length
                    }
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <button onClick={() => setSettings(true)}>
            <Settings2 size={18} />
            Settings & connections
          </button>
          <div className="privacy">
            <ShieldCheck size={17} />
            <div>
              <strong>
                {health?.settings.provider === "compatible"
                  ? "Online model selected"
                  : "Local model selected"}
              </strong>
              <small>
                {health?.settings.provider === "compatible"
                  ? "Conversation goes to your configured API"
                  : "Local inference · No cloud fallback"}
              </small>
            </div>
          </div>
          <span className="version">JARVIS LOCAL / 0.2.0</span>
        </div>
      </aside>
      <main className="main">
        <header>
          <div>
            <p className="eyebrow">PERSONAL INTELLIGENCE</p>
            <h1>
              {tab === "conversation"
                ? "A little less to do."
                : tab === "notes"
                  ? "Your knowledge, close by."
                  : tab === "memory"
                    ? "Only what you choose."
                    : tab === "reminders"
                      ? "Make room for what matters."
                      : "Work continues here."}
            </h1>
          </div>
          <div className="connection">
            <span className={connected ? "dot" : "dot off"} />
            {connected
              ? health?.settings.provider === "compatible"
                ? "API model session active"
                : "Local session active"
              : "Connecting…"}
          </div>
        </header>
        {records.control_requests
          ?.filter((r) => r.state === "pending")
          .map((r) => (
            <div className="control-review" key={r.id}>
              <h3>System action needs your approval</h3>
              <pre>{r.args}</pre>
              <p>
                Bring the named application to front within three seconds after
                approving. Keep passwords and private credentials out of
                model-controlled input.
              </p>
              <button
                onClick={() =>
                  void safe(async () => {
                    setError(
                      "Approved. Switch to the named target application within three seconds.",
                    );
                    const result = await api<{ ok: boolean; error?: string }>(
                      "/control/" + r.id + "/review",
                      "POST",
                      { approved: true },
                    );
                    if (!result.ok) throw new Error(result.error);
                    await refresh();
                  })
                }
              >
                Approve this exact action
              </button>
              <button
                onClick={() =>
                  void safe(async () => {
                    await api("/control/" + r.id + "/review", "POST", {
                      approved: false,
                    });
                    await refresh();
                  })
                }
              >
                Reject
              </button>
            </div>
          ))}
        {error && (
          <div className="alert" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss message" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {tab === "conversation" ? (
          <>
            <section className="voice-panel" aria-label="Voice controls">
              <div className="voice-top">
                <span className="eyebrow">VOICE SESSION</span>
                <button
                  className="icon-button"
                  aria-label={expanded ? "Exit fullscreen" : "Enter fullscreen"}
                  onClick={() =>
                    void safe(async () => {
                      await toggleFullscreen();
                    })
                  }
                >
                  {expanded ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
                </button>
              </div>
              <Visualizer
                input={micSignal}
                output={speakerSignal}
                state={state}
                expanded={focused || expanded}
              />
              <div className="voice-copy">
                <div className="state-tag">
                  <span className={`dot ${state === "idle" ? "quiet" : ""}`} />
                  {state.toUpperCase()}
                </div>
                <h2 aria-live="polite">
                  {state === "listening" && wakeMode.current && !wakeActive
                    ? "Waiting for “Hey Jarvis”"
                    : labels[state]}
                </h2>
                <p className="voice-hint">
                  {capturing
                    ? "Speak naturally. Your audio stays in memory."
                    : "Ask a question. Capture a thought. Get something done."}
                </p>
              </div>
              <div className="voice-controls">
                <button
                  className={`talk ${handsfree ? "recording" : ""}`}
                  disabled={!connected}
                  onClick={() => void activateHandsfree()}
                >
                  <Mic size={20} />
                  {handsfree ? "End conversation" : "Start conversation"}
                </button>
                <button
                  className="round"
                  aria-label="Stop speech and pause microphone"
                  title="Stop & pause microphone · Esc"
                  onClick={() => stop()}
                >
                  <Square size={17} />
                </button>
                <button
                  className="round"
                  aria-label={muted ? "Unmute voice" : "Mute voice"}
                  onClick={() => {
                    player.current.setMuted(!muted);
                    setMuted(!muted);
                  }}
                >
                  {muted ? <VolumeX size={20} /> : <Volume2 size={20} />}
                </button>
              </div>
              <button
                className={`handsfree ${handsfree ? "enabled" : ""}`}
                onClick={() => void talk()}
                disabled={!connected}
              >
                <Power size={13} />
                {capturing && !handsfree
                  ? "Finish push-to-talk"
                  : "Push-to-talk fallback · ⌥ Space"}
              </button>
              <p className="micro-status">
                MIC: {micHealth}
                {sourceRate
                  ? ` · ${sourceRate.toLocaleString()} Hz → 16,000 Hz`
                  : ""}
              </p>
            </section>
            <section className="conversation">
              {focused && (
                <div className="focus-caption" aria-live="polite">
                  <p>{caption(messages.at(-1)?.content || "")}</p>
                  {(messages.at(-1)?.content.length || 0) > 330 && (
                    <button onClick={() => setFocused(false)}>
                      Read full reply <ArrowUpRight size={12} />
                    </button>
                  )}
                </div>
              )}
              <div className="section-heading">
                <h2>Conversation <small className="memory-status">Saved automatically</small></h2>
                <span>
                  {health?.settings.model || "qwen3:8b"}{" "}
                  <span className="subtle">
                    /{" "}
                    {health?.settings.provider === "compatible"
                      ? "API"
                      : "local"}
                  </span>
                </span>
              </div>
              <div
                className="messages"
                role="log"
                aria-label="Conversation transcript"
              >
                {messages.length === 0 ? (
                  <div className="empty-conversation">
                    <p className="eyebrow">A QUIETER KIND OF ASSISTANT</p>
                    <h3>
                      Your thoughts. Your tools.
                      <br />
                      Your computer.
                    </h3>
                    <p>
                      Try a question, save a note, or set a reminder.
                      <br />
                      Nothing leaves your device unless you connect a service.
                    </p>
                    <div className="suggestions">
                      {[
                        "What can you help me with?",
                        "List my reminders",
                        "Create a note titled Ideas: make time for deep work.",
                      ].map((s) => (
                        <button
                          key={s}
                          onClick={() => void safe(() => submit(s))}
                        >
                          {s}
                          <ArrowUpRight size={14} />
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  messages.map((m, i) => (
                    <article key={m.turn + i} className={`message ${m.role}`}>
                      <span className="message-label">
                        {m.role === "user" ? "YOU" : "JARVIS"}
                      </span>
                      <div>{m.content}</div>

                    </article>
                  ))
                )}
                {messages.at(-1)?.role === "assistant" &&
                  /[\u0980-\u09ff]/.test(messages.at(-1)!.content) && (
                    <button
                      onClick={() =>
                        void safe(() =>
                          submit(
                            "Give the previous answer in English so the local English voice can read it.",
                          ),
                        )
                      }
                    >
                      English voice fallback
                    </button>
                  )}
                <div ref={end} />
              </div>
              <form
                className="composer"
                onSubmit={(e) => {
                  e.preventDefault();
                  void safe(() => submit());
                }}
              >
                <input
                  aria-label="Message Jarvis"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Or type a message to Jarvis…"
                  maxLength={10000}
                />
                <button
                  type="submit"
                  aria-label="Send message"
                  disabled={!text.trim() || !connected}
                >
                  <ArrowUp size={20} />
                </button>
              </form>
              <p className="composer-foot">
                Answers from a local model can be wrong. Tool activity shows
                what actually happened.
              </p>
            </section>
          </>
        ) : tab === "automations" ? (
          <Automations initialSection={automationSection} />
        ) : tab === "news" ? (
          <section className="records-panel">
            <div className="section-heading">
              <h2>Daily news cache</h2>
              <button
                onClick={() =>
                  void safe(async () => {
                    const job = await api<{ job_id: string }>(
                      "/news/refresh",
                      "POST",
                    );
                    setActivity((old) => [
                      "News refresh queued: " + job.job_id,
                      ...old,
                    ]);
                    await refresh();
                  })
                }
              >
                Refresh now
              </button>
            </div>
            <p className="subtle">
              Last refresh: {newsAge}. News uses optional internet access.
              Coverage is limited to selected source RSS feeds.
            </p>
            <label>
              Coverage
              <select
                value={newsCategory}
                onChange={(e) => {
                  setNewsCategory(e.target.value);
                  void safe(() => loadNews(e.target.value));
                }}
              >
                {[
                  "all",
                  "world",
                  "india",
                  "business",
                  "technology",
                  "science",
                  "politics",
                  "sport",
                  "culture",
                ].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <button onClick={() => void safe(() => loadNews())}>
              Reload cached items
            </button>
            <button
              onClick={() => {
                setTab("conversation");
                void safe(() =>
                  submit(
                    "Use get_news to summarize the latest cached " +
                      newsCategory +
                      " headlines. Cite source links and dates, disclose cache age, and clearly label your analysis as inference.",
                  ),
                );
              }}
            >
              Ask Jarvis to analyze
            </button>
            {newsItems.map((n) => (
              <article className="news-story" key={n.id}>
                <p className="eyebrow">
                  {n.source} · {n.category}
                </p>
                <h3>
                  <a href={n.url} target="_blank" rel="noopener noreferrer">
                    {n.title}
                  </a>
                </h3>
                <p>{n.excerpt}</p>
                <small>
                  Published {n.published} · Retrieved {n.fetched}
                </small>
              </article>
            ))}
            {!newsItems.length && (
              <p className="empty-record">
                No cached items yet. Enable news networking and refresh.
              </p>
            )}
          </section>
        ) : (
          <section className="records-panel">
            <div className="section-heading">
              <h2>
                {tab === "notes"
                  ? "Notes & selected documents"
                  : tab === "memory"
                    ? "Memory & conversation knowledge"
                    : tab === "reminders"
                      ? "Persistent reminders"
                      : "Persistent jobs"}
              </h2>
              {tab !== "jobs" && (
                <button
                  onClick={() => {
                    setEditingId(null);
                    setForm(!form);
                  }}
                >
                  <Plus size={16} />
                  Add{" "}
                  {tab === "memory"
                    ? "memory"
                    : tab === "reminders"
                      ? "reminder"
                      : "note"}
                </button>
              )}
            </div>
            {tab === "memory" && (
              <section className="conversation-knowledge" aria-label="Automatic conversation memory">
                <h3>Learned from your conversations</h3>
                <p className="subtle">Your messages are saved automatically and recalled when relevant. Questions and Jarvis’s answers are not promoted into confirmed personal facts. All earlier saved chats are included.</p>
                <form className="archive-search" onSubmit={(e) => {
                  e.preventDefault();
                  void safe(async () => { setArchive(await api<Row[]>("/conversations?query=" + encodeURIComponent(archiveQuery))); setArchiveLoaded(true); });
                }}>
                  <input aria-label="Search conversation memory" maxLength={500} placeholder="Search past conversations…" value={archiveQuery} onChange={(e) => setArchiveQuery(e.target.value)} />
                  <button>Search / inspect</button>
                </form>
                {archiveLoaded && !archive.length && <p className="subtle">No matching user messages.</p>}
                <div className="archive-results">
                  {archive.map((r) => <article className="archive-record" key={r.id}>
                    <small>{new Date(r.created).toLocaleString()} · You said</small>
                    <p>{r.content}</p>
                    <div className="archive-actions">
                      <button onClick={() => void safe(async () => {
                        const value = window.prompt("Correct this conversation memory. Its old paired answer will be removed.", r.content);
                        if (value === null || !value.trim()) return;
                        stop(); await api("/conversations/" + r.id, "PUT", {content: value});
                        setArchive(await api<Row[]>("/conversations?query=" + encodeURIComponent(archiveQuery))); setMessages([]);
                      })}>Edit</button>
                      <button onClick={() => void safe(async () => {
                        if (!window.confirm("Delete this message and its paired answer from conversation memory?")) return;
                        stop(); await api("/conversations/" + r.id, "DELETE");
                        setArchive(await api<Row[]>("/conversations?query=" + encodeURIComponent(archiveQuery))); setMessages([]);
                      })}>Delete</button>
                    </div>
                  </article>)}
                </div>
                <button className="clear-history" onClick={() => void safe(async () => {
                  if (!window.confirm("Delete all saved conversations and summaries? Notes, preferences and reminders will remain.")) return;
                  stop(); await api("/conversations", "DELETE"); setArchive([]); setMessages([]); setArchiveLoaded(true);
                })}>Clear conversation history</button>
                <h3 className="preferences-heading">Explicit preferences</h3>
              </section>
            )}
            {form && (
              <form
                className="record-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void safe(saveForm);
                }}
              >
                <label>
                  {tab === "memory" ? "Memory label" : "Title"}
                  <input
                    required
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    maxLength={tab === "memory" ? 100 : 200}
                  />
                </label>
                <label>
                  {tab === "reminders"
                    ? "ISO datetime including timezone offset, e.g. 2026-10-06T10:00:00+05:30"
                    : tab === "memory"
                      ? "Value supplied by you"
                      : "Note content"}
                  <textarea
                    required
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    maxLength={tab === "memory" ? 2000 : 20000}
                  />
                </label>
                {tab === "memory" && (
                  <p className="subtle">
                    Review the details you want carried into future chats. Up to
                    2,000 characters; a long message starts with its first
                    2,000. Conversation recall works automatically; this is an optional explicit preference.
                  </p>
                )}
                <button type="submit">
                  Save locally <Check size={16} />
                </button>
              </form>
            )}
            {tab === "notes" && (
              <div className="knowledge-tools">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void safe(async () =>
                      setResults(
                        (await tool("search_notes", {
                          query: content,
                        })) as unknown[],
                      ),
                    );
                  }}
                >
                  <input
                    aria-label="Search notes or documents"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder="Search your notes or indexed documents…"
                    required
                  />
                  <button>Notes</button>
                  <button
                    type="button"
                    onClick={() =>
                      void safe(async () =>
                        setResults(
                          (await tool("search_documents", {
                            query: content,
                          })) as unknown[],
                        ),
                      )
                    }
                  >
                    Documents
                  </button>
                </form>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void safe(async () => {
                      await api("/directories", "POST", { path });
                      setPath("");
                      await refresh();
                    });
                  }}
                >
                  <input
                    aria-label="Explicit directory to index"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder="Absolute path of a directory you choose to index"
                    required
                  />
                  <button>Index directory</button>
                </form>
                <small>
                  Selected files only. No binary files, credential files, or
                  symlink escapes.
                </small>
                <h3>Your generated documents</h3>
                <p>
                  Ask “Create a Word document from this voice note…” or “Make
                  this into a PDF.” Drafts stay here for your review.
                </p>
                {(records.generated_documents || []).map((r) => (
                  <div className="directory" key={r.id}>
                    <span>
                      {r.title} · {r.format.toUpperCase()} · draft
                    </span>
                    <a
                      href={`/api/generated-documents/${r.id}/download`}
                      download
                    >
                      Download
                    </a>
                  </div>
                ))}
                {records.directories.map((r) => (
                  <div className="directory" key={r.path}>
                    <code>{r.path}</code>
                    <button
                      onClick={() =>
                        void safe(async () => {
                          await api("/directories", "POST", { path: r.path });
                          await refresh();
                        })
                      }
                    >
                      Reindex
                    </button>
                    <button
                      onClick={() =>
                        void safe(async () => {
                          await api("/directories", "DELETE", { path: r.path });
                          await refresh();
                        })
                      }
                    >
                      Remove
                    </button>
                  </div>
                ))}
                {results.map((r, i) => (
                  <pre className="search-result" key={i}>
                    {JSON.stringify(r, null, 2)}
                  </pre>
                ))}
              </div>
            )}
            <div className="record-list">
              {(tab === "notes"
                ? records.notes
                : tab === "memory"
                  ? records.memory
                  : tab === "reminders"
                    ? records.reminders
                    : records.jobs
              ).map((r) => (
                <article className="record" key={r.id}>
                  <div>
                    <h3>{r.title || r.key || r.kind}</h3>
                    <p>
                      {r.content ||
                        r.value ||
                        `${r.state} · ${r.due ? new Date(r.due).toLocaleString("en-IN", { timeZone: health?.settings.timezone || "Asia/Kolkata" }) : r.id}`}
                    </p>
                    {r.due && <small>{r.timezone}</small>}
                    {r.result && <pre>{r.result}</pre>}
                    {r.error && <p className="error-text">{r.error}</p>}
                  </div>
                  <div className="record-actions">
                    {tab === "memory" && (
                      <button
                        onClick={() => {
                          setEditingId(r.id);
                          setTitle(r.key);
                          setContent(r.value);
                          setForm(true);
                        }}
                      >
                        Edit
                      </button>
                    )}
                    {(tab === "notes" || tab === "memory") && (
                      <button
                        onClick={() =>
                          void safe(async () => {
                            await api(`/records/${tab}/${r.id}`, "DELETE");
                            setMessages([]);
                            await refresh();
                          })
                        }
                      >
                        Forget
                      </button>
                    )}
                    {tab === "reminders" && r.state === "pending" && (
                      <button
                        onClick={() =>
                          void safe(() => tool("cancel_reminder", { id: r.id }))
                        }
                      >
                        Cancel
                      </button>
                    )}
                    {tab === "jobs" &&
                      ["queued", "running"].includes(r.state) && (
                        <button
                          onClick={() =>
                            void safe(async () => {
                              await api("/jobs/" + r.id + "/cancel", "POST");
                              await refresh();
                            })
                          }
                        >
                          Cancel
                        </button>
                      )}
                  </div>
                </article>
              ))}
              {(tab === "notes"
                ? records.notes
                : tab === "memory"
                  ? records.memory
                  : tab === "reminders"
                    ? records.reminders
                    : records.jobs
              ).length === 0 && (
                <p className="empty-record">Nothing saved here yet.</p>
              )}
            </div>
            <p className="subtle">
              {tab === "memory"
                ? "Conversation recall is automatic. Explicit preferences are separate; forgetting a preference also clears chat context to prevent it resurfacing."
                : tab === "reminders"
                  ? "Reminders notify in this dashboard while Jarvis is running. Overdue reminders return after restart."
                  : tab === "jobs"
                    ? "One bounded indexing worker. Interrupted work is never silently replayed."
                    : "Saved in a private SQLite database on this computer."}
            </p>
          </section>
        )}
        <footer>
          <span>
            <ShieldCheck size={14} /> LOCAL FIRST. ALWAYS YOURS.
          </span>
          <span>{health?.settings.timezone || "Asia/Kolkata"}</span>
        </footer>
      </main>
      <aside className="inspector">
        <div className="section-heading">
          <h2>System</h2>
          <span className="eyebrow">LIVE</span>
        </div>
        <div className="health-list">
          {healthItems.map(([name, ok]) => (
            <div key={String(name)}>
              <span>
                <span className={`dot ${ok ? "" : "off"}`} />
                {name}
              </span>
              <small>{ok ? "Ready" : "Unavailable"}</small>
            </div>
          ))}
          <div>
            <span>
              <span
                className={`dot ${micHealth === "Allowed" ? "" : "quiet"}`}
              />
              Microphone
            </span>
            <small>{micHealth}</small>
          </div>
        </div>
        <div className="engine-note">
          <span className="eyebrow">ENGINE STACK</span>
          <p>
            Whisper → {health?.settings.model || "Qwen"} →{" "}
            {health?.settings.voice || "local voice"}
          </p>
          <small>English voice · Multilingual recognition</small>
        </div>
        <div className="activity">
          <h2>Tool activity</h2>
          {activity.length ? (
            activity.map((a, i) => (
              <div key={i}>
                <span className="dot quiet" />
                {a}
              </div>
            ))
          ) : (
            <p className="subtle">Verified tool results will appear here.</p>
          )}
          {records.executions.slice(0, 5).map((r) => (
            <details key={r.key}>
              <summary>
                {r.tool} · {r.state}
              </summary>
              <pre>{r.result || "Pending result"}</pre>
            </details>
          ))}
        </div>
        <div className="metrics">
          <h2>Last turn</h2>
          {Object.keys(metrics).length ? (
            Object.entries(metrics).map(([key, value]) => (
              <div key={key}>
                <span>{key.replaceAll("_", " ")}</span>
                <strong>{(value / 1000).toFixed(2)} s</strong>
              </div>
            ))
          ) : (
            <p className="subtle">Timing is measured after a real request.</p>
          )}
        </div>
        <div className="calendar">
          <p className="eyebrow">OPTIONAL CONNECTOR</p>
          <h3>Calendar</h3>
          <span>
            {health?.calendar.writable_connected
              ? "Connected · Owner-reviewed editing"
              : health?.calendar.connected
              ? "Connected · Read only"
              : "Not connected"}
          </span>
          <button onClick={() => setSettings(true)}>
            Manage connection <ArrowUpRight size={15} />
          </button>
        </div>
      </aside>
      {voicePicker &&
        health &&
        createPortal(
          <div className="modal-backdrop">
            <section
              className="modal voice-picker"
              role="dialog"
              aria-modal="true"
              aria-label="Choose a voice"
            >
              <div className="section-heading">
                <h2>A voice you like.</h2>
                <button
                  aria-label="Close voice picker"
                  onClick={() => setVoicePicker(false)}
                >
                  <X size={20} />
                </button>
              </div>
              <p className="subtle">
                Local American, British and Indian voices. Groq voices use the
                internet when explicitly enabled.
              </p>
              <p className="subtle">
                Scroll for more voices. Preview before selecting.
              </p>
              <div
                className="voice-options"
                tabIndex={0}
                aria-label="Available voices"
              >
                {[
                  {
                    label: "Downloaded Kokoro voices",
                    voices:
                      health?.tts.voices.filter((v) =>
                        v.startsWith("kokoro-"),
                      ) || [],
                  },
                  {
                    label: "Other local voices",
                    voices:
                      health?.tts.voices.filter(
                        (v) =>
                          !v.startsWith("kokoro-") && !v.startsWith("groq-"),
                      ) || [],
                  },
                  {
                    label: "Online Groq voices",
                    voices:
                      health?.tts.voices.filter((v) => v.startsWith("groq-")) ||
                      [],
                  },
                ]
                  .filter((group) => group.voices.length)
                  .map(({ label, voices }) => (
                    <section
                      className="voice-group"
                      key={label}
                      aria-label={label}
                    >
                      <h3>
                        {label} · {voices.length}
                      </h3>
                      {voices.map((v) => (
                        <div className="voice-choice" key={v}>
                          <button
                            className={
                              health.settings.voice === v ? "selected" : ""
                            }
                            onClick={() =>
                              void safe(async () => {
                                await api("/settings", "PUT", {
                                  ...health.settings,
                                  voice: v,
                                });
                                setConfig((current) =>
                                  current ? { ...current, voice: v } : current,
                                );
                                await refresh();
                              })
                            }
                            aria-pressed={health.settings.voice === v}
                          >
                            {voiceNames[v] || v}
                            {health.settings.voice === v && <Check size={16} />}
                          </button>
                          <button
                            aria-label={`Preview ${voiceNames[v] || v}`}
                            disabled={Boolean(previewingVoice)}
                            onClick={() => void safe(() => previewVoice(v))}
                          >
                            {previewingVoice === v ? "Preparing…" : "Preview"}
                          </button>
                        </div>
                      ))}
                    </section>
                  ))}
              </div>
              {!health?.tts.voices.some((v) => v.startsWith("kokoro-")) && (
                <p>
                  Download the Kokoro model and voice bundle to enable these
                  voices. Piper remains available in Settings.
                </p>
              )}
              <button
                onClick={() => {
                  player.current.stop();
                  setState("idle");
                  setVoicePicker(false);
                }}
                className="primary"
              >
                Done
              </button>
            </section>
          </div>,
          document.body,
        )}
      {settings && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Settings and connections"
          >
            <div className="section-heading">
              <h2>Make Jarvis yours.</h2>
              <button
                aria-label="Close settings"
                onClick={() => setSettings(false)}
              >
                <X size={20} />
              </button>
            </div>
            {config && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void safe(async () => {
                    if (providerKey) {
                      await api("/provider-credential", "PUT", {
                        key: providerKey,
                        api_base: config.api_base,
                      });
                      setProviderKey("");
                    }
                    await api("/settings", "PUT", config);
                    await refresh();
                    setSettings(false);
                  });
                }}
              >
                <label>
                  AI provider
                  <select
                    value={
                      config.provider === "compatible" &&
                      config.api_base === "https://api.groq.com/openai/v1"
                        ? "groq"
                        : config.provider === "compatible" &&
                            config.api_base ===
                              "https://generativelanguage.googleapis.com/v1beta/openai"
                          ? "gemini"
                          : config.provider
                    }
                    onChange={(e) => {
                      setProviderKey("");
                      setConfig(
                        e.target.value === "groq"
                          ? {
                              ...config,
                              provider: "compatible",
                              api_base: "https://api.groq.com/openai/v1",
                              model: "openai/gpt-oss-20b",
                            }
                          : e.target.value === "gemini"
                            ? {
                                ...config,
                                provider: "compatible",
                                api_base:
                                  "https://generativelanguage.googleapis.com/v1beta/openai",
                                model: "gemini-3.1-flash-lite",
                              }
                            : e.target.value === "ollama"
                              ? {
                                  ...config,
                                  provider: "ollama",
                                  model: "qwen3:4b-instruct",
                                }
                              : {
                                  ...config,
                                  provider: "compatible",
                                  api_base: "http://127.0.0.1:1234/v1",
                                  model: "",
                                },
                      );
                    }}
                  >
                    <option value="ollama">
                      Local Ollama · offline default
                    </option>
                    <option value="groq">Groq · fast hosted model</option>
                    <option value="gemini">
                      Google Gemini · optional free tier
                    </option>
                    <option value="compatible">
                      OpenAI-compatible API · optional
                    </option>
                  </select>
                </label>
                <label>
                  Local model for private workflow analysis
                  <input
                    value={config.workflow_model || "qwen3:4b-instruct"}
                    onChange={(e) =>
                      setConfig({ ...config, workflow_model: e.target.value })
                    }
                  />
                </label>
                {config.provider === "compatible" && (
                  <>
                    {config.api_base === "https://api.groq.com/openai/v1" && (
                      <p className="subtle">
                        Groq preset: GPT-OSS 20B for everyday voice requests.
                        You can change the model to openai/gpt-oss-120b. An
                        account and internet connection are required; free usage
                        has rate limits.
                      </p>
                    )}
                    {config.api_base.includes(
                      "generativelanguage.googleapis.com",
                    ) && (
                      <p className="setting-note">
                        Gemini Flash-Lite has a rate-limited free tier. Keep
                        billing unlinked. Free-tier prompts and results may be
                        used to improve Google products. Test with non-sensitive
                        questions first; private workflow analysis remains
                        local. Availability and quotas depend on your Google
                        account.
                      </p>
                    )}
                    <label>
                      API base URL
                      <input
                        value={config.api_base}
                        onChange={(e) =>
                          setConfig({ ...config, api_base: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Model identifier
                      <input
                        value={config.model}
                        onChange={(e) =>
                          setConfig({ ...config, model: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      API key (saved only in OS keychain)
                      <input
                        type="password"
                        autoComplete="off"
                        value={providerKey}
                        onChange={(e) => setProviderKey(e.target.value)}
                      />
                    </label>
                    {health?.ollama.message && (
                      <p role="status" className="setting-note">
                        {health.ollama.message}
                      </p>
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        void safe(() =>
                          api("/provider-credential", "PUT", {
                            key: "",
                            api_base: config.api_base,
                          }),
                        )
                      }
                    >
                      Remove stored API key
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        void safe(async () => {
                          if (providerKey) {
                            await api("/provider-credential", "PUT", {
                              key: providerKey,
                              api_base: config.api_base,
                            });
                            setProviderKey("");
                          }
                          const result = await api<{
                            model: string;
                            ttft_ms: number;
                          }>("/provider-test", "POST", config);
                          setProviderStatus(
                            `Connection verified · ${result.model} · first text ${Math.round(result.ttft_ms)} ms`,
                          );
                        })
                      }
                    >
                      Test API connection
                    </button>
                    {providerStatus && <p role="status">{providerStatus}</p>}
                    <p className="subtle">
                      Optional remote inference sends conversation and requested
                      tool results to this endpoint. No automatic cloud
                      fallback. Native recognition remains local. Voice
                      synthesis uses the selected local or explicitly enabled
                      online voice.
                    </p>
                  </>
                )}
                {config.provider === "ollama" && (
                  <label>
                    Local model
                    <select
                      value={config.model}
                      onChange={(e) =>
                        setConfig({ ...config, model: e.target.value })
                      }
                    >
                      {health?.ollama.models.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </label>
                )}
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={config.online_voice_enabled}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        online_voice_enabled: e.target.checked,
                        voice:
                          !e.target.checked && config.voice.startsWith("groq-")
                            ? "kokoro-af_heart"
                            : config.voice,
                      })
                    }
                  />
                  Enable expressive Groq voices (online)
                </label>
                <p className="setting-note">
                  Sends spoken answer text to Groq using your saved key. Account
                  quotas and pricing apply. Choose a local voice for offline
                  use.
                </p>
                {config.online_voice_enabled && (
                  <label>
                    Local voice if online speech fails
                    <select
                      value={config.online_voice_fallback || "none"}
                      onChange={(e) =>
                        setConfig({
                          ...config,
                          online_voice_fallback: e.target.value,
                        })
                      }
                    >
                      <option value="none">
                        Disabled · keep the selected voice
                      </option>
                      {(health?.tts.voices || [])
                        .filter((v) =>
                          [
                            "kokoro-af_heart",
                            "kokoro-bf_emma",
                            "mac-Tara",
                            "mac-Rishi",
                            "en_US-ljspeech-high",
                          ].includes(v),
                        )
                        .map((v) => (
                          <option key={v} value={v}>
                            {voiceNames[v] || v}
                          </option>
                        ))}
                    </select>
                    <small>
                      Shows a notice and uses this local voice for the rest of
                      the reply. Your selected voice stays saved.
                    </small>
                  </label>
                )}
                <section className="update-settings">
                  <h3>Software updates · {softwareUpdate?.current_version || "0.2.0"}</h3>
                  <label className="check-label"><input type="checkbox" checked={config.update_checks ?? true} onChange={(e) => setConfig({...config,update_checks:e.target.checked})}/> Check for new releases daily</label>
                  <p className="setting-note">Only public release metadata is requested from GitHub. No chats, memory, credentials or device identifier are sent. Updates require your review; automatic installation is not enabled.</p>
                  <button type="button" onClick={() => void safe(async () => {setSoftwareUpdate(await api<NonNullable<typeof softwareUpdate>>("/updates/check", "POST"));})}>Check now</button>
                  <p className="setting-note">{softwareUpdate?.status === "up_to_date" ? "You have the current release." : softwareUpdate?.status === "unavailable" ? "Update check unavailable. Your installed software keeps working." : softwareUpdate?.status === "no_release" ? "No public release is available yet." : softwareUpdate?.status === "disabled" ? "Automatic checks disabled." : softwareUpdate?.available ? `Version ${softwareUpdate.latest_version} is available.` : "Check public releases without changing your installation."}</p>
                </section>
                <label className="check-label">
                  <input type="checkbox" checked={config.conversation_recall ?? true} onChange={(e) => setConfig({...config, conversation_recall: e.target.checked})} />
                  Automatically recall saved conversations
                </label>
                <p className="setting-note">Relevant past user messages inform future answers without “Remember this.” Inspect, correct or delete them in Memory. An online model receives selected excerpts. Turning recall off keeps the archive and current chat context.</p>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={config.child_mode}
                    onChange={(e) =>
                      setConfig({ ...config, child_mode: e.target.checked })
                    }
                  />
                  Family-friendly conversation and stories
                </label>
                <label>
                  Speaking voice
                  <select
                    value={config.voice}
                    onChange={(e) =>
                      setConfig({ ...config, voice: e.target.value })
                    }
                  >
                    {(config.online_voice_enabled
                      ? [
                          ...new Set([
                            ...(health?.tts.voices || []),
                            "groq-hannah",
                            "groq-diana",
                            "groq-autumn",
                            "groq-austin",
                            "groq-daniel",
                            "groq-troy",
                          ]),
                        ]
                      : (health?.tts.voices || []).filter(
                          (v) => !v.startsWith("groq-"),
                        )
                    ).map((v) => (
                      <option key={v} value={v}>
                        {voiceNames[v] || v}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Voice pacing
                  <select
                    value={config.voice_pace}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        voice_pace: Number(e.target.value),
                      })
                    }
                  >
                    <option value={0.9}>Brisk</option>
                    <option value={1.0}>Natural pace</option>
                    <option value={1.2}>Relaxed</option>
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() =>
                    void safe(async () => {
                      stop();
                      await player.current.activate();
                      setSpeakerSignal(player.current.analyser);
                      const response = await fetch("/api/voice-preview", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ voice: config.voice }),
                      });
                      if (!response.ok) throw await responseError(response);
                      let bytes = "";
                      for (const byte of new Uint8Array(
                        await response.arrayBuffer(),
                      ))
                        bytes += String.fromCharCode(byte);
                      setState("speaking");
                      player.current.push(btoa(bytes));
                      player.current.complete();
                    })
                  }
                >
                  Preview selected voice
                </button>
                <label>
                  Recognition language
                  <select
                    value={config.language}
                    onChange={(e) =>
                      setConfig({ ...config, language: e.target.value })
                    }
                  >
                    <option value="en">English</option>
                    <option value="bn">Bengali</option>
                    <option value="auto">Automatic / mixed language</option>
                  </select>
                </label>
                <p className="subtle">
                  Bengali text is supported by the multilingual STT model.
                  Bengali speech output is unverified; use English voice
                  fallback.
                </p>
                <label>
                  Context budget
                  <select
                    value={config.context_tokens}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        context_tokens: Number(e.target.value),
                      })
                    }
                  >
                    <option value={4096}>4,096 tokens</option>
                    <option value={6144}>6,144 tokens</option>
                    <option value={8192}>8,192 tokens</option>
                  </select>
                </label>
                <label>
                  Timezone
                  <input
                    value={config.timezone}
                    onChange={(e) =>
                      setConfig({ ...config, timezone: e.target.value })
                    }
                  />
                </label>
                <label>
                  Microphone
                  <select
                    value={device}
                    onChange={(e) => {
                      stop();
                      setDevice(e.target.value);
                    }}
                  >
                    <option value="">System default</option>
                    {devices.map((d, i) => (
                      <option key={d.deviceId} value={d.deviceId}>
                        {d.label || `Microphone ${i + 1}`}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() =>
                    void safe(async () => {
                      await talk();
                    })
                  }
                >
                  Test microphone permission
                </button>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={config.news_enabled}
                    onChange={(e) =>
                      setConfig({ ...config, news_enabled: e.target.checked })
                    }
                  />
                  Daily news refresh · uses internet
                </label>
                <label>
                  News priority
                  <select
                    value={config.news_priority}
                    onChange={(e) =>
                      setConfig({ ...config, news_priority: e.target.value })
                    }
                  >
                    <option value="india">India first, then the world</option>
                    <option value="world">Global briefing</option>
                  </select>
                </label>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={config.computer_control}
                    onChange={(e) =>
                      setConfig({
                        ...config,
                        computer_control: e.target.checked,
                      })
                    }
                  />
                  Allow owner-reviewed system control
                </label>
                <p className="subtle">
                  Every mouse/keyboard action still needs your explicit
                  approval. macOS needs Accessibility and Automation permission;
                  screen previews need Screen Recording.
                </p>
                <button
                  type="button"
                  onClick={() =>
                    void safe(async () => {
                      const response = await fetch("/api/control/snapshot");
                      if (!response.ok) throw await responseError(response);
                      if (snapshot) URL.revokeObjectURL(snapshot);
                      setSnapshot(URL.createObjectURL(await response.blob()));
                    })
                  }
                >
                  Preview current screen
                </button>
                {snapshot && (
                  <img
                    className="screen-preview"
                    src={snapshot}
                    alt="Current system screen, reviewed locally only"
                  />
                )}
                <button type="submit" className="primary">
                  Save settings
                </button>
              </form>
            )}
            <hr />
            <h3>Desktop startup & wake phrase</h3>
            <label className="check-label">
              <input
                type="checkbox"
                checked={startup}
                disabled={!desktopSupported}
                onChange={(e) =>
                  void safe(async () => {
                    setStartup(
                      await window.jarvisDesktop!.setStartup(e.target.checked),
                    );
                  })
                }
              />
              Start Jarvis when I log in
            </label>
            <p className="subtle">
              {desktopSupported
                ? "Login startup is managed by the operating system."
                : "Install the packaged desktop app to enable login startup."}
            </p>
            <label className="check-label">
              <input
                type="checkbox"
                checked={wake}
                onChange={(e) => {
                  const enabled = e.target.checked;
                  setWake(enabled);
                  localStorage.setItem("jarvis.wake", String(enabled));
                  if (!enabled) {
                    stop();
                    wakeMode.current = false;
                  } else {
                    wakeMode.current = true;
                    localStorage.removeItem("jarvis.voicePaused");
                    wakeAwaiting.current = false;
                    mode.current = true;
                    setHandsfree(true);
                    void safe(() => startCapture(true));
                  }
                }}
              />
              Listen locally for “Hey Jarvis”
            </label>
            <p className="subtle">
              Requires microphone permission. Silero detects speech; native
              Whisper checks the wake phrase locally. Pause when muted or
              stopped. Wake detection adds transcription latency; audio is never
              stored.
            </p>
            <hr />
            <h3>Google Calendar · Read only</h3>
            <p className="subtle">
              Optional network connector. Requires your own Google Desktop OAuth
              client. Refresh credentials stay in the OS keychain.
            </p>
            {!health?.calendar.configured && (
              <div className="calendar-setup">
                <p>
                  Not connected — import a Desktop OAuth client before signing
                  in.
                </p>
                <label>
                  Google Desktop OAuth JSON file path
                  <input
                    value={calendarPath}
                    onChange={(e) => setCalendarPath(e.target.value)}
                    placeholder="/absolute/path/client_secret.json"
                  />
                </label>
                <button
                  disabled={!calendarPath.trim()}
                  onClick={() =>
                    void safe(async () => {
                      await api("/calendar/configure", "POST", {
                        path: calendarPath,
                      });
                      setCalendarPath("");
                      await refresh();
                    })
                  }
                >
                  Import calendar configuration
                </button>
                <p className="subtle">
                  In Google Cloud Console, enable Calendar API, configure the
                  consent screen, add your account as a test user, create an
                  OAuth client of type Desktop app, and download its JSON.
                  Jarvis stores it in its private data folder.
                </p>
              </div>
            )}
            <button
              disabled={!health?.calendar.configured}
              onClick={() =>
                void safe(async () => {
                  const data = await api<{ url: string }>("/calendar/connect");
                  window.open(data.url, "_blank", "noopener,noreferrer");
                })
              }
            >
              Connect calendar <ArrowUpRight size={16} />
            </button>
            {health?.calendar.connected && (
              <>
                <button
                  onClick={() =>
                    void safe(async () =>
                      setCalendarEvents(await api<Row[]>("/calendar/events")),
                    )
                  }
                >
                  Read upcoming events
                </button>
                <button
                  onClick={() =>
                    void safe(async () => {
                      await api("/calendar", "DELETE");
                      await refresh();
                    })
                  }
                >
                  Disconnect
                </button>
              </>
            )}
            {calendarEvents.map((r) => (
              <p key={r.id}>
                {r.title} · {JSON.stringify(r.start)}
              </p>
            ))}
            <hr />
            <h3>Allowed applications</h3>
            <p>{health?.applications.join(" · ")}</p>
            <p className="subtle">
              Configure bundle identifiers in .env. Shell execution and external
              communications are outside the default permissions.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
