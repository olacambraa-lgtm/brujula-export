# ADR-006: Datos dinámicos — actualización al último informe DataComex sin romper la regla offline

**Estado:** Aceptada · 2026-06-20

## Contexto
La herramienta se publica en GitHub para que cualquiera la use. `data/` está en `.gitignore` (la base ocupa varios GB y cambia cada mes), así que un clon nuevo no trae datos y `run.sh` cae en un dataset sintético. El ETL ya descarga de DataComex de forma dinámica, pero no había (a) un comando único e incremental para «traer el último informe», (b) forma de distinguir datos reales de datos sintéticos en la UI, ni (c) automatización. A la vez, la regla dura del proyecto es **100 % offline en runtime** (sin CDNs, APIs externas ni LLM desde la app), pensada para que la herramienta funcione sin red y de forma reproducible.

## Decisión
La actualización es una **acción de mantenimiento explícita, separada y opt-in** que sí usa la red; **servir consultas sigue 100 % offline**. En concreto:

- `etl/update.py` (`python -m etl.update`, o `./update-data.sh`): detección de delta barata (1 GET a `ObtenerPeriodos`, filtrando Nivel 2), **cortocircuito «ya al día»** si la BD **real** ya tiene el último periodo —una BD sintética nunca cortocircuita—, descarga incremental, y **carga atómica** (build en `PATH.tmp` → validar → `os.replace`). Un fallo de red o validación **nunca corrompe** la BD que ya funciona. Antes de re-descargar el año en curso por CSV, purga ese año en `data/raw/trade_csv/` para no mezclar descargas previas (p.ej. `star_*.csv` sin manifiesto) → evita solapes/duplicados en la carga. La vía pública CSV (sin cuenta) es el camino primario; con cuenta se añade el desglose provincial.
- Marca de origen `meta_info.is_synthetic` (real = `FALSE`, sintético = `TRUE`; ausente —BDs reales antiguas, fixture de tests— = trátese como **real** `FALSE`, para no marcar como sintéticos datos legítimos; el banner se activa solo con `TRUE` explícito). `/api/meta` la expone y la UI muestra la **frescura** y, si es demo, un **banner `role=status`** con el comando de actualización. La app **no** consulta «¿hay datos nuevos?» en runtime (sería red): ese chequeo vive en `etl.update`.
- Automatización (opt-in, sin secretos): `.github/workflows/datacomex-liveness.yml` (cron mensual + manual) ejecuta el **smoke test de red** de la cadena de extracción para avisar a los *forks* si DataComex cambia y la rompe. No distribuye datos: la primera descarga completa por CSV tarda horas (no cabe en el límite de un job) y un artefacto de Actions no llega a un clon git; cada usuario actualiza localmente con `./update-data.sh`.

## Alternativas descartadas
- **Botón «Actualizar» dentro de la app que haga scraping de DataComex:** violaría la regla offline-runtime; además el hot-swap de la BD bajo una conexión read-only viva es frágil. El swap atómico de `etl.update` es seguro pero requiere reiniciar la app para servir lo nuevo. Queda como posible trabajo futuro deliberado.
- **Commitear la BD al repo / un endpoint de auto-actualización:** la BD es demasiado grande y volátil; rompería la separación servir-offline / actualizar-online.
- **Sustituir el cortocircuito por descargar siempre:** re-bajaría el año en curso por CSV en cada ejecución sin necesidad.

## Consecuencias
- Cualquier usuario mantiene sus datos al día con un comando; cuando DataComex publica un mes nuevo, se refleja tras `etl.update` + reiniciar.
- La regla offline-runtime se preserva intacta y la herramienta sigue siendo reproducible sin red.
- Un fallo de actualización degrada con elegancia: la BD vigente queda intacta y servible.
- Un KPI **Data Freshness** en `eval/scorecard.py` vigila el desfase y el cableado del mecanismo.
