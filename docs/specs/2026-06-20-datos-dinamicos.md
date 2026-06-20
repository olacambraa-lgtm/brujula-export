# Datos dinámicos — actualización al último informe DataComex

Fecha: 2026-06-20. Estado: en implementación.
Supera el alcance de `2026-06-11-brujula-export-design.md` §1 («actualización
automática programada de datos» estaba *fuera — YAGNI*) por petición explícita
del usuario: publicar la herramienta en GitHub para que **cualquier usuario, de
forma independiente, mantenga sus datos al día** cuando DataComex publique un
nuevo informe mensual.

> Endurecida con una crítica adversaria multiagente (2026-06-20). Hallazgos
> incorporados: el swap atómico protege de corrupción pero **no** refresca en
> caliente; el cortocircuito debe excluir la BD sintética; el `data/raw/trade_csv`
> existente usa ficheros legacy `star_*.csv` sin manifiesto; `is_synthetic` debe
> marcarse en positivo y por defecto `FALSE` (no marcar datos reales como demo).

## 1. Problema

El ETL ya descarga de DataComex de forma dinámica, pero la herramienta *se siente*
estática al publicarla:

1. `data/` está en `.gitignore` → un clon nuevo no trae datos → `run.sh` cae en un
   **dataset sintético** sin avisarlo de forma clara.
2. No hay un **comando único** ni incremental para «traer el último informe».
3. La app no expone la **frescura** de los datos ni avisa de que son demo.
4. Nada refleja un mes nuevo cuando DataComex lo publica.

## 2. Regla dura que NO se toca

`CLAUDE.md`: **100 % offline en runtime** y la salvaguarda de demo «datos
congelados». **Servir consultas sigue 100 % offline.** La actualización es una
acción de mantenimiento **explícita, separada y opt-in** que requiere internet;
nunca se dispara al responder una consulta. No se hace scraping desde la app.

## 3. Componentes

### 3.1 `etl/update.py` — actualización incremental en un comando (núcleo)

`python -m etl.update [--db PATH] [--from YYYY-MM] [--to auto] [--mode auto|api|csv] [--force]`

1. **Estado actual** (`coverage(db)`): `min/max(period)`, nº filas y, clave,
   `is_synthetic` de la BD vigente (si existe).
2. **Delta barato (1 GET a `ObtenerPeriodos`, 35 KB)**: `latest_available` =
   `max(CodPeriodo)` filtrando **siempre `Nivel == "2"`** (mensuales; nunca fiarse
   del orden lexicográfico frente a los anuales de 4 dígitos).
3. **Cortocircuito «ya al día»**: si la BD **real** (`is_synthetic == False`) ya
   tiene `db_max == latest_available` y no se pasa `--force`, **no descarga nada**,
   imprime «Ya al día (último periodo YYYY-MM)» y sale 0. Una BD **sintética o de
   origen desconocido NUNCA cortocircuita** (evita dejar datos demo creídos reales).
4. **Limpieza del año en curso (vía CSV)**: antes de descargar por CSV, borra
   `data/raw/trade_csv/<año_de_latest_available>/` para no mezclar el legacy
   `star_*.csv` (sin manifiesto) con los nuevos `{capítulo}_{idx}.csv` → evita el
   aborto «solape entre CSVs» y el doble conteo de `etl.load`. Los años anteriores
   (completos y definitivos) se conservan intactos.
5. **Descarga del delta**: `etl.download --from <from> --to auto --mode <mode>`
   (reanudable; API salta meses ya presentes; CSV re-baja solo el año en curso).
6. **Reconstrucción + swap atómico**: `build_db(PATH.tmp)`, y **solo si la carga y
   sus validaciones pasan**, `os.replace(PATH.tmp, PATH)`. Un fallo de red o
   validación **nunca** toca la BD que ya funciona (no más `unlink` de la BD viva).
   Se limpia `PATH.tmp` (y su `.wal` si quedara) ante fallo.
7. **Parte de frescura + reinicio**: «Actualizado 2026-03 → 2026-04 (+1 mes)» o el
   cortocircuito, y SIEMPRE: «Reinicia la app (./run.sh) para servir los datos
   nuevos» — porque el swap es **invisible a un proceso ya arrancado**: la conexión
   DuckDB read-only abierta sigue leyendo el inode antiguo hasta reiniciar
   (verificado en vivo, DuckDB 1.5.3/macOS). El swap aporta atomicidad, no
   refresco en caliente.

Modo por defecto `auto`: API si hay `DATACOMEX_*`, CSV público sin cuenta si no.

### 3.2 Marca de origen en la BD (`meta_info`)

- `etl/load.py`: `meta_info(extracted_at DATE NOT NULL, is_synthetic BOOLEAN NOT NULL DEFAULT FALSE)`,
  inserta `(current_date, FALSE)`.
- `scripts/make_synthetic_db.py`: crea `meta_info` con `is_synthetic = TRUE`.
- `get_meta` añade `is_synthetic` al contrato. Lectura tolerante: tabla/columna
  ausente → **`FALSE`** (no marcar datos reales legítimos como demo). El banner se
  basa SOLO en `is_synthetic == TRUE` explícito.

### 3.3 `/api/meta` + UI de frescura (offline, sin red)

- `web/` muestra en el `meta-badge` la frescura («actualizado <extracted_at>»).
- Si `is_synthetic`, un **banner** `role="status" aria-live="polite"`, con contraste
  AA (tokens `--amber-soft`/`--amber-ink`, como `.warning`): «⚠ Datos de
  demostración. Para datos reales ejecuta `./update-data.sh` y reinicia.»
- El banner se excluye de la impresión con `@media print { .demo-banner { display:none } }`
  (cubre el Ctrl+P directo, además del `print-mode`).
- Un único comando visible al usuario no técnico: **`./update-data.sh`** (alias de
  `./run.sh --update`). `python -m etl.update` queda para la doc técnica.
- Sin diálogos modales frágiles: guía breve inline; nada de focus-trap a mano.

### 3.4 Arranque, setup y CI

- `run.sh` y `update-data.sh`: guard que detecta la ausencia de `.venv/bin/python`
  y explica cómo crearlo (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`).
- `run.sh`: mensaje claro al caer en sintético + `./run.sh --update`.
- `.github/workflows/datacomex-liveness.yml`: cron mensual + `workflow_dispatch` que
  ejecuta el **smoke test de red** (`BRUJULA_NETWORK_TESTS=1 pytest tests/test_etl.py -k red`)
  para avisar a los *forks* si la cadena CSV de DataComex se rompe. **No** distribuye
  la BD (un artefacto caduca y un clon git no lo recibe; la BD sigue en `.gitignore`).

### 3.5 Publicación

- `README.md`: setup explícito (venv), sección «Datos dinámicos / actualización»,
  expectativa de tiempo de la primera carga sin cuenta (5-8 h vía CSV) y atajo
  `./update-data.sh --from 2022-01` (~1,5 h) para un primer vistazo.
- `LICENSE`: MIT para el **código** (los datos son de DataComex y mantienen sus
  condiciones de reutilización; nota explícita en README). *Decisión del titular:
  se deja MIT como opción razonable y reversible.*
- `requirements.txt`: quitar `httpx` (no se importa en ningún `.py`).
- `docs/adr/ADR-006-datos-dinamicos.md`: frontera offline-runtime, CLI-no-botón,
  swap atómico (atomicidad ≠ refresco en caliente), `is_synthetic`, reenfoque del
  workflow a liveness-CI.
- `docs/etl-runbook.md`: `etl.update`, cortocircuito y limpieza del año en curso.

### 3.6 KPI nuevo en el evaluador

`eval/scorecard.py`: KPI determinista `data_freshness` (sin red): mide el desfase
de `max(period)` respecto al mes en curso (DataComex publica con ~2-3 meses de
retraso → hasta ~5 se considera al día) y que el pipeline de actualización está
cableado (`etl.update` importable + `update-data.sh` ejecutable).

## 4. Fuera de alcance (consciente)

- Botón «Actualizar» en la app que haga scraping (violaría la regla dura; además
  el hot-swap bajo conexión read-only viva es invisible sin reiniciar).
- Distribución de la BD por GitHub (artefacto efímero; no resuelve el clon nuevo).
- Desglose provincial sin cuenta (el formulario CSV no tiene provincia).

## 5. Criterios de éxito (verificables)

1. `etl.update` sobre la BD real (max 2026-03, `is_synthetic=False`) con
   `latest_available == 2026-03` imprime «ya al día» y **no descarga nada**
   (verificable hoy, en vivo).
2. Sobre BD **sintética** con el mismo max, `etl.update` **no** cortocircuita.
3. Swap atómico: un fallo simulado en `build_db` deja **intacta y servible** la BD
   original (test sin red).
4. `tests/test_update.py` + `pytest -q` global en verde.
5. `/api/meta` devuelve `is_synthetic`; la UI muestra el banner demo solo con BD
   sintética y no en impresión (verificado por CDP/preview).
6. `eval.scorecard` sobre la BD real sin regresión vs baseline; nuevo KPI
   `data_freshness` en verde.
7. Simulación de clon nuevo: sin `.venv`, `run.sh`/`update-data.sh` avisan con un
   mensaje claro; con sintético, la app avisa y enseña `./update-data.sh`.
