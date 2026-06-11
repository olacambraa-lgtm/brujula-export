# DataComex — vías de extracción verificadas empíricamente (2026-06-11)

Resultado del research multi-agente con verificación por curl. Todo lo de abajo se comprobó con peticiones reales.

## Vía A — API oficial (PREFERIDA; requiere cuenta gratuita)

- **Registro:** formulario en `https://datacomex.comercio.es/User` (POST `/User/Register`: nombre, email, contraseña). La misma cuenta habilita la Descarga Masiva del portal.
- **Token:** `POST https://comercio.serviciosmin.gob.es/DatacomexAPI/IniciarSesion` con JSON `{"email": "...", "password": "..."}` → JWT. (Verificado vivo: credenciales falsas → 403 "Los datos introducidos Usuario/Pass son incorrectos".)
- **Datos:** `GET https://comercio.serviciosmin.gob.es/DatacomexAPI/ObtenerDatos?access_token=...&f=E&pe=202501&pa=ALL&ta=AT4&pr=50`
  - `f` = I | E | I/E · `pe` = `2021` | `202101` | `LastY` | `LastM` | `ALL` | `ALLM` | `D2018` (desde) | `H2019` (hasta); múltiples separados por `.`
  - `pa` = código país (`001` Francia) | `ALL` | `TOTAL` · `ta` = código | `AT2` | `AT4` | `AT6` | `TOTAL` | `H<taric>` · `pr` = código provincia | `ALL`
  - Respuesta JSON: `flujo, periodo, pais, id_pais, prov, id_prov, taric, euros, kilos, mensaje` (provisional/definitivo).
  - **Límites:** ~1.000.000 filas por llamada; `ta=AT4` obliga a UN periodo por llamada; `ta=AT6` obliga a un periodo y un país; si se supera devuelve `null` sin error. Token también por cabecera `Authorization: Bearer`.
  - Sin token: 401 (verificado). Doc oficial: `https://datacomex.comercio.es/Data/AyudaApi`.
- **Plan de paginación para el ETL:** nacional → 1 llamada por mes (`pe=YYYYMM&ta=AT4&pa=ALL`, ~135 meses 2015→2026-03); provincial Aragón → 1 llamada por mes × provincia (`pr=50|22|44`).

## Vía B — Cadena CSV pública (SIN cuenta; sin provincia)

Tres pasos con la MISMA cookie ASP.NET (verificado 2 veces con datos reales):
1. `GET https://datacomex.comercio.es/Data/Index` → captura cookie de sesión.
2. `POST https://datacomex.comercio.es/Data/ResultQueryData` (x-www-form-urlencoded, cabecera `X-Requested-With: XMLHttpRequest`) con `chk_export=on`, `chk_import=on`, `year_[202501]=on`, `[PaisOrigen].[001 Francia]=on`...
3. `GET https://datacomex.comercio.es/Data/CsvList` → CSV.

**Reglas empíricas críticas:**
- Marcar SIEMPRE ambos flujos (`chk_export` Y `chk_import`); con uno solo → POST 200 pero CsvList 500. Filtrar flujo en el ETL.
- CsvList "en frío" (sin POST previo) → HTTP 500. La cadena es obligatoria.
- CSV: ISO-8859-1/latin-1, separador `;`, decimal con coma, CRLF. Columnas: `flujo_codigo;flujo_nombre;periodo_anio;periodo_mes;periodo_provisional;pais_codigo;pais_nombre;taric;euros;kilos`. `periodo_provisional`: `D` definitivo / `P` provisional.
- El formulario NO tiene dimensión provincia (solo la API la tiene). Una consulta por sesión.
- La selección TARIC del formulario usa un árbol AJAX (`POST /Data/Taric` con level/parent/jerarquia); los nombres de checkbox de país van como `[PaisOrigen].[<código> <nombre>]` con entidades HTML.

## Tablas maestras — ABIERTAS sin token (verificadas 5/5, JSON)

| Endpoint | Contenido | Tamaño |
|---|---|---|
| `https://comercio.serviciosmin.gob.es/DatacomexAPI/ObtenerPaises` | `[{"Id":"001","Pais":"Francia","UE":"UE27"},...]` ~250 países | 16 KB |
| `.../ObtenerProvincias` | ~55 provincias con códigos (Zaragoza 50, Huesca 22, Teruel 44) | 2,4 KB |
| `.../ObtenerPeriodos` | Años y meses 1995→2026-03, con flag `DatosDefinitivos` | 35 KB |
| `.../ObtenerTarics` | **Nomenclatura TARIC completa y jerárquica EN ESPAÑOL**: `[{"Taric":"00","TaricPadre":"","Nombre":"...","Nivel":"1"},...]` | 7,5 MB |
| `.../ObtenerFlujos` | I/E | 69 B |

→ `ObtenerTarics` es la fuente del buscador de productos (coincide 1:1 con los códigos de los datos).

## Descartado

- **Descarga Masiva / Metadatos:** requieren login; URL inyectada tras autenticación (no capturable sin cuenta). Útil en el futuro con cuenta.
- **Power BI embebido:** solo visualización.
- **XHR internos** (`BuscarTree`, `CallApi`): frágiles (500/411 según parámetros), no usar.
- **datacomex_v6:** retirado.
- **Módulo Datos Empresas (operadores):** sin vía API verificada; el cubo web `/Metadata/Empresas` existe pero no se verificó export público. → El componente "espacio competitivo" del scoring degrada a neutro 50 + flag `nd_operators` si no hay datos; intentar export del cubo Empresas con tiempo acotado.

## Nomenclatura alternativa (backup del buscador)

AEAT publica `CN2026_Structure.xlsx` (~850 KB, 15.072 filas, español, sin login) en `https://sede.agenciatributaria.gob.es/Sede/estadisticas/estadisticas-comercio-exterior/nomenclatura-combinada-ano.html` — ojo: el esquema de columnas cambia entre años (parser por cabecera, no por posición). Eurostat RAMON está muerto (404). CIRCABC requiere EU Login para el listado.
