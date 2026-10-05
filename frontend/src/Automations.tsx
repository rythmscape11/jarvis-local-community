import { useEffect, useState } from "react";
import "./automations.css";
type Template = {
  id: string;
  title: string;
  description: string;
  connector: string;
};
type Definition = {
  title: string;
  template: string;
  inputs: {
    content: string;
    query: string;
    format: string;
    application: string;
    age: number;
    entity: string;
    service: string;
  };
  schedule: {
    kind: string;
    time: string;
    timezone: string;
    weekdays: number[];
    minutes: number;
  };
  enabled: boolean;
  run_on_startup: boolean;
};
type Workflow = Definition & { id: string; next_due: string | null };
type Run = {
  id: string;
  workflow_id: string;
  state: string;
  error: string | null;
  result: string | null;
  created: string;
};
type Action = {
  id: string;
  kind: string;
  args: string;
  state: string;
  result: string | null;
};
type Snapshot = {
  templates: Template[];
  workflows: Workflow[];
  runs: Run[];
  notifications: { id: string; title: string; text: string; read: number }[];
  connectors: {
    iphone: { available: boolean; enabled: boolean; call_audio_agent: boolean };
    profiles: {
      id: string;
      configured: boolean;
      connected: boolean;
      scope: string;
    }[];
    apis: { id: string; name: string; url: string; has_token: boolean }[];
    home: { connected: boolean; url?: string; entities?: string[] };
    actions: Action[];
  };
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
  if (!response.ok) {
    let reason = await response.text();
    try {
      reason = JSON.parse(reason).detail || reason;
    } catch {
      /* Plain text */
    }
    throw Error(typeof reason === "string" ? reason : JSON.stringify(reason));
  }
  return response.json();
}
const fresh = (template = "voice_document"): Definition => ({
  title: "",
  template,
  inputs: {
    content: "",
    query: "",
    format: "docx",
    application: "",
    age: 8,
    entity: "",
    service: "turn_on",
  },
  schedule: {
    kind: "manual",
    time: "10:00",
    timezone: "Asia/Kolkata",
    weekdays: [0],
    minutes: 60,
  },
  enabled: false,
  run_on_startup: false,
});
const labels: Record<string, string> = {
  mail_read: "Gmail · read recent messages",
  mail_send: "Gmail · owner-reviewed sending",
  calendar_write: "Calendar · create and edit events after review",
  tasks: "Google Tasks",
  drive: "Drive · Jarvis-created files",
};
export function Automations({
  initialSection = "workflows",
}: {
  initialSection?: string;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [form, setForm] = useState<Definition | null>(null),
    [edit, setEdit] = useState(""),
    [section, setSection] = useState(initialSection),
    [clientPath, setClientPath] = useState(""),
    [homeUrl, setHomeUrl] = useState(""),
    [entities, setEntities] = useState(""),
    [homeToken, setHomeToken] = useState(""),
    [preview, setPreview] = useState("");
  const [apiName, setApiName] = useState(""),
    [apiUrl, setApiUrl] = useState(""),
    [apiToken, setApiToken] = useState(""),
    [mailId, setMailId] = useState(""),
    [replyText, setReplyText] = useState("");
  const [action, setAction] = useState({
    kind: "create_task",
    to: "",
    subject: "",
    content: "",
    title: "",
    document_id: "",
    entity: "",
    service: "turn_on",
  });
  const load = async () => setSnapshot(await api<Snapshot>("/automations"));
  useEffect(() => setSection(initialSection), [initialSection]);
  useEffect(() => {
    let alive = true;
    const update = async () => {
      try {
        const value = await api<Snapshot>("/automations");
        if (alive) setSnapshot(value);
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    void update();
    const timer = setInterval(() => void update(), 5000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  async function perform(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function input(key: keyof Definition["inputs"], value: string | number) {
    if (form) setForm({ ...form, inputs: { ...form.inputs, [key]: value } });
  }
  function schedule(
    key: keyof Definition["schedule"],
    value: string | number | number[],
  ) {
    if (form)
      setForm({ ...form, schedule: { ...form.schedule, [key]: value } });
  }
  return (
    <section className="automation-space" aria-label="Automations">
      <div className="automation-heading">
        <div>
          <h2>Small routines. More time.</h2>
          <p>
            Local drafts and useful workflows. Connected writes wait for your
            review.
          </p>
        </div>
      </div>
      <div
        className="automation-nav"
        role="group"
        aria-label="Automation views"
      >
        {["workflows", "activity", "connections", "review"].map((s) => (
          <button
            key={s}
            className={section === s ? "selected" : ""}
            onClick={() => setSection(s)}
          >
            {s[0].toUpperCase() + s.slice(1)}
            {s === "review" &&
            snapshot?.connectors.actions.filter((a) => a.state === "pending")
              .length
              ? ` (${snapshot.connectors.actions.filter((a) => a.state === "pending").length})`
              : ""}
          </button>
        ))}
      </div>
      {error && (
        <p role="alert" className="automation-error">
          {error}
        </p>
      )}
      {!snapshot && <p>Connecting to the local workflow engine…</p>}
      {section === "workflows" && snapshot && (
        <>
          <p className="automation-caption">
            Analysis uses local Ollama, even when conversation uses an online
            model. Schedules run while Jarvis is open.
          </p>
          {!form && (
            <>
              <div className="automation-grid">
                {snapshot.templates.map((t) => {
                  const ready =
                    !t.connector ||
                    (t.connector === "home"
                      ? snapshot.connectors.home.connected
                      : snapshot.connectors.profiles.some(
                          (p) => p.id === t.connector && p.connected,
                        ));
                  return (
                    <button
                      className="automation-template"
                      key={t.id}
                      onClick={() => {
                        setEdit("");
                        setForm({ ...fresh(t.id), title: t.title });
                      }}
                    >
                      <span>{t.title}</span>
                      <p>{t.description}</p>
                      <small>
                        {ready
                          ? "Local / ready"
                          : `${t.connector === "home" ? "Home Assistant server" : labels[t.connector]} required`}
                      </small>
                    </button>
                  );
                })}
              </div>
              <h3>Your routines</h3>
              {!snapshot.workflows.length && (
                <p>Choose a template above to create your first routine.</p>
              )}
              {snapshot.workflows.map((w) => (
                <article className="automation-card" key={w.id}>
                  <div>
                    <h3>{w.title}</h3>
                    <p>
                      {w.schedule.kind === "manual"
                        ? "Run when asked"
                        : `${w.enabled ? "Scheduled" : "Paused"} · ${w.schedule.kind} · ${w.schedule.time} ${w.schedule.timezone}`}
                    </p>
                    {w.next_due && (
                      <small>
                        Next: {new Date(w.next_due).toLocaleString()}
                      </small>
                    )}
                  </div>
                  <div className="automation-actions">
                    <button
                      disabled={busy}
                      onClick={() =>
                        void perform(() =>
                          api(`/automations/${w.id}/run`, "POST", {
                            key: crypto.randomUUID(),
                          }),
                        )
                      }
                    >
                      Run
                    </button>
                    <button
                      onClick={() => {
                        setEdit(w.id);
                        const { id, next_due, ...definition } = w;
                        void id;
                        void next_due;
                        setForm(definition);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void perform(() =>
                          api(`/automations/${w.id}`, "PUT", {
                            title: w.title,
                            template: w.template,
                            inputs: w.inputs,
                            schedule: w.schedule,
                            enabled: !w.enabled,
                            run_on_startup: w.run_on_startup ?? false,
                          }),
                        )
                      }
                    >
                      {w.enabled ? "Pause" : "Enable"}
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Delete “${w.title}” and its activity? Created files remain in Notes & documents.`,
                          )
                        )
                          void perform(() =>
                            api(`/automations/${w.id}`, "DELETE"),
                          );
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </>
          )}
          {form && (
            <form
              className="automation-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  await api(
                    edit ? `/automations/${edit}` : "/automations",
                    edit ? "PUT" : "POST",
                    form,
                  );
                  setForm(null);
                });
              }}
            >
              <h3>{edit ? "Edit routine" : "Create routine"}</h3>
              <label>
                Title
                <input
                  required
                  maxLength={160}
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </label>
              {form.template === "desktop_routine" ? (
                <label>
                  Configured application name
                  <input
                    required
                    value={form.inputs.application}
                    placeholder="Calculator"
                    onChange={(e) => input("application", e.target.value)}
                  />
                  <small>
                    Only application names in Jarvis’s launch allowlist work.
                  </small>
                </label>
              ) : form.template === "smart_home" ? (
                <>
                  <label>
                    Allowlisted light entity
                    <input
                      required
                      value={form.inputs.entity}
                      placeholder="light.study"
                      onChange={(e) => input("entity", e.target.value)}
                    />
                  </label>
                  <label>
                    Action
                    <select
                      value={form.inputs.service}
                      onChange={(e) => input("service", e.target.value)}
                    >
                      <option value="turn_on">Turn on</option>
                      <option value="turn_off">Turn off</option>
                    </select>
                  </label>
                </>
              ) : (
                <>
                  <label>
                    {form.template === "meeting_followthrough"
                      ? "Meeting transcript (explicitly supplied)"
                      : "Dictated text, facts or instructions"}
                    <textarea
                      rows={6}
                      maxLength={20000}
                      value={form.inputs.content}
                      onChange={(e) => input("content", e.target.value)}
                      placeholder="Supply the facts Jarvis should use. It won’t invent your project data."
                    />
                  </label>
                  <label>
                    Topic / indexed-document query
                    <input
                      maxLength={500}
                      value={form.inputs.query}
                      onChange={(e) => input("query", e.target.value)}
                    />
                  </label>
                  <label>
                    Draft format
                    <select
                      value={form.inputs.format}
                      onChange={(e) => input("format", e.target.value)}
                    >
                      {["docx", "pdf", "md", "csv", "xlsx", "pptx"].map((f) => (
                        <option key={f} value={f}>
                          {f.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
              {form.template === "family_routine" && (
                <label>
                  Child’s age
                  <input
                    type="number"
                    min={3}
                    max={17}
                    value={form.inputs.age}
                    onChange={(e) => input("age", Number(e.target.value))}
                  />
                </label>
              )}
              <div className="automation-columns">
                <label>
                  Schedule
                  <select
                    value={form.schedule.kind}
                    onChange={(e) => schedule("kind", e.target.value)}
                  >
                    {["manual", "daily", "weekly", "interval"].map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </select>
                </label>
                {form.schedule.kind === "interval" ? (
                  <label>
                    Every (minutes)
                    <input
                      type="number"
                      min={15}
                      max={10080}
                      value={form.schedule.minutes}
                      onChange={(e) =>
                        schedule("minutes", Number(e.target.value))
                      }
                    />
                  </label>
                ) : (
                  <label>
                    Local time
                    <input
                      type="time"
                      value={form.schedule.time}
                      onChange={(e) => schedule("time", e.target.value)}
                    />
                  </label>
                )}
                <label>
                  Timezone
                  <input
                    required
                    value={form.schedule.timezone}
                    onChange={(e) => schedule("timezone", e.target.value)}
                  />
                </label>
              </div>
              {form.schedule.kind === "weekly" && (
                <label>
                  Weekday
                  <select
                    value={form.schedule.weekdays[0]}
                    onChange={(e) =>
                      schedule("weekdays", [Number(e.target.value)])
                    }
                  >
                    {[
                      "Monday",
                      "Tuesday",
                      "Wednesday",
                      "Thursday",
                      "Friday",
                      "Saturday",
                      "Sunday",
                    ].map((day, i) => (
                      <option key={day} value={i}>
                        {day}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="automation-check">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) =>
                    setForm({ ...form, enabled: e.target.checked })
                  }
                />
                Enable schedule
              </label>
              {form.template === "morning_briefing" && (
                <label className="automation-check">
                  <input
                    type="checkbox"
                    checked={form.run_on_startup ?? false}
                    onChange={(e) =>
                      setForm({ ...form, run_on_startup: e.target.checked })
                    }
                  />
                  Prepare on startup once per day (also requires Enable
                  schedule)
                </label>
              )}
              <div className="automation-actions">
                <button disabled={busy} type="submit">
                  Save routine
                </button>
                <button type="button" onClick={() => setForm(null)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </>
      )}
      {section === "activity" && snapshot && (
        <>
          <h3>Results</h3>
          {snapshot.notifications.map((n) => (
            <details className="automation-card" key={n.id}>
              <summary>
                {n.title}
                {!n.read ? " · New" : ""}
              </summary>
              <pre>{n.text}</pre>
              {!n.read && (
                <button
                  onClick={() =>
                    void perform(() =>
                      api(`/automation-notifications/${n.id}/read`, "POST"),
                    )
                  }
                >
                  Mark read
                </button>
              )}
            </details>
          ))}
          <h3>Runs</h3>
          {!snapshot.runs.length && <p>No runs yet.</p>}
          {snapshot.runs.map((r) => {
            let result: {
              document?: { download_url: string };
              text?: string;
            } | null = null;
            try {
              result = r.result ? JSON.parse(r.result) : null;
            } catch {
              /* interrupted result */
            }
            return (
              <details className="automation-card" key={r.id}>
                <summary>
                  {snapshot.workflows.find((w) => w.id === r.workflow_id)
                    ?.title || "Deleted routine"}{" "}
                  · {r.state}
                </summary>
                <small>
                  {new Date(r.created).toLocaleString()} · {r.id}
                </small>
                {r.error && <p role="alert">{r.error}</p>}
                {result?.document && (
                  <a href={result.document.download_url} download>
                    Download checked draft
                  </a>
                )}
                {result?.text && <pre>{result.text}</pre>}
                {["queued", "running", "awaiting_approval"].includes(
                  r.state,
                ) && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void perform(() =>
                        api(`/automation-runs/${r.id}/cancel`, "POST"),
                      )
                    }
                  >
                    Cancel run
                  </button>
                )}
              </details>
            );
          })}
        </>
      )}
      {section === "connections" && snapshot && (
        <>
          <article className="automation-card">
            <h3>iPhone calls through this Mac</h3>
            <p>
              {snapshot.connectors.iphone?.enabled
                ? "Enabled · every number needs review"
                : "Not enabled"}
            </p>
            <p>
              Use the same Apple Account on Mac and iPhone. On iPhone enable
              Settings → Apps → Phone → Calls on Other Devices for this Mac.
              Configure the Mac Phone app for your iPhone.
            </p>
            <p>
              Jarvis prepares a reviewed dialing request. You conduct the call;
              automatic call conversation and appointment confirmation are
              unavailable. Calls use your mobile plan.
            </p>
            <button
              disabled={busy || !snapshot.connectors.iphone?.available}
              onClick={() =>
                void perform(() =>
                  api("/connectors/iphone", "PUT", {
                    enabled: !snapshot.connectors.iphone.enabled,
                  }),
                )
              }
            >
              {snapshot.connectors.iphone?.enabled
                ? "Disable iPhone calls"
                : "Enable reviewed iPhone calls"}
            </button>
            {!snapshot.connectors.iphone?.available && (
              <small>The native macOS Phone app is required.</small>
            )}
          </article>
          <p>
            Optional Google APIs require internet, your own Desktop OAuth client
            and consent. No billing or paid API is enabled by Jarvis.
          </p>
          <form
            className="automation-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(() =>
                api("/calendar/configure", "POST", { path: clientPath }),
              );
            }}
          >
            <label>
              Downloaded Google Desktop OAuth JSON path
              <input
                value={clientPath}
                onChange={(e) => setClientPath(e.target.value)}
                placeholder="/Users/…/Downloads/client_secret_….json"
              />
            </label>
            <button disabled={busy || !clientPath.trim()}>Import client</button>
            <small>
              The client remains private on this computer. Never paste its
              contents into chat.
            </small>
          </form>
          {snapshot.connectors.profiles.map((p) => (
            <article className="automation-card" key={p.id}>
              <div>
                <h3>{labels[p.id]}</h3>
                <p>{p.connected ? "Connected" : "Not connected"}</p>
                <small>{p.scope}</small>
              </div>
              <div className="automation-actions">
                {p.connected ? (
                  <>
                    <button
                      disabled={busy}
                      onClick={() =>
                        void perform(() => api(`/connectors/${p.id}`, "DELETE"))
                      }
                    >
                      Disconnect
                    </button>
                    {p.id !== "mail_send" && (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void perform(async () =>
                            setPreview(
                              JSON.stringify(
                                await api(`/connectors/${p.id}/read`),
                                null,
                                2,
                              ),
                            ),
                          )
                        }
                      >
                        Test read
                      </button>
                    )}
                  </>
                ) : (
                  <button
                    disabled={busy || !p.configured}
                    onClick={() =>
                      void perform(async () => {
                        const result = await api<{ url: string }>(
                          `/connectors/${p.id}/connect`,
                          "POST",
                        );
                        window.open(
                          result.url,
                          "_blank",
                          "noopener,noreferrer",
                        );
                      })
                    }
                  >
                    Connect
                  </button>
                )}
              </div>
            </article>
          ))}
          <h3>Selected email</h3>
          <div className="automation-form">
            <label>
              Message ID from the Gmail test read
              <input
                value={mailId}
                onChange={(e) => setMailId(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !mailId}
              onClick={() =>
                void perform(async () =>
                  setPreview(
                    JSON.stringify(
                      await api(`/email/${encodeURIComponent(mailId)}`),
                      null,
                      2,
                    ),
                  ),
                )
              }
            >
              Read this message
            </button>
            <label>
              Reply draft
              <textarea
                rows={5}
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
              />
            </label>
            <button
              disabled={busy || !mailId || !replyText}
              onClick={() =>
                void perform(() =>
                  api("/email/reply", "POST", {
                    message_id: mailId,
                    content: replyText,
                  }),
                )
              }
            >
              Prepare threaded reply for review
            </button>
            <small>
              Read and send permissions must both be connected. Reply content
              appears in Review before sending.
            </small>
          </div>
          <h3>Named read-only APIs</h3>
          <p>
            Configure one public HTTPS JSON endpoint per name. Jarvis can read
            it when asked; it cannot invent URLs or send writes.
          </p>
          <form
            className="automation-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                await api("/custom-apis", "POST", {
                  name: apiName,
                  url: apiUrl,
                  token: apiToken,
                });
                setApiToken("");
              });
            }}
          >
            <label>
              Name
              <input
                required
                pattern="[a-z][a-z0-9_-]{1,40}"
                value={apiName}
                onChange={(e) => setApiName(e.target.value)}
                placeholder="project_status"
              />
            </label>
            <label>
              Public HTTPS JSON endpoint
              <input
                required
                type="url"
                value={apiUrl}
                onChange={(e) => setApiUrl(e.target.value)}
                placeholder="https://example.com/api/status"
              />
            </label>
            <label>
              Optional bearer token (OS keyring)
              <input
                type="password"
                autoComplete="off"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
              />
            </label>
            <button disabled={busy}>Save named API</button>
          </form>
          {snapshot.connectors.apis.map((a) => (
            <article className="automation-card" key={a.id}>
              <h3>{a.name}</h3>
              <p>{a.url}</p>
              <div className="automation-actions">
                <button
                  disabled={busy}
                  onClick={() =>
                    void perform(async () =>
                      setPreview(
                        JSON.stringify(
                          await api(`/custom-apis/${a.name}`),
                          null,
                          2,
                        ),
                      ),
                    )
                  }
                >
                  Test read
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void perform(() => api(`/connectors/${a.id}`, "DELETE"))
                  }
                >
                  Disconnect
                </button>
              </div>
            </article>
          ))}
          <h3>Home Assistant</h3>
          <p>
            {snapshot.connectors.home.connected
              ? "Configured · device state verified only when an approved action runs"
              : "Not connected · requires your own Home Assistant server"}
          </p>
          <form
            className="automation-form"
            onSubmit={(e) => {
              e.preventDefault();
              void perform(async () => {
                await api("/connectors/home/configure", "POST", {
                  url: homeUrl,
                  entities: entities
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                  token: homeToken,
                });
                setHomeToken("");
              });
            }}
          >
            <label>
              Local server URL
              <input
                required
                value={homeUrl}
                placeholder="http://192.168.1.20:8123"
                onChange={(e) => setHomeUrl(e.target.value)}
              />
            </label>
            <label>
              Allowed light entities, comma separated
              <input
                required
                value={entities}
                placeholder="light.study, light.bedroom"
                onChange={(e) => setEntities(e.target.value)}
              />
            </label>
            <label>
              Long-lived access token
              <input
                type="password"
                autoComplete="off"
                required
                value={homeToken}
                onChange={(e) => setHomeToken(e.target.value)}
              />
            </label>
            <button disabled={busy}>Store in OS keyring</button>
          </form>
          {snapshot.connectors.home.connected && (
            <button
              onClick={() =>
                void perform(() => api("/connectors/home", "DELETE"))
              }
            >
              Disconnect Home Assistant
            </button>
          )}
          {preview && (
            <details open>
              <summary>Verified read result</summary>
              <pre>{preview}</pre>
            </details>
          )}
        </>
      )}
      {section === "review" && snapshot && (
        <>
          <p>
            Review the exact recipient, content, file or device. Approval
            expires after 15 minutes. Uncertain writes are never retried
            automatically.
          </p>
          <details>
            <summary>Prepare a connected action</summary>
            <form
              className="automation-form"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(() => api("/external-actions", "POST", action));
              }}
            >
              <label>
                Action
                <select
                  value={action.kind}
                  onChange={(e) =>
                    setAction({ ...action, kind: e.target.value })
                  }
                >
                  <option value="create_task">Create Google Task</option>
                  <option value="send_email">Send one email</option>
                  <option value="upload_document">
                    Upload Jarvis document to Drive
                  </option>
                  <option value="home_light">Control allowlisted light</option>
                </select>
              </label>
              {action.kind === "send_email" ? (
                <>
                  <label>
                    Recipient
                    <input
                      required
                      type="email"
                      value={action.to}
                      onChange={(e) =>
                        setAction({ ...action, to: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Subject
                    <input
                      required
                      value={action.subject}
                      onChange={(e) =>
                        setAction({ ...action, subject: e.target.value })
                      }
                    />
                  </label>
                </>
              ) : action.kind === "create_task" ? (
                <label>
                  Task title
                  <input
                    required
                    value={action.title}
                    onChange={(e) =>
                      setAction({ ...action, title: e.target.value })
                    }
                  />
                </label>
              ) : action.kind === "upload_document" ? (
                <label>
                  Generated document ID
                  <input
                    required
                    value={action.document_id}
                    onChange={(e) =>
                      setAction({ ...action, document_id: e.target.value })
                    }
                  />
                </label>
              ) : (
                <>
                  <label>
                    Light entity
                    <input
                      required
                      value={action.entity}
                      onChange={(e) =>
                        setAction({ ...action, entity: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Service
                    <select
                      value={action.service}
                      onChange={(e) =>
                        setAction({ ...action, service: e.target.value })
                      }
                    >
                      <option value="turn_on">On</option>
                      <option value="turn_off">Off</option>
                    </select>
                  </label>
                </>
              )}
              {["create_task", "send_email"].includes(action.kind) && (
                <label>
                  Content
                  <textarea
                    rows={5}
                    value={action.content}
                    onChange={(e) =>
                      setAction({ ...action, content: e.target.value })
                    }
                  />
                </label>
              )}
              <button disabled={busy}>Prepare for review</button>
            </form>
          </details>
          {snapshot.connectors.actions.map((a) => (
            <article className="automation-card" key={a.id}>
              <h3>
                {a.kind.replaceAll("_", " ")} · {a.state}
              </h3>
              <pre>{JSON.stringify(JSON.parse(a.args), null, 2)}</pre>
              {a.result && <pre>{a.result}</pre>}
              {a.state === "pending" && (
                <div className="automation-actions">
                  <button
                    disabled={busy}
                    onClick={() =>
                      void perform(() =>
                        api(`/external-actions/${a.id}/review`, "POST", {
                          approve: true,
                        }),
                      )
                    }
                  >
                    Approve these exact details
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void perform(() =>
                        api(`/external-actions/${a.id}/review`, "POST", {
                          approve: false,
                        }),
                      )
                    }
                  >
                    Reject
                  </button>
                </div>
              )}
            </article>
          ))}
          {!snapshot.connectors.actions.length && (
            <p>No actions awaiting review.</p>
          )}
        </>
      )}
    </section>
  );
}
