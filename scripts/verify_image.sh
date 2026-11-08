#!/usr/bin/env bash
# Verify that a LoopForge image was built and signed by this repository's release workflow (Phase 17, ADR-0024).
#   bash scripts/verify_image.sh ghcr.io/<owner>/loopforge-backend@sha256:<digest> [owner/repo]
# Checks (1) the cosign keyless signature and its certificate identity, (2) the SLSA build provenance, (3) the SBOM
# attestation exists. Needs `cosign` (and `gh` for the provenance check). Exit 0 only if everything verifies; a missing
# tool is a FAILURE, not a skip. Never run against a real release yet - the release workflow has not run.
set -euo pipefail
IMAGE="${1:?usage: verify_image.sh <image@sha256:digest> [owner/repo]}"
REPO="${2:-Suhaskumard/LoopForge}"
case "$IMAGE" in *@sha256:*) ;; *) echo "FAIL: pass the image by digest (name@sha256:...), a tag can move"; exit 2;; esac
command -v cosign >/dev/null || { echo "FAIL: cosign is not installed"; exit 3; }

ISSUER="https://token.actions.githubusercontent.com"
IDENTITY="^https://github.com/${REPO}/\.github/workflows/release\.yml@refs/tags/v.*$"
echo "== signature (keyless; identity must be this repo's release workflow on a v* tag) =="
cosign verify "$IMAGE" --certificate-oidc-issuer "$ISSUER" --certificate-identity-regexp "$IDENTITY" >/dev/null
echo "  ok"
echo "== SBOM attestation (CycloneDX) =="
cosign verify-attestation "$IMAGE" --type cyclonedx --certificate-oidc-issuer "$ISSUER" \
    --certificate-identity-regexp "$IDENTITY" >/dev/null
echo "  ok"
echo "== build provenance (SLSA) =="
command -v gh >/dev/null || { echo "FAIL: gh is not installed (needed for the provenance check)"; exit 3; }
gh attestation verify "oci://$IMAGE" --repo "$REPO" >/dev/null
echo "  ok"
echo "VERIFIED: $IMAGE was built by ${REPO}'s release workflow"
