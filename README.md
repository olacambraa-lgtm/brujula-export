# Brújula Export

**Selección de mercados de exportación con datos oficiales DataComex — 100 % local, sin APIs de pago.**

Escribes un producto (texto o código TARIC) y obtienes al instante un ranking de países objetivo con scoring multicriterio transparente, fichas de mercado por país, la cuota de Aragón/Zaragoza en esa exportación y análisis ejecutivos generados con IA (pregenerados con Claude Code; cero tokens en runtime).

Demo construida para la Cámara de Comercio de Zaragoza. Pregunta a la que responde: *¿dónde debería exportar este producto?*

## Arranque

```bash
./run.sh          # → http://localhost:8765
```

Si no existe `data/brujula.duckdb`, `run.sh` genera un dataset sintético de demostración. Para datos reales, ver «Carga de datos reales».

## Arquitectura

| Pieza | Qué hace |
|---|---|
| `etl/` | Descarga DataComex (API oficial con token, o cadena CSV pública) y construye `data/brujula.duckdb` |
| `app/` | FastAPI: motor de scoring (SQL DuckDB + percentiles) y endpoints del [contrato](docs/specs/api-contract.md) |
| `web/` | SPA sin build step (vanilla JS + ECharts vendorizado) — funciona offline |
| `insights/` | Análisis ejecutivos por TARIC (markdown), pregenerados con Claude Code |
| `tests/` | pytest: métricas con valores calculados a mano, API y ETL |

Decisiones de arquitectura en `docs/adr/`. Spec completa en `docs/specs/2026-06-11-brujula-export-design.md`.

## Scoring (resumen)

Seis componentes por país, normalizados a percentil [0-100] entre los destinos candidatos del producto: tamaño (25 %), crecimiento CAGR 3a (25 %), estabilidad (15 %), valor unitario €/kg (15 %), espacio competitivo €/operador (10 %), accesibilidad UE/acuerdos (10 %). Los pesos se ajustan en vivo con sliders. Métrica incalculable → componente neutro 50 + flag visible; celdas con secreto estadístico → «n/d», nunca 0; datos 2024+ marcados como provisionales hasta la UI.

## Carga de datos reales

Requiere cuenta gratuita de DataComex (habilita la API): registro en <https://datacomex.comercio.es/User>.

```bash
export DATACOMEX_EMAIL="tu@email.com"
export DATACOMEX_PASSWORD="..."
.venv/bin/python -m etl.download --from 2015-01   # descarga reanudable
.venv/bin/python -m etl.load                       # construye data/brujula.duckdb
```

Detalle completo (tiempos, validaciones, vía CSV sin cuenta): `docs/etl-runbook.md`.

## Tests

```bash
.venv/bin/pytest -q
```

## Demo

Guion de 10-12 minutos en `docs/demo-guion.md`. Antes de la reunión: ejecutar el ETL real, regenerar los insights de `insights/`, ensayar el guion y probar «Generar informe» con Cmd+P.

## Fuente y reutilización

Datos: DataComex — Secretaría de Estado de Comercio (comercio declarado, ~98 % del total). Uso interno/demostrativo con cita de fuente y fecha, conforme a las condiciones generales de reutilización ministeriales. No redistribuir datos derivados comercialmente sin confirmación escrita del titular.
