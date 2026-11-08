import { NavLink, Navigate, Outlet, useNavigate } from "react-router";
import { useAuth } from "../auth";
import { AccountBanners, NotificationBell } from "./Notifications";
import { Loading } from "./ui";

export function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <Loading what="Restoring session" />;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

function Layout() {
  const { user, logout, orgs, activeOrg, switchOrg, can } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="shell">
      <nav className="nav">
        <strong className="brand">LoopForge</strong>
        <NavLink to="/" end>Command Center</NavLink>
        {can("developer") && <NavLink to="/tasks/new">New task</NavLink>}
        <NavLink to="/analytics">Loop Analytics</NavLink>
        {can("admin") && <NavLink to="/admin">Admin</NavLink>}
        <span className="spacer" />
        {orgs.length > 1 ? (
          <select
            aria-label="Organization"
            className="org-switch"
            value={activeOrg?.id ?? ""}
            onChange={(e) => {
              switchOrg(e.target.value);
              navigate("/");
            }}
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
        ) : (
          activeOrg && <span className="muted who" data-testid="org-name">{activeOrg.name}</span>
        )}
        {activeOrg && <span className="badge" data-testid="role">{activeOrg.role}</span>}
        <NotificationBell />
        <NavLink to="/settings" className="who">{user?.email}</NavLink>
        <button
          className="link"
          onClick={() => {
            void logout().then(() => navigate("/login"));
          }}
        >
          Sign out
        </button>
      </nav>
      {/* key: switching organization remounts the page, so nothing from the old one stays on screen */}
      <main className="page" key={activeOrg?.id ?? "none"}>
        <AccountBanners user={user} orgId={activeOrg?.id ?? null} />
        <Outlet />
      </main>
    </div>
  );
}

/** Tab bar shared by the per-task screens (3, 4, 5, 7). */
export function TaskTabs({ id }: { id: string }) {
  return (
    <div className="tabs">
      <NavLink to={`/tasks/${id}`} end>Live Workflow</NavLink>
      <NavLink to={`/tasks/${id}/code`}>Code Workspace</NavLink>
      <NavLink to={`/tasks/${id}/evaluation`}>Evaluation</NavLink>
      <NavLink to={`/tasks/${id}/report`}>Final Report</NavLink>
    </div>
  );
}
