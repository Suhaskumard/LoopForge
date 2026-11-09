import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { WEBHOOK_EVENTS, type ApiToken, type Webhook, type WebhookDelivery } from "../api/types";
import { useAsync } from "../hooks";
import { toast } from "./Toast";
import { Card, Empty, ErrorBox } from "./ui";

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
const when = (iso: string | null) => (iso ? new Date(iso.endsWith("Z") ? iso : iso + "Z").toLocaleString() : "—");

/** A value the server shows exactly once (signing secret, API token). Copy it now or lose it. */
export function OneTimeSecret({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      toast("Copied — store it somewhere safe", "ok");
    } catch {
      toast("Copy is blocked by the browser; select the text instead", "bad");
    }
  };
  return (
    <div className="secret" role="status">
      <div className="secret-head">
        <strong>{label}</strong>
        <span className="badge warn">shown once</span>
      </div>
      <code className="secret-value" data-testid="one-time-secret">{value}</code>
      <div className="row">
        <button type="button" className="primary" onClick={() => void copy()}>Copy</button>
        <button type="button" onClick={onDone}>I&apos;ve stored it</button>
      </div>
    </div>
  );
}

export function Integrations({ orgId }: { orgId: string }) {
  return (
    <div className="integrations">
      <p className="muted int-intro">
        Connect LoopForge to the rest of your tools: <b>webhooks</b> push task and approval events to Slack or any HTTPS
        endpoint, and <b>API tokens</b> let CI and scripts create and watch tasks.
      </p>
      <Webhooks orgId={orgId} />
      <Tokens orgId={orgId} />
    </div>
  );
}

function Webhooks({ orgId }: { orgId: string }) {
  const base = `/orgs/${orgId}/webhooks`;
  const list = useAsync(() => api.get<Webhook[]>(base), [orgId]);
  const [url, setUrl] = useState("");
  const [format, setFormat] = useState<"json" | "slack">("json");
  const [events, setEvents] = useState<string[]>(["task.completed", "task.failed", "task.escalated", "approval.needed"]);
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string>();

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const made = await api.post<Webhook & { secret: string }>(base, { url: url.trim(), events, format });
      setSecret({ label: `Signing secret for ${made.url}`, value: made.secret });
      setUrl("");
      list.reload();
    } catch (err) {
      setError(message(err));
    }
  };
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setError(undefined);
    try {
      await fn();
      toast(ok, "ok");
      list.reload();
    } catch (err) {
      setError(message(err));
    }
  };
  const toggle = (ev: string) => setEvents((cur) => (cur.includes(ev) ? cur.filter((x) => x !== ev) : [...cur, ev]));

  return (
    <Card title="Webhooks">
      {secret && <OneTimeSecret label={secret.label} value={secret.value} onDone={() => setSecret(null)} />}
      <form className="int-form" onSubmit={(e) => void create(e)}>
        <div className="row">
          <label className="grow">
            Endpoint URL
            <input type="url" required value={url} placeholder="https://hooks.slack.com/services/…" onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label>
            Format
            <select value={format} onChange={(e) => setFormat(e.target.value as "json" | "slack")}>
              <option value="json">JSON (signed)</option>
              <option value="slack">Slack message</option>
            </select>
          </label>
        </div>
        <fieldset className="ev-chips">
          <legend>Events <span className="muted small">(none selected = all)</span></legend>
          {WEBHOOK_EVENTS.map((ev) => (
            <label key={ev} className={`ev-chip${events.includes(ev) ? " on" : ""}`}>
              <input type="checkbox" checked={events.includes(ev)} onChange={() => toggle(ev)} />
              {ev}
            </label>
          ))}
        </fieldset>
        <button className="primary">Add webhook</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {list.error && <ErrorBox error={list.error} />}
      {list.data && list.data.length === 0 && <Empty>No webhooks yet.</Empty>}
      <ul className="int-list">
        {list.data?.map((w) => (
          <li key={w.id} className="int-item">
            <div className="int-main">
              <span className={`int-dot${w.active ? " on" : ""}`} aria-hidden="true" />
              <div className="int-text">
                <code>{w.url}</code>
                <span className="muted small">{w.format} · {w.events.length ? w.events.join(", ") : "all events"} · added {when(w.created_at)}</span>
              </div>
              <div className="row int-actions">
                <button type="button" onClick={() => void act(() => api.post(`${base}/${w.id}/test`), "Test event queued")}>Send test</button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const r = await api.post<{ secret: string; overlap_hours: number }>(`${base}/${w.id}/rotate`);
                      setSecret({ label: `New secret (old one still valid for ${r.overlap_hours}h)`, value: r.secret });
                    } catch (err) {
                      setError(message(err));
                    }
                  }}
                >
                  Rotate secret
                </button>
                <button type="button" aria-expanded={open === w.id} onClick={() => setOpen(open === w.id ? null : w.id)}>Deliveries</button>
                <button type="button" className="danger" onClick={() => void act(() => api.delete(`${base}/${w.id}`), "Webhook removed")}>Remove</button>
              </div>
            </div>
            {open === w.id && <Deliveries path={`${base}/${w.id}/deliveries`} />}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Deliveries({ path }: { path: string }) {
  const rows = useAsync(() => api.get<WebhookDelivery[]>(path), [path]);
  if (rows.error) return <ErrorBox error={rows.error} />;
  if (!rows.data) return <p className="muted small">Loading deliveries…</p>;
  if (rows.data.length === 0) return <p className="muted small deliveries-empty">No deliveries yet. Send a test.</p>;
  return (
    <table className="table deliveries">
      <thead><tr><th>Event</th><th>Status</th><th>Attempts</th><th>HTTP</th><th>When</th></tr></thead>
      <tbody>
        {rows.data.map((d) => (
          <tr key={d.id}>
            <td><code>{d.event}</code></td>
            <td><span className={`badge ${d.status === "delivered" ? "ok" : d.status === "failed" ? "bad" : "warn"}`}>{d.status}</span>{d.last_error && <div className="muted small">{d.last_error}</div>}</td>
            <td>{d.attempts}</td>
            <td>{d.response_status ?? "—"}</td>
            <td className="muted small">{when(d.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Tokens({ orgId }: { orgId: string }) {
  const base = `/orgs/${orgId}/tokens`;
  const list = useAsync(() => api.get<ApiToken[]>(base), [orgId]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"viewer" | "developer" | "approver">("developer");
  const [days, setDays] = useState("90");
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string>();

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      const made = await api.post<ApiToken & { token: string }>(base, { name: name.trim(), scope, expires_days: days ? Number(days) : null });
      setSecret(made.token);
      setName("");
      list.reload();
    } catch (err) {
      setError(message(err));
    }
  };
  const revoke = async (t: ApiToken) => {
    setError(undefined);
    try {
      await api.delete(`${base}/${t.id}`);
      toast(`Revoked "${t.name}"`, "ok");
      list.reload();
    } catch (err) {
      setError(message(err));
    }
  };

  return (
    <Card title="API tokens">
      {secret && <OneTimeSecret label="Your new API token" value={secret} onDone={() => setSecret(null)} />}
      <form className="int-form row" onSubmit={(e) => void create(e)}>
        <label className="grow">
          Token name
          <input required maxLength={80} value={name} placeholder="e.g. CI pipeline" onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Scope
          <select value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="viewer">viewer — read only</option>
            <option value="developer">developer — create &amp; run</option>
            <option value="approver">approver — also approve</option>
          </select>
        </label>
        <label>
          Expires
          <select value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="30">in 30 days</option>
            <option value="90">in 90 days</option>
            <option value="365">in a year</option>
            <option value="">never</option>
          </select>
        </label>
        <button className="primary">Create token</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {list.error && <ErrorBox error={list.error} />}
      {list.data && list.data.length === 0 && <Empty>No API tokens yet.</Empty>}
      <ul className="int-list">
        {list.data?.map((t) => (
          <li key={t.id} className={`int-item${t.revoked_at ? " revoked" : ""}`}>
            <div className="int-main">
              <span className={`int-dot${t.revoked_at ? "" : " on"}`} aria-hidden="true" />
              <div className="int-text">
                <strong>{t.name}</strong>
                <span className="muted small">
                  <code>{t.prefix}…</code> · {t.scope} · last used {when(t.last_used_at)} · {t.revoked_at ? `revoked ${when(t.revoked_at)}` : t.expires_at ? `expires ${when(t.expires_at)}` : "no expiry"}
                </span>
              </div>
              {!t.revoked_at && (
                <div className="row int-actions">
                  <button type="button" className="danger" onClick={() => void revoke(t)}>Revoke</button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
