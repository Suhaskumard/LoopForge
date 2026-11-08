# Releasing

A release is a tagged commit whose gate passed on that exact commit. Nothing below is automated end to end: the last steps need a human with
repository access.

## Checklist
1. **Clean tree on the release commit**; `git status` empty.
2. `make gate18` passes (it chains every earlier gate; needs Docker and Node). Keep its output with the release notes.
3. **API snapshot**: `python scripts/export_openapi.py` produces no diff (a test enforces it). If the API changed on purpose, commit the new `docs/openapi.json`
   and check `CHANGELOG.md` lists the change (**Added/Changed/Deprecated**). Breaking changes need a MAJOR bump.
4. **Version**: edit `backend/app/version.py` (the only place), `sdk/python/pyproject.toml`, `sdk/python/loopforge_sdk/client.py` (`__version__`), `sdk/typescript/package.json`
   and `sdk/typescript/src/index.ts` (`VERSION`); a test fails if any disagrees.
5. **Changelog**: move `[Unreleased]` entries under the new version heading with the date.
6. **Schema baseline**: in `docs/schema_baselines.json` set `previous_release.head` to the head of the release you are *replacing* and `current.head` to the new head; a test checks `current.head`
   is the real Alembic head. Re-run `python scripts/upgrade_test.py` (and with `--database-url` on a scratch PostgreSQL).
7. **Upgrade guide**: add a section for this release to `docs/upgrade_guide.md` (what to set, what changes).
8. **Evaluation report**: `python benchmarks/check_report.py` must pass; for a 1.0.0 (not an rc) the report must contain *real-model* results for the release commit.
9. Tag: `git tag -s vX.Y.Z -m "LoopForge X.Y.Z"` and push the tag. `.github/workflows/release.yml` builds, signs, attests and SBOMs the image
   (**never yet run**: verify with `scripts/verify_image.sh <image@digest>` after the first tag; fix the workflow if it fails).
10. Publish the SDKs only after the server tag exists (PyPI/npm are not set up; that is a deliberate manual step, and not done for the rc).

## What blocks a 1.0.0 (as of the release candidate)
Real-model evaluation results (Phase 14 run), CI history on GitHub (the workflows have never run), a verified signed release, an external penetration test,
and at least one external user running it. The rc exists so the platform surface can be tried before those are in place.
