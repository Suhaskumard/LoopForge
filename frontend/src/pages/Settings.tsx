import { useState } from "react";
import { api } from "../api/client";
import type { MyUsage, SessionInfo } from "../api/types";
import { useAuth } from "../auth";
import { IconGear } from "../components/icons";
import { Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useTheme } from "../theme";
import { useAsync } from "../hooks";
import { num } from "../lib/format";

const when = (iso: string | null) => (iso ? new Date(iso + "Z").toLocaleString() : "never");

/** Account settings (Phase 15): sessions, notification email, and my own quota use. */
export function Settings() {
  const { user, activeOrg } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const initial = (user?.email ?? "?").slice(0, 1).toUpperCase();
  return (
    <>
      <PageHeader icon={<IconGear />} title="Settings" sub={user?.email} />
      <section className="profile-hero">
        <span className="profile-avatar" aria-hidden="true">{initial}</span>
        <div className="profile-text">
          <strong>{user?.email}</strong>
          <span className="muted small">
            {activeOrg ? <>{activeOrg.name} · <span className="badge">{activeOrg.role}</span></> : "No organization"}
            {user?.email_verified_at ? <span className="badge ok profile-verified">verified</span> : <span className="badge warn profile-verified">not verified</span>}
          </span>
        </div>
      </section>
      <Card title="Appearance">
        <div className="theme-tiles" role="radiogroup" aria-label="Theme">
          {(["dark", "light"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={theme === t}
              className={`theme-tile ${t}${theme === t ? " on" : ""}`}
              onClick={() => theme !== t && toggleTheme()}
            >
              <span className="tt-preview" aria-hidden="true"><i /><i /><i /></span>
              <span className="tt-label">{t === "dark" ? "Dark" : "Light"}</span>
            </button>
          ))}
        </div>
      </Card>
      <Sessions />
      <Preferences />
      {activeOrg && <MyQuota orgId={activeOrg.id} />}
    </>
  );
}

export function Sessions() {
  const list = useAsync(
    () =>
      api.request<SessionInfo[]>("GET", "/auth/sessions", {
        headers: api.currentRefreshToken ? { "X-Refresh-Token": api.currentRefreshToken } : {},
      }),
    [],
  );
  const [error, setError] = useState<string>();
  const revoke = async (id: string) => {
    setError(undefined);
    try {
      await api.delete(`/auth/sessions/${id}`);
      list.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not revoke the session");
    }
  };
  return (
    <Card title="Signed-in sessions">
      {list.loading && !list.data && <Loading what="Loading sessions" />}
      {list.error && <ErrorBox error={list.error} />}
      <table className="table">
        <caption className="visually-hidden">Signed-in sessions</caption>
        <thead>
          <tr>
            <th>Device</th>
            <th>Address</th>
            <th>Started</th>
            <th>Last used</th>
            <th><span className="visually-hidden">Action</span></th>
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((s) => (
            <tr key={s.family_id}>
              <td>
                {s.user_agent || "Unknown device"} {s.current && <span className="badge ok">this session</span>}
              </td>
              <td>{s.ip || "-"}</td>
              <td>{when(s.created_at)}</td>
              <td>{when(s.last_used_at)}</td>
              <td>{!s.current && <button onClick={() => void revoke(s.family_id)}>Sign out</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}

export function Preferences() {
  const prefs = useAsync(() => api.get<{ notify_email: boolean }>("/notifications/preferences"), []);
  const [error, setError] = useState<string>();
  const toggle = async (value: boolean) => {
    setError(undefined);
    try {
      await api.put("/notifications/preferences", { notify_email: value });
      prefs.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    }
  };
  return (
    <Card title="Notifications">
      <label className="check">
        <input
          type="checkbox"
          checked={prefs.data?.notify_email ?? true}
          disabled={!prefs.data}
          onChange={(e) => void toggle(e.target.checked)}
        />
        Email me when a task finishes, an approval needs me, or a quota is nearly used
      </label>
      <p className="muted small">In-app notifications (the bell) are always on.</p>
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}

const cap = (v: number | null) => (v === null ? "no cap" : num(v));

export function MyQuota({ orgId }: { orgId: string }) {
  const u = useAsync(() => api.get<MyUsage>(`/orgs/${orgId}/my-usage`), [orgId]);
  if (!u.data) return null;
  const { org, member } = u.data;
  return (
    <Card title="Usage this month">
      <table className="table">
        <thead>
          <tr>
            <th><span className="visually-hidden">Scope</span></th>
            <th>Tokens</th>
            <th>Tasks</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Organization</th>
            <td>{num(org.tokens_used)} / {cap(org.token_quota_month)}</td>
            <td>{org.tasks_created} / {cap(org.max_tasks_month)}</td>
          </tr>
          <tr>
            <th scope="row">You</th>
            <td>{num(member.tokens_used)} / {cap(member.token_quota_month)}</td>
            <td>{member.tasks_created} / {cap(member.max_tasks_month)}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  );
}
