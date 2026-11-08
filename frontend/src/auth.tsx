import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api/client";
import type { User } from "./api/types";

interface AuthValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(api.hasSession);

  useEffect(() => {
    api.onAuthLost = () => setUser(null);
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
      return api.get<User>("/auth/me");
    };
    const start = api.hasSession ? api.get<User>("/auth/me").catch(() => null) : Promise.resolve(null);
    setLoading(true);
    start
      .then((u) => u ?? autoLogin())
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      loading,
      login: async (email, password) => {
        await api.login(email, password);
        setUser(await api.get<User>("/auth/me"));
      },
      register: async (email, password) => {
        await api.register(email, password);
        await api.login(email, password);
        setUser(await api.get<User>("/auth/me"));
      },
      logout: async () => {
        await api.logout();
        setUser(null);
      },
    }),
    [user, loading],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
