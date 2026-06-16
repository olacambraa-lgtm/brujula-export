# ADR-005: Eliminar el análisis IA pregenerado en favor de un resumen ejecutivo determinista

**Estado:** Aceptada · 2026-06-16 · **Supersede a ADR-004**

## Contexto
La auditoría UX/UI detectó incoherencias sistémicas del bloque "Análisis del analista (IA)": no se actualizaba con los pesos ni con el país (era idéntico para cualquier país del mismo producto), su "top-3" textual no coincidía con el ranking visible por score, y solo existía para 6 productos estrella. Al no haber modelo en runtime (los `insights/<taric>.md` eran estáticos pregenerados, ADR-004), la feature no es extrapolable al resto del catálogo y genera más confusión que valor.

## Decisión
Eliminar la feature por completo: endpoint `GET /api/insights/{taric}`, `app/insights.py`, el panel y estilos del frontend, y los ficheros `insights/*.md`.

En su lugar, el **informe imprimible** incorpora un **resumen ejecutivo determinista** generado de los datos del panel y de los pesos vigentes (producto, exportación 12 m, cuotas Aragón/Zaragoza, perfil de pesos normalizado, top-5 por score con cifras clave y una cautela metodológica). Un botón "Copiar resumen" exporta ese resumen como texto plano/markdown para que el usuario lo use como contexto en una IA externa, fuera de la app.

## Alternativas descartadas
- **Arreglar el análisis IA pregenerado** (etiquetarlo "del producto", avisar de pesos personalizados): mantiene una feature que no escala al catálogo completo y sigue siendo estática.
- **Generar el análisis con IA en runtime:** prohibido por el requisito de coste/offline (ADR-004 sigue vigente en ese principio).

## Consecuencias
- Se simplifica la herramienta y desaparece la incoherencia ranking ↔ texto.
- El valor analítico se traslada a un artefacto determinista, reproducible y copiable, válido para cualquier producto y para cualquier configuración de pesos.
- Cero IA en runtime se mantiene; el coste marginal sigue siendo nulo.
