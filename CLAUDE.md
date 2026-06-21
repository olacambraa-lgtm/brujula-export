# Brújula Export

Herramienta local y open source de selección de mercados de exportación sobre datos oficiales DataComex, con una capa de análisis provincial centrada en Aragón.

## Reglas duras

- 100 % offline en runtime: nada de CDNs, APIs externas ni llamadas LLM desde la app.
- Celdas ocultas por secreto estadístico → `NULL`, nunca 0.
- Datos 2024+ son provisionales: el flag `is_provisional` se propaga hasta la UI.
- Python del proyecto: `.venv/bin/python` (no el del sistema). Tests: `.venv/bin/pytest`.
- Frontend sin build step: `web/` se sirve tal cual; ECharts está vendorizado en `web/vendor/`.
- Spec fuente de verdad: `docs/specs/2026-06-11-brujula-export-design.md`. ADRs en `docs/adr/`.

## Comandos

- Arrancar app: `./run.sh` (uvicorn en :8765)
- Tests: `.venv/bin/pytest -q`
- ETL completo: `.venv/bin/python -m etl.download && .venv/bin/python -m etl.load`
