"""KPI: Chart Completeness Rate — verificar que todas las gráficas esperadas
se renderizan correctamente (present=true, has_data=true) en la UI.

La expectativa de gráficas se determina por los datos disponibles en api_market:
- 'monthly' y 'yearly': SIEMPRE esperadas (si el par tiene datos)
- 'season': esperada SOLO si api_market.seasonality tiene ≥1 elemento
- 'provinces': esperada SOLO si api_market.provinces tiene ≥1 elemento

Score = (gráficas esperadas que renderizan con datos) / (gráficas esperadas)
sobre TODOS los pares. No penalizamos gráficas ausentes que no se esperaban.
"""

from eval.kpis._util import kpi, status_from, pct


def check(bundle, con):
    """
    bundle: {"evidence": [item...], ...}
    item: {"taric", "country_code", "chart_inventory", "api_market", ...}

    Ignoramos items con clave 'error'.
    """

    evidence = bundle.get("evidence", [])

    # Ignorar items con error
    items = [ev for ev in evidence if "error" not in ev]

    if not items:
        return kpi(
            "chart_completeness",
            "Gráficas",
            "Chart Completeness Rate",
            "guardrail",
            score=None,
            value={},
            target={},
            detail="sin evidencias válidas"
        )

    total_expected = 0
    total_rendered = 0
    missing_charts = []

    for item in items:
        taric = item.get("taric")
        country_code = item.get("country_code")
        api_market = item.get("api_market", {})
        chart_inventory = item.get("chart_inventory", {})

        # Determinar gráficas esperadas
        expected = ["monthly", "yearly"]

        if api_market.get("seasonality"):
            expected.append("season")

        if api_market.get("provinces"):
            expected.append("provinces")

        # Mapeo de nombres esperados a claves en chart_inventory
        chart_key_map = {
            "monthly": "chart-monthly",
            "yearly": "chart-yearly",
            "season": "chart-season",
            "provinces": "chart-provinces",
        }

        # Contar gráficas esperadas que se renderizan
        for chart_name in expected:
            total_expected += 1
            chart_key = chart_key_map[chart_name]

            inv_entry = chart_inventory.get(chart_key, {})

            # Gráfica esperada se cuenta como renderizada si present=true y has_data=true
            if inv_entry.get("present") and inv_entry.get("has_data"):
                total_rendered += 1
            else:
                missing_charts.append({
                    "taric": taric,
                    "country_code": country_code,
                    "chart": chart_name,
                    "present": inv_entry.get("present", False),
                    "has_data": inv_entry.get("has_data", False),
                })

    # Calcular score como porcentaje
    score = pct(total_rendered, total_expected) if total_expected else None

    # Detalles para el reporte
    detail_parts = [
        f"{total_rendered}/{total_expected} gráficas esperadas renderizadas",
    ]

    if missing_charts:
        detail_parts.append(f"({len(missing_charts)} ausentes o incompletas)")

    return kpi(
        "chart_completeness",
        "Gráficas",
        "Chart Completeness Rate",
        "guardrail",
        score=score,
        value={
            "expected": total_expected,
            "rendered": total_rendered,
            "missing": missing_charts[:10],  # top 10 para el reporte
        },
        target={
            "expected": total_expected,
            "rendered": total_expected,  # objetivo: 100%
        },
        detail="; ".join(detail_parts)
    )
