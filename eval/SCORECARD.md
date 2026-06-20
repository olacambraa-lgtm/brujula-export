# Scorecard de KPIs — Brújula Export

_Generado: 2026-06-20T16:54:37+02:00 · DB: `/Users/oscar-lac/Desktop/Reunión Marta Sorbed/brujula-export/data/brujula.duckdb` · 2015-01..2026-03 · 1241 productos · 236 países_

## Puntuación global: **99.3/100**

- 🛡️ Guardarraíles: **99.3/100** (11 medidos)
- 🎨 Calidad/UX: _sin medir_
- ⏳ Pendientes (na): 9/21

| | KPI | Capa | Tier | Score | Detalle |
|---|---|---|---|---:|---|
| ✅ | Data Coverage Rate | Integridad de datos | guardrail | 100 | 135/135 meses; 0 meses anómalos; flag provisional correcto en 13781174/13781174 filas. |
| ✅ | Missing Value Rate | Integridad de datos | guardrail | 100 | 0 euros NULL / 8582455 filas (0.000%); kilos NULL: 0. |
| ✅ | Duplicate Key Rate | Integridad de datos | guardrail | 100 | 0 grupos de clave duplicada (inflarían exportaciones). |
| ✅ | Aggregation Accuracy | Cálculo económico | guardrail | 100 | 0/104497 pares con sobre-conteo provincial; API total = SQL en 15/15 productos. |
| ✅ | Unit Value Accuracy | Cálculo económico | guardrail | 100 | valor unitario = €/kg recalculado en 576/576 celdas. |
| ✅ | Score Formula Consistency | Scoring | guardrail | 100 | fórmula Σw·c/Σw consistente, invariante a escala, Σw=0→0. |
| ✅ | Weight Monotonicity Pass Rate | Scoring | guardrail | 100 | 40/40 productos: +peso growth favorece a los de mayor crecimiento (Spearman≥0). |
| ✅ | Rank Stability | Scoring | guardrail | 92 | solapamiento medio top-10 bajo ±0.03 de peso: 0.925. |
| ✅ | Deterministic Ranking Rate | Ranking | guardrail | 100 | orden idéntico 25/25; top-10 reproducible 25/25; valores estables (≤1e-9) 25/25 (ruido ULP de sumas DOUBLE, invisible). |
| ✅ | Crash-free Benchmark Rate | Robustez | guardrail | 100 | 159/159 ejecuciones sin error. |
| ✅ | p95 Latency | Performance técnica | guardrail | 100 | p95 231 ms (objetivo ≤1500); p50 206 ms. |
| ℹ️ | Complexity Tax | Mantenibilidad | quality | — | 2993 LOC en núcleo (app.js+metrics+main+etl+css). |
| ⏳ | Graph-to-Data Parity | Gráficas | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | Chart Completeness Rate | Gráficas | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | CSV Export Parity | Exportaciones | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | PNG Export Success Rate | Exportaciones | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | Numeric Faithfulness Rate | Informes | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | Citation / Source Traceability | Informes | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | Executive Summary Validity | Informes | guardrail | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | Task Completion Rate | Usabilidad | quality | — | pendiente Fase 2 (Chrome headless por CDP) |
| ⏳ | Source Reconciliation Rate | Coherencia con DataComex | guardrail | — | pendiente: reconciliar contra data/raw |
