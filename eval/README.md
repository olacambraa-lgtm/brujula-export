# eval/ — Bucle de auto-mejora de Brújula Export

Harness de evaluación inspirado en el sistema *autoresearch* de Karpathy: en
lugar de "mejorar a ojo", se define un **evaluador** (los KPIs de la herramienta)
y se itera midiendo si cada cambio mejora —o al menos no degrada— los
**guardarraíles duros** antes de tocar UI/UX.

## Cómo se ejecuta

```bash
.venv/bin/python -m eval.scorecard            # mide y actualiza SCORECARD.md + ledger
.venv/bin/python -m eval.scorecard --json     # imprime el JSON completo
.venv/bin/python -m eval.scorecard --no-ledger
```

Tarda ~1 min (barre ~200 productos contra la DB completa de 13,7 M filas).

El harness de frontend (`eval.frontend`: KPIs de gráficas y exportaciones por Chrome
headless) requiere además, fuera de `requirements.txt`, el paquete `websockets` y, en el
sistema, Chrome/Chromium y `poppler` (`pdftoppm`).

## Salidas

Todas son generadas por la ejecución e **ignoradas por git** (cada quien las regenera sobre su propia DB):

- `SCORECARD.md` — última foto legible (puntuación global + tabla de KPIs).
- `ledger.jsonl` — histórico (una línea por ejecución) para ver la mejora en el tiempo.
- `reports/scorecard-<ts>.json` — volcado completo por ejecución.

## KPIs y cómo se miden

Fuente: el documento de KPIs del usuario (24 KPIs en 11 capas de evaluación).
Cada KPI puntúa 0–100 y se etiqueta `guardrail` (duro) o `quality` (UX/mantenibilidad).
La puntuación global pondera **80 % guardarraíles + 20 % calidad** (prioridad del usuario).

**Capa backend/datos (medida aquí, determinista):** Data Coverage, Missing Value,
Duplicate Key, Aggregation Accuracy, Unit Value Accuracy, Score Formula Consistency,
Weight Monotonicity, Rank Stability, Deterministic Ranking + Top-10 Reproducibility,
Crash-free, p95 Latency, Complexity Tax.

**Capa frontend (Fase 2, Chrome headless por CDP — pendiente):** Graph-to-Data Parity,
Chart Completeness, CSV Export Parity, PNG Export Success, Numeric Faithfulness,
Citation Traceability, Executive Summary Validity, Task Completion.

**Pendiente de datos:** Source Reconciliation (reconciliar contra `data/raw`).

## Decisiones de medición (para que el evaluador sea fiable)

- **Determinismo:** el KPI exige el mismo *ranking*, no identidad byte a byte. Las
  sumas `DOUBLE` de DuckDB son paralelas y varían a nivel ULP (≤1e-9 relativo,
  invisible a cualquier precisión mostrada); el orden y el top-10 son estables.
- **Data Coverage:** el comercio es *event-based*; un mes sin operaciones de un
  producto-país no es un dato "faltante". Se mide cobertura estructural (eje
  temporal completo, ningún mes anómalo, flag provisional correcto), no huecos de serie.
