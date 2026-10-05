import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Microphone, Player, PlaybackInterruption, pcmBase64 } from "./audio";
import "./companion.css";
import { SourceCards, type SourceData } from "./SourceCards";
async function api(path: string, body?: unknown) {
  const r = await fetch("/phone/" + path, {
    credentials: "same-origin",
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let message = "Connection failed";
    try {
      message = (await r.json()).detail || message;
    } catch {
      /* no private HTTP bodies */
    }
    throw Error(typeof message === "string" ? message : "Invalid request");
  }
  return r.json();
}
function Companion() {
  const [status, setStatus] = useState("unpaired"),
    [error, setError] = useState(""),
    [code, setCode] = useState(""),
    [name, setName] = useState("My iPhone"),
    [password, setPassword] = useState("");
  const [state, setState] = useState("idle"),
    [question, setQuestion] = useState(""),
    [answer, setAnswer] = useState(""),
    [text, setText] = useState(""),
    [connected, setConnected] = useState(false),
    [listening, setListening] = useState(false),
    [rate, setRate] = useState(0);
  const [reconnect, setReconnect] = useState(0);
  const [sources, setSources] = useState<SourceData | null>(null);
  const [reminders, setReminders] = useState<
    { id: string; title: string; due: string; timezone: string }[]
  >([]);
  const interruption = useRef(new PlaybackInterruption());
  const ws = useRef<WebSocket | null>(null),
    mic = useRef(new Microphone()),
    player = useRef(new Player()),
    active = useRef(false),
    capturing = useRef(false),
    turn = useRef<string | null>(null),
    session = useRef(""),
    seq = useRef(0),
    audioSeq = useRef(0),
    bargeSeq = useRef(0),
    voiceState = useRef("idle");
  const send = (body: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN)
      ws.current.send(JSON.stringify(body));
  };
  const stop = () => {
    active.current = false;
    capturing.current = false;
    turn.current = null;
    player.current.stop();
    interruption.current.reset();
    void mic.current.stop();
    send({ type: "interrupt" });
    setListening(false);
    setState("idle");
  };
  function capture() {
    if (!active.current || ws.current?.readyState !== WebSocket.OPEN) return;
    turn.current = crypto.randomUUID();
    seq.current = audioSeq.current = bargeSeq.current = 0;
    capturing.current = true;
    voiceState.current = "listening";
    setState("listening");
    send({
      type: "capture_start",
      turn_id: turn.current,
      mode: "handsfree",
      sample_rate: 16000,
      encoding: "pcm_s16le",
    });
  }
  useEffect(() => {
    let alive = true;
    async function update() {
      try {
        const value = await api("status");
        if (!alive) return;
        setStatus(
          value.status === "approved" &&
            value.owner.enabled &&
            value.owner.locked
            ? "locked"
            : value.status,
        );
        if (value.status === "approved" && !value.owner.locked) {
          const records = await api("reminders");
          if (alive) setReminders(records);
        }
      } catch {
        if (alive) setStatus("unpaired");
      }
    }
    void update();
    const timer = setInterval(() => void update(), 5000);
    const hidden = () => {
      if (document.hidden) stop();
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", hidden);
      stop();
      ws.current?.close();
    };
  }, []);
  useEffect(() => {
    if (status !== "approved") {
      stop();
      ws.current?.close();
      return;
    }
    let alive = true;
    const socket = new WebSocket("wss://" + location.host + "/phone/ws");
    ws.current = socket;
    player.current.onError = setError;
    player.current.onDrained = () => {
      if (!interruption.current.drained()) return;
      send({ type: "playback_done", turn_id: turn.current });
      voiceState.current = "idle";
      setState("idle");
      if (active.current) capture();
    };
    socket.onopen = () => {
      if (alive) {
        setConnected(true);
        setError("");
      }
    };
    socket.onclose = () => {
      if (alive) {
        stop();
        setConnected(false);
        setError("Voice disconnected. Reconnect before speaking.");
      }
    };
    socket.onerror = () => {
      if (alive)
        setError(
          "Voice connection unavailable. Check the desktop and private connection.",
        );
    };
    socket.onmessage = (event) => {
      const m = JSON.parse(event.data);
      if (m.type === "hello") {
        session.current = m.session_id;
        return;
      }
      if (m.session_id !== session.current) return;
      if (m.type === "owner_locked") {
        stop();
        setStatus("locked");
        return;
      }
      if (m.type === "interrupted") {
        player.current.stop();
        return;
      }
      if (m.type === "barge_in") {
        interruption.current.reset();
        player.current.stop();
        capturing.current = false;
        turn.current = m.new_turn;
        audioSeq.current = bargeSeq.current = 0;
        setAnswer("");
        setSources(null);
        if (m.stopped) stop();
        return;
      }
      if (m.turn_id !== turn.current) return;
      if (m.type === "barge_candidate") {
        interruption.current.candidate();
        void player.current.pause();
        return;
      }
      if (m.type === "barge_rejected") {
        const drained = interruption.current.reject();
        void player.current.resume().then(() => {
          if (drained) player.current.onDrained();
        });
        return;
      }
      if (m.type === "state") {
        voiceState.current = m.state;
        setState(m.state);
      }
      if (m.type === "capture_ended") capturing.current = false;
      if (m.type === "transcript") {
        setQuestion(m.text);
        setAnswer("");
        setSources(null);
      }
      if (
        m.type === "tool" &&
        m.result?.ok &&
        ["get_news", "search_current_news", "get_directions"].includes(m.name)
      )
        setSources(m.result.data);
      if (m.type === "delta") setAnswer((previous) => previous + m.text);
      if (m.type === "audio") {
        if (m.seq !== audioSeq.current++) {
          stop();
          setError("Audio order changed; playback stopped.");
          return;
        }
        player.current.push(m.audio);
      }
      if (m.type === "done") player.current.complete();
      if (m.type === "warning") setError(m.message);
      if (m.type === "error") {
        stop();
        setError(m.message);
      }
    };
    mic.current.onLost = () => {
      stop();
      setError("Microphone disconnected. Start conversation again.");
    };
    mic.current.onSamples = (pcm) => {
      if (capturing.current)
        send({
          type: "audio",
          turn_id: turn.current,
          seq: seq.current++,
          audio: pcmBase64(pcm),
        });
      else if (active.current && voiceState.current === "speaking")
        send({
          type: "barge_audio",
          turn_id: turn.current,
          seq: bargeSeq.current++,
          audio: pcmBase64(pcm),
        });
    };
    return () => {
      alive = false;
      stop();
      socket.close();
    };
  }, [status, reconnect]);
  async function begin() {
    try {
      setError("");
      await player.current.activate();
      setRate(await mic.current.start(""));
      active.current = true;
      setListening(true);
      capture();
    } catch {
      stop();
      setError(
        "Microphone unavailable. Allow microphone access in Safari and use the private HTTPS address.",
      );
    }
  }
  async function submit() {
    if (!text.trim() || !connected) return;
    stop();
    await player.current.activate();
    turn.current = crypto.randomUUID();
    audioSeq.current = 0;
    setQuestion(text);
    setAnswer("");
    setSources(null);
    send({ type: "text", turn_id: turn.current, text, voice: true });
    setText("");
    setState("thinking");
  }
  return (
    <main className="phone-shell">
      <header>
        <span>JARVIS</span>
        <small>Private companion</small>
      </header>
      {error && (
        <p role="alert" className="phone-error">
          {error}
        </p>
      )}
      {status === "unpaired" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void api("pair", { code, name })
              .then(() => setStatus("pending_desktop_approval"))
              .catch((e) => setError(String(e)));
          }}
        >
          <h1>Your Jarvis. With you.</h1>
          <p>
            Get a two-minute code from Desktop → Automations → Devices. Approve
            this phone on the desktop after entering it here.
          </p>
          <label>
            Device name
            <input
              value={name}
              maxLength={60}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </label>
          <label>
            Pairing code
            <input
              inputMode="numeric"
              autoComplete="off"
              pattern="[0-9]{8}"
              maxLength={8}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
          </label>
          <button>Request pairing</button>
        </form>
      )}
      {status === "pending_desktop_approval" && (
        <section>
          <h1>Awaiting your desktop approval</h1>
          <p>
            This phone has no conversation, reminder or tool access until you
            approve its name on the desktop.
          </p>
        </section>
      )}
      {status === "locked" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void api("unlock", { password })
              .then(() => {
                setPassword("");
                setStatus("approved");
              })
              .catch((e) => setError(String(e)));
          }}
        >
          <h1>Owner locked</h1>
          <label>
            Jarvis owner passphrase
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
              required
            />
          </label>
          <button>Unlock this phone session</button>
        </form>
      )}
      {status === "approved" && (
        <>
          {!connected && (
            <button onClick={() => setReconnect((v) => v + 1)}>
              Reconnect voice
            </button>
          )}
          <section className="phone-voice">
            <div className={"phone-orb " + state} aria-hidden="true">
              J
            </div>
            <p role="status">
              {connected ? state : "Connecting to your desktop…"}
            </p>
            <h1>{listening ? "I’m listening." : "Ready when you are."}</h1>
            <div className="phone-controls">
              <button
                disabled={!connected}
                onClick={() => (listening ? stop() : void begin())}
              >
                {listening ? "Pause conversation" : "Start conversation"}
              </button>
              <button onClick={stop}>Stop</button>
            </div>
            <small>
              {rate
                ? `Microphone ${rate.toLocaleString()} Hz → 16,000 Hz · `
                : ""}
              Keep this page open. Background wake and push alerts are not
              available.
            </small>
          </section>
          <section className="phone-transcript" aria-live="polite">
            <p className="phone-question">{question}</p>
            <div>{answer}</div>
            {sources && <SourceCards data={sources} />}
          </section>
          <form
            className="phone-message"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label className="phone-sr" htmlFor="message">
              Message Jarvis
            </label>
            <input
              id="message"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={10000}
              placeholder="Or type a message…"
            />
            <button disabled={!connected || !text.trim()}>Send</button>
          </form>
          <details>
            <summary>Your reminders · {reminders.length}</summary>
            {reminders.map((r) => (
              <p key={r.id}>
                {r.title}
                <br />
                <small>
                  {new Intl.DateTimeFormat("en-IN", {
                    dateStyle: "medium",
                    timeStyle: "short",
                    timeZone: r.timezone,
                  }).format(new Date(r.due))}{" "}
                  · {r.timezone}
                </small>
              </p>
            ))}
          </details>
          <p className="phone-footnote">
            Connected account writes need exact review on your desktop.
            Navigation requests return Maps links; open them on this phone. Your
            Mac must be awake and Jarvis running.
          </p>
        </>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Companion />);
