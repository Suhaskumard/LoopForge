# Dependency policy (Phase 17)

| Rule | How it is enforced |
|---|---|
| Runtime dependencies are **pinned** (`backend/requirements-runtime.txt`, `frontend/package-lock.json`) | review of the pin file; `pip-audit`/`npm audit` run on exactly those pins |
| A known vulnerability in a runtime dependency blocks the gate | `scripts/security_scan.sh` (`pip-audit --strict`, `npm audit --omit=dev --audit-level=high`), the `supply-chain` CI job |
| Updates arrive as small reviewed PRs | `.github/dependabot.yml` (weekly, minor+patch grouped) |
| **Critical/high** security fix: patch within 7 days of the advisory; **medium**: 30 days; **low**: next routine update | owner's judgement; the age of an open advisory is visible in the weekly Dependabot list |
| A major version bump is its own PR with the full gate | `make gate17` must pass; see the FastAPI/Starlette and react-router upgrades in Phase 13 for the pattern |
| Images are built from a pinned base, scanned (Trivy HIGH/CRITICAL, unfixed ignored), SBOM-attested and **signed** | `ci.yml` `supply-chain`, `release.yml`, `scripts/verify_image.sh` |
| Nothing is pulled at run time | the sandbox has no network and no `pip`; generated code can only use the approved package list |

**Exceptions** (a vulnerability that cannot be fixed yet) are recorded in `docs/security_review.md` with the advisory id, why it is not
exploitable here, and a review date. There are none today.

**Honest limits:** `pip-audit` and `npm audit` only know published advisories; Trivy/signing/provenance are written but
**have never run on a CI runner** (the repository has no CI history). Treat the signed-image story as unverified until the first tagged
release passes `scripts/verify_image.sh`.
