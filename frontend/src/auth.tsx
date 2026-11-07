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
    if (!api.hasSession) return;
    api
      .get<User>("/auth/me")
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
