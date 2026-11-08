#!/usr/bin/env bash
# The CLI installs into a CLEAN virtualenv and works (Phase 18): `pip install ./backend` (client only) provides
# `loopforge`; --version matches app/version.py; completions generate for every shell; the server-side commands
# (`keys`, `ops`) refuse politely without the server extra. Needs network access only if pip must download httpx.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/Scripts/python ]; then PY=$PWD/.venv/Scripts/python; else PY=${PYTHON:-$PWD/.venv/bin/python}; fi
VENV="$(mktemp -d)"; command -v cygpath >/dev/null 2>&1 && VENV="$(cygpath -m "$VENV")"
trap 'rm -rf "$VENV" backend/build backend/*.egg-info' EXIT
"$PY" -m venv "$VENV/v"
if [ -x "$VENV/v/Scripts/python" ]; then VPY="$VENV/v/Scripts/python"; BIN="$VENV/v/Scripts"; else VPY="$VENV/v/bin/python"; BIN="$VENV/v/bin"; fi
"$VPY" -m pip install -q ./backend
WANT="$("$PY" -c 'import sys; sys.path.insert(0, "backend"); from app.version import __version__; print(__version__)')"
GOT="$("$BIN/loopforge" --version)"
[ "$GOT" = "loopforge $WANT" ] || { echo "FAIL: --version says '$GOT', app/version.py says '$WANT'"; exit 1; }
for shell in bash zsh fish; do
  "$BIN/loopforge" completion "$shell" | grep -q "publish" || { echo "FAIL: $shell completion lacks the publish command"; exit 1; }
done
out="$("$BIN/loopforge" keys status 2>&1 || true)"
echo "$out" | grep -q "server extra" || { echo "FAIL: 'keys' without the server extra should explain itself, got: $out"; exit 1; }
echo "CLI INSTALL: PASS (loopforge $WANT in a clean virtualenv)"
