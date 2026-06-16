# Spec — Iteración de auditoría UX/UI (2026-06-16)

**Estado:** Aprobado por el usuario · 2026-06-16
**Origen:** Informe consolidado de auditoría UX/UI (Claude vía Chrome) contrastado con las notas del usuario. Las notas tienen prioridad sobre el informe.
**Alcance:** Mejoras sobre la herramienta existente. No se añaden features nuevas salvo el resumen ejecutivo del informe (sustituto del análisis IA que se elimina). Spec fuente de verdad de base: `docs/specs/2026-06-11-brujula-export-design.md`.

## Decisiones transversales (fijadas por el usuario)

1. **Calidad de datos / scoring:** solo señalización visual, **no se toca el cálculo** del score. Preserva la transparencia metodológica (ADR-003). El nº1 micromercado es consecuencia de los pesos, no un fallo del algoritmo.
2. **Filas con 0 € de exportación reciente:** se mantienen en el ranking con un badge claro, no se segregan a otra sección.
3. **Análisis IA:** se **elimina por completo** de la herramienta. Se sustituye por un resumen ejecutivo determinista dentro del informe + botón "Copiar resumen" (texto para pegar en una IA externa).
4. **Pesos:** los sliders muestran el **peso efectivo normalizado a 100 %** en vivo.

## Restricciones del proyecto (heredadas)

- 100 % offline en runtime: sin CDNs, APIs externas ni llamadas LLM. El portapapeles (`navigator.clipboard`) es API local del navegador, cumple.
- Celdas ocultas por secreto estadístico → `NULL`, nunca 0.
- Frontend sin build step. ECharts vendorizado.
- Python: `.venv/bin/python`. Tests: `.venv/bin/pytest`.

---

## Workstream A — Eliminar la feature de análisis IA (PRIORIDAD ALTA)

Disuelve los hallazgos del informe §3.1, §3.2, §3.3, §3.4 (todos sobre incoherencias del análisis IA) y una de las causas de §6.1 (el insight usaba un tercer nombre del producto).

**Cambios:**
- `app/insights.py` → eliminar archivo.
- `app/main.py` → eliminar `from app.insights import load_insight`, la env `BRUJULA_INSIGHTS`, el endpoint `GET /api/insights/{taric}` y la línea de docstring que la menciona.
- `web/index.html` → eliminar el bloque `#insights-panel` (cabecera, body, fecha, badge IA).
- `web/app.js` → eliminar `loadInsights()`, `renderMarkdown()`, la llamada `loadInsights(taric)` en `loadProduct()`, y la línea `$('#insights-panel').hidden = true;` en `resetCountryPanel()`.
- `web/styles.css` → eliminar las reglas `.insights`, `.insights-head`, `.ia-badge`, `.md *`, `#insights-date`, y la parte `.insights h3` de la regla compartida.
- `insights/*.md` → eliminar los 7 ficheros (contenido de la feature; git conserva el histórico).
- `tests/test_api.py` → eliminar `test_insights_existing_file`, `test_insights_missing_404` y la creación del `insights_dir` + env en el fixture `client`.
- `docs/adr/ADR-005-eliminar-insights.md` → nuevo ADR que supersede al ADR-004. Marcar ADR-004 como "Superseded by ADR-005".
- `docs/specs/api-contract.md` → eliminar la sección `GET /api/insights/{taric}`.
- `docs/specs/2026-06-11-brujula-export-design.md` → actualizar referencias a insights (estructura de árbol, tabla de endpoints, decisiones).
- `README.md` → actualizar el párrafo de intro, la fila `insights/` de la tabla de arquitectura y la mención en el guion.

**Verificación:**
- `.venv/bin/pytest -q` verde sin los tests de insights.
- `GET /api/insights/2204` → 404 con `detail` en español (la ruta ya no existe → handler de Starlette traducido).
- `grep -rni insight app/ web/` sin resultados (salvo, si acaso, comentarios de docs).

---

## Workstream B — Resumen ejecutivo del informe + "Copiar resumen" (PRIORIDAD ALTA)

Sustituye el rol que tenía el análisis IA. Determinista, generado de los datos del panel; cero IA en runtime.

**Contenido del resumen** (calculado del estado actual: producto + pesos vigentes):
- Producto (TARIC + descripción canónica de nomenclatura).
- Exportación España 12 m, cuota Aragón, cuota Zaragoza, nº de países candidatos.
- Perfil de pesos aplicado (normalizado a 100 %).
- Top-5 mercados por score con: posición, país, score, export 12 m, CAGR 3a (con tope visual), €/kg, accesibilidad.
- Cautela metodológica: el ranking se ordena por score (oportunidad multicriterio), no por volumen; las cifras son exportación española declarada, no demanda mundial.

**Cambios:**
- `web/app.js`:
  - `summaryData()` → objeto con los datos calculados (reutilizado por HTML y texto).
  - `buildSummaryHtml()` → sección `.r-summary` insertada en `buildReport()` entre KPIs y ranking.
  - `buildSummaryText()` → markdown/texto plano para el portapapeles.
  - `bindCopySummary()` → `navigator.clipboard.writeText(...)` + toast. Fallback con `document.execCommand('copy')` si `clipboard` no está disponible.
- `web/index.html` → botón `#btn-copy-summary` en la cabecera de producto, junto a `#btn-report`.
- `web/styles.css` → estilo de la sección `.r-summary` en el bloque `@media print`; el botón reutiliza `.btn-ghost`.

**Verificación:** arranque real; "Generar informe" muestra el resumen con el top-5 correcto; "Copiar resumen" copia texto plano coherente (toast confirma). Se valida con captura del informe.

---

## Workstream C — Bug de compresión de gráficos (PRIORIDAD ALTA)

Causa raíz única (confirmada en código): las instancias ECharts se cachean en `charts[id]` con el tamaño del contenedor del momento del `init`; `renderMonthlyChart`/`renderYearlyChart` no llaman a `resize()`. Si el contenedor estaba a 0/estrecho (panel recién mostrado, reflow del grid), el gráfico queda colapsado hasta un resize de ventana. Explica §4.1 (eje X ilegible), §4.2 (estacionalidad/provincias colapsadas), §4.3 (toggle pisa "120 M"), §4.4 (leyenda solapada), §4.5 (plot al 20 %), §4.6/§4.7 secundarios.

**Cambios:**
- `web/app.js` `chart(id)`: al crear la instancia, adjuntar un `ResizeObserver` sobre el contenedor que llama `instance.resize()` (creado una sola vez por id).
- Añadir `chart(id).resize()` al inicio de `renderMonthlyChart` y `renderYearlyChart`.
- Ajuste menor de `grid.top` en monthly/yearly si tras el fix la leyenda aún roza el eje.

**Verificación:** arranque real; seleccionar país (8703/Polonia, 8708/Luxemburgo); los 4 gráficos legibles y ocupando el ancho; estrechar la ventana y confirmar que se recomponen. Capturas antes/después.

---

## Workstream D — Pesos normalizados a 100 % (PRIORIDAD ALTA, §2.5)

**Cambios:**
- `web/app.js` `renderSliders()`: extraer `refreshWeightLabels()` que recalcula `Σw` y actualiza **todos** los `<output>` a `round(w_i/Σw × 100) %` y su `aria-valuetext`. Llamarla en cada `input` y en el reset. El valor crudo del slider (0–50) sigue siendo la posición del mando; el porcentaje mostrado es el peso efectivo. Σ=0 → outputs a "—" (ya hay aviso que bloquea el informe).

**Verificación:** arranque real; subir un slider y confirmar que los demás bajan su % y el conjunto suma 100 %.

---

## Workstream E — Señalización de calidad de datos (PRIORIDAD ALTA/MEDIA)

Frontend, sobre métricas que ya envía el backend. **No** se toca el scoring.

**Cambios en `web/app.js` (`buildRankingRows`/`updateRanking`) y `web/styles.css`:**
- **Badge base reducida / sin export. reciente** (§2.1, §2.3):
  - `size_eur_12m === 0` → badge "sin export. reciente" (tono ámbar) + tooltip.
  - `size_eur_12m > 0` y `size_eur_12m / total_exports_12m < 0.001` (<0,1 % del total nacional) → badge "base reducida" + tooltip "mercado diminuto: crecimiento/€-kg sobre base pequeña, alta volatilidad".
- **€/kg atípico** (§2.2): si `unit_value_rel > 5` (>5× la mediana de candidatos), realce de aviso en la celda €/kg + `title` "valor unitario atípico: posible artefacto de envío marginal".
- **Tope visual CAGR** (§2.4): `fmtCagr(v)` → si `v > 5` (>+500 %) muestra ">+500 %" y pone el valor real en `title`. Aplica en columna CAGR del ranking, resumen del informe y tooltip del gráfico anual.
- **Leyenda de colores del desglose** (§5.1, §7.3): tira fija de 5 dots + etiqueta (reutiliza `COMPONENTS[].color/label`) en la cabecera del ranking, además del `title` del stack.

**Verificación:** arranque real con DB real; en 8708 Luxemburgo muestra "base reducida" y €/kg atípico; CAGR extremos (1214/Grecia) muestran ">+500 %"; la leyenda de colores es visible.

---

## Workstream F — UX, estados, accesibilidad, responsive

**ALTA:**
- §7.1 — cada opción del autocompletado lleva `aria-label="{taric} {description}"` explícito (nombre accesible garantizado).
- §8.1 — responsive del buscador: `@media (max-width: 1280px)` la topbar envuelve y `.search-box` recupera ancho usable (min-width); `@media (max-width: 980px)` el layout pasa a una columna.

**MEDIA:**
- §5.3 — ordenar el autocompletado de texto por `has_data DESC` antes de `n.level` para que los productos con datos vayan antes que los capítulos "sin datos". No rompe los tests existentes (2204 antes que 2205; 0203 primero en "carne porcino").
- §5.5 — resetear `#ranking-card.scrollTop = 0` al construir el ranking de un producto nuevo.
- §8.2 — en anchos reducidos `#btn-report`/`#btn-copy-summary` dejan de ser `position:absolute` (pasan a flujo) y el título recupera su ancho.
- §4.7 — `padding-right`/gutter en `.ranking-card` para que el scrollbar no tape la columna €/kg.
- §6.1 — nombre canónico: con el insight eliminado, header, buscador, informe y tooltip ya usan la descripción de nomenclatura. Los chips de ejemplo conservan su etiqueta curada corta (decisión: aceptable; son accesos directos curados).
- **Verificar (probablemente ya resueltos en el código actual):** §5.2 (estado "Sin resultados" ya implementado en `runSearch`) y §5.6 (`#left-skeleton` ya se muestra durante la carga). Confirmar en navegador; actuar solo si fallan.

**BAJA:**
- §5.9 — cabecera opaca: `.topbar` pasa a fondo sólido (sin translucidez del 3 %).
- §5.4, §5.8, §5.10, §5.11 — comportamiento aceptable o cosmético de bajo impacto con riesgo de churn. **No-fix documentado** (principio quirúrgico/YAGNI). Revisable si el usuario lo pide.

---

## Plan de verificación global

1. **Backend:** `.venv/bin/pytest -q` verde tras los cambios (insights fuera, orden de búsqueda ajustado). Tests nuevos/ajustados donde el contrato cambie.
2. **Frontend:** arranque real (`./run.sh`) y recorrido por navegador con capturas:
   - Gráficos legibles y a ancho completo (8703, 8708) + recomposición al estrechar.
   - Badges de calidad de datos, €/kg atípico, tope CAGR, leyenda de colores.
   - Pesos sumando 100 % al mover sliders.
   - Informe con resumen ejecutivo correcto; "Copiar resumen" funcional.
   - Responsive a ~1280px y <980px sin solapamientos ni buscador inaccesible.
3. **Review:** workflow adversarial read-only sobre el diff antes de cerrar.

## Criterios de éxito

- Ningún rastro de la feature IA en runtime (endpoint, panel, estilos) ni en docs como característica viva.
- Los 4 gráficos legibles y a ancho completo de forma consistente.
- Sliders que comunican el peso efectivo real (suma 100 %).
- Señalización visible para 0 €/base reducida, €/kg atípico y CAGR extremos, sin alterar el ranking.
- Informe con resumen ejecutivo copiable.
- Suite de tests verde.
