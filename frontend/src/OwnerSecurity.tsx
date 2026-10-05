import { useEffect, useRef, useState, type ReactNode } from "react";
import { Microphone, pcmBase64 } from "./audio";
import { responseError } from "./http";

type Status = { enabled: boolean; locked: boolean; model_downloaded: boolean };
async function ownerApi<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api/owner/" + path, {
    method: body ? "POST" : "GET", credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await responseError(response);
  return response.json();
}

export function OwnerBoundary({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    const check = async () => {
      try {
        const token = new URLSearchParams(location.hash.slice(1)).get("token");
        if (token) {
          history.replaceState(null, "", location.pathname);
          const response = await fetch("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
          if (!response.ok) throw new Error("Open the installed Jarvis app to authenticate.");
        }
        const next = await ownerApi<Status>("status");
        if (live) { setStatus(next); setError(""); }
      } catch (err) {
        if (live) { setError((err as Error).message); setStatus(null); }
      }
    };
    const locked = () => { setStatus((value) => value ? { ...value, locked: true } : null); setPassword(""); };
    window.addEventListener("jarvis-owner-locked", locked);
    void check();
    const timer = setInterval(() => void check(), 5000);
    return () => { live = false; clearInterval(timer); window.removeEventListener("jarvis-owner-locked", locked); };
  }, []);
  if (status && !status.locked) return children;
  return <main className="owner-lock-screen">
    <div className="owner-lock-card">
      <span className="eyebrow">JARVIS LOCAL · PRIVATE WORKSPACE</span>
      <h1>{status?.locked ? "Owner access required" : "Connecting securely"}</h1>
      <p>{status?.locked ? "Enter your Jarvis owner passphrase. Voice matching is an additional check; it cannot unlock private data by itself." : "Your conversations stay hidden until the local session is authenticated."}</p>
      {status?.locked && <form onSubmit={(event) => { event.preventDefault(); setBusy(true); void ownerApi<Status>("unlock", { password }).then((next) => { setStatus(next); setPassword(""); setError(""); }).catch((err) => setError(err.message)).finally(() => setBusy(false)); }}>
        <label>Jarvis owner passphrase<input type="password" autoComplete="current-password" autoFocus value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} maxLength={128} required /></label>
        <button className="primary" disabled={busy}>{busy ? "Verifying…" : "Unlock for 10 minutes"}</button>
      </form>}
      {error && <p role="alert">{error}</p>}
      <p className="setting-note">This is your Jarvis passphrase, separate from your Mac login or API keys. If an action was already submitted before locking, locking cannot undo it.</p>
    </div>
  </main>;
}

export function OwnerSecurityPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [consent, setConsent] = useState(false);
  const [samples, setSamples] = useState<string[]>([]);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const mic = useRef<Microphone | null>(null);
  const epoch = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    void ownerApi<Status>("status").then(setStatus).catch((err) => setMessage(err.message));
    return () => { alive.current = false; epoch.current++; void mic.current?.stop(); mic.current = null; };
  }, []);
  const record = async () => {
    window.dispatchEvent(new Event("jarvis-pause"));
    setRecording(true); setMessage("Speak normally for eight seconds. Keep other voices and speakers quiet.");
    const capture = new Microphone(); mic.current = capture;
    const id = ++epoch.current, chunks: Int16Array[] = [];
    let count = 0;
    capture.onSamples = (pcm) => { if (id === epoch.current && count < 8 * 16000) { chunks.push(pcm); count += pcm.length; } };
    capture.onLost = () => { epoch.current++; void capture.stop(); if (alive.current) { setRecording(false); setMessage("Microphone disconnected. Record this sample again."); } };
    try {
      await capture.start("");
      await new Promise((resolve) => setTimeout(resolve, 8000));
      await capture.stop();
      if (!alive.current || id !== epoch.current) return;
      const all = new Int16Array(count); let offset = 0;
      chunks.forEach((chunk) => { all.set(chunk, offset); offset += chunk.length; });
      setSamples((previous) => [...previous, pcmBase64(all)]);
      setMessage("Sample recorded in memory only. Record a different phrase next.");
    } catch (err) { if (alive.current) setMessage((err as Error).message); }
    finally { if (alive.current) setRecording(false); mic.current = null; }
  };
  const action = async (path: string, body: unknown) => {
    setBusy(true);
    try {
      await ownerApi(path, body);
      setPassword(""); setConfirm(""); setSamples([]);
      window.dispatchEvent(new Event("jarvis-owner-locked"));
    } catch (err) { setMessage((err as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="owner-security-panel">
    <h3>Owner protection · experimental</h3>
    <p className="setting-note">{status?.enabled ? "Enabled. Each spoken request must match the enrolled voice, and your passphrase is required after restart, locking or ten minutes. Unrecognized voices stay locked." : "Off until you explicitly enroll. Whisper recognizes words; it does not recognize the owner."}</p>
    <p className="setting-note">A recording or synthetic voice can fool speaker matching. Keep exact action approvals and OS screen lock. Short or noisy commands can cause a lock. This does not protect against someone controlling your OS account.</p>
    {!status?.enabled && <>
      {!status?.model_downloaded && <p>Prerequisite: run <code>.venv/bin/python scripts/download-owner-model.py</code> from your source installation. For the installed app, use the runtime’s --download-owner-model command documented in the README. The local voice model is 28 MB.</p>}
      <label>New Jarvis owner passphrase<input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <label>Confirm passphrase<input type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
      <label className="check-label"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />I consent to recording my own voice and storing an encrypted voiceprint on this device.</label>
      <p className="setting-note">Record three different sentences and a fourth to test the match before activation. Only embeddings are encrypted and saved; audio is discarded. Forgetting this passphrase requires an OS-level recovery; there is no public reset endpoint.</p>
      <button type="button" disabled={!consent || !status?.model_downloaded || recording || samples.length >= 4 || busy} onClick={() => void record()}>{recording ? "Recording for eight seconds…" : `Record sample ${Math.min(4, samples.length + 1)} of 4`}</button>
      <button type="button" disabled={recording || busy || !samples.length} onClick={() => { setSamples([]); setMessage(""); }}>Discard samples</button>
      <button type="button" disabled={recording || busy || samples.length !== 4 || password.length < 8 || password !== confirm || !consent} onClick={() => void action("enroll", { password, samples })}>Enable owner lock</button>
    </>}
    {status?.enabled && <>
      <button type="button" onClick={() => void action("lock", {})} disabled={busy}>Lock now</button>
      <label>Passphrase to delete voiceprint<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <button type="button" disabled={busy || password.length < 8} onClick={() => { if (window.confirm("Delete your encrypted voiceprint and disable owner protection?")) void action("remove", { password }); }}>Delete voiceprint & disable</button>
    </>}
    {message && <p role="status">{message}</p>}
  </section>;
}
