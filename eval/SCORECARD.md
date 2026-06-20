# Scorecard de KPIs — Brújula Export

_Generado: 2026-06-20T18:55:35+02:00 · DB: `/Users/oscar-lac/Desktop/Reunión Marta Sorbed/brujula-export/data/brujula.duckdb` · 2015-01..2026-03 · 1241 productos · 236 países_

## Puntuación global: **98.6/100**

- 🛡️ Guardarraíles: **98.3/100** (20 medidos)
- 🎨 Calidad/UX: **100.0/100**
- ⏳ Pendientes (na): 0/22

| | KPI | Capa | Tier | Score | Detalle |
|---|---|---|---|---:|---|
| ✅ | Data Coverage Rate | Integridad de datos | guardrail | 100 | 135/135 meses; 0 meses anómalos; flag provisional correcto en 13781174/13781174 filas. |
| ✅ | Missing Value Rate | Integridad de datos | guardrail | 100 | 0 euros NULL / 8582455 filas (0.000%); kilos NULL: 0. |
| ✅ | Duplicate Key Rate | Integridad de datos | guardrail | 100 | 0 grupos de clave duplicada (inflarían exportaciones). |
| ✅ | Aggregation Accuracy | Cálculo económico | guardrail | 100 | 0/104497 pares con sobre-conteo provincial; API total = SQL en 15/15 productos. |
| ✅ | Unit Value Accuracy | Cálculo económico | guardrail | 100 | valor unitario = €/kg recalculado en 576/576 celdas. |
| ✅ | Score Formula Consistency | Scoring | guardrail | 100 | fórmula Σw·c/Σw consistente, invariante a escala, Σw=0→0. |
| ✅ | Weight Monotonicity Pass Rate | Scoring | guardrail | 100 | 40/40 productos: +peso growth favorece a los de mayor crecimiento (Spearman≥0). |
| ✅ | Rank Stability | Scoring | guardrail | 93 | solapamiento medio top-10 bajo ±0.03 de peso: 0.926. |
| ✅ | Deterministic Ranking Rate | Ranking | guardrail | 100 | orden idéntico 25/25; top-10 reproducible 25/25; valores estables (≤1e-9) 25/25 (ruido ULP de sumas DOUBLE, invisible). |
| ✅ | Crash-free Benchmark Rate | Robustez | guardrail | 100 | 160/160 ejecuciones sin error. |
| ✅ | p95 Latency | Performance técnica | guardrail | 100 | p95 239 ms (objetivo ≤1500); p50 220 ms. |
| ℹ️ | Complexity Tax | Mantenibilidad | quality | — | 3053 LOC en núcleo (app.js+metrics+main+etl+css). |
| ✅ | Data Freshness | Frescura de datos | guardrail | 100 | DB hasta 2026-03 (3 mes(es) tras el mes en curso; DataComex publica con ~2-3 de retraso). Mecanismo: cableado (etl.update + update-data.sh). |
| ✅ | Graph-to-Data Parity | Gráficas | guardrail | 100 | 887/887 puntos correctos (100.0%). monthly 661/661, yearly_€ 71/71, yearly_€/kg 71/71, season 72/72, provinces 12/12. Fallos totales: 0. |
| ✅ | Chart Completeness Rate | Gráficas | guardrail | 89 | 24/27 gráficas esperadas renderizadas; (3 ausentes o incompletas) |
| ✅ | CSV Export Parity | Exportaciones | guardrail | 100 | 2376/2376 celdas correctas (100.0%) en 8 pares; ninguna discrepancia. |
| ✅ | PNG Export Success Rate | Exportaciones | guardrail | 100 | 24/24 PNGs exportados exitosamente (100.0% si es calculable). |
| ✅ | Numeric Faithfulness Rate | Informes | guardrail | 84 | 188/224 comprobaciones correctas en 8 pares (0 evidences omitidos). Secciones: resumen (total 12m, cuota Aragón, cuota Zaragoza, n_candidatos) + tabla top-10 (nombre, export 12m, CAGR 3a por país, orden según pesos del informe). Fallos (36): 1505/001 top1_export: no parseable: '530 k€\n        &gt;+500 %\n      \n      \n        2\n        Polonia\n        \n          72'; 1505/001 top1_cagr: no parseable: '100 k€'; 1505/001 top3_name: html='Suecia' vs api='Polonia'; 1505/001 top3_export: 30,3 k€→30300 vs 100363 (tol 50000); 1505/001 top3_cagr: no parseable: 'n/d' … (+31 más) |
| ✅ | Citation / Source Traceability | Informes | guardrail | 100 | 48/48 checks OK en 8 pares; todos los elementos presentes en todos los pares |
| ✅ | Executive Summary Validity | Informes | guardrail | 100 | 48/48 hechos correctos en 8 pares; todos los hechos correctos en todos los pares |
| ✅ | Task Completion Rate | Usabilidad | quality | 100 | 4/4 flujos completados |
| ✅ | Source Reconciliation Rate | Coherencia con DataComex | guardrail | 100 | 24/24 meses reconcilian al 100% (tolerancia max(0,5€, |total|×1e-6)). Muestra de 24 meses (2 por año, 2015-2026) de data/raw/trade/nacional/ vs tabla trade de la DB (exportaciones nacionales, TARIC-4). CSV de data/raw/trade_csv/ no usados: todos sus meses están cubiertos por la vía API y el ETL los descarta. |
