# ADR-001: DuckDB embebido como motor de datos

**Estado:** Aceptada · 2026-06-11

## Contexto
La app debe correr 100 % local y offline, consultar millones de filas (TARIC-4 × país × mes × 11 años + provincial Aragón) con agregaciones analíticas en <2 s, y arrancar sin servicios externos.

## Decisión
DuckDB embebido (fichero único `data/brujula.duckdb`), consultado desde FastAPI con conexión read-only.

## Alternativas descartadas
- **SQLite:** sin optimizador columnar; las agregaciones analíticas sobre millones de filas son un orden de magnitud más lentas.
- **PostgreSQL:** requiere servicio corriendo — fricción y riesgo en demo.
- **Parquet + pandas en memoria:** sin SQL declarativo para el motor de métricas; más código y más RAM.

## Consecuencias
Un solo fichero portable, consultas OLAP rápidas, cero administración. La escritura es de un solo proceso, irrelevante aquí (ETL escribe una vez, app lee).
