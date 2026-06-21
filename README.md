# Brújula Export

**Selección de mercados de exportación con datos oficiales DataComex — 100 % local, sin APIs de pago.**

Escribes un producto (texto o código TARIC) y la herramienta te da un ranking de países con scoring multicriterio, fichas de mercado y la cuota de Aragón/Zaragoza en esa exportación. Genera también un informe imprimible (resumen ejecutivo con los top-5 mercados y cifras clave) que puedes pegar directamente como contexto en cualquier IA externa. Además, todas las gráficas generadas de cada país del score, son exportables a formato PNG y CSV, para poder utilizarlos en presentaciones, archivos Excel, etc.

> *¿Dónde debería exportar este producto?* — eso es lo que responde.

<br>
<div align="center">
  

[![Liveness DataComex](https://github.com/olacambraa-lgtm/brujula-export/actions/workflows/datacomex-liveness.yml/badge.svg)](https://github.com/olacambraa-lgtm/brujula-export/actions/workflows/datacomex-liveness.yml)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-blue?labelColor=0d1117)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11+-38bdf8?logo=python&logoColor=white&labelColor=0d1117)
![DuckDB](https://img.shields.io/badge/DuckDB-local-f59e0b?logo=duckdb&logoColor=white&labelColor=0d1117)
![FastAPI](https://img.shields.io/badge/FastAPI-scoring-a78bfa?logo=fastapi&logoColor=white&labelColor=0d1117)
![Offline](https://img.shields.io/badge/100%25-offline-10b981?labelColor=0d1117)

</div>

<br>

<p align="center">
  <img src="docs/assets/arch.svg" alt="Arquitectura de Brújula Export: ETL → DuckDB → FastAPI → SPA Web" width="820"/>
</p>

---

## En un vistazo

| | |
|---|---|
| **100 % local** | Funciona sin conexión; la única acción que usa la red es actualizar los datos, y es manual |
| **Datos oficiales** | DataComex — Secretaría de Estado de Comercio · comercio declarado, ~98 % del total |
| **Scoring transparente** | 6 criterios con pesos ajustables en vivo; normalizados a percentil entre países candidatos |
| **Cuota Aragón/Zaragoza** | Desglose provincial disponible con cuenta gratuita de DataComex |
| **Datos siempre al día** | Ejecutas la actualización cuando quieras y la app refleja lo último publicado |
| **Sin build step** | SPA vanilla JS + ECharts vendorizado; funciona desde cualquier navegador moderno |

---


<img width="2828" height="1622" alt="image" src="https://github.com/user-attachments/assets/486eca2e-f93d-4e6b-a411-989c0a62b5e6" />


---

## Instalación paso a paso

> Esta guía está pensada para cualquier persona, aunque no tengas experiencia con programación ni con el Terminal. Sigue los pasos en orden y tendrás la herramienta funcionando en tu ordenador.

---

### Antes de empezar

Necesitas tener instalado **Python 3.11 o superior**. Para comprobarlo, abre el Terminal y escribe:

```bash
python3 --version
```

Si ves un número como `Python 3.11.x` o superior, estás listo. Si no tienes Python, descárgalo desde [python.org](https://www.python.org/downloads/).

También necesitarás una **cuenta gratuita en DataComex** para descargar los datos oficiales. Puedes registrarte en <https://datacomex.comercio.es/User> — lleva menos de 5 minutos.

---

### ¿Cómo abro el Terminal?

**En Mac:** Pulsa `Cmd ⌘ + Espacio`, escribe `Terminal` y pulsa Intro.

Verás una ventana con texto. Es normal. Aquí pegarás los comandos de esta guía.

> **¿Qué es un comando?** Es una instrucción de texto que le das al ordenador. Copia el bloque de texto, pégalo en el Terminal con `Cmd ⌘ + V` y pulsa **Intro** para ejecutarlo.

---

### Paso 1 — Descarga el proyecto

Copia este bloque completo, pégalo en el Terminal y pulsa Intro:

```bash
git clone https://github.com/olacambraa-lgtm/brujula-export
cd brujula-export
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

El Terminal mostrará texto durante un par de minutos mientras descarga e instala todo. Espera a que aparezca de nuevo el símbolo `$` — eso significa que ha terminado.

---

### Paso 2 — Configura tus credenciales de DataComex

La herramienta necesita conectarse a DataComex para descargar los datos. Tienes dos formas de hacerlo. **Elige solo una.**

> ⚠️ **Importante:** usa el token **o** el correo y contraseña, nunca los dos a la vez. Si rellenas ambos, el sistema puede fallar o comportarse de forma inesperada. Cuando dudes, usa el token: es más fiable.

---

#### Opción A — Token (recomendado)

El token es una clave larga que obtienes desde tu cuenta. Es más seguro y no caduca.

1. Inicia sesión en [datacomex.comercio.es](https://datacomex.comercio.es)
2. Ve a la sección **«Ayuda API»** y pulsa el botón **«Obtener Token»**
3. Copia el texto largo que aparece (empieza por `eyJ…`)
4. En el Terminal, ejecuta:
   ```bash
   cp .env.example .env
   nano .env
   ```
5. Dentro del editor, busca la línea que empieza por `# DATACOMEX_TOKEN=`. Quita el `#` del principio y pega tu token al final:
   ```
   DATACOMEX_TOKEN=eyJhbGciOi…tu-token-completo-aquí
   ```
   Las líneas de `DATACOMEX_EMAIL` y `DATACOMEX_PASSWORD` deben seguir con `#` delante (inactivas).
6. Guarda y cierra: pulsa `Ctrl+O` → Intro → `Ctrl+X`

---

#### Opción B — Correo y contraseña

Si prefieres usar directamente tus datos de acceso a DataComex:

1. En el Terminal, ejecuta:
   ```bash
   cp .env.example .env
   nano .env
   ```
2. Rellena tus datos en las dos líneas siguientes. Si tu contraseña tiene caracteres especiales (`!`, `$`, `&`…), ponla entre comillas dobles:
   ```
   DATACOMEX_EMAIL="tucorreo@ejemplo.com"
   DATACOMEX_PASSWORD="tucontraseña"
   ```
   La línea de `DATACOMEX_TOKEN` debe seguir con `#` delante (inactiva).
3. Guarda y cierra: pulsa `Ctrl+O` → Intro → `Ctrl+X`

> **¿El sistema rechaza tus credenciales?** Si al ejecutar el paso siguiente aparece el error `Credenciales DataComex rechazadas`, el problema suele estar en la contraseña. En ese caso, cambia a la Opción A (token): abre de nuevo el archivo con `nano .env`, añade `#` al inicio de las líneas de email y contraseña para desactivarlas, y activa la línea del token quitando su `#`.

> **Privacidad:** tus credenciales viven solo en tu archivo `.env` local. Está en `.gitignore` y nunca se sube a ningún sitio.

---

### Paso 3 — Descarga los datos oficiales

```bash
./update-data.sh
```

Esto conecta con DataComex y descarga los datos de comercio exterior de España. **La primera vez tarda entre 15 y 30 minutos** (descarga varios años de histórico). Verás texto avanzando en el Terminal — es normal, espera hasta que aparezca de nuevo el `$`.

---

### Paso 4 — Arranca la herramienta

```bash
./run.sh
```

Cuando veas esta línea en el Terminal:

```
Uvicorn running on http://127.0.0.1:8765
```

Abre tu navegador y ve a:

**→ http://localhost:8765**

¡Listo! Ya tienes Brújula Export funcionando con datos reales.

> **No cierres el Terminal mientras usas la herramienta.** El servidor necesita estar en marcha. Cuando termines, ciérralo pulsando `Ctrl+C`.

---

### Cómo arrancarla las próximas veces

Cada vez que quieras usar la herramienta, abre el Terminal y ejecuta:

```bash
cd brujula-export
./run.sh
```

Si aparece el error `ya hay un servidor escuchando en :8765`, significa que hay una sesión anterior activa. Ciérrala y vuelve a arrancar con:

```bash
lsof -ti TCP:8765 | xargs kill -9 2>/dev/null; sleep 1; ./run.sh
```

---

### Actualizar los datos cada mes

DataComex publica datos nuevos mensualmente. Para traer lo último:

```bash
cd brujula-export
./update-data.sh
```

Cuando termine, reinicia la app para que los cambios se apliquen:

```bash
lsof -ti TCP:8765 | xargs kill -9 2>/dev/null; sleep 1; ./run.sh
```

---

### ¿Quieres probarla sin datos reales?

Ejecuta `./run.sh` directamente sin haber configurado nada. Si no hay datos descargados, la app genera automáticamente un **dataset de demostración** con datos inventados y te avisa con un banner. Es útil para ver cómo funciona la interfaz antes de registrarte en DataComex.

---

## Configurar DataComex (referencia rápida)

La herramienta no incluye datos: cada usuario descarga los suyos con su propia cuenta de DataComex (gratuita). Sin credenciales la app funciona, pero con datos muy limitados — [ver diferencias](#con-cuenta-o-sin-cuenta).

Con cualquiera de las dos opciones descritas arriba, `./run.sh` y `./update-data.sh` cargan el `.env` automáticamente.

---

<p align="center">
  <img src="docs/assets/cuenta-comparativa.svg" alt="Comparativa: sin cuenta solo datos nacionales; con cuenta gratuita datos completos incluyendo Aragón y Zaragoza" width="700"/>
</p>

### Con cuenta o sin cuenta

La herramienta está diseñada para usarse **con cuenta gratuita de DataComex**. Sin cuenta también funciona, pero con importantes limitaciones:

**Sin cuenta de DataComex**
La app descarga solo datos nacionales básicos por la vía pública. No hay desglose provincial, así que el análisis de Aragón/Zaragoza desaparece por completo. Si tu objetivo es analizar el potencial exportador de empresas aragonesas, esta opción no tiene mucho sentido.

**Con cuenta gratuita de DataComex** 
Acceso completo: datos nacionales y provinciales (Aragón/Zaragoza), scoring con todos los indicadores, fichas de mercado sin lagunas. Es la versión para la que fue diseñada la herramienta. Registrarse es gratuito y lleva menos de 5 minutos.

Cuando ejecutas `./update-data.sh`, la app descarga solo los meses que le faltan — no empieza de cero cada vez. Para que los datos nuevos aparezcan en la app, reinicia con `./run.sh` (o `./run.sh --update` para actualizar y arrancar en un paso).

> La primera descarga por la vía pública (sin cuenta) baja todo el histórico desde 2015 y puede tardar varias horas por los límites del formulario público (~5-8 h, ~42 MB). Para un primer vistazo más rápido: `./update-data.sh --from 2022-01` (~1,5 h). Un CI opcional ([`datacomex-liveness.yml`](.github/workflows/datacomex-liveness.yml)) avisa si DataComex cambia algo que rompa la extracción.

---

## Datos dinámicos

Los datos no van en el repositorio (son grandes y el ministerio los actualiza cada mes): cada usuario los descarga y los mantiene al día con `./update-data.sh`. Cuando DataComex publica un mes nuevo, basta volver a ejecutarlo.

```bash
./update-data.sh   # trae lo último de DataComex y reconstruye la base
./run.sh           # sirve los datos (offline)
```
---

## Arquitectura

| Pieza | Qué hace |
|---|---|
| `etl/` | Descarga DataComex (API oficial con token, o cadena CSV pública) y construye `data/brujula.duckdb` |
| `app/` | FastAPI: motor de scoring (SQL DuckDB + percentiles) y endpoints del [contrato](docs/specs/api-contract.md) |
| `web/` | SPA sin build step (vanilla JS + ECharts vendorizado) — funciona offline |
| `tests/` | pytest: métricas con valores calculados a mano, API y ETL |

Decisiones de arquitectura en `docs/adr/`. Spec completa en `docs/specs/2026-06-11-brujula-export-design.md`.

---

## Scoring

<p align="center">
  <img src="docs/assets/scoring.svg" alt="Scoring multicriterio: 6 criterios con sus pesos" width="700"/>
</p>

---

### Criterios de selección

El scoring utiliza 5 componentes normalizados a percentil

<div align="center">
  
| Criterio | Descripción |
|----------|-------------|
| **Tamaño** | Volumen total de importaciones (USD) |
| **Crecimiento** | Tasa anual compuesta últimos 3 años |
| **Estabilidad** | Consistencia en volúmenes (sin caídas bruscas) |
| **Valor unitario €/kg** | Precio promedio y margen potencial |
| **Accesibilidad** | Barreras arancelarias y acuerdos comerciales |

</div>

**Notas:**
- Pesos ajustables en vivo mediante sliders
- Métrica incalculable → componente neutro 50 + flag visible
- Celdas con secreto estadístico → `<n/d>`

---

## Carga de datos reales (avanzado)

`./update-data.sh` (= `python -m etl.update`) hace descarga incremental + reconstrucción en un paso (ver «Datos dinámicos»). Si prefieres controlar cada fase por separado:

```bash
.venv/bin/python -m etl.download --from 2015-01   # descarga reanudable a data/raw/
.venv/bin/python -m etl.load                       # reconstruye data/brujula.duckdb
```

Detalle completo (tiempos, validaciones, vías API/CSV, límites del formulario público): `docs/etl-runbook.md`.

---

## Tests

```bash
.venv/bin/pytest -q
```

---

## Fuente y licencia

**Fuente de datos:** [DataComex](https://datacomex.comercio.es)  
Estadísticas de comercio exterior de bienes de España y la UE

**Código:** licencia [MIT](LICENSE).
