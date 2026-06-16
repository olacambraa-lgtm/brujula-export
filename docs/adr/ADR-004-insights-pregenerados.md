# ADR-004: Insights IA pregenerados con Claude Code (cero tokens en runtime)

**Estado:** Superseded by [ADR-005](ADR-005-eliminar-insights.md) · 2026-06-16 (la feature de insights se elimina; el principio "cero tokens en runtime" sigue vigente) — original: Aceptada · 2026-06-11

## Contexto
Requisito del usuario: la herramienta no debe consumir tokens de API externa; todo gasto de IA va contra la suscripción de Claude Code. La demo debe ser instantánea y funcionar sin red.

## Decisión
Claude Code analiza los datos reales del DuckDB **antes** de la reunión y escribe `insights/<taric>.md` para 5-6 productos estrella aragoneses, con estructura fija (lectura del ranking, mercado destacado, riesgo, recomendación, cautelas). La app solo lee ficheros. Etiqueta visible: "Generado con IA · revisado por el analista".

## Alternativas descartadas
- **Llamadas API en runtime:** prohibido por requisito (coste) y añade riesgo de red/latencia en vivo.
- **Ollama embebido:** calidad de análisis notablemente inferior y complejidad de instalación; rechazado en fase de enfoque.

## Consecuencias
Los insights son estáticos (válidos mientras no se recargue el ETL — aceptable: los datos están congelados para la demo). Si la reunión va bien, se puede regenerar uno en vivo con Claude Code como "extra" opcional, fuera del flujo de la app.
