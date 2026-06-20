#!/usr/bin/env bash
# abrir-brujula.command — Acceso directo de escritorio para Brújula Export
# Doble clic desde Finder: abre la app en el navegador, arrancando el servidor
# si aún no está en marcha.

# ------------------------------------------------------------
# 1. Ir a la raíz del repositorio (Finder lanza .command con cwd=$HOME)
# ------------------------------------------------------------
cd "/Users/oscar-lac/Desktop/Reunión Marta Sorbed/brujula-export" || {
    echo "❌  No se encontró el repositorio en:"
    echo "    /Users/oscar-lac/Desktop/Reunión Marta Sorbed/brujula-export"
    echo "Asegúrate de que la carpeta no se ha movido y vuelve a intentarlo."
    read -r -p "Pulsa Enter para cerrar…"
    exit 1
}

PUERTO=8765
URL="http://localhost:${PUERTO}"

# ------------------------------------------------------------
# 2. Comprobar si ya hay un servidor escuchando en el puerto
# ------------------------------------------------------------
if lsof -nP -iTCP:"${PUERTO}" -sTCP:LISTEN &>/dev/null; then
    echo "✅  Brújula ya está en marcha en ${URL}"
    echo "Abriendo el navegador…"
    open "${URL}"
    exit 0
fi

# ------------------------------------------------------------
# 3. No hay servidor: lanzar un vigilante en segundo plano que
#    abra el navegador en cuanto la API responda, y luego
#    arrancar el servidor en primer plano con exec ./run.sh
# ------------------------------------------------------------
(
    # Esperar hasta que /api/meta responda (máx. ~30 s)
    for _ in $(seq 1 60); do
        if curl -s "${URL}/api/meta" &>/dev/null; then
            open "${URL}"
            break
        fi
        sleep 0.5
    done
) &

echo "🧭  Arrancando Brújula Export…"
echo "    Cierra esta ventana para parar el servidor."
echo ""

exec ./run.sh
