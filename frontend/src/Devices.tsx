import { useEffect, useState } from "react";
type Snapshot = {
  config: { enabled: boolean; origin: string };
  gateway_running: boolean;
  gateway_error: string | null;
  devices: {
    id: string;
    name: string;
    state: string;
    created: string;
    expires: number;
  }[];
};
async function request(path: string, method = "GET", body?: unknown) {
  const r = await fetch("/api/devices" + path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const e = await r.json();
    throw Error(
      typeof e.detail === "string" ? e.detail : "Device request failed",
    );
  }
  return r.json();
}
export function Devices() {
  const [data, setData] = useState<Snapshot | null>(null),
    [origin, setOrigin] = useState(""),
    [error, setError] = useState(""),
    [pair, setPair] = useState<{
      code: string;
      expires_seconds: number;
      url: string;
    } | null>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () =>
      request("")
        .then((value) => {
          if (active) setData(value);
        })
        .catch((e) => {
          if (active) setError(String(e));
        });
    void load();
    const timer = setInterval(load, 4000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      setData(await request(""));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Paired devices">
      <h3>Jarvis, on your phone</h3>
      <p>
        Private voice and text conversation through your own Tailscale network.
        This uses a separate loopback gateway; the main backend is never
        exposed. Your Mac must stay awake with Jarvis running.
      </p>
      {error && (
        <p role="alert" className="automation-error">
          {error}
        </p>
      )}
      <form
        className="automation-form"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => request("/config", "PUT", { enabled: true, origin }));
        }}
      >
        <label>
          Your private HTTPS origin
          <input
            required
            type="url"
            value={origin}
            placeholder={
              data?.config.origin || "https://your-mac.your-tailnet.ts.net"
            }
            onChange={(e) => setOrigin(e.target.value)}
          />
        </label>
        <small>
          Install Tailscale on this Mac and your iPhone, sign in to the same
          private network, and run “tailscale serve --bg http://127.0.0.1:8770”.
          Use Serve, which is private; never use Funnel or expose port 8765.
          Network setup is your explicit action.
        </small>
        <button disabled={busy}>Enable private companion</button>
      </form>
      <p>
        Gateway:{" "}
        {data?.gateway_running
          ? "Ready on loopback port 8770"
          : data?.gateway_error ||
            "Not running; restart the updated Jarvis app"}{" "}
        · Companion: {data?.config.enabled ? "Enabled" : "Off"}
      </p>
      {data?.config.enabled && (
        <div className="automation-actions">
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => setPair(await request("/pair", "POST")))
            }
          >
            Create two-minute pairing code
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await request("/config", "PUT", {
                  enabled: false,
                  origin: data.config.origin,
                });
                setPair(null);
              })
            }
          >
            Disable and revoke all phones
          </button>
        </div>
      )}
      {pair && (
        <div className="automation-card">
          <h4>Pairing code · {pair.code}</h4>
          <p>
            Expires two minutes after creation. Open {pair.url} on the phone and
            enter this code. Then review its exact device name below. A code
            alone grants no account access.
          </p>
        </div>
      )}
      {data?.devices.map((d) => (
        <article className="automation-card" key={d.id}>
          <h4>
            {d.name} · {d.state}
          </h4>
          <p>
            Requested {new Date(d.created).toLocaleString()} · access expires{" "}
            {new Date(d.expires * 1000).toLocaleString()}
          </p>
          {d.state === "pending" && (
            <>
              <p>
                Approving shares your Jarvis conversation context, reminders and
                connected reads with this phone. Outbound actions remain
                desktop-reviewed. Approve only the device you just paired.
              </p>
              <div className="automation-actions">
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      request("/" + d.id + "/review", "POST", {
                        approve: true,
                      }),
                    )
                  }
                >
                  Approve this phone
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      request("/" + d.id + "/review", "POST", {
                        approve: false,
                      }),
                    )
                  }
                >
                  Reject
                </button>
              </div>
            </>
          )}
          {d.state === "approved" && (
            <button
              disabled={busy}
              onClick={() => void run(() => request("/" + d.id, "DELETE"))}
            >
              Revoke device
            </button>
          )}
        </article>
      ))}
      <p>
        Owner protection, when enrolled, also requires unlocking and voice
        matching on the phone. There is no background wake word, cellular-call
        audio control, or push notification service in this web companion. Add
        the private page to your iPhone Home Screen for a convenient shortcut.
      </p>
    </section>
  );
}
