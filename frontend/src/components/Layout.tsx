import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Loading } from "./ui";

export function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <Loading what="Restoring session" />;
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="shell">
      <nav className="nav">
        <strong className="brand">LoopForge</strong>
        <NavLink to="/" end>Command Center</NavLink>
        <NavLink to="/tasks/new">New task</NavLink>
        <NavLink to="/analytics">Loop Analytics</NavLink>
        <span className="spacer" />
        <span className="muted who">{user?.email}</span>
        <button
          className="link"
          onClick={() => {
            void logout().then(() => navigate("/login"));
          }}
        >
          Sign out
        </button>
      </nav>
      <main className="page">
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
