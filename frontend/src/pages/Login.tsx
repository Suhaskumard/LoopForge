import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { api } from "../api/client";
import { useAuth } from "../auth";

/** What the SSO callback put in the URL fragment: tokens (success) or a safe error message. */
export function parseSsoFragment(hash: string): { tokens?: { access_token: string; refresh_token: string }; error?: string } {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const error = params.get("error");
  if (error) return { error };
  const access_token = params.get("access_token");
  const refresh_token = params.get("refresh_token");
  return access_token && refresh_token ? { tokens: { access_token, refresh_token } } : {};
}

export function Login() {
  const { user, login, register, completeSso } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .request<{ sso_enabled: boolean }>("GET", "/auth/config", { auth: false })
      .then((c) => alive && setSsoEnabled(c.sso_enabled))
      .catch(() => undefined); // no config endpoint reachable: just no SSO button
    const { tokens, error: ssoError } = parseSsoFragment(window.location.hash);
    if (tokens || ssoError) window.history.replaceState(null, "", window.location.pathname); // tokens must not linger in the URL
    if (ssoError) setError(ssoError);
    if (tokens) {
      setBusy(true);
      completeSso(tokens)
        .then(() => navigate("/"))
        .catch((e: unknown) => setError(e instanceof Error ? e.message : "Single sign-on failed"))
        .finally(() => setBusy(false));
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      await (mode === "login" ? login(email, password) : register(email, password));
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <form className="card auth-card" onSubmit={(e) => void submit(e)}>
        <h1>LoopForge</h1>
        <p className="muted">Autonomous, test-driven software engineering — with evidence.</p>
        {ssoEnabled && (
          <>
            {/* a full-page navigation: the identity provider takes over, then returns to this page */}
            <a className="primary btn-link" href="/api/v1/auth/sso/login">Sign in with SSO</a>
            <p className="muted small center">or with a password</p>
          </>
        )}
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 8 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>
        {mode === "register" && <p className="muted small">At least 8 characters, with a letter and a digit.</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
        {mode === "login" && <Link to="/forgot-password">Forgot your password?</Link>}
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
