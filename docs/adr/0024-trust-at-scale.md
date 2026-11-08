# ADR-0024: Trust at scale - key ring, enterprise identity, hardened sandbox runtime, SLOs and recovery (Phase 17)

**Status:** accepted. Built and tested here: key ring and rotation, encrypted/rotatable webhook secrets, SSO group mapping, SCIM 2.0,
TOTP MFA, sandbox runtime option, queue back-pressure, SLO alerts, a measured DR drill and PostgreSQL load profile, control mapping.
**Not done and not claimed:** an external penetration test, any gVisor/Firecracker measurement, a real KMS adapter, a verified signed release.

## Decisions
- **Key ring, not a single secret.** `KEYRING_JSON` holds named keys with one active. Ciphertext is `v2:<kid>:<fernet>`; JWTs carry `kid`.
  The pre-existing keys are the implicit `legacy` key, so enabling the ring breaks nothing. A missing/wrong key raises `KeyUnavailable`
  (before: a silent `None` that looked like "no token"). Production now requires `SECRETS_KEY` or a ring, distinct from `JWT_SECRET`.
  `python -m app.keys_cli rotate` re-encrypts idempotently and never destroys a value it cannot read.
- **KMS is an interface, not a dependency.** `KeyProvider` is where a KMS adapter plugs in; only the local provider exists and is tested.
- **Webhook secrets** are encrypted at rest and rotate with an overlap (both `v1=` signatures for `WEBHOOK_ROTATION_OVERLAP_HOURS`).
- **SCIM is per organization.** A SCIM token is bound to one org; "active" means "has a membership of this org". Deprovisioning never disables an
  account that still belongs to another org, and never removes the last admin. Groups are the four fixed role groups.
- **SSO group mapping touches only `source='sso'` memberships**; manual and SCIM-managed ones are left alone; every change is audited.
- **MFA is TOTP (RFC 6238, stdlib), single-use per time step, with hashed recovery codes.** Org policy `require_mfa` applies to password
  accounts; SSO-only accounts and API tokens are exempt because their identity provider / scope owns authentication.
- **Sandbox runtime is configurable and fails closed.** `SANDBOX_RUNTIME=runsc|kata` adds `--runtime`; if the daemon lacks it the run errors,
  it never falls back to `runc`. `SANDBOX_REQUIRE_HARDENED_RUNTIME` forbids plain `runc` in production.
- **Back-pressure** refuses new starts (429 + `Retry-After`) rather than queueing without bound; globally and per org.
- **SLO alerts use multi-window burn rates**; targets live in `docs/slo.md`.
- **`app.keys_cli`** (not the HTTP `cli`) performs rotation because it needs database access, not an API token.

## Known limits (read these)
- **No external penetration test.** `docs/pentest/` is the package for one; the results table is empty by design.
- **gVisor/Kata are not installed on the development machine**: only argument building and the fail-closed check are tested (mocked
  `docker info`). Isolation strength and performance cost under gVisor are **unmeasured**. Egress remains `--network none`; a per-task allow-list is deferred to Phase 18.
- **RTO 15.4 s / RPO 3.4 s** come from one container on one machine with a tiny database. In production RPO equals the backup interval.
- **SCIM** is tested against our own client, not Okta or Entra. TOTP is not phishing-resistant; WebAuthn is out of scope. There is no MFA UI yet
  (API and login step-up exist; the React login page does not prompt for a code).
- **`release.yml` (cosign, provenance, SBOM attestation) and Dependabot have never run**; the repository has no CI history. Signed images are
  unverified until the first tagged release passes `scripts/verify_image.sh`.
- Burn-rate thresholds follow the formulas and are untuned. The compliance mapping is a readiness aid, not an attestation.
