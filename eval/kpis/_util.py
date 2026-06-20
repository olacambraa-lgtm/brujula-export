"""Utilidades compartidas por los scorers de KPIs de frontend.

Mantiene la misma forma de dict que eval.scorecard.kpi() para que la integración
sea trivial. Los scorers comparan a la PRECISIÓN QUE VE EL USUARIO (euros enteros,
ratios a 2 decimales): el ruido de coma flotante (sumas DOUBLE de DuckDB, ≤1e-9)
no es un fallo.
"""

import re


def status_from(score, warn=80.0, fail=50.0):
    if score is None:
        return "na"
    if score >= warn:
        return "pass"
    if score >= fail:
        return "warn"
    return "fail"


def kpi(kid, layer, name, tier, score, value=None, target=None, detail="", status=None):
    return {"id": kid, "layer": layer, "name": name, "tier": tier,
            "status": status or status_from(score), "score": score,
            "value": value, "target": target, "detail": detail}


def parse_es_number(s):
    """'1.234.567,89' (es-ES) → 1234567.89 ; '' / '—' / 'n/d' → None."""
    if s is None:
        return None
    t = str(s).strip()
    if t in ("", "—", "-", "–", "n/d", "nd", "N/D"):
        return None
    t = re.sub(r"[^\d,.\-]", "", t)
    if not t or t == "-":
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def approx(a, b, rel=1e-6, abs_=0.5):
    """Igualdad a precisión de display: tolera ruido ULP y redondeo a céntimo."""
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(abs_, abs(b) * rel)


def pct(ok, total):
    """Porcentaje 0-100; None si no hay nada que medir."""
    return round(100.0 * ok / total, 1) if total else None
