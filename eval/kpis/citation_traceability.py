"""KPI: Citation / Source Traceability — capa Informes, tier guardrail.

Verifica que cada informe (report_html) contiene los 6 elementos de trazabilidad
que permiten rastrear cada afirmación a su fuente:

  (a) Atribución de fuente DataComex en el pie del informe.
  (b) Disclaimer/cautelas: dato provisional 2024+ Y secreto estadístico (≤5 operadores).
  (c) Sección "Metodología" con la definición de cada criterio/componente del score.
  (d) Pesos aplicados mostrados explícitamente (en el bloque de leyenda de pesos).
  (e) Ventana temporal declarada (12 meses o periodo concreto).
  (f) Nota de que el ranking es multicriterio y las cifras son exportación declarada
      (no demanda mundial).

Score = % medio de elementos presentes, promediado por par.

Nota sobre los pesos (elemento d):
  El frontend emplea su propio DEFAULT_WEIGHTS de 5 componentes (sin 'competition',
  suman 1: 0.28/0.28/0.16/0.16/0.12 → 28/28/16/16/12 %).
  La API devuelve 6 componentes (con 'competition', suman también 1).
  El informe muestra los pesos del frontend (los operativos reales del ranking);
  esto es correcto y esperado — no es una discrepancia.
"""

import re

from eval.kpis._util import kpi, pct


# Peso máximo (total de elementos a verificar por par)
NUM_ELEMENTS = 6


def _check_html(html: str) -> dict:
    """Comprueba los 6 elementos de trazabilidad en el HTML del informe.

    Devuelve un dict con una clave por elemento (a–f) y True/False.
    """
    # (a) Atribución de fuente DataComex en el pie
    ok_a = "DataComex" in html

    # (b) Disclaimer/cautelas: provisionalidad 2024+ Y secreto estadístico
    ok_b_prov = "provisionales" in html or "provisional" in html
    ok_b_secret = "secreto estadístico" in html
    ok_b = ok_b_prov and ok_b_secret

    # (c) Sección Metodología con definición de criterios
    # Se exige presencia de la cabecera y al menos 3 definiciones de criterio
    ok_c_section = "Metodología" in html
    # Cada definición aparece en un <div class="r-def"> con la definición del criterio
    n_defs = len(re.findall(r'r-def', html))
    ok_c = ok_c_section and n_defs >= 3

    # (d) Pesos aplicados mostrados (bloque r-wchip con porcentajes)
    # Ejemplo: <span class="r-wchip"><i ...></i>Tamaño 28%</span>
    wchips = re.findall(r'r-wchip', html)
    ok_d = len(wchips) >= 3  # al menos 3 chips de peso visibles

    # (e) Ventana temporal declarada (12 m o rango de meses concreto)
    ok_e = ("12 m" in html or "12 meses" in html or "Ventana" in html)

    # (f) Nota de ranking multicriterio + cifras de exportación declarada (no demanda mundial)
    ok_f_multi = "multicriterio" in html
    ok_f_decl = "declarada" in html or "declarado" in html
    ok_f = ok_f_multi and ok_f_decl

    return {
        "a_datacomex_attribution": ok_a,
        "b_cautelas_provisional_secret": ok_b,
        "c_metodologia_con_definiciones": ok_c,
        "d_pesos_mostrados": ok_d,
        "e_ventana_temporal": ok_e,
        "f_multicriterio_declarada": ok_f,
    }


def check(bundle, con):
    """Scorer de Citation / Source Traceability.

    bundle: {"evidence": [item...], ...}
    item: {"taric", "country_code", "report_html", ...}
    con: conexión DuckDB (no se usa aquí; la verdad de referencia es report_html).

    Ignora items con clave 'error'.
    """
    evidence = bundle.get("evidence", [])
    items = [ev for ev in evidence if "error" not in ev]

    if not items:
        return kpi(
            "citation_traceability",
            "Informes",
            "Citation / Source Traceability",
            "guardrail",
            score=None,
            value={},
            target={},
            detail="sin evidencias válidas",
        )

    # Acumuladores por par y por elemento
    total_checks = 0
    total_ok = 0

    # Resumen de ausencias (para el campo value.missing)
    missing_by_pair = []
    # Contadores globales por elemento (para el campo value.elements)
    element_ok = {
        "a_datacomex_attribution": 0,
        "b_cautelas_provisional_secret": 0,
        "c_metodologia_con_definiciones": 0,
        "d_pesos_mostrados": 0,
        "e_ventana_temporal": 0,
        "f_multicriterio_declarada": 0,
    }

    for item in items:
        taric = item.get("taric")
        cc = item.get("country_code")
        html = item.get("report_html", "")

        if not html:
            # El informe está vacío: todos los elementos fallan para este par
            missing_by_pair.append({
                "pair": f"{taric}/{cc}",
                "missing": list(element_ok.keys()),
            })
            total_checks += NUM_ELEMENTS
            continue

        results = _check_html(html)
        absent = [k for k, v in results.items() if not v]

        if absent:
            missing_by_pair.append({"pair": f"{taric}/{cc}", "missing": absent})

        for key, ok in results.items():
            if ok:
                element_ok[key] += 1
                total_ok += 1
        total_checks += NUM_ELEMENTS

    score = pct(total_ok, total_checks)
    n = len(items)

    # Elementos que NO están al 100 %
    elements_not_perfect = {
        k: f"{v}/{n}" for k, v in element_ok.items() if v < n
    }

    detail_parts = [f"{total_ok}/{total_checks} checks OK en {n} pares"]
    if elements_not_perfect:
        detail_parts.append(
            "ausentes en algún par: " + ", ".join(elements_not_perfect.keys())
        )
    else:
        detail_parts.append("todos los elementos presentes en todos los pares")

    return kpi(
        "citation_traceability",
        "Informes",
        "Citation / Source Traceability",
        "guardrail",
        score=score,
        value={
            "pairs_checked": n,
            "checks_ok": total_ok,
            "checks_total": total_checks,
            "elements_ok_per_pair": {k: f"{v}/{n}" for k, v in element_ok.items()},
            "missing_by_pair": missing_by_pair[:10],
            "elements_not_perfect": elements_not_perfect,
        },
        target={
            "score": 100.0,
            "all_elements_present": True,
        },
        detail="; ".join(detail_parts),
    )
