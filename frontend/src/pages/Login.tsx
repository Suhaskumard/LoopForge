import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { api, MfaRequired } from "../api/client";
import { useAuth } from "../auth";
import { PasswordField } from "../components/PasswordField";

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
  const [needCode, setNeedCode] = useState(false); // two-factor step
  const [code, setCode] = useState("");

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
      await (mode === "login" ? login(email, password, needCode ? code : undefined) : register(email, password));
      navigate("/");
    } catch (err) {
      if (err instanceof MfaRequired) {
        setNeedCode(true); // password accepted: ask for the authenticator code, no error shown
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong");
        if (needCode) setCode("");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth auth-split">
      <aside className="auth-hero" aria-hidden="true">
        <div className="orbit"><span /><span /><span /></div>
        <div className="code-demo">
          <div className="code-demo-bar"><i /><i /><i /><small>loop · iteration 2</small></div>
          <code className="l1">def slugify(text: str) -&gt; str:</code>
          <code className="l2">    return re.sub(r"\W+", "-", text).strip("-").lower()</code>
          <code className="l3 test">✔ test_basic_slug</code>
          <code className="l4 test">✔ test_unicode_is_stripped</code>
          <code className="l5 pass">Reviewer: accepted · quality 94</code>
        </div>
        <h2>Ship code that proves itself.</h2>
        <ul>
          <li><b>Plan</b> from plain English</li>
          <li><b>Build &amp; test</b> in a sandbox</li>
          <li><b>Review</b> independently</li>
          <li><b>Repair</b> until it passes</li>
        </ul>
      </aside>
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
          <PasswordField
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 8 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>
        {mode === "register" && <p className="muted small">At least 8 characters, with a letter and a digit.</p>}
        {needCode && mode === "login" && (
          <div className="mfa-step">
            <span className="mfa-shield" aria-hidden="true">⛨</span>
            <label>
              Authentication code
              <input
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123 456"
                required
                minLength={6}
                maxLength={20}
                className="mfa-code"
              />
            </label>
            <p className="muted small">Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>
          </div>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{mode === "login" ? (needCode ? "Verify and sign in" : "Sign in") : "Create account"}</button>
        {mode === "login" && <Link to="/forgot-password">Forgot your password?</Link>}
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Need an account? Register" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
