"""Scorecard de KPIs de Brújula Export — evaluador del bucle de auto-mejora.

Mide los KPIs automatizables de la capa backend/datos contra la DB de
producción y la API, y deja constancia del histórico (ledger) para verificar
que cada iteración mejora —o al menos no degrada— los guardarraíles duros.

KPIs de la capa frontend (paridad gráfica/CSV/PNG, fidelidad del informe,
task completion) se miden en eval/frontend.py (Fase 2, Chrome headless por CDP)
y, cuando existan, se fusionan aquí; mientras tanto aparecen como `na`.

Uso:
    .venv/bin/python -m eval.scorecard                 # DB por defecto
    .venv/bin/python -m eval.scorecard --db data/brujula.duckdb
    .venv/bin/python -m eval.scorecard --no-ledger     # no añade al histórico
"""

import argparse
import json
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from app.metrics import (DEFAULT_WEIGHTS, Database, get_meta, market_detail,
                         score_product)

BASE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
LEDGER = Path(__file__).resolve().parent / "ledger.jsonl"
SCORECARD_MD = Path(__file__).resolve().parent / "SCORECARD.md"

COMPONENT_KEYS = list(DEFAULT_WEIGHTS)
EXPECTED_MONTHS = 135  # 2015-01 .. 2026-03 inclusive
RNG = random.Random(42)  # perturbaciones reproducibles para rank-stability

# Latencia objetivo p95 (ms) de un /api/score sobre la DB completa.
P95_TARGET_MS = 1500.0


# --------------------------------------------------------------- formula port
# Réplica fiel de web/app.js (computeScore + currentRanking) para poder testear
# las propiedades del scoring sin navegador. El contrato es la fuente de verdad
# (docs/specs/api-contract.md §score): score = Σ(w_i·c_i) / Σ(w_i), c_i nulo→50,
# desempate por size_eur_12m desc.

def compute_score(components, weights):
    num = den = 0.0
    for k in COMPONENT_KEYS:
        w = weights.get(k, 0) or 0
        c = components.get(k)
        num += w * (50 if c is None else c)
        den += w
    return num / den if den else 0.0


def rank_countries(countries, weights):
    scored = sorted(
        countries,
        key=lambda c: (compute_score(c["components"], weights),
                       c["metrics"].get("size_eur_12m") or 0.0),
        reverse=True)
    return [c["country_code"] for c in scored]


# ------------------------------------------------------------------- helpers

def kpi(kid, layer, name, tier, status, score, value=None, target=None, detail=""):
    return {"id": kid, "layer": layer, "name": name, "tier": tier,
            "status": status, "score": score, "value": value,
            "target": target, "detail": detail}


def _status(score, warn=80.0, fail=50.0):
    if score is None:
        return "na"
    if score >= warn:
        return "pass"
    if score >= fail:
        return "warn"
    return "fail"


def _spearman(xs, ys):
    """Correlación de rango de Spearman (sin scipy)."""
    n = len(xs)
    if n < 3:
        return 0.0
    rx = _rankdata(xs)
    ry = _rankdata(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx ** 0.5 * vy ** 0.5)


def _rankdata(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _sample_products(con, top_n):
    rows = con.execute(
        "SELECT taric FROM ("
        "  SELECT taric, count(DISTINCT country_code) nc FROM trade "
        "  WHERE flow='X' AND province_code IS NULL GROUP BY taric "
        f"  ORDER BY nc DESC LIMIT {int(top_n)})").fetchall()
    return [r[0] for r in rows]


def _sweep_products(con, n):
    """Conjunto amplio para crash-free/latencia: mezcla productos ricos en
    candidatos con productos por volumen, para barrer casos diversos."""
    by_nc = con.execute(
        "SELECT taric, count(DISTINCT country_code) nc FROM trade "
        "WHERE flow='X' AND province_code IS NULL GROUP BY taric "
        f"ORDER BY nc DESC LIMIT {n // 2}").fetchall()
    by_vol = con.execute(
        "SELECT taric, sum(euros) v FROM trade "
        "WHERE flow='X' AND province_code IS NULL GROUP BY taric "
        f"ORDER BY v DESC NULLS LAST LIMIT {n // 2}").fetchall()
    seen, out = set(), []
    for r in by_nc + by_vol:
        if r[0] not in seen:
            seen.add(r[0])
            out.append(r[0])
    return out


# --------------------------------------------------------------------- checks
# Cada check devuelve un dict kpi(). Reciben `db` (app.metrics.Database) y/o la
# conexión cruda `con`, más muestras precomputadas.

def check_data_coverage(con):
    # El comercio es event-based: un (taric,país) sin operaciones un mes NO es
    # un dato "faltante" (no hubo transacción), así que no penalizamos huecos de
    # series. La cobertura "esperada" se mide estructuralmente: (1) todo el eje
    # temporal presente, (2) ningún mes anómalamente vacío (señal de ETL parcial)
    # y (3) la propagación correcta del flag provisional (regla dura: 2024+).
    months = con.execute(
        "SELECT count(DISTINCT period) FROM trade WHERE flow='X'").fetchone()[0]
    cov_month = months / EXPECTED_MONTHS
    per_month = [r[0] for r in con.execute(
        "SELECT count(DISTINCT taric) FROM trade WHERE flow='X' "
        "AND province_code IS NULL GROUP BY period").fetchall()]
    med = statistics.median(per_month) if per_month else 0
    thin = sum(1 for x in per_month if med and x < 0.5 * med)
    consist = 1 - thin / len(per_month) if per_month else 1.0
    total = con.execute("SELECT count(*) FROM trade").fetchone()[0]
    bad_prov = con.execute(
        "SELECT count(*) FROM trade "
        "WHERE (period >= DATE '2024-01-01') <> is_provisional").fetchone()[0]
    prov_ok = 1 - bad_prov / total if total else 1.0
    score = round(100 * cov_month * consist * prov_ok, 1)
    return kpi("data_coverage", "Integridad de datos", "Data Coverage Rate",
               "guardrail", _status(score), score,
               value={"months": months, "thin_months": thin,
                      "provisional_violations": bad_prov},
               target={"months": EXPECTED_MONTHS, "thin_months": 0,
                       "provisional_violations": 0},
               detail=f"{months}/{EXPECTED_MONTHS} meses; {thin} meses anómalos; "
                      f"flag provisional correcto en {total - bad_prov}/{total} filas.")


def check_missing_value(con):
    row = con.execute(
        "SELECT count(*), sum(CASE WHEN euros IS NULL THEN 1 ELSE 0 END), "
        "sum(CASE WHEN kilos IS NULL THEN 1 ELSE 0 END) "
        "FROM trade WHERE flow='X'").fetchone()
    total, null_e, null_k = row[0], row[1] or 0, row[2] or 0
    rate = (null_e) / total if total else 0
    score = round(100 * (1 - rate), 1)
    return kpi("missing_value", "Integridad de datos", "Missing Value Rate",
               "guardrail", _status(score), score,
               value={"null_euros": null_e, "null_kilos": null_k, "rows": total},
               target={"null_euros": 0},
               detail=f"{null_e} euros NULL / {total} filas "
                      f"({rate*100:.3f}%); kilos NULL: {null_k}.")


def check_duplicate_key(con):
    dup = con.execute("""
        SELECT count(*) FROM (
          SELECT period,flow,taric,country_code,province_code
          FROM trade GROUP BY 1,2,3,4,5 HAVING count(*) > 1)""").fetchone()[0]
    total = con.execute("SELECT count(*) FROM trade").fetchone()[0]
    score = 100.0 if dup == 0 else round(100 * (1 - dup / total), 1)
    return kpi("duplicate_key", "Integridad de datos", "Duplicate Key Rate",
               "guardrail", _status(score), score,
               value={"dup_key_groups": dup, "rows": total},
               target={"dup_key_groups": 0},
               detail=f"{dup} grupos de clave duplicada (inflarían exportaciones).")


def check_aggregation(con, db, sample):
    # 1) No sobre-conteo: el desglose provincial nunca debe superar el nacional
    #    de su (taric, periodo) — sería doble conteo / exportación inflada.
    agg = con.execute("""
        WITH nat AS (SELECT taric, period, sum(euros) e FROM trade
                     WHERE flow='X' AND province_code IS NULL GROUP BY 1,2),
             prov AS (SELECT taric, period, sum(euros) e FROM trade
                      WHERE flow='X' AND province_code IS NOT NULL GROUP BY 1,2)
        SELECT count(*),
               sum(CASE WHEN prov.e > nat.e * 1.0001 + 1 THEN 1 ELSE 0 END)
        FROM prov JOIN nat USING (taric, period)""").fetchone()
    pairs, overcount = agg[0], agg[1] or 0
    # 2) Integridad API↔SQL: total_exports_12m del endpoint = suma SQL directa.
    api_ok = api_n = 0
    for taric in sample[:15]:
        res = score_product(db, taric)
        if not res or res.get("total_exports_12m") is None:
            continue
        win = res["period_window"]
        sql_total = con.execute(
            "SELECT sum(euros) FROM trade WHERE taric=? AND flow='X' "
            "AND province_code IS NULL AND strftime(period,'%Y-%m') BETWEEN ? AND ?",
            [taric, win["from"], win["to"]]).fetchone()[0] or 0.0
        api_n += 1
        if abs(res["total_exports_12m"] - sql_total) <= max(1.0, sql_total * 1e-6):
            api_ok += 1
    overcount_ok = 1 - (overcount / pairs) if pairs else 1.0
    api_rate = api_ok / api_n if api_n else 1.0
    score = round(100 * min(overcount_ok, api_rate), 1)
    return kpi("aggregation_accuracy", "Cálculo económico", "Aggregation Accuracy",
               "guardrail", _status(score), score,
               value={"prov_nat_pairs": pairs, "overcount": overcount,
                      "api_total_ok": api_ok, "api_total_checked": api_n},
               target={"overcount": 0},
               detail=f"{overcount}/{pairs} pares con sobre-conteo provincial; "
                      f"API total = SQL en {api_ok}/{api_n} productos.")


def check_unit_value(db, sample):
    ok = checked = 0
    fails = []
    for taric in sample[:12]:
        res = score_product(db, taric)
        if not res:
            continue
        for c in res["countries"][:4]:
            m = market_detail(db, taric, c["country_code"])
            if not m:
                continue
            for y in m["yearly"]:
                checked += 1
                e, k, uv = y["euros"], y["kilos"], y["unit_value"]
                expected = (e / k) if (e is not None and k) else None
                if expected is None:
                    if uv is None:
                        ok += 1
                    else:
                        fails.append((taric, c["country_code"], y["year"]))
                elif uv is not None and abs(uv - expected) <= abs(expected) * 1e-9 + 1e-9:
                    ok += 1
                else:
                    fails.append((taric, c["country_code"], y["year"]))
    score = round(100 * ok / checked, 1) if checked else None
    return kpi("unit_value_accuracy", "Cálculo económico", "Unit Value Accuracy",
               "guardrail", _status(score), score,
               value={"ok": ok, "checked": checked, "sample_fails": fails[:5]},
               target={"rate": 1.0},
               detail=f"valor unitario = €/kg recalculado en {ok}/{checked} celdas.")


def check_scoring_formula(db, sample):
    """Score Formula Consistency + Weight Sum Validation."""
    issues = []
    # Pesos por defecto suman 1.0
    if abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) > 1e-9:
        issues.append("default_weights no suman 1.0")
    # Invariancia de escala: multiplicar todos los pesos por k no cambia el score
    # (el score depende solo de pesos relativos, Σw·c/Σw).
    comps = {"size": 80, "growth": 20, "stability": 50, "unit_value": 60,
             "competition": None, "access": 100}
    s1 = compute_score(comps, DEFAULT_WEIGHTS)
    s3 = compute_score(comps, {k: v * 3 for k, v in DEFAULT_WEIGHTS.items()})
    if abs(s1 - s3) > 1e-9:
        issues.append("no invariante a escala de pesos")
    # Pesos todos a cero → score 0 sin crash (Weight Sum Validation)
    try:
        if compute_score(comps, {k: 0 for k in COMPONENT_KEYS}) != 0:
            issues.append("Σw=0 no devuelve 0")
    except Exception as e:  # noqa: BLE001
        issues.append(f"Σw=0 lanza excepción: {e}")
    # El orden inicial que sirve el backend coincide con el ranking por pesos
    # por defecto (frontend y backend de acuerdo).
    mism = 0
    for taric in sample[:20]:
        res = score_product(db, taric)
        if not res or len(res["countries"]) < 2:
            continue
        backend_order = [c["country_code"] for c in res["countries"]]
        if backend_order != rank_countries(res["countries"], DEFAULT_WEIGHTS):
            mism += 1
    if mism:
        issues.append(f"{mism} productos con orden backend≠fórmula")
    score = 100.0 if not issues else max(0.0, 100 - 25 * len(issues))
    return kpi("score_formula", "Scoring", "Score Formula Consistency",
               "guardrail", _status(score), score,
               value={"issues": issues}, target={"issues": []},
               detail="; ".join(issues) if issues else
                      "fórmula Σw·c/Σw consistente, invariante a escala, Σw=0→0.")


def check_weight_monotonicity(db, sample):
    """Subir el peso de 'growth' debe favorecer (de media) a los mercados con
    mayor componente de crecimiento — correlación de Spearman ≥ 0 por producto."""
    bumped = dict(DEFAULT_WEIGHTS)
    bumped["growth"] = DEFAULT_WEIGHTS["growth"] * 3
    passes = total = 0
    rhos = []
    for taric in sample:
        res = score_product(db, taric)
        if not res or len(res["countries"]) < 5:
            continue
        base = rank_countries(res["countries"], DEFAULT_WEIGHTS)
        bump = rank_countries(res["countries"], bumped)
        pos_base = {c: i for i, c in enumerate(base)}
        pos_bump = {c: i for i, c in enumerate(bump)}
        growth = [c["components"]["growth"] for c in res["countries"]]
        improve = [pos_base[c["country_code"]] - pos_bump[c["country_code"]]
                   for c in res["countries"]]
        rho = _spearman(growth, improve)
        rhos.append(rho)
        total += 1
        if rho >= -1e-9:
            passes += 1
    score = round(100 * passes / total, 1) if total else None
    return kpi("weight_monotonicity", "Scoring", "Weight Monotonicity Pass Rate",
               "guardrail", _status(score), score,
               value={"pass": passes, "products": total,
                      "mean_rho": round(statistics.mean(rhos), 3) if rhos else None},
               target={"rate": 1.0},
               detail=f"{passes}/{total} productos: +peso growth favorece a los "
                      "de mayor crecimiento (Spearman≥0).")


def check_rank_stability(db, sample, perturb=0.03, trials=20):
    """Perturbaciones pequeñas de pesos → el top-k apenas cambia (solapamiento)."""
    overlaps = []
    for taric in sample:
        res = score_product(db, taric)
        if not res or len(res["countries"]) < 5:
            continue
        countries = res["countries"]
        k = min(10, len(countries))
        base_top = set(rank_countries(countries, DEFAULT_WEIGHTS)[:k])
        for _ in range(trials):
            w = {key: max(0.0, val + RNG.uniform(-perturb, perturb))
                 for key, val in DEFAULT_WEIGHTS.items()}
            top = set(rank_countries(countries, w)[:k])
            overlaps.append(len(base_top & top) / k)
    mean_overlap = statistics.mean(overlaps) if overlaps else None
    score = round(100 * mean_overlap, 1) if mean_overlap is not None else None
    return kpi("rank_stability", "Scoring", "Rank Stability",
               "guardrail", _status(score), score,
               value={"mean_top10_overlap": round(mean_overlap, 3)
                      if mean_overlap is not None else None,
                      "perturb": perturb, "trials": trials},
               target={"overlap": 0.8},
               detail=f"solapamiento medio top-10 bajo ±{perturb} de peso: "
                      f"{mean_overlap:.3f}." if mean_overlap is not None else "sin datos")


def _close(a, b, rel=1e-9, abs_=1e-6):
    """Igualdad hasta el ruido ULP de las sumas DOUBLE de DuckDB (≤1e-9 rel.)."""
    import math
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k], rel, abs_) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y, rel, abs_) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)
    return a == b


def check_determinism(db, sample):
    """Deterministic Ranking + Top 10 Reproducibility.

    El KPI exige el MISMO ranking ante la misma entrada (no identidad byte a byte
    de los floats). Las sumas DOUBLE de DuckDB son paralelas y varían a nivel ULP
    (≤1e-9 relativo, invisible a cualquier precisión mostrada), pero el orden y el
    top-10 son estables. Medimos: orden idéntico, top-10 reproducible y valores
    estables dentro del ruido ULP."""
    rank_ok = total = top_ok = top_total = val_stable = 0
    for taric in sample[:25]:
        r1 = score_product(db, taric)
        r2 = score_product(db, taric)
        if r1 is None:
            continue
        total += 1
        if [c["country_code"] for c in r1["countries"]] == \
           [c["country_code"] for c in r2["countries"]]:
            rank_ok += 1
        if _close(r1, r2):
            val_stable += 1
        if len(r1.get("countries", [])) >= 2:
            top_total += 1
            t1 = rank_countries(r1["countries"], DEFAULT_WEIGHTS)[:10]
            t2 = rank_countries(r2["countries"], DEFAULT_WEIGHTS)[:10]
            if t1 == t2:
                top_ok += 1
    score = round(100 * rank_ok / total, 1) if total else None
    return kpi("deterministic_ranking", "Ranking", "Deterministic Ranking Rate",
               "guardrail", _status(score), score,
               value={"order_identical": f"{rank_ok}/{total}",
                      "top10_reproducible": f"{top_ok}/{top_total}",
                      "values_stable_1e-9": f"{val_stable}/{total}"},
               target={"rate": 1.0},
               detail=f"orden idéntico {rank_ok}/{total}; top-10 reproducible "
                      f"{top_ok}/{top_total}; valores estables (≤1e-9) "
                      f"{val_stable}/{total} (ruido ULP de sumas DOUBLE, invisible).")


def check_crash_free_and_latency(db, sweep):
    crashes = []
    latencies = []
    for taric in sweep:
        t0 = time.perf_counter()
        try:
            res = score_product(db, taric)
            if res and res["countries"]:
                c = res["countries"][0]["country_code"]
                market_detail(db, taric, c)
        except Exception as e:  # noqa: BLE001
            crashes.append((taric, repr(e)))
            continue
        latencies.append((time.perf_counter() - t0) * 1000)
    n = len(sweep)
    cf_rate = (n - len(crashes)) / n if n else 1.0
    cf_score = round(100 * cf_rate, 1)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    p50 = statistics.median(latencies) if latencies else 0.0
    lat_score = round(100 * min(1.0, P95_TARGET_MS / p95), 1) if p95 else 100.0
    cf = kpi("crash_free", "Robustez", "Crash-free Benchmark Rate",
             "guardrail", _status(cf_score), cf_score,
             value={"runs": n, "crashes": crashes[:5]}, target={"rate": 1.0},
             detail=f"{n - len(crashes)}/{n} ejecuciones sin error.")
    lat = kpi("p95_latency", "Performance técnica", "p95 Latency",
              "guardrail", _status(lat_score), lat_score,
              value={"p95_ms": round(p95, 1), "p50_ms": round(p50, 1), "runs": len(latencies)},
              target={"p95_ms": P95_TARGET_MS},
              detail=f"p95 {p95:.0f} ms (objetivo ≤{P95_TARGET_MS:.0f}); p50 {p50:.0f} ms.")
    return cf, lat


def check_complexity_tax():
    files = {
        "web/app.js": BASE_DIR / "web/app.js",
        "web/styles.css": BASE_DIR / "web/styles.css",
        "app/metrics.py": BASE_DIR / "app/metrics.py",
        "app/main.py": BASE_DIR / "app/main.py",
        "etl/load.py": BASE_DIR / "etl/load.py",
    }
    loc = {name: len(p.read_text(encoding="utf-8").splitlines())
           for name, p in files.items() if p.is_file()}
    total = sum(loc.values())
    # Informativo: el baseline fija el presupuesto; iteraciones futuras penalizan
    # crecimiento de LOC sin mejora de KPI guardarraíl.
    return kpi("complexity_tax", "Mantenibilidad", "Complexity Tax",
               "quality", "info", None,
               value={"loc": loc, "total_core_loc": total},
               target=None,
               detail=f"{total} LOC en núcleo (app.js+metrics+main+etl+css).")


def _na(kid, layer, name, note):
    return kpi(kid, layer, name, "guardrail", "na", None, detail=note)


def frontend_placeholders():
    note = "pendiente Fase 2 (Chrome headless por CDP)"
    return [
        _na("graph_parity", "Gráficas", "Graph-to-Data Parity", note),
        _na("chart_completeness", "Gráficas", "Chart Completeness Rate", note),
        _na("csv_parity", "Exportaciones", "CSV Export Parity", note),
        _na("png_success", "Exportaciones", "PNG Export Success Rate", note),
        _na("numeric_faithfulness", "Informes", "Numeric Faithfulness Rate", note),
        _na("citation_traceability", "Informes", "Citation / Source Traceability", note),
        _na("exec_summary_validity", "Informes", "Executive Summary Validity", note),
        kpi("task_completion", "Usabilidad", "Task Completion Rate", "quality",
            "na", None, detail=note),
        _na("source_reconciliation", "Coherencia con DataComex",
            "Source Reconciliation Rate", "pendiente: reconciliar contra data/raw"),
    ]


# ------------------------------------------------------------------- runner

def run(db_path):
    db = Database(db_path)
    con = db.con
    meta = get_meta(db)
    score_sample = _sample_products(con, 40)
    sweep = _sweep_products(con, 200)

    kpis = []
    kpis.append(check_data_coverage(con))
    kpis.append(check_missing_value(con))
    kpis.append(check_duplicate_key(con))
    kpis.append(check_aggregation(con, db, score_sample))
    kpis.append(check_unit_value(db, score_sample))
    kpis.append(check_scoring_formula(db, score_sample))
    kpis.append(check_weight_monotonicity(db, score_sample))
    kpis.append(check_rank_stability(db, score_sample))
    kpis.append(check_determinism(db, score_sample))
    cf, lat = check_crash_free_and_latency(db, sweep)
    kpis.extend([cf, lat])
    kpis.append(check_complexity_tax())
    kpis.extend(frontend_placeholders())

    scored = [k for k in kpis if isinstance(k["score"], (int, float))]
    guard = [k for k in scored if k["tier"] == "guardrail"]
    qual = [k for k in scored if k["tier"] == "quality"]
    guard_score = round(statistics.mean(k["score"] for k in guard), 1) if guard else None
    qual_score = round(statistics.mean(k["score"] for k in qual), 1) if qual else None
    parts = [s for s in (guard_score, qual_score) if s is not None]
    # Prioridad del usuario: guardarraíles primero (80%) > calidad (20%).
    overall = round(0.8 * (guard_score or 0) + 0.2 * (qual_score if qual_score is not None
                    else guard_score or 0), 1) if guard_score is not None else None

    na = [k for k in kpis if k["status"] == "na"]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "db": str(db_path),
        "meta": {"period": f"{meta['period_min']}..{meta['period_max']}",
                 "n_products": meta["n_products"], "n_countries": meta["n_countries"]},
        "scores": {"overall": overall, "guardrail": guard_score, "quality": qual_score,
                   "guardrail_measured": len(guard), "na": len(na),
                   "total_kpis": len(kpis)},
        "kpis": kpis,
    }


# ------------------------------------------------------------------- output

def _icon(status):
    return {"pass": "✅", "warn": "⚠️", "fail": "❌", "na": "⏳", "info": "ℹ️"}.get(status, "·")


def to_markdown(report):
    s = report["scores"]
    lines = [
        "# Scorecard de KPIs — Brújula Export",
        "",
        f"_Generado: {report['generated_at']} · DB: `{report['db']}` · "
        f"{report['meta']['period']} · {report['meta']['n_products']} productos · "
        f"{report['meta']['n_countries']} países_",
        "",
        f"## Puntuación global: **{s['overall']}/100**",
        "",
        f"- 🛡️ Guardarraíles: **{s['guardrail']}/100** ({s['guardrail_measured']} medidos)",
        f"- 🎨 Calidad/UX: **{s['quality']}/100**" if s["quality"] is not None
        else "- 🎨 Calidad/UX: _sin medir_",
        f"- ⏳ Pendientes (na): {s['na']}/{s['total_kpis']}",
        "",
        "| | KPI | Capa | Tier | Score | Detalle |",
        "|---|---|---|---|---:|---|",
    ]
    for k in report["kpis"]:
        sc = "—" if k["score"] is None else f"{k['score']:.0f}"
        lines.append(f"| {_icon(k['status'])} | {k['name']} | {k['layer']} | "
                     f"{k['tier']} | {sc} | {k['detail']} |")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scorecard de KPIs de Brújula Export")
    ap.add_argument("--db", default=str(BASE_DIR / "data" / "brujula.duckdb"))
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--json", action="store_true", help="imprime el JSON completo")
    args = ap.parse_args(argv)

    report = run(args.db)
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")[:15]
    (REPORTS_DIR / f"scorecard-{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    SCORECARD_MD.write_text(to_markdown(report), encoding="utf-8")

    if not args.no_ledger:
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": report["generated_at"],
                                **report["scores"],
                                "kpi_scores": {k["id"]: k["score"]
                                               for k in report["kpis"]}},
                               ensure_ascii=False) + "\n")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(report))
    return report


if __name__ == "__main__":
    main()
