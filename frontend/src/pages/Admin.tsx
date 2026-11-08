import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { ROLE_RANK, type AuditEntry, type Invite, type Member, type OrgDetails, type Role, type Usage } from "../api/types";
import { useAuth } from "../auth";
import { Card, Empty, ErrorBox, Kpi, Loading } from "../components/ui";
import { useAsync } from "../hooks";
import { num } from "../lib/format";

const ROLES = Object.keys(ROLE_RANK) as Role[];
const TABS = ["Members", "Usage & limits", "Audit log", "Data"] as const;
type Tab = (typeof TABS)[number];

/** Organization administration (Phase 10). Everything here is enforced server-side as well. */
export function Admin() {
  const { can, activeOrg } = useAuth();
  const [tab, setTab] = useState<Tab>("Members");
  if (!activeOrg || !can("admin")) return <Empty>Organization settings are for admins.</Empty>;
  return (
    <>
      <header className="page-head">
        <h1>Administration</h1>
        <span className="muted">{activeOrg.name}</span>
      </header>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "Members" && (
        <>
          <Members orgId={activeOrg.id} />
          <Invites orgId={activeOrg.id} />
        </>
      )}
      {tab === "Usage & limits" && (
        <>
          <Limits orgId={activeOrg.id} />
          <MemberQuotas orgId={activeOrg.id} />
        </>
      )}
      {tab === "Audit log" && <AuditLog orgId={activeOrg.id} />}
      {tab === "Data" && <DataLifecycle orgId={activeOrg.id} />}
    </>
  );
}

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function Members({ orgId }: { orgId: string }) {
  const list = useAsync(() => api.get<Member[]>(`/orgs/${orgId}/members`), [orgId]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("developer");
  const [error, setError] = useState<string>();

  const run = async (fn: () => Promise<unknown>) => {
    setError(undefined);
    try {
      await fn();
      list.reload();
    } catch (e) {
      setError(message(e));
    }
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post(`/orgs/${orgId}/members`, { email, role });
      setEmail("");
    });
  };

  return (
    <Card title="Members">
      {list.loading && !list.data && <Loading what="Loading members" />}
      {list.error && <ErrorBox error={list.error} />}
      <table className="table">
        <thead>
          <tr><th>Email</th><th>Role</th><th /></tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((m) => (
            <tr key={m.user_id}>
              <td>{m.email}</td>
              <td>
                <select
                  aria-label={`Role of ${m.email}`}
                  value={m.role}
                  onChange={(e) => void run(() => api.request("PATCH", `/orgs/${orgId}/members/${m.user_id}`, { json: { role: e.target.value } }))}
                >
                  {ROLES.map((r) => <option key={r}>{r}</option>)}
                </select>
              </td>
              <td>
                <button onClick={() => void run(() => api.request("DELETE", `/orgs/${orgId}/members/${m.user_id}`))}>Remove</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="row" onSubmit={add}>
        <label>
          Add an existing user by email
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <button className="primary">Add member</button>
      </form>
      <p className="muted small">This adds someone who already has an account. To invite anyone by email, use the form below.</p>
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}

/** Invite by email (Phase 15). The reply is the same whether or not the address has an account. */
export function Invites({ orgId }: { orgId: string }) {
  const list = useAsync(() => api.get<Invite[]>(`/orgs/${orgId}/invites`), [orgId]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("developer");
  const [error, setError] = useState<string>();
  const [sent, setSent] = useState(false);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    setSent(false);
    try {
      await api.post(`/orgs/${orgId}/invites`, { email, role });
      setEmail("");
      setSent(true);
      list.reload();
    } catch (err) {
      setError(message(err));
    }
  };
  const revoke = async (id: string) => {
    setError(undefined);
    try {
      await api.delete(`/orgs/${orgId}/invites/${id}`);
      list.reload();
    } catch (err) {
      setError(message(err));
    }
  };

  return (
    <Card title="Invitations">
      <form className="row" onSubmit={(e) => void send(e)}>
        <label>
          Email to invite
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <button className="primary">Send invitation</button>
      </form>
      {sent && <p role="status" className="muted small">If the address can receive an invitation, one was sent.</p>}
      {(list.data ?? []).length > 0 && (
        <table className="table">
          <caption className="visually-hidden">Pending invitations</caption>
          <thead><tr><th>Email</th><th>Role</th><th>Expires</th><th /></tr></thead>
          <tbody>
            {(list.data ?? []).map((i) => (
              <tr key={i.id}>
                <td>{i.email}</td>
                <td>{i.role}</td>
                <td>{new Date(i.expires_at + "Z").toLocaleDateString()}</td>
                <td><button onClick={() => void revoke(i.id)}>Revoke</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}

/** Personal monthly caps per member (empty = no personal cap; the organization cap still applies). */
export function MemberQuotas({ orgId }: { orgId: string }) {
  const list = useAsync(() => api.get<Member[]>(`/orgs/${orgId}/members`), [orgId]);
  const [draft, setDraft] = useState<Record<string, { tokens: string; tasks: string }>>({});
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const save = async (m: Member) => {
    const d = draft[m.user_id] ?? { tokens: "", tasks: "" };
    setError(undefined);
    try {
      await api.put(`/orgs/${orgId}/members/${m.user_id}/quota`, {
        token_quota_month: asNumber(d.tokens),
        max_tasks_month: asNumber(d.tasks),
      });
      setSaved(m.email);
    } catch (err) {
      setError(message(err));
    }
  };
  const edit = (m: Member, key: "tokens" | "tasks", value: string) =>
    setDraft({ ...draft, [m.user_id]: { ...(draft[m.user_id] ?? { tokens: "", tasks: "" }), [key]: value } });
  return (
    <Card title="Per-member limits">
      <table className="table">
        <caption className="visually-hidden">Per-member monthly limits</caption>
        <thead><tr><th>Member</th><th>Tokens / month</th><th>Tasks / month</th><th /></tr></thead>
        <tbody>
          {(list.data ?? []).map((m) => (
            <tr key={m.user_id}>
              <td>{m.email}</td>
              <td><input aria-label={`Token limit for ${m.email}`} inputMode="numeric" placeholder="no cap" onChange={(e) => edit(m, "tokens", e.target.value)} /></td>
              <td><input aria-label={`Task limit for ${m.email}`} inputMode="numeric" placeholder="no cap" onChange={(e) => edit(m, "tasks", e.target.value)} /></td>
              <td><button aria-label={`Save limits for ${m.email}`} onClick={() => void save(m)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">A task is limited by the lower of the organization&apos;s and its creator&apos;s remaining allowance. Saving with empty boxes removes the personal cap.</p>
      {saved && <p role="status" className="muted small">Saved limits for {saved}.</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}

const cap = (v: number | null) => (v === null ? "no cap" : num(v));
const asNumber = (v: string): number | null => (v.trim() === "" ? null : Number(v));

export function Limits({ orgId }: { orgId: string }) {
  const usage = useAsync(() => api.get<Usage>(`/orgs/${orgId}/usage`), [orgId]);
  const org = useAsync(() => api.get<OrgDetails>(`/orgs/${orgId}`), [orgId]);
  const [form, setForm] = useState<{ tokens: string; tasks: string; days: string; pii: boolean } | null>(null);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const o = org.data;
  const values = form ?? {
    tokens: o?.token_quota_month?.toString() ?? "",
    tasks: o?.max_tasks_month?.toString() ?? "",
    days: o?.retention_days?.toString() ?? "",
    pii: o?.redact_pii ?? false,
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    setSaved(false);
    try {
      // empty box = null = remove the cap
      await api.request("PATCH", `/orgs/${orgId}`, {
        json: {
          token_quota_month: asNumber(values.tokens),
          max_tasks_month: asNumber(values.tasks),
          retention_days: asNumber(values.days),
          redact_pii: values.pii,
        },
      });
      setSaved(true);
      setForm(null);
      org.reload();
      usage.reload();
    } catch (err) {
      setError(message(err));
    }
  };

  return (
    <>
      <Card title="This month">
        {usage.error && <ErrorBox error={usage.error} />}
        {usage.data && (
          <div className="kpis">
            <Kpi label="Tokens used" value={num(usage.data.tokens_used)} hint={`quota: ${cap(usage.data.token_quota_month)}`} />
            <Kpi label="Tokens left" value={usage.data.tokens_remaining === null ? "unlimited" : num(usage.data.tokens_remaining)} />
            <Kpi label="Tasks created" value={num(usage.data.tasks_created)} hint={`limit: ${cap(usage.data.max_tasks_month)}`} />
          </div>
        )}
        <p className="muted small">Token figures are estimates from agent runs, not billing data.</p>
      </Card>
      <Card title="Limits and data handling">
        <form className="form" onSubmit={(e) => void save(e)}>
          <label>
            Monthly token quota
            <input inputMode="numeric" placeholder="no cap" value={values.tokens} onChange={(e) => setForm({ ...values, tokens: e.target.value })} />
          </label>
          <label>
            Tasks per month
            <input inputMode="numeric" placeholder="no cap" value={values.tasks} onChange={(e) => setForm({ ...values, tasks: e.target.value })} />
          </label>
          <label>
            Keep finished tasks for (days)
            <input inputMode="numeric" placeholder="forever" value={values.days} onChange={(e) => setForm({ ...values, days: e.target.value })} />
          </label>
          <label className="check">
            <input type="checkbox" checked={values.pii} onChange={(e) => setForm({ ...values, pii: e.target.checked })} />
            Mask emails and phone numbers in the audit log
          </label>
          <button className="primary">Save</button>
          {saved && <span className="badge ok">saved</span>}
          {error && <p className="error" role="alert">{error}</p>}
        </form>
      </Card>
    </>
  );
}

export function AuditLog({ orgId }: { orgId: string }) {
  const [action, setAction] = useState("");
  const rows = useAsync(
    () => api.get<AuditEntry[]>(`/orgs/${orgId}/audit`, { limit: 100, action: action || undefined }),
    [orgId, action],
  );
  return (
    <Card
      title="Audit log"
      actions={
        <input aria-label="Filter by action" placeholder="filter, e.g. member.add" value={action} onChange={(e) => setAction(e.target.value.trim())} />
      }
    >
      {rows.error && <ErrorBox error={rows.error} />}
      {rows.data?.length === 0 && <Empty>No entries.</Empty>}
      {rows.data && rows.data.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>When (UTC)</th><th>Action</th><th>Target</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {rows.data.map((r) => (
              <tr key={r.id}>
                <td>{r.created_at.replace("T", " ").slice(0, 19)}</td>
                <td><code>{r.action}</code></td>
                <td className="small">{r.target_type} {r.target_id.slice(0, 8)}</td>
                <td className="small clip">{Object.keys(r.detail).length ? JSON.stringify(r.detail) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">Append-only: entries cannot be edited or deleted, not even by admins.</p>
    </Card>
  );
}

export function DataLifecycle({ orgId }: { orgId: string }) {
  const org = useAsync(() => api.get<OrgDetails>(`/orgs/${orgId}`), [orgId]);
  const [confirm, setConfirm] = useState("");
  const [info, setInfo] = useState<string>();
  const [error, setError] = useState<string>();

  const act = async (fn: () => Promise<string>) => {
    setError(undefined);
    setInfo(undefined);
    try {
      setInfo(await fn());
    } catch (e) {
      setError(message(e));
    }
  };
  const exportData = () =>
    act(async () => {
      const blob = await api.blob(`/orgs/${orgId}/export`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${org.data?.slug ?? "organization"}-export.zip`;
      a.click();
      URL.revokeObjectURL(url);
      return "Export downloaded.";
    });

  return (
    <Card title="Data">
      <div className="row">
        <button onClick={() => void exportData()}>Export organization data (.zip)</button>
        <button
          onClick={() =>
            void act(async () => {
              const r = await api.request<{ purged_tasks: number }>("POST", `/orgs/${orgId}/retention/run`, { json: {} });
              return `Retention run removed ${r.purged_tasks} finished task(s).`;
            })
          }
        >
          Run retention now
        </button>
      </div>
      <hr />
      <h3>Delete all projects and tasks</h3>
      <p className="muted small">
        Irreversible. The organization, its members and the audit log stay. Type the organization slug
        {org.data && <> (<code>{org.data.slug}</code>)</>} to confirm.
      </p>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          void act(async () => {
            const r = await api.request<{ deleted_tasks: number }>("DELETE", `/orgs/${orgId}/data`, { json: { confirm } });
            setConfirm("");
            return `Deleted ${r.deleted_tasks} task(s).`;
          });
        }}
      >
        <input aria-label="Confirm organization slug" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <button className="danger" disabled={!org.data || confirm !== org.data.slug}>Delete everything</button>
      </form>
      {info && <p className="badge ok" role="status">{info}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}
