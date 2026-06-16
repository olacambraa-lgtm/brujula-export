# Plan de implementación — Iteración de auditoría UX/UI

> **Para ejecución:** plan task-by-task. Backend con TDD (pytest); frontend con verificación en navegador (sin infra de tests JS). Pasos con checkbox para tracking.

**Goal:** Aplicar las mejoras de la auditoría UX/UI: eliminar la feature de análisis IA (sustituida por resumen ejecutivo en el informe), arreglar la compresión de gráficos, normalizar los pesos a 100 %, señalizar la calidad de datos sin tocar el scoring, y resolver UX/accesibilidad/responsive — por orden de prioridad.

**Architecture:** Cambios quirúrgicos sobre la app existente (FastAPI + DuckDB backend; SPA vanilla JS + ECharts vendorizado). El scoring no se toca: la calidad de datos se comunica con señalización en el frontend. Spec: `docs/specs/2026-06-16-auditoria-ux-iteracion.md`.

**Tech Stack:** Python 3.13 (`.venv`), FastAPI, DuckDB, pytest · HTML/CSS/JS vanilla, ECharts.

## Global Constraints

- 100 % offline en runtime: sin CDNs, APIs externas ni LLM. `navigator.clipboard` (API local) permitido.
- Secreto estadístico → `NULL`, nunca 0.
- Frontend sin build step; ECharts vendorizado en `web/vendor/`.
- Python del proyecto: `.venv/bin/python`. Tests: `.venv/bin/pytest -q`.
- No alterar el cálculo del score (ADR-003). La calidad de datos solo se señaliza.
- Estilo de cambios: quirúrgico, DRY, YAGNI; adaptarse al estilo existente.

---

### Task 1: Eliminar el endpoint de insights (backend + tests + contrato) — TDD

**Files:**
- Delete: `app/insights.py`
- Modify: `app/main.py` (quitar import, env, endpoint, docstring)
- Modify: `tests/test_api.py` (quitar fixture insights + 2 tests; ajustar `client`)
- Modify: `docs/specs/api-contract.md` (quitar sección insights)

- [ ] **Step 1:** En `tests/test_api.py`, eliminar `test_insights_existing_file` y `test_insights_missing_404`; en el fixture `client`, eliminar la creación de `insights_dir`, el `write_text` y `os.environ["BRUJULA_INSIGHTS"]`. Añadir un test nuevo `test_insights_route_removed` que afirme `client.get("/api/insights/2204").status_code == 404`.
- [ ] **Step 2:** Run: `.venv/bin/pytest tests/test_api.py -q` → Expected: FAIL (la ruta aún existe y devuelve 200/404 según fichero; el test nuevo puede pasar pero el fixture ya no crea fichero — confirmar el estado real y por qué falla antes de seguir).
- [ ] **Step 3:** En `app/main.py`: quitar `from app.insights import load_insight`, la línea `insights_dir = os.environ.get(...)`, el bloque `@app.get("/api/insights/{taric}")`, y la línea de docstring `- BRUJULA_INSIGHTS: ...`. Borrar `app/insights.py`.
- [ ] **Step 4:** Run: `.venv/bin/pytest tests/test_api.py -q` → Expected: PASS (incluido `test_insights_route_removed` → 404 vía handler Starlette en español).
- [ ] **Step 5:** En `docs/specs/api-contract.md`, eliminar la sección `## GET /api/insights/{taric}`.
- [ ] **Step 6:** Run: `.venv/bin/pytest -q` (suite completa) → Expected: PASS. Commit: `git add -A && git commit -m "feat: eliminar endpoint /api/insights (feature IA fuera)"`

---

### Task 2: Ordenar el autocompletado por datos antes que capítulos sin datos (§5.3) — TDD

**Files:**
- Modify: `app/metrics.py` (`search`, ORDER BY de la rama de texto)
- Modify: `tests/test_api.py` (test nuevo)

- [ ] **Step 1:** Añadir en `tests/test_api.py` `test_search_data_before_chapters`: una consulta de texto que matchee a la vez un capítulo (level 2, sin datos) y un producto con datos debe devolver el producto con datos primero. En el fixture, "Bebidas" matchea el capítulo 22 (level 2, has_data false) y 2204/2205 no contienen "bebidas"; usar el término del capítulo. Verificar que el capítulo 22 no precede a un producto con datos cuando ambos matchean. (Si ningún término compartido existe en el fixture, ajustar la nomenclatura del fixture añadiendo un término común, p. ej. que la descripción del capítulo 22 y la de 2204 compartan una palabra; preferible: test que afirme orden `has_data` con los datos existentes.)
- [ ] **Step 2:** Run: `.venv/bin/pytest tests/test_api.py::test_search_data_before_chapters -v` → Expected: FAIL.
- [ ] **Step 3:** En `app/metrics.py`, rama de texto de `search`, cambiar el ORDER BY de `({relevance}) DESC, n.level, t.total DESC NULLS LAST, n.taric` a `({relevance}) DESC, (t.total IS NOT NULL) DESC, n.level, t.total DESC NULLS LAST, n.taric`.
- [ ] **Step 4:** Run: `.venv/bin/pytest tests/test_api.py -q` → Expected: PASS (nuevo + existentes: `test_search_text_orders_by_exports`, `test_search_multiword_all_tokens_required` siguen verdes).
- [ ] **Step 5:** Commit: `git add -A && git commit -m "fix: priorizar productos con datos sobre capítulos sin datos en búsqueda (§5.3)"`

---

### Task 3: Eliminar el panel de análisis IA del frontend (§3.x, A)

**Files:**
- Modify: `web/index.html` (quitar `#insights-panel`)
- Modify: `web/app.js` (quitar `loadInsights`, `renderMarkdown`, llamada, reset)
- Modify: `web/styles.css` (quitar `.insights`, `.ia-badge`, `.md`, `#insights-date`)
- Delete: `insights/0203.md … 8708.md` (7 ficheros)

- [ ] **Step 1:** `web/index.html`: eliminar el bloque `<div id="insights-panel">…</div>` completo (líneas ~195-202).
- [ ] **Step 2:** `web/app.js`: eliminar la sección `/* Insights IA */` con `loadInsights()` y `renderMarkdown()`; eliminar la llamada `loadInsights(taric);` en `loadProduct()`; eliminar `$('#insights-panel').hidden = true;` en `resetCountryPanel()`.
- [ ] **Step 3:** `web/styles.css`: eliminar el bloque `/* Insights */` (`.insights`, `.insights-head`, `.ia-badge`, `.md h1/h2/h3/p/ul/li`, `#insights-date`) y la referencia `.insights h3` de la regla compartida `#operators-card h3, .insights h3` (eliminar toda la regla: `#operators-card` tampoco existe en el HTML actual).
- [ ] **Step 4:** Borrar `insights/*.md`.
- [ ] **Step 5 (verificación):** `grep -rni "insight\|renderMarkdown\|ia-badge\|\.md " web/ app/` → Expected: sin coincidencias funcionales. Arrancar `./run.sh`, abrir un producto y un país: no aparece el panel IA; consola del navegador sin errores.
- [ ] **Step 6:** Commit: `git add -A && git commit -m "feat: eliminar panel de análisis IA del frontend (feature fuera)"`

---

### Task 4: Arreglar la compresión de gráficos (causa raíz, C)

**Files:**
- Modify: `web/app.js` (`chart()`, `renderMonthlyChart`, `renderYearlyChart`)

- [ ] **Step 1:** En `chart(id)`, tras `echarts.init`, crear y observar un `ResizeObserver(() => instance.resize())` sobre el contenedor (guardado para no duplicar). Mantener la firma `chart(id) → instance`.
- [ ] **Step 2:** Añadir `chart('chart-monthly').resize();` al inicio de `renderMonthlyChart` (antes de `setOption`) — patrón ya usado en season/provinces. Igual en `renderYearlyChart`.
- [ ] **Step 3 (verificación):** Arrancar; seleccionar 8703→Polonia y 8708→Luxemburgo: eje X mensual legible (años separados), serie anual legible, estacionalidad (12 meses legibles), provincias legibles; el plot ocupa el ancho. Estrechar/ensanchar la ventana → los gráficos se recomponen sin recargar. Capturas antes/después.
- [ ] **Step 4:** Commit: `git add -A && git commit -m "fix: gráficos ECharts se recomponen al cambiar de tamaño (ResizeObserver + resize); arregla compresión intermitente (§4.x)"`

---

### Task 5: Pesos normalizados a 100 % (§2.5, D)

**Files:**
- Modify: `web/app.js` (`renderSliders`, `bindWeightsReset`)

- [ ] **Step 1:** En `renderSliders`, guardar referencias `{key → output}` y extraer `refreshWeightLabels()` que calcula `Σw = Σ state.weights[key]` y pone cada `output.textContent` = `Σw>0 ? Math.round(w/Σw*100)+' %' : '—'`, actualizando también `aria-valuetext`. Llamarla al final de `renderSliders`, en cada `input`, y en el reset (`bindWeightsReset`).
- [ ] **Step 2 (verificación):** Arrancar; abrir un producto, desplegar "Ajustar criterios": al subir Tamaño a 50, los demás bajan su % y la suma de los 5 = 100 %. "Restablecer pesos" vuelve a 28/28/16/16/12.
- [ ] **Step 3:** Commit: `git add -A && git commit -m "fix: sliders muestran peso efectivo normalizado a 100% (§2.5)"`

---

### Task 6: Señalización de calidad de datos (E)

**Files:**
- Modify: `web/app.js` (`fmtCagr` nuevo; `buildRankingRows`; helper umbrales; leyenda de colores)
- Modify: `web/index.html` (contenedor de leyenda de colores en la ranking-card)
- Modify: `web/styles.css` (estilos badges, €/kg atípico, leyenda)

- [ ] **Step 1:** `fmtCagr(v)`: si `v != null && isFinite(v) && v > 5` → devuelve `'>+500 %'`; si `< -5` (no esperado) análogo; en otro caso `fmtPct(v, true)`. Usar `fmtCagr` en la columna CAGR del ranking (sustituye `fmtPct(c.metrics.cagr_3y, true)`), poniendo el valor real en `title` de la celda cuando hay tope.
- [ ] **Step 2:** En `buildRankingRows`, calcular badges por país a partir de métricas existentes y `state.product.total_exports_12m`:
  - `size_eur_12m === 0` → badge "sin export. reciente" (clase `flag-stale`).
  - `size_eur_12m > 0 && total>0 && size/total < 0.001` → badge "base reducida" (clase `flag-small`) con tooltip explicativo.
  - `unit_value_rel != null && unit_value_rel > 5` → marcar la celda €/kg con clase `uv-outlier` + `title`.
- [ ] **Step 3:** Leyenda de colores del desglose: añadir en `web/index.html` una tira `<div class="comps-legend">` en la cabecera de la ranking-card, rellenada desde `COMPONENTS` (dot color + label) en una función `renderCompsLegend()` llamada al cargar producto.
- [ ] **Step 4:** Estilos en `web/styles.css` para `.flag-stale`, `.flag-small`, `.uv-outlier`, `.comps-legend`.
- [ ] **Step 5 (verificación):** Arrancar con DB real; 8708: Luxemburgo muestra "base reducida" y €/kg atípico realzado; 1214: CAGR extremos muestran ">+500 %" (real en tooltip); leyenda de colores visible bajo la cabecera.
- [ ] **Step 6:** Commit: `git add -A && git commit -m "feat: señalización de calidad de datos (base reducida, €/kg atípico, tope CAGR, leyenda de colores) sin tocar el scoring (§2.1-2.4, §5.1)"`

---

### Task 7: Resumen ejecutivo del informe + "Copiar resumen" (B)

**Files:**
- Modify: `web/app.js` (`summaryData`, `buildSummaryHtml`, `buildSummaryText`, `buildReport`, `bindCopySummary`, `init`)
- Modify: `web/index.html` (botón `#btn-copy-summary`)
- Modify: `web/styles.css` (`.r-summary` en `@media print`)

- [ ] **Step 1:** `summaryData()` → objeto con producto, total 12m, cuotas, perfil de pesos normalizado (`COMPONENTS.map(k → {label, pct})`), y `top5 = currentRanking().slice(0,5)` con `{rank, name, score, size, cagr, uv, access}`.
- [ ] **Step 2:** `buildSummaryHtml(d)` → markup de la sección `.r-summary` (prosa + lista top-5). Insertarla en `buildReport()` entre `.r-kpis` y `.r-ranking`.
- [ ] **Step 3:** `buildSummaryText(d)` → markdown/texto plano equivalente (cabecera, cifras, perfil de pesos, top-5 con cifras, cautela metodológica).
- [ ] **Step 4:** `web/index.html`: botón `<button id="btn-copy-summary" class="btn btn-ghost">Copiar resumen</button>` junto a `#btn-report`. `bindCopySummary()`: `navigator.clipboard.writeText(buildsummaryText)` con fallback `execCommand`; toast "Resumen copiado al portapapeles". Mostrar/ocultar el botón con la misma condición que `#btn-report` (`hasData`). Bind en `init`.
- [ ] **Step 5:** Estilos `.r-summary` en `@media print` (encabezado de sección como `.r-method`, lista del top-5 legible).
- [ ] **Step 6 (verificación):** Arrancar; "Generar informe" muestra el resumen con el top-5 correcto y el perfil de pesos vigente; "Copiar resumen" copia texto coherente (pegar en un editor) y dispara el toast.
- [ ] **Step 7:** Commit: `git add -A && git commit -m "feat: resumen ejecutivo en el informe + botón Copiar resumen (sustituye al análisis IA) (§B)"`

---

### Task 8: UX, accesibilidad y responsive (F)

**Files:**
- Modify: `web/app.js` (aria-label en opciones; reset scrollTop)
- Modify: `web/styles.css` (responsive; cabecera opaca; gutter scrollbar; btn no-absolute)

- [ ] **Step 1 (§7.1):** En `runSearch`, añadir `aria-label="${escHtml(r.taric)} ${escHtml(r.description)}"` a cada `.search-item`.
- [ ] **Step 2 (§5.5):** Tras `buildRankingRows()` (o al final de `loadProduct`), `const rc = $('.ranking-card'); if (rc) rc.scrollTop = 0;`.
- [ ] **Step 3 (§5.9):** `.topbar` → fondo sólido `var(--bg)` (quitar la translucidez `.97`).
- [ ] **Step 4 (§4.7):** `.ranking-card` → `padding-right` o `scrollbar-gutter: stable` para que el scrollbar no tape la columna €/kg.
- [ ] **Step 5 (§8.1, §8.2):** Añadir al final de `web/styles.css` un bloque responsive:
  - `@media (max-width: 1280px)`: `.topbar { flex-wrap: wrap; }`, `.search-box { order: 3; flex-basis: 100%; max-width: none; margin: 8px 0 0; }`, `.meta-badge { margin-left: auto; }`.
  - `@media (max-width: 980px)`: `.layout { grid-template-columns: 1fr; }`; `#btn-report, #btn-copy-summary { position: static; }`; `.product-title { padding-right: 0; }`; permitir apilado de chips/botones.
- [ ] **Step 6 (verificación):** Arrancar; a ~1280px el buscador sigue siendo un campo usable (no un icono muerto); a <980px una columna sin solapamientos (botones en flujo, chips apilados); cabecera opaca al hacer scroll; columna €/kg no tapada por el scrollbar; opciones del autocompletado con nombre accesible (árbol de accesibilidad / VoiceOver). Verificar §5.2 (escribir "zzzzqx" → "Sin resultados…") y §5.6 (skeleton al cambiar de producto) siguen OK; actuar solo si fallan.
- [ ] **Step 7:** Commit: `git add -A && git commit -m "fix: responsive del buscador y layout, accesibilidad de opciones, cabecera opaca, reset de scroll, gutter €/kg (§5.5, §5.9, §7.1, §8.1, §8.2)"`

---

### Task 9: Documentación — coherencia tras los cambios

**Files:**
- Modify: `README.md`, `docs/specs/2026-06-11-brujula-export-design.md`

- [ ] **Step 1:** `README.md`: actualizar el párrafo de intro (quitar "análisis ejecutivos generados con IA"), la fila `insights/` de la tabla de arquitectura (sustituir por la mención al resumen ejecutivo del informe), y la línea del guion que dice "regenerar los insights".
- [ ] **Step 2:** `docs/specs/2026-06-11-brujula-export-design.md`: actualizar las referencias a insights (árbol de directorios, tabla de endpoints, lista de decisiones/ADR) para reflejar que la feature se elimina (ADR-005) y que el análisis vive en el informe.
- [ ] **Step 3 (verificación):** `grep -rni "insight" README.md docs/specs/` → solo referencias históricas/ADR coherentes (ADR-004 superseded, ADR-005). 
- [ ] **Step 4:** Commit: `git add -A && git commit -m "docs: actualizar README y spec tras eliminar insights (ADR-005)"`

---

### Task 10: Verificación global y review adversarial

- [ ] **Step 1:** `.venv/bin/pytest -q` → Expected: PASS (toda la suite).
- [ ] **Step 2:** Recorrido completo en navegador con capturas: gráficos, badges, pesos, informe + copiar, responsive. Consola sin errores.
- [ ] **Step 3:** Workflow adversarial read-only sobre el diff de la rama (varios revisores: correctness, regresiones de scoring/secreto estadístico, offline, accesibilidad). Triagear hallazgos reales y corregir.
- [ ] **Step 4:** Resumen final al usuario; decisión sobre merge a `main`.

## Self-Review (cobertura del spec)

- A (eliminar IA): Tasks 1, 3, 9 (+ADR-005 ya creado). ✓
- B (resumen ejecutivo + copiar): Task 7. ✓
- C (compresión gráficos): Task 4. ✓
- D (pesos 100 %): Task 5. ✓
- E (señalización calidad datos: 2.1-2.4, 5.1, 7.3): Task 6. ✓
- F (7.1, 8.1, 5.3, 5.5, 8.2, 4.7, 6.1, 5.9; verificar 5.2/5.6; no-fix 5.4/5.8/5.10/5.11): Tasks 2, 8. ✓
- Sin placeholders; nombres de funciones consistentes entre tareas (`summaryData/buildSummaryHtml/buildSummaryText`, `fmtCagr`, `refreshWeightLabels`, `renderCompsLegend`).
