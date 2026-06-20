"""Scorer del KPI 'PNG Export Success Rate' (capa Exportaciones, tier guardrail).

Mide el porcentaje de gráficas presentes con datos que se exportan exitosamente
a PNG. Una gráfica sin datos (no presente o sin has_data=True) NO cuenta como fallo.

Un PNG exitoso requiere:
  - ok=True
  - sig_ok=True (firma PNG válida)
  - width>0 y height>0
  - bytes >= 1000 (tamaño razonable)

score = (PNGs exitosos) / (intentos sobre gráficas presentes con datos)
"""

from eval.kpis._util import kpi, status_from, pct


def check(bundle, con):
    """
    Recorre bundle['evidence'], ignora items con 'error'.

    Para cada par (taric, country_code):
      - Mapeo: chart-monthly -> png.monthly, chart-yearly -> png.yearly, etc.
      - Para cada gráfica en chart_inventory:
        - Si present=True y has_data=True: cuenta como "intento"
        - Si png[kind].ok=True y sig_ok=True y width>0 y height>0 y bytes>=1000:
          es "éxito"; sino, acumula fallo
    """
    # Mapeo de keys de chart_inventory a keys de png
    chart_to_png = {
        "chart-monthly": "monthly",
        "chart-yearly": "yearly",
        "chart-season": "season",
        "chart-provinces": "provinces",
    }

    total_attempts = 0
    total_success = 0
    failures = []

    for item in bundle.get("evidence", []):
        # Saltar items con error
        if "error" in item:
            continue

        taric = item.get("taric")
        country_code = item.get("country_code")
        chart_inventory = item.get("chart_inventory", {})
        png_data = item.get("png", {})

        # Para cada gráfica potencial
        for chart_kind, png_key in chart_to_png.items():
            inv = chart_inventory.get(chart_kind, {})
            # Contar solo si la gráfica está presente Y tiene datos
            if inv.get("present") and inv.get("has_data"):
                total_attempts += 1

                pnginfo = png_data.get(png_key, {})
                # Verificar que cumple todos los criterios de éxito
                is_ok = (
                    pnginfo.get("ok") is True
                    and pnginfo.get("sig_ok") is True
                    and pnginfo.get("width", 0) > 0
                    and pnginfo.get("height", 0) > 0
                    and pnginfo.get("bytes", 0) >= 1000
                )

                if is_ok:
                    total_success += 1
                else:
                    # Registrar el fallo con razón
                    reason = []
                    if pnginfo.get("ok") is not True:
                        reason.append("ok=False")
                    if pnginfo.get("sig_ok") is not True:
                        reason.append("sig_ok=False")
                    if pnginfo.get("width", 0) <= 0:
                        reason.append(f"width={pnginfo.get('width')}")
                    if pnginfo.get("height", 0) <= 0:
                        reason.append(f"height={pnginfo.get('height')}")
                    if pnginfo.get("bytes", 0) < 1000:
                        reason.append(f"bytes={pnginfo.get('bytes')}")
                    failures.append(
                        {
                            "taric": taric,
                            "country_code": country_code,
                            "chart": chart_kind,
                            "reason": ", ".join(reason),
                        }
                    )

    # Calcular score: porcentaje de éxito
    score = pct(total_success, total_attempts)

    return kpi(
        "png_success",
        "Exportaciones",
        "PNG Export Success Rate",
        "guardrail",
        score,
        value={"ok": total_success, "attempts": total_attempts, "failures": failures},
        target={"rate": 100.0},
        detail=f"{total_success}/{total_attempts} PNGs exportados exitosamente "
        f"({score:.1f}% si es calculable).",
    )
