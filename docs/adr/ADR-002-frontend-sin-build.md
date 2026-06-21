# ADR-002: Frontend vanilla sin build step, ECharts vendorizado

**Estado:** Aceptada · 2026-06-11

## Contexto
La herramienta debe funcionar offline en el equipo local, arrancar con un comando y no romperse jamás en vivo. El usuario tipo compara mentalmente con Power BI.

## Decisión
SPA en `web/` con HTML + CSS + JS vanilla (ES modules) y ECharts 5.5 vendorizado en `web/vendor/echarts.min.js`. FastAPI la sirve como estáticos. Sin npm, sin bundler, sin CDN en runtime.

## Alternativas descartadas
- **React + Vite:** build step, node_modules, más superficie de fallo; el alcance de UI (una pantalla, 3 zonas) no lo justifica.
- **Streamlit/Dash:** estética de prototipo; rechazado ya en la fase de enfoque.
- **CDN para ECharts:** rompe el requisito offline.

## Consecuencias
Cero dependencias de frontend en runtime; el coste es escribir DOM a mano, asumible para una pantalla. ECharts da el nivel visual "Power BI" que exige el contexto de uso.
