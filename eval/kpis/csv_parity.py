"""KPI: CSV Export Parity (capa Exportaciones, tier guardrail, id csv_parity).

Compara el contenido de los CSV exportados (capturados en bundle.json) con los
datos de api_market a la precisión que ve el usuario:
  - monthly  → Periodo;Euros;Estado
  - yearly   → Año;Exportación (€);Valor unitario (€/kg)
  - season   → Mes;Cuota media (%)
  - provinces → Provincia;Exportación 12m (€);Cuota nacional (%)

score = % de celdas que coinciden sobre el total de celdas evaluadas.
Un valor vacío en el CSV corresponde a null en api; null ≠ 0 (regla dura).
"""

import io
import csv as _csv

from eval.kpis._util import kpi, status_from, parse_es_number, approx, pct

# Nombres abreviados de mes en español (como los genera la app)
_MES_NAMES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def _parse_csv(text):
    """Parsea CSV es-ES (sep=';', decimal=',', posible BOM).
    Devuelve lista de listas de strings (celdas ya stripped).
    Ignora filas de cabecera (primera fila) y líneas vacías.
    """
    if not text:
        return []
    # Quitar BOM si existe
    if text.startswith("﻿"):
        text = text[1:]
    reader = _csv.reader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    # Quitar cabecera (primera fila) y filas vacías
    return [[c.strip() for c in row] for row in rows[1:] if any(c.strip() for c in row)]


def _csv_num(s, decimals):
    """Convierte número es-ES a float redondeado a `decimals` dígitos.
    Cadena vacía / guion → None (campo vacío = null, NUNCA 0).
    """
    v = parse_es_number(s)
    if v is None:
        return None
    return round(v, decimals)


# ─────────────────────────────── checkers por kind ────────────────────────────

def _check_monthly(csv_rows, api_monthly):
    """Columnas: Periodo;Euros;Estado.
    Euros → entero; Estado = 'Provisional' si is_provisional, si no 'Definitivo'.
    """
    ok = total = 0
    mismatches = []
    api_by_period = {r["period"]: r for r in api_monthly}

    for row in csv_rows:
        if len(row) < 3:
            continue
        periodo, euros_str, estado = row[0], row[1], row[2]
        ref = api_by_period.get(periodo)
        if ref is None:
            # Periodo en CSV no existe en api → fallo de paridad
            total += 3
            mismatches.append(f"periodo {periodo} no encontrado en api_market")
            continue

        # Celda Periodo (string)
        total += 1
        if periodo == ref["period"]:
            ok += 1

        # Celda Euros (entero). JS usa toFixed(0) que redondea .5 al alza;
        # Python round() usa "banker's rounding" (.5 → par). Para no penalizar
        # esa diferencia comparamos el entero del CSV contra el valor crudo de
        # la API con tolerancia abs_=0.5 (cualquier redondeo de .5 es aceptable).
        total += 1
        csv_euros = _csv_num(euros_str, 0)
        api_euros_raw = ref["euros"]
        if approx(csv_euros, api_euros_raw, abs_=0.5):
            ok += 1
        else:
            mismatches.append(
                f"monthly {periodo}: Euros csv={csv_euros!r} api={api_euros_raw!r}"
            )

        # Celda Estado
        total += 1
        esperado = "Provisional" if ref["is_provisional"] else "Definitivo"
        if estado == esperado:
            ok += 1
        else:
            mismatches.append(
                f"monthly {periodo}: Estado csv={estado!r} esperado={esperado!r}"
            )

    return ok, total, mismatches


def _check_yearly(csv_rows, api_yearly):
    """Columnas: Año;Exportación (€);Valor unitario (€/kg).
    Euros → entero; UV → 2 decimales (null si kilos es null).
    """
    ok = total = 0
    mismatches = []
    api_by_year = {r["year"]: r for r in api_yearly}

    for row in csv_rows:
        if len(row) < 3:
            continue
        anio_str, euros_str, uv_str = row[0], row[1], row[2]
        try:
            anio = int(anio_str)
        except (ValueError, TypeError):
            continue
        ref = api_by_year.get(anio)
        if ref is None:
            total += 3
            mismatches.append(f"yearly año {anio} no encontrado en api_market")
            continue

        # Año
        total += 1
        if anio == ref["year"]:
            ok += 1

        # Exportación (€) → entero (misma tolerancia .5 que en monthly)
        total += 1
        csv_euros = _csv_num(euros_str, 0)
        api_euros_raw = ref["euros"]
        if approx(csv_euros, api_euros_raw, abs_=0.5):
            ok += 1
        else:
            mismatches.append(
                f"yearly {anio}: Euros csv={csv_euros!r} api={api_euros_raw!r}"
            )

        # Valor unitario (€/kg) → 2 decimales
        total += 1
        csv_uv = _csv_num(uv_str, 2)
        api_uv = ref.get("unit_value")
        if api_uv is not None:
            api_uv_r = round(api_uv, 2)
        else:
            api_uv_r = None
        if approx(csv_uv, api_uv_r, abs_=0.005):
            ok += 1
        else:
            mismatches.append(
                f"yearly {anio}: UV csv={csv_uv!r} api_rounded={api_uv_r!r} (raw={api_uv!r})"
            )

    return ok, total, mismatches


def _check_season(csv_rows, api_seasonality):
    """Columnas: Mes;Cuota media (%).
    Mes → nombre abreviado español (ene, feb, …).
    Cuota → avg_share * 100, 2 decimales.
    """
    ok = total = 0
    mismatches = []
    api_by_month = {r["month"]: r for r in api_seasonality}

    for row in csv_rows:
        if len(row) < 2:
            continue
        mes_str, cuota_str = row[0], row[1]

        # Buscar mes por nombre
        mes_num = None
        for num, nombre in _MES_NAMES.items():
            if mes_str.lower() == nombre:
                mes_num = num
                break
        if mes_num is None:
            total += 2
            mismatches.append(f"season mes desconocido: {mes_str!r}")
            continue

        ref = api_by_month.get(mes_num)
        if ref is None:
            total += 2
            mismatches.append(f"season mes {mes_str} (num={mes_num}) no en api")
            continue

        # Celda Mes
        total += 1
        esperado_mes = _MES_NAMES[mes_num]
        if mes_str.lower() == esperado_mes:
            ok += 1

        # Celda Cuota media (%)
        total += 1
        csv_cuota = _csv_num(cuota_str, 2)
        api_cuota = round(ref["avg_share"] * 100, 2) if ref["avg_share"] is not None else None
        if approx(csv_cuota, api_cuota, abs_=0.005):
            ok += 1
        else:
            mismatches.append(
                f"season {mes_str}: cuota csv={csv_cuota!r} api={api_cuota!r} (raw={ref['avg_share']!r})"
            )

    return ok, total, mismatches


def _check_provinces(csv_rows, api_provinces):
    """Columnas: Provincia;Exportación 12m (€);Cuota nacional (%).
    Euros → entero; cuota → share*100 a 2 decimales.
    """
    ok = total = 0
    mismatches = []
    api_by_name = {r["name"]: r for r in api_provinces}

    for row in csv_rows:
        if len(row) < 3:
            continue
        prov_str, euros_str, cuota_str = row[0], row[1], row[2]
        ref = api_by_name.get(prov_str)
        if ref is None:
            total += 3
            mismatches.append(f"provinces: provincia {prov_str!r} no en api")
            continue

        # Provincia (string)
        total += 1
        if prov_str == ref["name"]:
            ok += 1

        # Exportación 12m (€) → entero (misma tolerancia .5 que en monthly)
        total += 1
        csv_euros = _csv_num(euros_str, 0)
        api_euros_raw = ref["euros_12m"]
        if approx(csv_euros, api_euros_raw, abs_=0.5):
            ok += 1
        else:
            mismatches.append(
                f"provinces {prov_str}: Euros csv={csv_euros!r} api={api_euros_raw!r}"
            )

        # Cuota nacional (%) → share*100 a 2 decimales
        total += 1
        csv_cuota = _csv_num(cuota_str, 2)
        api_cuota = round(ref["share"] * 100, 2) if ref["share"] is not None else None
        if approx(csv_cuota, api_cuota, abs_=0.005):
            ok += 1
        else:
            mismatches.append(
                f"provinces {prov_str}: cuota csv={csv_cuota!r} api={api_cuota!r}"
            )

    return ok, total, mismatches


# ─────────────────────────────────── main ─────────────────────────────────────

def check(bundle, con):
    """Scorer csv_parity.

    Recorre bundle['evidence'] (ignora items con clave 'error') y compara cada
    CSV exportado contra api_market a la precisión de display del usuario.
    Devuelve un dict kpi() con score = % de celdas correctas (0-100).
    """
    total_ok = 0
    total_cells = 0
    all_mismatches = []
    pairs_checked = 0
    pairs_skipped = 0

    # Contadores por kind para el detalle
    kind_ok = {"monthly": 0, "yearly": 0, "season": 0, "provinces": 0}
    kind_total = {"monthly": 0, "yearly": 0, "season": 0, "provinces": 0}

    for item in bundle.get("evidence", []):
        # Ignorar items con error (evidencia incompleta)
        if "error" in item:
            pairs_skipped += 1
            continue

        taric = item.get("taric", "?")
        cc = item.get("country_code", "?")
        csv_data = item.get("csv", {})
        am = item.get("api_market", {})

        pairs_checked += 1

        # monthly
        csv_monthly = csv_data.get("monthly")
        api_monthly = am.get("monthly", [])
        if csv_monthly is not None and api_monthly:
            rows = _parse_csv(csv_monthly)
            ok, tot, mm = _check_monthly(rows, api_monthly)
            total_ok += ok
            total_cells += tot
            kind_ok["monthly"] += ok
            kind_total["monthly"] += tot
            for m in mm:
                all_mismatches.append(f"[{taric}/{cc}] {m}")

        # yearly
        csv_yearly = csv_data.get("yearly")
        api_yearly = am.get("yearly", [])
        if csv_yearly is not None and api_yearly:
            rows = _parse_csv(csv_yearly)
            ok, tot, mm = _check_yearly(rows, api_yearly)
            total_ok += ok
            total_cells += tot
            kind_ok["yearly"] += ok
            kind_total["yearly"] += tot
            for m in mm:
                all_mismatches.append(f"[{taric}/{cc}] {m}")

        # season
        csv_season = csv_data.get("season")
        api_season = am.get("seasonality", [])
        if csv_season is not None and api_season:
            rows = _parse_csv(csv_season)
            ok, tot, mm = _check_season(rows, api_season)
            total_ok += ok
            total_cells += tot
            kind_ok["season"] += ok
            kind_total["season"] += tot
            for m in mm:
                all_mismatches.append(f"[{taric}/{cc}] {m}")

        # provinces
        csv_prov = csv_data.get("provinces")
        api_prov = am.get("provinces", [])
        if csv_prov is not None and api_prov:
            rows = _parse_csv(csv_prov)
            ok, tot, mm = _check_provinces(rows, api_prov)
            total_ok += ok
            total_cells += tot
            kind_ok["provinces"] += ok
            kind_total["provinces"] += tot
            for m in mm:
                all_mismatches.append(f"[{taric}/{cc}] {m}")

    score = pct(total_ok, total_cells)

    # Resumen por kind para el campo value
    value = {
        "pairs_checked": pairs_checked,
        "pairs_skipped": pairs_skipped,
        "cells_ok": total_ok,
        "cells_total": total_cells,
        "by_kind": {
            k: {"ok": kind_ok[k], "total": kind_total[k]}
            for k in ("monthly", "yearly", "season", "provinces")
        },
        "mismatches_sample": all_mismatches[:10],
    }
    target = {"cells_ok": total_cells, "score": 100.0}

    n_mm = len(all_mismatches)
    if score is None:
        detail = "Sin datos medibles (no hay CSV ni api_market en el bundle)."
    elif n_mm == 0:
        detail = (
            f"{total_ok}/{total_cells} celdas correctas ({score}%) en "
            f"{pairs_checked} pares; ninguna discrepancia."
        )
    else:
        detail = (
            f"{total_ok}/{total_cells} celdas correctas ({score}%) en "
            f"{pairs_checked} pares; {n_mm} discrepancias — "
            f"primera: {all_mismatches[0]}"
        )

    return kpi("csv_parity", "Exportaciones", "CSV Export Parity", "guardrail",
               score, value=value, target=target, detail=detail)
