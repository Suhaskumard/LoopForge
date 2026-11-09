import { useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { useAsync } from "../hooks";
import { encodeQr } from "../lib/qr";
import { OneTimeSecret } from "./Integrations";
import { toast } from "./Toast";
import { Card, ErrorBox } from "./ui";

interface MfaStatus {
  enabled: boolean;
  recovery_codes_left: number;
}

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

/** "ABCDEFGHIJKL" -> "ABCD EFGH IJKL": easier to type into an authenticator app by hand. */
export const groupSecret = (s: string) => s.replace(/(.{4})/g, "$1 ").trim();

/** A QR code drawn as SVG (dark on white with a quiet zone, so it scans in either theme). */
export function QrImage({ text }: { text: string }) {
  const qr = useMemo(() => {
    try {
      return encodeQr(text);
    } catch {
      return null; // too long for v1-10: the setup key below still works
    }
  }, [text]);
  if (!qr) return null;
  const n = qr.modules.length;
  const quiet = 4;
  let path = "";
  qr.modules.forEach((row, y) => row.forEach((dark, x) => { if (dark) path += `M${x + quiet} ${y + quiet}h1v1h-1z`; }));
  return (
    <svg className="mfa-qr" viewBox={`0 0 ${n + quiet * 2} ${n + quiet * 2}`} role="img" aria-label="QR code for your authenticator app" shapeRendering="crispEdges" data-testid="mfa-qr">
      <rect width="100%" height="100%" fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}

/** Two-factor sign-in: enrol an authenticator app, confirm a code, keep the recovery codes. */
export function TwoFactorCard() {
  const status = useAsync(() => api.get<MfaStatus>("/auth/mfa"), []);
  const [enrol, setEnrol] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const run = async (fn: () => Promise<void>) => {
    setError(undefined);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const start = () => run(async () => setEnrol(await api.post("/auth/mfa/enroll")));
  const activate = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const r = await api.post<{ recovery_codes: string[] }>("/auth/mfa/activate", { code: code.replace(/\s+/g, "") });
      setRecovery(r.recovery_codes);
      setEnrol(null);
      setCode("");
      toast("Two-factor sign-in is on", "ok");
      status.reload();
    });
  };
  const disable = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api.post("/auth/mfa/disable", { code: code.replace(/\s+/g, "") });
      setDisabling(false);
      setCode("");
      toast("Two-factor sign-in is off", "info");
      status.reload();
    });
  };
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied", "ok");
    } catch {
      toast("Copy is blocked by the browser; select the text instead", "bad");
    }
  };

  const s = status.data;
  return (
    <Card title="Two-factor authentication">
      {recovery && (
        <OneTimeSecret label="Recovery codes — each works once if you lose your phone" value={recovery.join("   ")} onDone={() => setRecovery(null)} />
      )}
      {status.error && <ErrorBox error={status.error} />}
      <div className={`mfa${s?.enabled ? " on" : ""}`}>
        <span className="mfa-badge" aria-hidden="true">⛨</span>
        <div className="mfa-text">
          <strong data-testid="mfa-state">{s ? (s.enabled ? "On — sign-in asks for a code" : "Off") : "…"}</strong>
          <span className="muted small">
            {s?.enabled
              ? `${s.recovery_codes_left} recovery code${s.recovery_codes_left === 1 ? "" : "s"} left.`
              : "Protect your account with a 6-digit code from an authenticator app (Google Authenticator, 1Password, Authy…)."}
          </span>
        </div>
        {s && !s.enabled && !enrol && <button type="button" className="primary" disabled={busy} onClick={() => void start()}>Set up</button>}
        {s?.enabled && !disabling && <button type="button" className="danger" onClick={() => setDisabling(true)}>Turn off</button>}
      </div>

      {enrol && (
        <form className="mfa-enrol" onSubmit={activate}>
          <ol className="mfa-steps">
            <li>
              <b>Scan this with your authenticator app</b>
              <QrImage text={enrol.otpauth_uri} />
              <span className="muted small">Can&apos;t scan? Type this setup key instead:</span>
              <div className="mfa-secret">
                <code data-testid="mfa-secret">{groupSecret(enrol.secret)}</code>
                <button type="button" onClick={() => void copy(enrol.secret)}>Copy key</button>
              </div>
              <details>
                <summary className="muted small">Using a setup link instead?</summary>
                <div className="mfa-secret">
                  <code className="mfa-uri">{enrol.otpauth_uri}</code>
                  <button type="button" onClick={() => void copy(enrol.otpauth_uri)}>Copy link</button>
                </div>
              </details>
            </li>
            <li>
              <b>Enter the 6-digit code</b> it shows to finish:
              <div className="row">
                <label className="mfa-code-label">
                  Code
                  <input className="mfa-code" inputMode="numeric" autoComplete="one-time-code" required minLength={6} maxLength={8} value={code} onChange={(e) => setCode(e.target.value)} placeholder="123 456" />
                </label>
                <button className="primary" disabled={busy}>Turn on</button>
                <button type="button" onClick={() => { setEnrol(null); setCode(""); }}>Cancel</button>
              </div>
            </li>
          </ol>
        </form>
      )}

      {disabling && (
        <form className="mfa-enrol row" onSubmit={disable}>
          <label className="mfa-code-label">
            Current code or a recovery code
            <input className="mfa-code" autoComplete="one-time-code" required minLength={6} maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
          <button className="danger" disabled={busy}>Turn off two-factor</button>
          <button type="button" onClick={() => { setDisabling(false); setCode(""); }}>Keep it on</button>
        </form>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </Card>
  );
}
