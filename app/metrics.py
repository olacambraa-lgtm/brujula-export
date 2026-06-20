"""Motor de scoring de Brújula Export.

Agregaciones en SQL (DuckDB) + winsorización y rankings percentiles en Python.
Contrato de salida: docs/specs/api-contract.md.
"""

import os
import threading
import re
import unicodedata
from bisect import bisect_left, bisect_right
from datetime import date
from math import floor, sqrt
from statistics import median

import duckdb

DEFAULT_WEIGHTS = {
    "size": 0.25, "growth": 0.25, "stability": 0.15,
    "unit_value": 0.15, "competition": 0.10, "access": 0.10,
}

ACCESS_COMPONENT = {"UE": 100.0, "EFTA/Acuerdo UE": 75.0, "Resto": 40.0}
MIN_CANDIDATES = 5  # mínimo de países para mostrar ranking sin aviso

PROVINCE_NAMES = {
    "50": "Zaragoza", "22": "Huesca", "44": "Teruel",
    "08": "Barcelona", "28": "Madrid", "46": "Valencia",
    "43": "Tarragona", "30": "Murcia", "48": "Vizcaya", "20": "Guipúzcoa",
}
ARAGON_PROVINCES = ("50", "22", "44")

SOURCE = "DataComex — Secretaría de Estado de Comercio. Comercio declarado (~98% del total)."
DISCLAIMER = ("Datos 2024 en adelante provisionales. "
              "Celdas con ≤5 operadores ocultas por secreto estadístico.")
SEARCH_SUGGESTION = "Prueba con 'vino' o un código como 2204"

# Filas de la nomenclatura que no son productos exportables y ensucian el
# buscador: placeholders sin descripción real ('=====(literal pendiente…'),
# agregados estadísticos de DataComex con letras en el código (XXSS tráfico
# confidencial, XXCC correcciones, XXMM comercio intracomunitario) y el capítulo
# 00 (comercio confidencial; no existe en la nomenclatura estándar). Se excluyen.
_SEARCH_JUNK = ("n.description NOT LIKE '=%' "
                "AND NOT regexp_matches(n.taric, '[A-Za-z]') "
                "AND n.taric NOT LIKE '00%'")


class Database:
    """Conexión DuckDB de solo lectura protegida con lock.

    DuckDB no es thread-safe sobre una misma conexión y FastAPI ejecuta los
    endpoints síncronos en un pool de hilos: cada consulta va dentro del lock.
    """

    def __init__(self, path):
        self.path = path
        self.con = duckdb.connect(path, read_only=True)
        self.lock = threading.Lock()

    def query(self, sql, params=()):
        with self.lock:
            return self.con.execute(sql, list(params)).fetchall()


# ------------------------------------------------------------ puras (units)

def winsorize(values, p_low=5.0, p_high=95.0):
    """Recorta los valores a los percentiles [p_low, p_high] (interpolación
    lineal, mismo método que numpy por defecto)."""
    n = len(values)
    if n == 0:
        return []
    ordered = sorted(values)

    def quantile(p):
        pos = p / 100 * (n - 1)
        lo = floor(pos)
        frac = pos - lo
        if frac == 0 or lo + 1 >= n:
            return ordered[lo]
        return ordered[lo] + frac * (ordered[lo + 1] - ordered[lo])

    lo_v, hi_v = quantile(p_low), quantile(p_high)
    return [min(max(v, lo_v), hi_v) for v in values]


def cagr_3y(values):
    """CAGR sobre los 3 últimos valores anuales (ya winsorizados).

    Null si no hay 3 años completos con valor > 0; un año NULL nunca se trata
    como 0.
    """
    if len(values) < 3:
        return None
    last3 = values[-3:]
    if any(v is None or v <= 0 for v in last3):
        return None
    return (last3[-1] / last3[0]) ** 0.5 - 1


def coef_variation(values):
    """Coeficiente de variación (std poblacional / media) de los valores no
    nulos; requiere mínimo 3. Los NULL se excluyen, nunca cuentan como 0."""
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None
    mean = sum(vals) / len(vals)
    # Media no positiva (devoluciones aduaneras netas): el CV pierde sentido y
    # uno negativo daría la mejor "estabilidad" al país más errático.
    if mean <= 0:
        return None
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    return sqrt(variance) / mean


def percentile_ranks(values):
    """Ranking percentil [0,100] por rank medio / (n−1) × 100.

    Los None reciben 50 (neutro) y no participan en el ranking del resto.
    Con un único valor no nulo → 50.
    """
    out = [50.0] * len(values)
    idx = [i for i, v in enumerate(values) if v is not None]
    if len(idx) <= 1:
        return out
    n = len(idx)
    ordered = sorted(values[i] for i in idx)
    for i in idx:
        v = values[i]
        rank = (bisect_left(ordered, v) + bisect_right(ordered, v) - 1) / 2
        out[i] = rank / (n - 1) * 100
    return out


def _add_months(d, n):
    total = d.year * 12 + (d.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


def _ym(d):
    return f"{d.year:04d}-{d.month:02d}"


def _normalize(text):
    """minúsculas + sin acentos, para búsqueda robusta."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _stem(token):
    """Stem ligero para español: quita plural (-es/-s) y vocal final de género."""
    if len(token) > 4 and token.endswith("es"):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    if len(token) > 3 and token[-1] in "oa":
        token = token[:-1]
    return token


# ------------------------------------------------------------------- meta

def get_meta(db):
    pmin, pmax = db.query(
        "SELECT min(period), max(period) FROM trade WHERE flow='X'")[0]
    prov = db.query(
        "SELECT min(period) FROM trade WHERE flow='X' AND is_provisional")[0][0]
    n_products, n_countries = db.query(
        "SELECT count(DISTINCT taric), count(DISTINCT country_code) "
        "FROM trade WHERE flow='X'")[0]
    try:
        extracted = db.query("SELECT extracted_at FROM meta_info")[0][0].isoformat()
    except Exception:  # DBs anteriores a la tabla meta_info (p.ej. sintético)
        extracted = date.fromtimestamp(os.path.getmtime(db.path)).isoformat()
    # is_synthetic: marca POSITIVA del generador sintético. Lectura tolerante: si
    # la tabla o la columna no existen (DBs reales antiguas, fixtures), por defecto
    # FALSE — nunca marcar como «demo» datos posiblemente reales. El banner del
    # frontend se basa solo en is_synthetic=TRUE explícito.
    try:
        is_synthetic = bool(db.query("SELECT is_synthetic FROM meta_info")[0][0])
    except Exception:
        is_synthetic = False
    return {
        "extracted_at": extracted,
        "period_min": _ym(pmin) if pmin else None,
        "period_max": _ym(pmax) if pmax else None,
        "provisional_from": _ym(prov) if prov else None,
        "n_products": n_products,
        "n_countries": n_countries,
        "is_synthetic": is_synthetic,
        "source": SOURCE,
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------ search

def search(db, q):
    q = q.strip()
    base = (
        "SELECT n.taric, n.description, n.level, t.total IS NOT NULL AS has_data "
        "FROM nomenclature n LEFT JOIN ("
        "  SELECT taric, sum(euros) AS total FROM trade "
        "  WHERE flow='X' AND province_code IS NULL GROUP BY taric"
        ") t USING (taric) "
    )
    if q.isdigit():
        numeric_sql = (
            base + f"WHERE {_SEARCH_JUNK} AND n.taric LIKE ? "
            "ORDER BY (n.taric = ?) DESC, n.level, t.total DESC NULLS LAST, n.taric "
            "LIMIT 20")
        rows = db.query(numeric_sql, (q + "%", q))
        if not rows and not q.startswith("0"):
            # Excel come los ceros iniciales: '203' → reintento como '0203'
            rows = db.query(numeric_sql, ("0" + q + "%", "0" + q))
    else:
        # Cada palabra de la consulta debe aparecer como prefijo de palabra en
        # la descripción, con stem ligero (quita plural y vocal de género): así
        # «porcino» encuentra «porcina» y «vinos» encuentra «vino». Relevancia:
        # las coincidencias del token sin stem (p.ej. «vino» en «vinos») van
        # antes que las que solo alcanza el stem (p.ej. «vin» en «vinagre»).
        tokens = [tok for tok in _normalize(q).split() if tok]
        if not tokens:
            return {"results": [], "suggestion": SEARCH_SUGGESTION}
        norm_desc = "lower(strip_accents(n.description))"
        condition = " AND ".join(
            f"regexp_matches({norm_desc}, ?)" for _ in tokens)
        relevance = " + ".join(
            f"CAST(regexp_matches({norm_desc}, ?) AS INT)" for _ in tokens)
        params = tuple("(^|[^a-z])" + re.escape(_stem(t)) for t in tokens) + \
            tuple("(^|[^a-z])" + re.escape(t) for t in tokens)
        rows = db.query(
            base + f"WHERE {_SEARCH_JUNK} AND {condition} "
            # has_data antes que n.level: un producto con datos va antes que un
            # capítulo "sin datos" de igual relevancia (no accionable arriba, §5.3).
            f"ORDER BY ({relevance}) DESC, (t.total IS NOT NULL) DESC, n.level, "
            "t.total DESC NULLS LAST, n.taric LIMIT 20",
            params)
    results = [
        {"taric": r[0], "description": r[1], "level": r[2], "has_data": bool(r[3])}
        for r in rows
    ]
    payload = {"results": results}
    if not results:
        payload["suggestion"] = SEARCH_SUGGESTION
    return payload


# ------------------------------------------------------------------ chapter

def chapter_index(db, code):
    """Índice de subpartidas (TARIC-4) de un capítulo (código de 2 dígitos).

    Para un código que no apunta a un producto concreto (un capítulo), devuelve
    sus subpartidas de 4 dígitos como referencia navegable, ordenadas por
    exportación española de los últimos 12 meses (las sin datos al final).
    None si el código no existe en la nomenclatura.
    """
    nomen = db.query(
        "SELECT description, level FROM nomenclature WHERE taric = ?", (code,))
    if not nomen:
        return None
    description, level = nomen[0]
    win = _windows(db)
    if win:
        window_sql = "AND period BETWEEN ? AND ? "
        params = [win["from_12m"], win["to"], code + "%"]
    else:
        window_sql = ""
        params = [code + "%"]
    rows = db.query(
        "SELECT n.taric, n.description, t.total "
        "FROM nomenclature n LEFT JOIN ("
        "  SELECT taric, sum(euros) AS total FROM trade "
        f"  WHERE flow='X' AND province_code IS NULL {window_sql}GROUP BY taric"
        ") t USING (taric) "
        f"WHERE n.level = 4 AND n.taric LIKE ? AND {_SEARCH_JUNK} "
        "ORDER BY t.total DESC NULLS LAST, n.taric",
        params)
    children = [
        {"taric": r[0], "description": r[1],
         "total_12m": r[2], "has_data": r[2] is not None}
        for r in rows
    ]
    return {"code": code, "description": description, "level": level,
            "children": children}


# ------------------------------------------------------------------- score

def _windows(db):
    """Ventanas temporales comunes a partir del último mes con dato."""
    period_max = db.query("SELECT max(period) FROM trade WHERE flow='X'")[0][0]
    if period_max is None:
        return None
    last_complete_year = period_max.year if period_max.month == 12 else period_max.year - 1
    return {
        "to": period_max,
        "from_12m": _add_months(period_max, -11),
        "from_3y": _add_months(period_max, -35),
        "from_60m": _add_months(period_max, -59),
        "years5": list(range(last_complete_year - 4, last_complete_year + 1)),
    }


def _country_meta(db):
    rows = db.query(
        "SELECT country_code, name, iso2, region, eu_member, access_tier FROM countries")
    return {r[0]: r for r in rows}


def score_product(db, taric):
    """Métricas, componentes percentiles y flags por país candidato.

    Devuelve None si el TARIC no existe en la nomenclatura.
    """
    nomen = db.query("SELECT description FROM nomenclature WHERE taric = ?", (taric,))
    if not nomen:
        return None
    description = nomen[0][0]
    win = _windows(db)

    codes = []
    if win:
        codes = [r[0] for r in db.query(
            "SELECT country_code FROM trade "
            "WHERE taric=? AND flow='X' AND province_code IS NULL AND period >= ? "
            "GROUP BY country_code HAVING sum(euros) > 0 ORDER BY country_code",
            (taric, win["from_3y"]))]

    result = {
        "taric": taric,
        "description": description,
        "total_exports_12m": None,  # null sin candidatos: nunca un 0 fabricado
        "aragon_share": None,
        "zaragoza_share": None,
        "period_window": {"from": _ym(win["from_12m"]), "to": _ym(win["to"])} if win else None,
        "n_candidates": len(codes),
        "warning": None,
        "default_weights": dict(DEFAULT_WEIGHTS),
        "countries": [],
    }
    if len(codes) < MIN_CANDIDATES:
        n = len(codes)
        detail = "ningún país" if n == 0 else (
            f"solo {n} país{'es' if n != 1 else ''}")
        result["warning"] = (
            f"Producto con histórico insuficiente: {detail} con exportaciones "
            f"en los últimos 3 años (mínimo {MIN_CANDIDATES}).")
    if not codes:
        return result

    # --- agregados SQL ---
    twelve = {r[0]: (r[1], r[2]) for r in db.query(
        "SELECT country_code, sum(euros), sum(kilos) FROM trade "
        "WHERE taric=? AND flow='X' AND province_code IS NULL "
        "AND period BETWEEN ? AND ? GROUP BY country_code",
        (taric, win["from_12m"], win["to"]))}
    total_12m = db.query(
        "SELECT sum(euros) FROM trade WHERE taric=? AND flow='X' "
        "AND province_code IS NULL AND period BETWEEN ? AND ?",
        (taric, win["from_12m"], win["to"]))[0][0] or 0.0
    yearly = {(r[0], r[1]): r[2] for r in db.query(
        "SELECT country_code, year(period), sum(euros) FROM trade "
        "WHERE taric=? AND flow='X' AND province_code IS NULL "
        "AND period >= ? AND period < ? GROUP BY 1, 2",
        (taric, date(win["years5"][0], 1, 1), date(win["years5"][-1] + 1, 1, 1)))}
    months_with_data = {r[0]: r[1] for r in db.query(
        "SELECT country_code, count(*) FROM trade "
        "WHERE taric=? AND flow='X' AND province_code IS NULL "
        "AND euros IS NOT NULL AND period >= ? GROUP BY country_code",
        (taric, win["from_60m"]))}
    # último año con operadores publicados (no ocultos) por país
    operators = {}
    for code, year, num, euros in db.query(
            "SELECT country_code, year, num_operators, euros FROM operators "
            "WHERE taric=? AND flow='X' ORDER BY year", (taric,)):
        if num is not None and num > 0:
            operators[code] = (num, euros)
    # euros IS NOT NULL: una provincia con todas las celdas ocultas por secreto
    # estadístico (suma NULL) desaparece del desglose en vez de romper la suma.
    provincial = {r[0]: r[1] for r in db.query(
        "SELECT province_code, sum(euros) FROM trade "
        "WHERE taric=? AND flow='X' AND province_code IS NOT NULL "
        "AND euros IS NOT NULL "
        "AND period BETWEEN ? AND ? GROUP BY province_code",
        (taric, win["from_12m"], win["to"]))}
    meta = _country_meta(db)

    result["total_exports_12m"] = total_12m
    if provincial and total_12m > 0:
        aragon = sum(provincial.get(p, 0.0) for p in ARAGON_PROVINCES)
        result["aragon_share"] = aragon / total_12m
        result["zaragoza_share"] = provincial.get("50", 0.0) / total_12m

    years3 = win["years5"][-3:]

    # --- métricas por país (CAGR sobre anuales brutos; ver winsorización abajo) ---
    sizes, cagrs, cvs, unit_values, eur_per_ops = [], [], [], [], []
    for c in codes:
        # Sin filas en la ventana → 0 legítimo (dejó de exportar); filas
        # presentes con suma NULL (celdas ocultas) → None: neutro 50 + nd_size.
        euros_12m, kilos_12m = twelve.get(c, (0.0, 0.0))
        sizes.append(euros_12m)
        cagrs.append(cagr_3y([yearly.get((c, y)) for y in years3]))
        cvs.append(coef_variation([yearly.get((c, y)) for y in win["years5"]]))
        if euros_12m and kilos_12m:
            unit_values.append(euros_12m / kilos_12m)
        else:
            unit_values.append(None)
        num, op_euros = operators.get(c, (None, None))
        eur_per_ops.append(op_euros / num if num and op_euros is not None else None)

    uv_median = median([v for v in unit_values if v is not None]) if any(
        v is not None for v in unit_values) else None
    uv_rels = [v / uv_median if v is not None and uv_median else None
               for v in unit_values]

    comp_size = percentile_ranks(sizes)
    # Winsorización p5-p95 del vector de CAGRs del conjunto candidato: modera
    # crecimientos explosivos desde base mínima sin aplastar la señal de los
    # mercados grandes (clamping de niveles ≠ clamping de tasas). El CAGR que
    # se muestra en metrics es el bruto; el recortado solo alimenta el ranking.
    not_null = [v for v in cagrs if v is not None]
    clamped = iter(winsorize(not_null))
    cagrs_rank = [next(clamped) if v is not None else None for v in cagrs]
    comp_growth = percentile_ranks(cagrs_rank)
    comp_stability = [100 - p if cv is not None else 50.0
                      for cv, p in zip(cvs, percentile_ranks(cvs))]
    comp_uv = percentile_ranks(uv_rels)
    comp_competition = percentile_ranks(eur_per_ops)

    countries = []
    for i, c in enumerate(codes):
        _, name, iso2, region, eu_member, tier = meta.get(
            c, (c, c, c, None, None, "Resto"))
        tier = tier or "Resto"
        num_ops = operators.get(c, (None, None))[0]
        flags = []
        if months_with_data.get(c, 0) < 12:
            flags.append("low_data")
        if sizes[i] is None:
            flags.append("nd_size")
        if cagrs[i] is None:
            flags.append("nd_growth")
        if cvs[i] is None:
            flags.append("nd_stability")
        if uv_rels[i] is None:
            flags.append("nd_unit_value")
        if eur_per_ops[i] is None:
            flags.append("nd_operators")
        countries.append({
            "country_code": c,
            "name": name,
            "iso2": iso2,
            "region": region,
            "eu_member": eu_member,
            "metrics": {
                "size_eur_12m": sizes[i],
                "cagr_3y": cagrs[i],
                "stability_cv": cvs[i],
                "unit_value_eur_kg": unit_values[i],
                "unit_value_rel": uv_rels[i],
                "eur_per_operator": eur_per_ops[i],
                "num_operators": num_ops,
                "access": tier,
            },
            "components": {
                "size": comp_size[i],
                "growth": comp_growth[i],
                "stability": comp_stability[i],
                "unit_value": comp_uv[i],
                "competition": comp_competition[i],
                "access": ACCESS_COMPONENT.get(tier, 40.0),
            },
            "flags": flags,
        })

    # orden inicial: score con los pesos por defecto (el frontend reordena)
    countries.sort(
        key=lambda c: sum(DEFAULT_WEIGHTS[k] * v for k, v in c["components"].items()),
        reverse=True)
    result["countries"] = countries
    return result


# ------------------------------------------------------------------ market

def market_detail(db, taric, country_code):
    """Ficha país para un producto. None si no hay datos para el par."""
    rows = db.query(
        "SELECT period, euros, kilos, is_provisional FROM trade "
        "WHERE taric=? AND flow='X' AND country_code=? AND province_code IS NULL "
        "ORDER BY period", (taric, country_code))
    if not rows:
        return None
    win = _windows(db)
    nomen = db.query("SELECT description FROM nomenclature WHERE taric = ?", (taric,))
    description = nomen[0][0] if nomen else taric
    meta = _country_meta(db).get(country_code)
    country = ({"country_code": meta[0], "name": meta[1], "iso2": meta[2],
                "region": meta[3], "eu_member": meta[4]} if meta else
               {"country_code": country_code, "name": country_code,
                "iso2": country_code, "region": None, "eu_member": None})

    monthly = [{"period": _ym(p), "euros": e, "kilos": k, "is_provisional": bool(prov)}
               for p, e, k, prov in rows]

    # Agregación anual con semántica SUM de SQL: los meses ocultos (NULL) no
    # cuentan como 0, y un año con TODO oculto queda en euros null, nunca 0.
    yearly_acc = {}
    for p, e, k, _ in rows:
        eu, ki = yearly_acc.get(p.year, (None, None))
        if e is not None:
            eu = (eu or 0.0) + e
        if k is not None:
            ki = (ki or 0.0) + k
        yearly_acc[p.year] = (eu, ki)
    yearly = [{"year": y, "euros": eu, "kilos": ki,
               "unit_value": eu / ki if eu is not None and ki else None}
              for y, (eu, ki) in sorted(yearly_acc.items())]

    # estacionalidad: solo años completos (desde enero) y definitivos; los
    # meses ocultos (NULL) se excluyen en vez de computar como cuota 0
    prov_min = db.query(
        "SELECT min(period) FROM trade WHERE flow='X' AND is_provisional")[0][0]
    definitive_max = (prov_min.year - 1) if prov_min else win["years5"][-1]
    first_period = rows[0][0]
    by_year_month = {}
    for p, e, _, _ in rows:
        if e is not None:
            by_year_month.setdefault(p.year, {})[p.month] = e
    eligible = [y for y in sorted(by_year_month)
                if y <= definitive_max and first_period <= date(y, 1, 1)
                and sum(by_year_month[y].values()) > 0]
    seasonality = []
    if len(eligible) >= 2:
        for m in range(1, 13):
            shares = [by_year_month[y].get(m, 0.0) / sum(by_year_month[y].values())
                      for y in eligible]
            seasonality.append({"month": m, "avg_share": sum(shares) / len(shares)})

    operators = [{"year": r[0], "num_operators": r[1], "euros": r[2]}
                 for r in db.query(
                     "SELECT year, num_operators, euros FROM operators "
                     "WHERE taric=? AND flow='X' AND country_code=? ORDER BY year",
                     (taric, country_code))]

    spain_total = db.query(
        "SELECT sum(euros) FROM trade WHERE taric=? AND flow='X' "
        "AND province_code IS NULL AND period BETWEEN ? AND ?",
        (taric, win["from_12m"], win["to"]))[0][0] or 0.0
    country_12m = db.query(
        "SELECT sum(euros) FROM trade WHERE taric=? AND flow='X' "
        "AND country_code=? AND province_code IS NULL AND period BETWEEN ? AND ?",
        (taric, country_code, win["from_12m"], win["to"]))[0][0] or 0.0

    # desglose provincial del producto (12m): top 8 + Aragón siempre que tenga dato
    # euros IS NOT NULL: una provincia con todas las celdas ocultas por secreto
    # estadístico (suma NULL) se omite del desglose; nunca aparece como 0.
    prov_rows = db.query(
        "SELECT province_code, sum(euros) FROM trade "
        "WHERE taric=? AND flow='X' AND province_code IS NOT NULL "
        "AND euros IS NOT NULL "
        "AND period BETWEEN ? AND ? GROUP BY province_code ORDER BY 2 DESC",
        (taric, win["from_12m"], win["to"]))
    selected = [r for r in prov_rows[:8]]
    selected += [r for r in prov_rows[8:] if r[0] in ARAGON_PROVINCES]
    provinces = [{
        "province_code": code,
        "name": PROVINCE_NAMES.get(code, code),
        "euros_12m": euros,
        "share": euros / spain_total if spain_total else None,
    } for code, euros in selected]

    return {
        "taric": taric,
        "description": description,
        "country": country,
        "monthly": monthly,
        "yearly": yearly,
        "seasonality": seasonality,
        "operators": operators,
        "provinces": provinces,
        "spain_total_12m": spain_total,
        "country_share_12m": country_12m / spain_total if spain_total else None,
    }
