# Brújula Export — Especificación de diseño

**Fecha:** 2026-06-11 · **Autor:** Oscar Lacambra (con Claude Code) · **Estado:** Aprobada (Gate 2)

## 1. Problema y objetivo

**Problema en una frase:** la Cámara de Comercio de Zaragoza ofrece "Selección de mercados" como servicio premium de consultoría a medida (semanas, "según presupuesto"); no existe una herramienta que responda al instante, con datos oficiales y metodología transparente, la pregunta *"¿dónde debería exportar este producto?"*.

**Objetivo:** demo local (portátil de Oscar, sin internet, sin APIs de pago) que impresione a Marta Sorbed (Directora de Internacional) en una reunión de ~15 min, como demostración de las competencias de la oferta de Analista de Mercados Internacionales: análisis de mercados, IA aplicada y visualización avanzada.

**Criterios de éxito medibles (Gate 0):**
1. Ante cualquier código TARIC-4/NC con datos (~1.200 productos), devuelve ranking de países objetivo en <2 s.
2. Arranca con un solo comando (`./run.sh`) y funciona 100 % offline.
3. El scoring es transparente: cada nota se descompone en sus componentes y los pesos son ajustables en vivo.
4. Muestra capa Aragón/Zaragoza (cuota provincial) — el dato que ESTACOM público no analiza así.
5. Incluye análisis ejecutivo IA pregenerado para ≥5 productos estrella aragoneses.
6. Suite de tests verde (`pytest`) y verificación visual del frontend.

**Alcance explícito — fuera (YAGNI):** autenticación, multiusuario, actualización automática programada de datos, despliegue en servidor, datos de servicios (solo mercancías), shipment-level/empresas nominales (DataComex no los tiene), comparativa mundial Comtrade (fase 2 si hay interés).

## 2. Usuarios y narrativa

- **Usuario primario:** Oscar conduciendo la demo.
- **Espectador objetivo:** Marta Sorbed y técnicos del área internacional — perfil técnico-consultivo, conocen ESTACOM, PIC, TechMarket y la metodología de selección de mercados.
- **Narrativa de la demo:** "esto que os enseño replica la primera capa de vuestro servicio de selección de mercados, con datos oficiales DataComex, al instante, y con las cautelas metodológicas correctas (provisionalidad, secreto estadístico, comercio declarado)".

## 3. Arquitectura

```
brujula-export/
├── etl/            Extracción DataComex → data/brujula.duckdb  (se ejecuta antes de la demo)
│   ├── download.py     descarga por la vía verificada (API con token / CSV / masiva)
│   ├── load.py         normalización + carga DuckDB (flags provisional, celdas ocultas)
│   └── nomenclature.py carga NC/TARIC con descripciones en español
├── app/            Backend FastAPI (sirve API + frontend estático)
│   ├── main.py         endpoints + static files
│   ├── metrics.py      motor de scoring (SQL DuckDB + normalización en Python)
│   └── insights.py     carga insights pregenerados (insights/*.md|json)
├── web/            Frontend SPA sin build step (HTML+CSS+JS vanilla + ECharts vendorizado)
├── insights/       Análisis ejecutivos pregenerados con Claude (por TARIC)
├── data/           brujula.duckdb + raw/ (gitignored)
└── tests/          pytest: métricas, API, integración
```

**Decisiones (ADRs en docs/adr/):** DuckDB embebido (ADR-001), frontend sin build step con ECharts local (ADR-002), scoring por percentiles con pesos ajustables (ADR-003), insights IA pregenerados — cero tokens en runtime (ADR-004).

## 4. Modelo de datos (DuckDB)

```sql
-- Hechos: comercio declarado español, mensual
CREATE TABLE trade (
  period        DATE NOT NULL,        -- primer día del mes
  flow          CHAR(1) NOT NULL,     -- 'X' export / 'M' import
  country_code  VARCHAR NOT NULL,     -- ISO-2 o código DataComex normalizado
  country_name  VARCHAR NOT NULL,
  taric         VARCHAR NOT NULL,     -- NC a 4 dígitos (TARIC-4); ampliable a 6/8
  province_code VARCHAR,              -- NULL = total nacional; '50' = Zaragoza, etc.
  euros         DOUBLE,
  kilos         DOUBLE,
  is_provisional BOOLEAN NOT NULL DEFAULT FALSE
);

-- Operadores (Datos Empresas): nº exportadores por país/producto/año
CREATE TABLE operators (
  year          INTEGER NOT NULL,
  flow          CHAR(1) NOT NULL,
  country_code  VARCHAR NOT NULL,
  taric         VARCHAR NOT NULL,
  num_operators INTEGER,              -- NULL si oculto por secreto estadístico (≤5)
  euros         DOUBLE
);

-- Nomenclatura para el buscador
CREATE TABLE nomenclature (
  taric       VARCHAR PRIMARY KEY,
  description VARCHAR NOT NULL,       -- español
  level       INTEGER NOT NULL        -- 2/4/6/8 dígitos
);

-- Países: metadatos para presentación y accesibilidad
CREATE TABLE countries (
  country_code VARCHAR PRIMARY KEY,
  name         VARCHAR,
  iso2         VARCHAR,               -- para banderas/UI
  region       VARCHAR,
  eu_member    BOOLEAN,
  access_tier  VARCHAR                -- 'UE' | 'EFTA/Acuerdo UE' | 'Resto' (mapeo estático en carga)
);
```

Reglas de oro del ETL: celda oculta por secreto estadístico → `NULL`, nunca 0; todo mes de 2024+ marcado `is_provisional` según metadato de origen; granularidad mínima TARIC-4 nacional + TARIC-4 provincial para Aragón (Zaragoza 50, Huesca 22, Teruel 44); ventana temporal objetivo: 2015-01 → último mes disponible (~2026-03).

## 5. Motor de scoring (el corazón)

Para un producto TARIC dado, se calculan métricas por país destino sobre exportaciones españolas (demanda revelada del producto español — la misma lógica que usa la metodología camera). Países candidatos: todos con exportación española > 0 en los últimos 3 años.

| Componente | Peso por defecto | Definición | Dirección |
|---|---|---|---|
| **Tamaño** | 25 % | Valor exportado (€) últimos 12 meses completos | ↑ mejor |
| **Crecimiento** | 25 % | CAGR 3 años del valor anual bruto (el vector de CAGRs del conjunto se winsoriza p5-p95 antes del ranking) | ↑ mejor |
| **Estabilidad** | 15 % | 1 − coef. de variación de los valores anuales (5 años) | ↑ mejor |
| **Valor unitario** | 15 % | €/kg últimos 12 m vs mediana de destinos (proxy de mercado premium) | ↑ mejor |
| **Espacio competitivo** | 10 % | Valor medio por operador español (€/operador, último año con dato) | ↑ mejor |
| **Accesibilidad** | 10 % | UE/EFTA/acuerdo comercial UE = score alto; resto por región | ↑ mejor |

**Normalización:** cada métrica → ranking percentil [0,100] entre los países candidatos de ESE producto. **Score final** = suma ponderada → 0-100. Los pesos se ajustan con sliders en la UI y el ranking se reordena al instante (el backend devuelve los componentes; la suma ponderada se hace en frontend).

**Salvaguardas:** país con <12 meses de datos en 5 años → flag `low_data` y penalización visible (no oculta); métrica incalculable (kilos=0, operadores NULL) → componente neutro 50 con flag `n/d`; mínimo 5 países candidatos para mostrar ranking, si no → aviso "producto con histórico insuficiente".

## 6. API (FastAPI)

| Endpoint | Devuelve |
|---|---|
| `GET /api/search?q=vino` | Lista de códigos TARIC coincidentes por texto (búsqueda en descripción, acentos normalizados) o por prefijo numérico |
| `GET /api/score/{taric}` | Por país: componentes de score, métricas brutas, flags; + metadatos del producto (descripción, total exportado, cuota Aragón) |
| `GET /api/market/{taric}/{country}` | Ficha país: serie mensual (con flag provisional), serie anual, estacionalidad media por mes, valor unitario, operadores por año, desglose provincial (top + Aragón) |
| `GET /api/insights/{taric}` | Análisis IA pregenerado (markdown) si existe, si no 404 |
| `GET /api/meta` | Rango temporal de los datos, fecha de extracción, recuentos, disclaimer metodológico |
| `GET /` | Frontend estático |

## 7. Frontend (una pantalla, tres zonas)

**Estética:** profesional tipo producto de datos (no prototipo); paleta sobria con acento granate (guiño a Cámara Zaragoza); tipografía del sistema; responsive no necesario (se presenta en portátil/proyector). Vanilla JS + ECharts 5 local. Sin build step: `web/` se sirve tal cual.

1. **Cabecera:** logo/nombre "Brújula Export", buscador con autocompletado (texto o código), badge "Datos: DataComex (S.E. Comercio) · ene 2015 – mar 2026 · datos 2024+ provisionales".
2. **Zona izquierda — Ranking:** tabla de países ordenada por score con barra de score, mini-desglose por componente (barras apiladas), flags ⚠ para `low_data`. Panel plegable de **sliders de pesos** (reordena en vivo). Botón "Informe" → vista imprimible.
3. **Zona derecha — Ficha país** (al hacer clic): serie mensual (provisionales en trazo discontinuo), estacionalidad, valor unitario vs mediana, operadores/año, **cuota de Aragón** en la exportación española del producto, y panel "Análisis del analista (IA)" si es producto estrella.

**Vista informe:** página imprimible (CSS print) con ranking top-10, gráficos clave, metodología y disclaimer — el "entregable" que demuestra la función "elaboración de informes" de la oferta.

## 8. Capa IA (pregenerada, cero tokens en runtime)

Antes de la reunión, Claude Code analiza los datos reales del DuckDB para 5-6 productos estrella aragoneses (según research: p.ej. automoción 8703/8708, porcino 0203, vino 2204, maquinaria, papel/cartón, electrodomésticos) y escribe `insights/<taric>.md`: análisis ejecutivo de ~400 palabras con estructura fija (lectura del ranking, mercado destacado, riesgo principal, recomendación accionable, cautelas metodológicas). El frontend lo muestra renderizado con etiqueta honesta: *"Generado con IA sobre los datos del panel · revisado por el analista"*.

## 9. Manejo de errores

- Búsqueda sin resultados → sugerencias por similitud (trigram) + ejemplo de uso.
- TARIC válido sin datos suficientes → mensaje claro con el umbral no alcanzado.
- Celdas de secreto estadístico → "n/d (secreto estadístico)" nunca 0.
- Meses provisionales siempre marcados visualmente.
- Backend caído / fetch fallido → toast con instrucción de reinicio (`./run.sh`).
- ETL: reintentos con backoff, validación de filas cargadas vs esperadas, abortar si descarga incompleta (no demo con datos a medias).

## 10. Testing

- **Unit (pytest):** métricas de scoring sobre fixture sintética con valores conocidos a mano (CAGR, CV, percentiles, winsorización, casos NULL/secreto estadístico).
- **API (httpx TestClient):** shape y códigos de respuesta de todos los endpoints sobre DuckDB de fixture.
- **Integración:** ETL de carga sobre CSVs de muestra → DuckDB → score end-to-end.
- **Validación de datos reales:** totales anuales de 2-3 series contrastados contra cifras publicadas (DataComex web) con tolerancia.
- **Visual:** arranque real + capturas con preview antes de dar por terminado.

## 11. Guion de demo (10-12 min) — entregable docs/demo-guion.md

1. (1 min) Contexto: "datos oficiales DataComex, local, metodología transparente".
2. (3 min) Producto estrella precargado (vino 2204): ranking, desglose del score, ficha de un país, cuota Aragón.
3. (2 min) Sliders: "si priorizamos crecimiento sobre tamaño, el ranking cambia así" — demuestra criterio analítico.
4. (2 min) **Momento wow:** "Marta, dime un producto de cualquier empresa que asesores" → búsqueda libre → ranking al instante.
5. (2 min) Panel IA + botón Informe: el entregable de consultoría en un clic.
6. (1 min) Cierre honesto: limitaciones (comercio declarado, sin nombres de empresas) y roadmap natural (Comtrade, alertas, TechMarket-like).

## 12. Riesgos

| Riesgo | Mitigación |
|---|---|
| Vía de extracción DataComex inestable o con login | Research con verificación empírica ANTES de implementar ETL; fallback en cascada API → CSV consulta → granularidad TARIC-4 |
| Volumen de datos (TARIC-8 × país × mes × provincia es enorme) | Granularidad TARIC-4; provincial solo Aragón; DuckDB maneja decenas de millones de filas sin problema |
| Demo falla en vivo | 100 % offline, un comando, datos congelados, tests verdes, ensayo previo |
| Zona gris legal de reutilización | Uso interno/demo no comercial + cita de fuente y fecha en la UI (cumple condiciones ministeriales de reutilización) |
