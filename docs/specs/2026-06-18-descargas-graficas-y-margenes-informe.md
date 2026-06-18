# Spec — Descargas por gráfica (PNG/CSV) y márgenes del informe (2026-06-18)

**Estado:** Aprobado por el usuario · 2026-06-18
**Alcance:** Dos añadidos sobre la app existente. Respeta la estructura y el formato originales. 100% offline (sin libs ni red).

## A — Descargas en las 4 gráficas de la ficha de país

Cada una de las cuatro gráficas (evolución mensual, serie anual y valor unitario, estacionalidad, provincias) gana un control de descarga: **PNG** y **CSV**. La descarga **refleja la configuración interactiva visible** (series ocultadas por la leyenda de ECharts no se exportan).

### UI
- En la cabecera (`<h3>`) de cada `.chart-card`, alineado a la derecha, un control discreto `.chart-dl` con dos mini-botones: `PNG` y `CSV`.
- Estilo sobrio coherente con el resto (no el toolbox de ECharts).

### PNG
- `echarts.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#102236' })` sobre la instancia del chart → respeta automáticamente las series deseleccionadas en la leyenda. Descarga vía `Blob`/`<a download>`.

### CSV (adaptado a la leyenda)
- **Mensual** → `Periodo; Euros; Estado` (Estado = Definitivo/Provisional). Si la leyenda oculta "Definitivo" o "Provisional", se excluyen los periodos de esa serie.
- **Serie anual** → `Año; Exportación (€); Valor unitario (€/kg)`. Cada columna se incluye solo si su serie está visible en la leyenda.
- **Estacionalidad** → `Mes; Cuota media (%)` (sin leyenda → siempre completa).
- **Provincias** → `Provincia; Exportación 12m (€); Cuota nacional (%)` (sin leyenda → siempre completa).
- Formato: separador `;`, decimales con coma (es-ES), UTF-8 con BOM (Excel ES). Valores numéricos crudos (euros enteros; €/kg y cuotas con decimales); celdas nulas vacías (nunca 0 fabricado).

### Datos y estado
- `renderCountryPanel(d)` guarda `state.market = d` para que las funciones de descarga accedan a `monthly/yearly/seasonality/provinces` y a `taric`/país.
- El estado de visibilidad de cada serie se lee de `chart(id).getOption().legend?.[0]?.selected` (mapa nombre→bool).

### Nombre de archivo
- `brujula_{taric}_{iso2|country_code}_{grafica}.{png|csv}` (slug sin acentos).

### Verificación
- CDP: para 8703→país, descargar PNG (dataURL no vacío) y CSV de cada gráfica; ocultar una serie en la anual y confirmar que el CSV excluye su columna y el PNG no la dibuja.

## B — Margen superior de las páginas 2+ del informe

### Problema (verificado con el PDF real)
La pág. 2 (Metodología) arranca con el título pegado al borde superior: el `margin-top: 6mm` de `.r-method` se descarta cuando la sección cae al inicio de una página nueva (fragmentación CSS), quedando solo el margen del `@page` (16mm), con la mitad inferior de la página vacía.

### Fix
- Subir el margen superior de las páginas 2+: `@page { size: A4; margin: 16mm 0 }` → `@page { size: A4; margin: 22mm 0 0 }` reservando también el inferior necesario. Concretamente: `margin: 22mm 0 16mm` (sup 22mm, lat 0, inf 16mm).
- **No tocar la portada**: `@page :first { margin: 0 0 16mm }` se mantiene (banda a sangre arriba).

### Verificación
- Regenerar el PDF (CDP printToPDF) y comprobar: pág. 2 con el título de Metodología claramente más aireado; pág. 1 (portada) idéntica.

## Restricciones heredadas
- 100% offline; ECharts vendorizado; sin build step; secreto estadístico → vacío/null, nunca 0; `.venv/bin/pytest` verde (estos cambios son frontend/CSS, sin impacto en tests Python, pero la suite debe seguir verde).
