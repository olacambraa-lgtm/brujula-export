#!/bin/bash
# Brújula Export — arranque en un comando (100% offline).
set -euo pipefail
cd "$(dirname "$0")"

if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: ya hay un servidor escuchando en :8765 (¿instancia anterior?)." >&2
  echo "Para pararlo: kill \$(lsof -t -iTCP:8765 -sTCP:LISTEN)" >&2
  exit 1
fi

if [ ! -f data/brujula.duckdb ]; then
  echo "No existe data/brujula.duckdb — generando datos sintéticos de demo..."
  .venv/bin/python scripts/make_synthetic_db.py
fi

exec .venv/bin/python -m uvicorn app.main:app --port 8765
