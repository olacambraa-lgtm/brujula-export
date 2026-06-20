"""KPI: Graph-to-Data Parity (graph_parity) — capa Gráficas, tier guardrail.

Mide que cada punto/barra de cada gráfica coincide con el dato real de api_market.
score = % de puntos que casan (a precisión de display) sobre el total comparado
en TODAS las gráficas de TODOS los pares del bundle.

Reglas de comparación por gráfica:
- chart-monthly : series Definitivo/Provisional; empareja por periodo del xAxis.
  En cada periodo, el valor no nulo (o ambos en el empalme) debe igualar
  api_market.monthly[periodo].euros. Tolerancia: approx() con abs_=0.5 (euros enteros).
- chart-yearly  : xAxis de años; series 'Exportación (€)' y 'Valor unitario (€/kg)'.
  Los items pueden ser dicts con clave 'value'. Tolerancia euros: abs_=0.5; €/kg: abs_=0.005.
- chart-season  : 12 barras en % (avg_share × 100). Tolerancia: abs_=0.01 (2 decimales de %).
  Cuando avg_share=0.0 la gráfica muestra 0 — es correcto, no es NULL (no aplica la regla
  de secreto estadístico; la cuota cero es un dato genuino).
- chart-provinces: barras en orden INVERSO respecto al orden de la API (la API devuelve
  desc por euros; el gráfico horizontal apila de menor a mayor visualmente).
  Cuando api_market.provinces está vacío no hay puntos esperados para ese gráfico.

Regla dura del proyecto: NULL ≠ 0. Un valor None en la API NUNCA se compara con 0.
"""

from eval.kpis._util import kpi, status_from, approx, pct


def _extract_value(item):
    """Extrae el float de un item de serie, que puede ser un dict {value:...} o un escalar."""
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get("value")
    return item


def _check_monthly(charts, api_monthly):
    """Compara chart-monthly contra api_market.monthly.

    Retorna (ok, total, fallos[]).
    """
    ok = total = 0
    fallos = []

    ch = charts.get("chart-monthly")
    if not ch or not ch.get("xAxis") or not ch.get("series"):
        return ok, total, fallos

    xaxis = ch["xAxis"][0] if ch["xAxis"] else []
    series = ch["series"]
    # Localizar series por nombre
    def_data = prov_data = None
    for s in series:
        name = s.get("name", "")
        if name == "Definitivo":
            def_data = s["data"]
        elif name == "Provisional":
            prov_data = s["data"]

    if def_data is None or prov_data is None:
        return ok, total, fallos

    # Índice de la API por periodo
    api_by_period = {m["period"]: m["euros"] for m in api_monthly}

    for j, periodo in enumerate(xaxis):
        api_euros = api_by_period.get(periodo)
        if api_euros is None:
            # Periodo no presente en la API: esperamos None en ambas series
            continue

        d_val = def_data[j]
        p_val = prov_data[j]

        # El valor de la gráfica es el no-None entre las dos series.
        # En el empalme ambos pueden coincidir con el mismo valor.
        chart_val = None
        if d_val is not None:
            chart_val = d_val
        if p_val is not None:
            # Si def también tiene valor, ambos deben coincidir entre sí y con la API.
            if chart_val is not None and not approx(d_val, p_val, abs_=0.5):
                # Divergencia interna entre series en el empalme — contamos como fallo
                total += 1
                fallos.append(f"monthly {periodo}: def={d_val} prov={p_val} (divergen en empalme)")
                continue
            chart_val = p_val

        if chart_val is None:
            # Ni def ni prov tienen dato para un periodo que SÍ está en la API
            total += 1
            fallos.append(f"monthly {periodo}: chart=None api={api_euros}")
            continue

        total += 1
        if approx(chart_val, api_euros, abs_=0.5):
            ok += 1
        else:
            fallos.append(f"monthly {periodo}: chart={chart_val} api={api_euros}")

    return ok, total, fallos


def _check_yearly(charts, api_yearly):
    """Compara chart-yearly contra api_market.yearly.

    Retorna (ok_euros, total_euros, ok_uv, total_uv, fallos[]).
    """
    ok_e = tot_e = ok_uv = tot_uv = 0
    fallos = []

    ch = charts.get("chart-yearly")
    if not ch or not ch.get("xAxis") or not ch.get("series"):
        return ok_e, tot_e, ok_uv, tot_uv, fallos

    xaxis = ch["xAxis"][0] if ch["xAxis"] else []
    series = ch["series"]

    euros_data = uv_data = None
    for s in series:
        name = s.get("name", "")
        if "€)" in name or "Exportaci" in name:
            euros_data = s["data"]
        elif "€/kg" in name or "Valor unitario" in name:
            uv_data = s["data"]

    api_by_year = {y["year"]: y for y in api_yearly}

    for j, year in enumerate(xaxis):
        api = api_by_year.get(year)
        if api is None:
            continue

        # Euros
        if euros_data is not None and j < len(euros_data):
            chart_e = _extract_value(euros_data[j])
            if chart_e is not None and api["euros"] is not None:
                tot_e += 1
                if approx(chart_e, api["euros"], abs_=0.5):
                    ok_e += 1
                else:
                    fallos.append(f"yearly {year} euros: chart={chart_e} api={api['euros']}")
            elif chart_e is None and api["euros"] is not None:
                tot_e += 1
                fallos.append(f"yearly {year} euros: chart=None api={api['euros']}")

        # Valor unitario (€/kg) — tolerancia 2 decimales (0.005)
        if uv_data is not None and j < len(uv_data):
            chart_uv = _extract_value(uv_data[j])
            if chart_uv is not None and api["unit_value"] is not None:
                tot_uv += 1
                if approx(chart_uv, api["unit_value"], rel=1e-6, abs_=0.005):
                    ok_uv += 1
                else:
                    fallos.append(f"yearly {year} uv: chart={chart_uv} api={api['unit_value']}")
            elif chart_uv is None and api["unit_value"] is not None:
                tot_uv += 1
                fallos.append(f"yearly {year} uv: chart=None api={api['unit_value']}")

    return ok_e, tot_e, ok_uv, tot_uv, fallos


def _check_season(charts, api_seasonality):
    """Compara chart-season (barras en %) contra api_market.seasonality (avg_share fracción).

    La gráfica muestra avg_share × 100, redondeado a 2 decimales.
    avg_share=0.0 → chart=0; es correcto (cuota real de cero, no secreto estadístico).
    Retorna (ok, total, fallos[]).
    """
    ok = total = 0
    fallos = []

    ch = charts.get("chart-season")
    if not ch or not ch.get("series") or not api_seasonality:
        return ok, total, fallos

    series = ch["series"]
    if not series:
        return ok, total, fallos

    chart_vals = series[0].get("data", [])

    # api_seasonality viene ordenado por mes (1..12)
    for j, ap in enumerate(api_seasonality):
        if j >= len(chart_vals):
            break
        api_pct = ap["avg_share"] * 100  # fracción → %
        chart_v = chart_vals[j]

        # avg_share puede ser 0.0 genuinamente (mes sin exportaciones).
        # chart muestra 0 en ese caso; approx(0, 0) → True.
        total += 1
        if approx(chart_v, api_pct, rel=1e-4, abs_=0.01):
            ok += 1
        else:
            fallos.append(f"season mes {ap['month']}: chart={chart_v} api_pct={round(api_pct,4)}")

    return ok, total, fallos


def _check_provinces(charts, api_provinces):
    """Compara chart-provinces contra api_market.provinces.

    Las barras están en orden INVERSO respecto a la API (la API devuelve desc por euros;
    el gráfico horizontal apila de menor a mayor, así que el primer item del array es la
    barra más pequeña abajo).
    Cuando api_provinces está vacío, no hay puntos a comparar (se omite el gráfico).
    Retorna (ok, total, fallos[]).
    """
    ok = total = 0
    fallos = []

    ch = charts.get("chart-provinces")
    if not ch or not ch.get("series"):
        return ok, total, fallos

    if not api_provinces:
        # Sin provincias en la API no hay referencia → no se puntúa este gráfico
        return ok, total, fallos

    series = ch["series"]
    if not series:
        return ok, total, fallos

    bars = series[0].get("data", [])
    # La API viene ordenada desc; la gráfica está en orden inverso (asc)
    api_reversed = list(reversed(api_provinces))

    for j, (bar, prov) in enumerate(zip(bars, api_reversed)):
        chart_val = _extract_value(bar)
        api_euros = prov["euros_12m"]

        if chart_val is None and api_euros is None:
            continue  # ambos nulos: no comparamos (secreto estadístico)
        if api_euros is None:
            # La API dice NULL → la gráfica no debería mostrar valor
            total += 1
            if chart_val is None:
                ok += 1
            else:
                fallos.append(f"provinces {prov['name']}: chart={chart_val} api=NULL")
            continue

        total += 1
        if chart_val is not None and approx(chart_val, api_euros, abs_=0.5):
            ok += 1
        else:
            fallos.append(f"provinces {prov['name']}: chart={chart_val} api={api_euros}")

    return ok, total, fallos


def check(bundle, con):  # noqa: ARG001  (con disponible por contrato de interfaz)
    """Scorer de Graph-to-Data Parity.

    Recorre bundle['evidence'] (ignora items con clave 'error') y acumula
    ok/total por tipo de gráfica. Retorna el dict kpi() estándar.
    """
    counts = {
        "monthly":   [0, 0],   # [ok, total]
        "yearly_e":  [0, 0],
        "yearly_uv": [0, 0],
        "season":    [0, 0],
        "provinces": [0, 0],
    }
    todos_los_fallos = []

    for ev in bundle.get("evidence", []):
        if "error" in ev:
            continue

        taric = ev.get("taric", "?")
        cc = ev.get("country_code", "?")
        prefijo = f"{taric}/{cc}"

        charts = ev.get("charts", {})
        am = ev.get("api_market", {})

        # chart-monthly
        ok_m, tot_m, f_m = _check_monthly(charts, am.get("monthly", []))
        counts["monthly"][0] += ok_m
        counts["monthly"][1] += tot_m
        todos_los_fallos.extend(f"{prefijo} | {f}" for f in f_m)

        # chart-yearly
        ok_e, tot_e, ok_uv, tot_uv, f_y = _check_yearly(charts, am.get("yearly", []))
        counts["yearly_e"][0] += ok_e
        counts["yearly_e"][1] += tot_e
        counts["yearly_uv"][0] += ok_uv
        counts["yearly_uv"][1] += tot_uv
        todos_los_fallos.extend(f"{prefijo} | {f}" for f in f_y)

        # chart-season
        ok_s, tot_s, f_s = _check_season(charts, am.get("seasonality", []))
        counts["season"][0] += ok_s
        counts["season"][1] += tot_s
        todos_los_fallos.extend(f"{prefijo} | {f}" for f in f_s)

        # chart-provinces
        ok_p, tot_p, f_p = _check_provinces(charts, am.get("provinces", []))
        counts["provinces"][0] += ok_p
        counts["provinces"][1] += tot_p
        todos_los_fallos.extend(f"{prefijo} | {f}" for f in f_p)

    # Score global: % de puntos correctos sobre el total comparado
    total_ok = sum(v[0] for v in counts.values())
    total_pts = sum(v[1] for v in counts.values())
    score = pct(total_ok, total_pts)

    # Value con conteos por tipo
    value = {
        "monthly_ok":    counts["monthly"][0],
        "monthly_total": counts["monthly"][1],
        "yearly_euros_ok":    counts["yearly_e"][0],
        "yearly_euros_total": counts["yearly_e"][1],
        "yearly_uv_ok":       counts["yearly_uv"][0],
        "yearly_uv_total":    counts["yearly_uv"][1],
        "season_ok":     counts["season"][0],
        "season_total":  counts["season"][1],
        "provinces_ok":  counts["provinces"][0],
        "provinces_total": counts["provinces"][1],
        "total_ok":  total_ok,
        "total_pts": total_pts,
        "sample_fails": todos_los_fallos[:10],
    }

    target = {
        "score": 100.0,
        "monthly": "todos los periodos",
        "yearly":  "todos los años (€ y €/kg)",
        "season":  "12 meses (% a 2 dec.)",
        "provinces": "por valor real (orden inverso al de la API)",
    }

    n_fail = len(todos_los_fallos)
    if score is None:
        detalle = "Sin puntos comparables en el bundle."
    else:
        detalle = (
            f"{total_ok}/{total_pts} puntos correctos ({score}%). "
            f"monthly {counts['monthly'][0]}/{counts['monthly'][1]}, "
            f"yearly_€ {counts['yearly_e'][0]}/{counts['yearly_e'][1]}, "
            f"yearly_€/kg {counts['yearly_uv'][0]}/{counts['yearly_uv'][1]}, "
            f"season {counts['season'][0]}/{counts['season'][1]}, "
            f"provinces {counts['provinces'][0]}/{counts['provinces'][1]}. "
            f"Fallos totales: {n_fail}."
        )
        if todos_los_fallos:
            detalle += " Primer fallo: " + todos_los_fallos[0]

    return kpi(
        "graph_parity",
        "Gráficas",
        "Graph-to-Data Parity",
        "guardrail",
        score,
        value=value,
        target=target,
        detail=detalle,
    )
