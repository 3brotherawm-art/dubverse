#!/usr/bin/env bash
# DubVerse local run — uses the workspace venv when present.
cd "$(dirname "$0")"
if [ -x "$HOME/workspace/.venvs/whispenv/bin/python" ]; then
  PY="$HOME/workspace/.venvs/whispenv/bin/python"
else
  PY="$(command -v python3)"
fi
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
