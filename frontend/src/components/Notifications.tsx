import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { AppNotification, MyUsage, User } from "../api/types";

interface NotificationList {
  unread: number;
  items: AppNotification[];
}

/** The bell: unread count + a list. Polls gently; failures are silent (it is only a convenience). */
export function NotificationBell() {
  const [data, setData] = useState<NotificationList>({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);

  const load = () =>
    api
      .get<NotificationList>("/notifications", { limit: 15 })
      .then((d) => Array.isArray(d?.items) && setData(d))
      .catch(() => undefined);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const read = async (n: AppNotification) => {
    if (!n.read_at) await api.post(`/notifications/${n.id}/read`).catch(() => undefined);
    void load();
  };
  const taskLink = (n: AppNotification) => {
    const id = n.detail["task_id"];
    return typeof id === "string" ? `/tasks/${id}` : null;
  };

  return (
    <div className="bell">
      <button
        className="link"
        aria-label={`Notifications, ${data.unread} unread`}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen(!open)}
      >
        <span aria-hidden="true">🔔</span>
        {data.unread > 0 && <span className="badge warn" data-testid="unread">{data.unread}</span>}
      </button>
      {open && (
        <div className="bell-panel card" role="region" aria-label="Notification list">
          {data.items.length === 0 && <p className="muted">Nothing yet.</p>}
          <ul className="notes">
            {data.items.map((n) => {
              const to = taskLink(n);
              return (
                <li key={n.id} className={n.read_at ? "read" : "unread"}>
                  {to ? (
                    <Link to={to} onClick={() => void read(n)}>{n.title}</Link>
                  ) : (
                    <button className="link" onClick={() => void read(n)}>{n.title}</button>
                  )}
                  <span className="muted small"> {new Date(n.created_at + "Z").toLocaleString()}</span>
                </li>
              );
            })}
          </ul>
          {data.unread > 0 && (
            <button className="link" onClick={() => void api.post("/notifications/read-all").then(load)}>
              Mark all read
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Banner for an unverified email and for quotas close to their cap. */
export function AccountBanners({ user, orgId }: { user: User | null; orgId: string | null }) {
  const [usage, setUsage] = useState<MyUsage>();
  const [resent, setResent] = useState(false);
  useEffect(() => {
    if (!orgId) return;
    api
      .get<MyUsage>(`/orgs/${orgId}/my-usage`)
      .then((u) => Array.isArray(u?.warnings) && setUsage(u))
      .catch(() => undefined);
  }, [orgId]);
  return (
    <>
      {user && !user.email_verified_at && (
        <section className="banner" role="status" data-testid="verify-banner">
          <span>
            Please verify your email address. We sent a link to <strong>{user.email}</strong>.
          </span>
          {resent ? (
            <span className="muted small">Sent. Check your inbox.</span>
          ) : (
            <button className="link" onClick={() => void api.post("/auth/resend-verification").then(() => setResent(true))}>
              Send it again
            </button>
          )}
        </section>
      )}
      {usage?.warnings.map((w) => (
        <section className="banner" role="status" key={`${w.scope}-${w.resource}`} data-testid="quota-banner">
          {w.scope === "org" ? "Your organization has" : "You have"} used {w.used.toLocaleString()} of{" "}
          {w.cap.toLocaleString()} {w.resource} this month.
        </section>
      ))}
    </>
  );
}
