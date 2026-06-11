#!/bin/bash
# Brújula Export — arranque en un comando (100% offline).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f data/brujula.duckdb ]; then
  echo "No existe data/brujula.duckdb — generando datos sintéticos de demo..."
  .venv/bin/python scripts/make_synthetic_db.py
fi

exec .venv/bin/python -m uvicorn app.main:app --port 8765
