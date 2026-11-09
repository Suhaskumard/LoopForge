import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router";
import { Toaster } from "./Toast";
import { prefersReducedMotion } from "./Confetti";
import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { CommandPalette, ShortcutSheet } from "./CommandPalette";
import { useTheme } from "../theme";
import { IconBulb, IconGraph, IconChart, IconCheck, IconCode, IconDoc, IconFlow, IconHome, IconMoon, IconPlus, IconShield, IconSun, Logo } from "./icons";
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
  const [theme, toggleTheme] = useTheme();
  const { pathname } = useLocation();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  useEffect(() => {
    // shortcuts: Ctrl/Cmd+K palette; "g" then c/n/a/s jumps; "?" shows the sheet. Ignored while typing.
    let lastG = 0;
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      const t = e.target as HTMLElement | null;
      if (e.ctrlKey || e.metaKey || e.altKey || t?.closest?.("input, textarea, select, [contenteditable]")) return;
      if (e.key === "Escape") setShortcutsOpen(false);
      if (e.key === "?") {
        setShortcutsOpen((o) => !o);
        return;
      }
      if (Date.now() - lastG < 1200) {
        const to = { c: "/", n: "/tasks/new", a: "/analytics", s: "/settings", g: "/graph", l: "/lessons" }[e.key];
        lastG = 0;
        if (to) {
          navigate(to);
          return;
        }
      }
      if (e.key === "g") lastG = Date.now();
    };
    // cursor spotlight: cards read --mx/--my relative to themselves; KPI tiles also tilt (--rx/--ry)
    const still = prefersReducedMotion();
    let tilted: HTMLElement | null = null;
    const move = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest?.(".card, .kpi") as HTMLElement | null | undefined;
      const kpi = el?.classList.contains("kpi") ? el : null;
      if (tilted && tilted !== kpi) {
        tilted.style.removeProperty("--rx");
        tilted.style.removeProperty("--ry");
        tilted = null;
      }
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${e.clientX - r.left}px`);
      el.style.setProperty("--my", `${e.clientY - r.top}px`);
      if (kpi && !still) {
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        kpi.style.setProperty("--rx", `${(-py * 10).toFixed(2)}deg`);
        kpi.style.setProperty("--ry", `${(px * 12).toFixed(2)}deg`);
        tilted = kpi;
      }
    };
    window.addEventListener("keydown", key);
    window.addEventListener("mousemove", move, { passive: true });
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("mousemove", move);
    };
  }, [navigate]);
  return (
    <div className="shell">
      <div className="aurora" aria-hidden="true"><i /><i /><i /></div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Toaster />
      {shortcutsOpen && <ShortcutSheet onClose={() => setShortcutsOpen(false)} />}
      <nav className="nav">
        <strong className="brand"><Logo />LoopForge</strong>
        <button className="palette-trigger" onClick={() => setPaletteOpen(true)} aria-label="Open quick search">
          Search… <kbd>Ctrl K</kbd>
        </button>
        <NavLink to="/" end><IconHome />Command Center</NavLink>
        {can("developer") && <NavLink to="/tasks/new"><IconPlus />New task</NavLink>}
        <NavLink to="/graph"><IconGraph />Task Graph</NavLink>
        <NavLink to="/lessons"><IconBulb />Lessons</NavLink>
        <NavLink to="/analytics"><IconChart />Loop Analytics</NavLink>
        {can("admin") && <NavLink to="/admin"><IconShield />Admin</NavLink>}
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
        <button className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
          {theme === "dark" ? <IconSun /> : <IconMoon />}
          {theme === "dark" ? "Light mode" : "Dark mode"}
        </button>
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
        <div className="route" key={pathname}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

/** Tab bar shared by the per-task screens (3, 4, 5, 7). */
export function TaskTabs({ id }: { id: string }) {
  return (
    <nav className="tabs task-tabs" aria-label="Task views">
      <NavLink to={`/tasks/${id}`} end><IconFlow />Live Workflow</NavLink>
      <NavLink to={`/tasks/${id}/code`}><IconCode />Code Workspace</NavLink>
      <NavLink to={`/tasks/${id}/evaluation`}><IconCheck />Evaluation</NavLink>
      <NavLink to={`/tasks/${id}/report`}><IconDoc />Final Report</NavLink>
      <Link className="tab-graph" to={`/graph?focus=${encodeURIComponent(`t:${id}`)}`} title="Show this task on the workspace map">
        <IconGraph />In graph
      </Link>
    </nav>
  );
}
