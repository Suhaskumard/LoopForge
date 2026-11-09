import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api/client";
import { ROLE_RANK, type OrgMembership, type Role, type User } from "./api/types";

interface AuthValue {
  user: User | null;
  loading: boolean;
  orgs: OrgMembership[];
  /** The organization requests are made in, and the caller's role there. */
  activeOrg: OrgMembership | null;
  role: Role | null;
  can: (minimum: Role) => boolean;
  switchOrg: (id: string) => void;
  reloadOrgs: () => Promise<void>;
  login: (email: string, password: string, mfaCode?: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  /** Finish an SSO login: the login page passes the tokens it found in the URL fragment. */
  completeSso: (tokens: { access_token: string; refresh_token: string }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

/** Keep the remembered org if the user still belongs to it, otherwise fall back to their first. */
export function pickOrg(orgs: OrgMembership[], remembered: string | null): OrgMembership | null {
  return orgs.find((o) => o.id === remembered) ?? orgs[0] ?? null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(api.hasSession);
  const [orgs, setOrgs] = useState<OrgMembership[]>([]);
  const [activeId, setActiveId] = useState<string | null>(api.orgId);

  const loadOrgs = useCallback(async () => {
    const list = await api.get<OrgMembership[]>("/orgs");
    const chosen = pickOrg(list, api.orgId);
    api.setOrg(chosen?.id ?? null);
    setOrgs(list);
    setActiveId(chosen?.id ?? null);
  }, []);

  const loadUser = useCallback(async (): Promise<User> => {
    const me = await api.get<User>("/auth/me");
    await loadOrgs();
    setUser(me);
    return me;
  }, [loadOrgs]);

  useEffect(() => {
    api.onAuthLost = () => {
      setUser(null);
      setOrgs([]);
    };
    // Dev-only convenience: `npm run dev` with VITE_DEV_AUTOLOGIN=1 signs in (registering if needed), also
    // when a saved session has gone stale (e.g. the dev API restarted). import.meta.env.DEV is false in
    // production builds, so this is dead code there.
    const env = import.meta.env;
    const autoLogin = async (): Promise<User | null> => {
      if (!(env.DEV && env.VITE_DEV_AUTOLOGIN === "1")) return null;
      const email = env.VITE_DEV_EMAIL ?? "demo@example.com";
      const password = env.VITE_DEV_PASSWORD ?? "demo12345";
      try {
        await api.login(email, password);
      } catch {
        await api.register(email, password);
        await api.login(email, password);
      }
      return loadUser();
    };
    const start = api.hasSession ? loadUser().catch(() => null) : Promise.resolve(null);
    setLoading(true);
    start
      .then((u) => u ?? autoLogin())
      .then((u) => u && setUser(u))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, [loadUser]);

  const activeOrg = useMemo(() => orgs.find((o) => o.id === activeId) ?? null, [orgs, activeId]);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      orgs,
      activeOrg,
      role: activeOrg?.role ?? null,
      can: (minimum) => activeOrg !== null && ROLE_RANK[activeOrg.role] >= ROLE_RANK[minimum],
      switchOrg: (id) => {
        api.setOrg(id);
        setActiveId(id);
      },
      reloadOrgs: loadOrgs,
      login: async (email, password, mfaCode) => {
        await api.login(email, password, mfaCode);
        await loadUser();
      },
      register: async (email, password) => {
        await api.register(email, password);
        await api.login(email, password);
        await loadUser();
      },
      completeSso: async (tokens) => {
        api.adoptTokens(tokens);
        await loadUser();
      },
      logout: async () => {
        await api.logout();
        setUser(null);
        setOrgs([]);
        setActiveId(null);
      },
    }),
    [user, loading, orgs, activeOrg, loadOrgs, loadUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
