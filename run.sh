#!/bin/bash
# Brújula Export — arranque en un comando. La app sirve 100% offline.
#
#   ./run.sh            arranca (genera una demo sintética si no hay datos reales)
#   ./run.sh --update   actualiza antes los datos desde DataComex (necesita red)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "No existe el entorno .venv. Créalo una vez con:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

UPDATE=0
for arg in "$@"; do
  [ "$arg" = "--update" ] && UPDATE=1
done

if [ "$UPDATE" = "1" ]; then
  echo "Actualizando datos desde DataComex (usa la red)…"
  .venv/bin/python -m etl.update
fi

if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ERROR: ya hay un servidor escuchando en :8765 (¿instancia anterior?)." >&2
  echo "Para pararlo: kill \$(lsof -t -iTCP:8765 -sTCP:LISTEN)" >&2
  exit 1
fi

if [ ! -f data/brujula.duckdb ]; then
  echo "No hay datos reales todavía (data/brujula.duckdb):"
  echo "  • Datos REALES de DataComex (recomendado): ./update-data.sh"
  echo "  • Demo instantánea: genero ahora un dataset SINTÉTICO de ejemplo."
  .venv/bin/python scripts/make_synthetic_db.py
fi

exec .venv/bin/python -m uvicorn app.main:app --port 8765
