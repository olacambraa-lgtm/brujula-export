# Contrato de API — Brújula Export (fuente de verdad para backend y frontend)

Todas las respuestas son JSON UTF-8. Errores: `{"detail": "<mensaje en español>"}` con código HTTP apropiado.

## GET /api/meta

```json
{
  "extracted_at": "2026-06-11",
  "period_min": "2015-01",
  "period_max": "2026-03",
  "provisional_from": "2024-01",
  "n_products": 1200,
  "n_countries": 230,
  "source": "DataComex — Secretaría de Estado de Comercio. Comercio declarado (~98% del total).",
  "disclaimer": "Datos 2024 en adelante provisionales. Celdas con ≤5 operadores ocultas por secreto estadístico."
}
```

## GET /api/search?q=texto

`q` puede ser texto libre (búsqueda en descripción, sin acentos, case-insensitive) o prefijo numérico de código. Máximo 20 resultados, ordenados por: prefijo numérico exacto primero, luego nivel 4 antes que 6/8, luego valor exportado descendente.

```json
{"results": [{"taric": "2204", "description": "Vino de uvas frescas...", "level": 4, "has_data": true}]}
```

Sin resultados: `{"results": [], "suggestion": "Prueba con 'vino' o un código como 2204"}`.

## GET /api/score/{taric}

404 si el TARIC no existe en nomenclatura. Si existe pero hay <5 países candidatos (export > 0 en últimos 3 años): 200 con `"warning"` y `countries` con lo que haya. Sin ningún candidato, `total_exports_12m` es `null` (nunca un 0 fabricado) y `period_window` puede ser `null` si la base no tiene datos de comercio.

```json
{
  "taric": "2204",
  "description": "Vino de uvas frescas...",
  "total_exports_12m": 2950000000.0,
  "aragon_share": 0.034,
  "zaragoza_share": 0.021,
  "period_window": {"from": "2025-04", "to": "2026-03"},
  "n_candidates": 87,
  "warning": null,
  "default_weights": {"size": 0.25, "growth": 0.25, "stability": 0.15, "unit_value": 0.15, "competition": 0.10, "access": 0.10},
  "countries": [
    {
      "country_code": "FR", "name": "Francia", "iso2": "FR", "region": "Europa occidental", "eu_member": true,
      "metrics": {
        "size_eur_12m": 410000000.0,
        "cagr_3y": 0.12,
        "stability_cv": 0.18,
        "unit_value_eur_kg": 3.2,
        "unit_value_rel": 1.4,
        "eur_per_operator": 80000.0,
        "num_operators": 321,
        "access": "UE"
      },
      "components": {"size": 98, "growth": 55, "stability": 70, "unit_value": 62, "competition": 40, "access": 100},
      "flags": []
    }
  ]
}
```

Reglas:
- `components`: percentiles 0-100 entre los países candidatos de ESE producto (método: rank average / (n-1) × 100; si n=1 → 50). Métrica incalculable → componente **50** (neutro) + flag correspondiente (`nd_size`, `nd_growth`, `nd_unit_value`, `nd_operators`, `nd_stability`). `nd_size` solo aparece cuando hay filas en la ventana 12m pero su suma es NULL (celdas ocultas); un país sin filas tiene tamaño 0 legítimo sin flag.
- `cagr_3y`: CAGR sobre los valores ANUALES brutos del país; null si falta histórico (<3 años completos con valor > 0). Para el componente `growth`, el vector de CAGRs del conjunto candidato se winsoriza a p5-p95 antes del ranking percentil (modera crecimientos desde base mínima sin aplastar la señal de los mercados grandes; `metrics.cagr_3y` siempre muestra el bruto).
- `stability_cv`: coeficiente de variación de los últimos 5 valores anuales (mínimo 3); el componente usa 1−percentil(cv).
- `unit_value_rel`: €/kg del país / mediana de €/kg de candidatos (12m); null si kilos = 0.
- `access`: "UE" (componente 100), "EFTA/Acuerdo UE" (75), "Resto" (40). Tabla estática en `countries`.
- `flags` incluye `low_data` si el país tiene <12 meses con dato en los últimos 5 años.
- El score final NO viene del backend: lo calcula el frontend como `Σ(w_i × component_i) / Σ(w_i)`.
- `metrics` con valores null donde no calculable; nunca 0 fabricado.
- `aragon_share`/`zaragoza_share`: cuota provincial (Zaragoza+Huesca+Teruel / solo Zaragoza) sobre exportación nacional del producto, 12m; null si sin datos provinciales.

## GET /api/market/{taric}/{country_code}

404 si no hay datos para el par.

```json
{
  "taric": "2204", "description": "Vino...",
  "country": {"country_code": "FR", "name": "Francia", "iso2": "FR", "region": "Europa occidental", "eu_member": true},
  "monthly": [{"period": "2015-01", "euros": 1000.0, "kilos": 500.0, "is_provisional": false}],
  "yearly": [{"year": 2015, "euros": 12000.0, "kilos": 6000.0, "unit_value": 2.0}],
  "seasonality": [{"month": 1, "avg_share": 0.07}],
  "operators": [{"year": 2020, "num_operators": 12, "euros": 340000.0}],
  "provinces": [{"province_code": "50", "name": "Zaragoza", "euros_12m": 1000000.0, "share": 0.21}],
  "spain_total_12m": 2950000000.0,
  "country_share_12m": 0.139
}
```

- `seasonality`: cuota media de cada mes sobre el total de su año, solo años completos y definitivos; lista vacía si <2 años completos.
- `provinces`: top 8 por valor 12m + siempre Zaragoza (50), Huesca (22) y Teruel (44) si tienen dato; `share` sobre total nacional del producto.
- `operators`: años con dato; `num_operators` null = secreto estadístico (el frontend muestra "n/d").

## GET /

Sirve `web/index.html`. Estáticos bajo `/static/*` → `web/*`.
