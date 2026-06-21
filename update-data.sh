#!/bin/bash
# Brújula Export — actualiza los datos desde DataComex en un comando.
#
#   ./update-data.sh              # hasta el último mes publicado (vía pública, sin cuenta)
#   ./update-data.sh --force      # reconstruye aunque ya esté al día
#   ./update-data.sh --from 2022-01   # primer vistazo más rápido (menos histórico)
#
# Con cuenta DataComex (añade el desglose provincial de Aragón): copia
# .env.example a .env y pega tu token; este script carga .env automáticamente.
#
# Necesita conexión a internet. La app sigue siendo 100% offline al servir; tras
# actualizar hay que reiniciar la app (./run.sh) para servir los datos nuevos.
set -euo pipefail
cd "$(dirname "$0")"

# Carga automática de credenciales DataComex desde .env (si existe), para no
# tener que exportarlas a mano.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

if [ ! -x .venv/bin/python ]; then
  echo "No existe el entorno .venv. Créalo una vez con:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

exec .venv/bin/python -m etl.update "$@"
