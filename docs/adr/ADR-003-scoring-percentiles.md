# ADR-003: Scoring por percentiles con pesos ajustables en cliente

**Estado:** Aceptada · 2026-06-11

## Contexto
Las métricas tienen escalas incomparables (€, %, €/kg, €/operador). El público es técnico (consultores de internacionalización): desconfiará de una "nota mágica" opaca.

## Decisión
Cada métrica se normaliza a percentil [0,100] **dentro del conjunto de países candidatos del producto consultado**. Score final = suma ponderada. El backend devuelve los componentes sin ponderar; la suma ponderada vive en el frontend, donde los sliders de pesos reordenan el ranking al instante sin nueva petición.

## Alternativas descartadas
- **Z-scores:** sensibles a outliers extremos (típicos en comercio exterior: un país puede ser 100× el siguiente); los percentiles son robustos y explicables ("este país está en el percentil 90 de crecimiento").
- **Min-max:** un solo outlier comprime el resto del rango a ~0.
- **Ponderación en backend:** obligaría a round-trip por cada movimiento de slider; matar la fluidez destruye la experiencia interactiva.

## Consecuencias
Score explicable componente a componente (clave para la credibilidad y explicabilidad); ranking relativo al producto (no comparable entre productos, se documenta en la metodología); winsorización p5-p95 previa al CAGR para evitar que rebotes desde base ~0 dominen.
