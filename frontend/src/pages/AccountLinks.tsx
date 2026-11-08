import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth";

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

function Shell({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="auth">
      <main className="card auth-card">
        <h1>{title}</h1>
        {children}
      </main>
    </div>
  );
}

/** Opened from the verification email: `/verify-email?token=...`. The link works once. */
export function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "bad">(token ? "working" : "bad");
  useEffect(() => {
    if (!token) return;
    api
      .request<User>("POST", "/auth/verify-email", { json: { token }, auth: false })
      .then(() => setState("ok"))
      .catch(() => setState("bad"));
  }, [token]);
  return (
    <Shell title="Email verification">
      {state === "working" && <p role="status">Verifying…</p>}
      {state === "ok" && <p role="status">Your email address is verified. Thank you.</p>}
      {state === "bad" && (
        <p className="error" role="alert">
          This link is invalid or has expired. Sign in and request a new one.
        </p>
      )}
      <Link to="/">Continue to LoopForge</Link>
    </Shell>
  );
}

/** Always answers the same way, so it never reveals whether an address has an account. */
export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string>();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      await api.request("POST", "/auth/password-reset/request", { json: { email }, auth: false });
      setSent(true);
    } catch (err) {
      setError(message(err));
    }
  };
  return (
    <Shell title="Reset your password">
      {sent ? (
        <p role="status">
          If that address is registered, an email with a reset link is on its way. The link expires in one hour.
        </p>
      ) : (
        <form className="form" onSubmit={(e) => void submit(e)}>
          <label>
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary">Send reset link</button>
        </form>
      )}
      <Link to="/login">Back to sign in</Link>
    </Shell>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    try {
      await api.request("POST", "/auth/password-reset/confirm", { json: { token, password }, auth: false });
      setDone(true);
      window.setTimeout(() => navigate("/login"), 1500);
    } catch (err) {
      setError(message(err));
    }
  };
  return (
    <Shell title="Choose a new password">
      {done ? (
        <p role="status">Password changed. All other sessions were signed out. Redirecting to sign in…</p>
      ) : (
        <form className="form" onSubmit={(e) => void submit(e)}>
          <label>
            New password
            <input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </label>
          <p className="muted small">At least 8 characters, with a letter and a digit.</p>
          {error && <p className="error" role="alert">{error}</p>}
          {!token && <p className="error" role="alert">This link is missing its token.</p>}
          <button className="primary" disabled={!token}>Change password</button>
        </form>
      )}
    </Shell>
  );
}

/** `/accept-invite?token=...`. Needs a signed-in account whose verified email matches the invite. */
export function AcceptInvite() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { user, loading, reloadOrgs, switchOrg } = useAuth();
  const [state, setState] = useState<"idle" | "ok" | "bad">("idle");
  const [error, setError] = useState<string>();
  const accept = async () => {
    setError(undefined);
    try {
      const r = await api.post<{ org_id: string }>("/invites/accept", { token });
      await reloadOrgs();
      switchOrg(r.org_id);
      setState("ok");
    } catch (err) {
      setError(message(err));
      setState("bad");
    }
  };
  return (
    <Shell title="Join an organization">
      {loading ? (
        <p role="status">Checking your session…</p>
      ) : !user ? (
        <p>
          Sign in or register with the <strong>email address that received the invitation</strong>, verify it, then open
          this link again. <Link to="/login">Go to sign in</Link>
        </p>
      ) : state === "ok" ? (
        <p role="status">
          You joined the organization. <Link to="/">Open the Command Center</Link>
        </p>
      ) : (
        <>
          <p>
            Signed in as <strong>{user.email}</strong>.
          </p>
          {!user.email_verified_at && <p className="error">Verify your email address first (check your inbox).</p>}
          {error && <p className="error" role="alert">{error}</p>}
          <button className="primary" onClick={() => void accept()} disabled={!token}>
            Accept invitation
          </button>
        </>
      )}
    </Shell>
  );
}
