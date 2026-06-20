# Runbook del ETL — Brújula Export

Fecha: 2026-06-11. Vías verificadas empíricamente (ver
`docs/research/datacomex-extraccion.md` y los hallazgos nuevos de la §3).

## 0. Resumen de comandos

```bash
# Actualización en un comando (descarga incremental + reconstrucción) — datos dinámicos
./update-data.sh                     # = python -m etl.update  (hasta el último mes publicado)
./update-data.sh --force             # reconstruye aunque ya esté al día

# O por fases:
.venv/bin/python -m etl.download --from 2015-01 --to auto --mode auto   # API si hay credenciales, CSV si no
.venv/bin/python -m etl.load --db data/brujula.duckdb                   # reconstruye el DuckDB

# Tests del ETL (offline); con red: BRUJULA_NETWORK_TESTS=1
.venv/bin/pytest tests/test_etl.py tests/test_update.py -q
```

### Actualización periódica (datos dinámicos)

`etl.update` es el flujo recomendado para mantener los datos al día (ver
`docs/specs/2026-06-20-datos-dinamicos.md` y `docs/adr/ADR-006`). Imprime la
cobertura actual, hace un **GET barato** a `ObtenerPeriodos` para conocer el último
periodo publicado, **cortocircuita** si la BD real ya lo tiene (no descarga nada),
descarga **solo el delta** (idempotente) y reconstruye con **swap atómico**
(build en `.tmp` → validar → `os.replace`; un fallo deja intacta la BD vigente).
DataComex publica con ~2-3 meses de retraso; cuando aparece un mes nuevo, basta
re-ejecutar y reiniciar la app. Una BD **sintética** nunca cortocircuita (se
reconstruiría a datos reales en cuanto haya red).

Ficheros generados:

- `data/raw/masters/*.json` — 5 maestras (siempre se refrescan).
- `data/raw/trade/{nacional,prov50,prov22,prov44}/YYYYMM.json` — vía API.
- `data/raw/trade_csv/{año}/{capítulo}_{nn}.csv` — vía CSV pública.
- `data/raw/failed.log` — meses/lotes fallidos (la descarga continúa).

## 1. Descarga completa con cuenta API (vía preferida)

1. **Registro gratuito**: formulario en `https://datacomex.comercio.es/User`
   (nombre, email, contraseña). La cuenta habilita la API y la Descarga Masiva.
2. **Variables de entorno**:
   ```bash
   export DATACOMEX_EMAIL="tu@email.com"
   export DATACOMEX_PASSWORD="tu-contraseña"
   .venv/bin/python -m etl.download            # mode auto → api
   ```
3. **Qué hace**: login JWT (`POST IniciarSesion`) y, por cada mes del rango,
   4 llamadas a `ObtenerDatos` con `ta=AT4&pa=ALL&f=I/E`: nacional (sin `pr`)
   y provincial Zaragoza/Huesca/Teruel (`pr=50|22|44`). AT4 obliga a UN
   periodo por llamada.
4. **Tiempo estimado**: 135 meses × 4 objetivos = ~540 llamadas; con pausa
   cortés de 0,7 s y latencia normal, **30–60 min**.
5. **Reanudación**: la descarga es idempotente. Si un fichero
   `YYYYMM.json` existe y contiene una lista JSON válida, se salta. Basta
   relanzar el mismo comando tras un corte.
6. **Límite de la API**: ~1M filas por llamada; si responde `null`, el ETL
   reintenta el mes con `f=E` y `f=I` por separado; si persiste, lo apunta en
   `data/raw/failed.log` y sigue.

## 2. Qué se puede sin cuenta

- **Las 5 maestras** (países, provincias, periodos, tarics, flujos): abiertas
  sin token en `https://comercio.serviciosmin.gob.es/DatacomexAPI/Obtener*`.
- **Datos nacionales mensuales a TARIC-4 por país**, vía la cadena CSV
  pública (`--mode csv`). Verificado con datos reales: la consulta
  12 meses × 291 países × 4 códigos TARIC-4 devuelve el detalle completo.
- **NO se puede sin cuenta**: el desglose **provincial** (el formulario
  público no tiene la dimensión provincia; solo la API la expone) ni el
  módulo Datos Empresas (operadores) — por eso `operators` queda vacía y el
  backend degrada ese componente a neutro.

Tiempo estimado de la vía CSV completa: 471 lotes/año completo + 152 para
2026 ⇒ **~5.300 llamadas** para 2015-01→2026-03; a ~3-5 s por lote, **5–8 h**.
Reanudable: cada lote se guarda en su propio fichero y se salta si ya existe.

## 3. Hallazgos de la exploración del formulario CSV/TARIC (2026-06-11)

Todo verificado con peticiones reales contra `https://datacomex.comercio.es`:

- **Cadena obligatoria** (misma cookie ASP.NET): `GET /Data/Index` →
  `POST /Data/ResultQueryData` (x-www-form-urlencoded,
  `X-Requested-With: XMLHttpRequest`) → `GET /Data/CsvList`.
  `chk_export=on` **y** `chk_import=on` siempre (con uno solo, CsvList da 500).
- **Selección TARIC por lotes — conseguida**: con `jerarquiaTaric=1` el árbol
  plano de 4 dígitos (`POST /Data/Taric` con `level=2&parent=&jerarquia=1`
  devuelve los 1.728 nodos) y los checkboxes se envían como
  `[Taric].&[2204]=on` (el `&` es literal). Los países van como
  `[PaisOrigen].[001 Francia]=on` (nombres exactos parseados de Index, con
  entidades HTML decodificadas; UTF-8 aceptado). Periodos: `year_[202401]=on`
  mensual, `year_[2024]=on` anual (fila agregada con mes vacío).
- **Límite de combinaciones ≈ 30.000**: el producto
  flujos(2) × periodos × países × tarics debe quedar bajo ~30.000
  (verificado: 29.100 OK, 32.010 rechazado). Si se excede, el POST devuelve
  200 con el mensaje «la selección es demasiado amplia y excedería el límite
  de filas». El ETL usa lotes de capítulo TARIC-2 troceados (4 códigos × 12
  meses × 291 países = 27.936) con margen de seguridad de 28.000.
- **PELIGRO — caché de sesión**: tras un POST rechazado, `GET /Data/CsvList`
  devuelve **el resultado de la consulta anterior** de la sesión (CSV
  obsoleto, HTTP 200). El cliente verifica que los códigos TARIC del CSV
  pertenecen a la selección pedida y aborta si no (CsvChainError).
- **Sin selección de país** el resultado es la fila agregada
  `"000";"Total País"` (sin detalle por país): inútil para el ranking.
- **CSV**: latin-1, `;`, decimal coma, CRLF, todas las celdas entrecomilladas
  y `;` final. Columnas: `flujo_codigo;flujo_nombre;periodo_anio;periodo_mes;
  periodo_provisional;pais_codigo;pais_nombre;taric;euros;kilos`.
  `periodo_provisional`: `D` definitivo / `P` provisional. Celda sin dato →
  vacía (se carga como NULL, nunca 0). País sin comercio → fila ausente.

## 4. Carga y validaciones post-carga

`python -m etl.load` reconstruye `data/brujula.duckdb` desde cero:

- `trade`: API (nacional + provincial) y CSV (solo nacional). Si un mes
  nacional existe por la vía API, los CSV de ese mes se ignoran (sin
  duplicados). Flujo `E→X`, `I→M`; TARIC agregado a 4 dígitos (SUM conserva
  NULL si todas las celdas son NULL); agrupaciones no-país (Total Mundo,
  avituallamiento, pesca, zonas) excluidas vía `etl/static/countries_meta.csv`.
- `countries`: 265 países de la maestra enriquecidos con iso2/región/tier.
- `nomenclature`: descripciones en español de niveles 2 y 4 dígitos (1.827
  códigos), sin el código repetido al inicio.
- `operators`: creada y vacía (sin vía verificada para Datos Empresas).

Validaciones automáticas (la carga **falla ruidosamente** si no se cumplen):

1. `countries` entre 200 y 300 filas y `nomenclature` ≥ 1.200 códigos.
2. `trade` > 0 filas si hay raw de comercio presente.
3. Exportación nacional de los últimos 12 meses del TARIC 2204 (vino) > 0.

Comprobaciones manuales recomendadas tras una carga completa:

```sql
-- Rango temporal y huecos
SELECT min(period), max(period), count(DISTINCT period) FROM trade;
-- Total anual nacional contra la web de DataComex (tolerancia <1%)
SELECT year(period), round(sum(euros)/1e9,1) AS mm_eur
FROM trade WHERE flow='X' AND province_code IS NULL GROUP BY 1 ORDER BY 1;
-- Cuota Aragón plausible (~3-4% de la exportación española)
SELECT sum(euros) FILTER (province_code IN ('50','22','44'))
     / sum(euros) FILTER (province_code IS NULL)
FROM trade WHERE flow='X' AND period >= '2025-01-01';
```

## 5. Supuesto pendiente de verificar con cuenta real

La forma exacta del JSON de `ObtenerDatos` (campos `flujo, periodo, pais,
id_pais, prov, id_prov, taric, euros, kilos, mensaje`) procede del research;
sin credenciales no se pudo capturar una respuesta real con datos. El mapeo
de `etl/load.py` es tolerante (flujo por inicial E/I, provisionalidad por
`mensaje` con fallback a la maestra de periodos, `id_pais` con relleno de
ceros), pero conviene revisar el primer `YYYYMM.json` descargado y ajustar
`api_rows()` si algún nombre de campo difiere.

## Salvaguardas añadidas tras la review (2026-06-12)

- **Solapes CSV↔CSV**: `etl.load` aborta con mensaje claro si dos CSVs cubren la misma celda (periodo, flujo, país, taric4). Caso típico: `star_*.csv` (descarga acotada de productos estrella) + descarga completa posterior → eliminar los `star_*.csv` antes de recargar.
- **CSV de 0 bytes**: la descarga escribe de forma atómica (`.tmp` + rename) y la carga aborta nombrando el fichero corrupto.
- **Anti-stale reforzado**: la cadena CSV verifica que tarics Y periodos devueltos coinciden con lo pedido (la caché de sesión de CsvList puede devolver la consulta anterior).
- **Reanudación con rango distinto**: cada directorio de año guarda un `months.json`; si el rango pedido cambia (p.ej. `--to auto` avanzó un mes), el año se vuelve a descargar entero.
- **Mes API vacío (`[]`)**: no se persiste (se registra en `failed.log`) para no suprimir datos CSV del mismo mes en el dedup.
- **Flag provisional**: la columna `periodo_provisional` del CSV del portal es inservible (marca 'D' incluso 2026); manda la maestra de periodos (`DatosDefinitivos`).

## Limitaciones conocidas (decisión consciente, no bugs pendientes)

- `size_eur_12m` y las series anuales tratan «sin filas» y «filas todas NULL» igual (0/omisión). En datos Comex reales no se ha observado ni una celda NULL en 526k filas (el secreto estadístico aplica al módulo Empresas, no al comercio declarado), así que no compensa la complejidad de distinguirlos. Si el módulo Empresas se integra algún día, revisar.
- `_to_float` interpreta '1.234' (punto de miles sin coma) como 1.234. El CSV real siempre trae coma decimal; solo afectaría a un formato que el portal no emite.
