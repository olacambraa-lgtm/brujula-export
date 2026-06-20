"""KPI: Executive Summary Validity — capa Informes, tier guardrail.

Extrae la sección class='r-summary' de cada report_html y verifica que
menciona correctamente, contra api_product y los pesos operativos del frontend
(5 componentes, sin 'competition'), los siguientes 6 hechos:

  (a) Producto: taric y/o descripción presentes en el informe (en r-product,
      fuera del r-summary pero dentro del mismo HTML).
  (b) Exportación total 12 m: total_exports_12m formateado con la misma lógica
      compacta que usa app.js (fmtEur): M€ / k€ / € según magnitud.
  (c) Cuotas Aragón y Zaragoza: formateadas a 1 decimal (es-ES) o 'n/d' si null.
  (d) Nº de mercados candidatos: n_candidates como número entero.
  (e) Perfil de pesos aplicado: los 5 componentes del frontend con sus %
      (redondeados) presentes en el r-summary.
  (f) Top-5 de mercados: nombres y scores (redondeados, media ponderada con
      pesos del frontend, componente nulo→50) coinciden con los primeros 5
      del ranking recalculado.

Score = % de hechos presentes y correctos, promediado por par (0-100).

Nota sobre pesos:
  El frontend usa DEFAULT_WEIGHTS de 5 componentes (sin 'competition', que
  no tiene señal en esta extracción): size=0.28, growth=0.28, stability=0.16,
  unit_value=0.16, access=0.12 → suman 1.0.
  El backend (api_product.default_weights) incluye 6 componentes con pesos
  distintos (0.25/0.25/0.15/0.15/0.10/0.10). El informe muestra los del
  frontend (los reales del ranking visible), no los del backend.
"""

import re

from eval.kpis._util import kpi, pct

# Pesos operativos del frontend (5 componentes, sin 'competition').
# Fuente: web/app.js const DEFAULT_WEIGHTS.
_FE_WEIGHTS = {
    'size':       0.28,
    'growth':     0.28,
    'stability':  0.16,
    'unit_value': 0.16,
    'access':     0.12,
}
_FE_COMPONENT_ORDER = ['size', 'growth', 'stability', 'unit_value', 'access']

# Etiquetas en español tal como aparecen en el informe.
_FE_LABELS = {
    'size':       'Tamaño',
    'growth':     'Crecimiento',
    'stability':  'Estabilidad',
    'unit_value': 'Valor unitario',
    'access':     'Accesibilidad',
}

# Porcentajes de cada peso (redondeados), precomputados.
# Con FE_WEIGHTS: 28/28/16/16/12 (suman 100).
_FE_WSUM = sum(_FE_WEIGHTS.values())
_FE_PCTS = {k: round(_FE_WEIGHTS[k] / _FE_WSUM * 100) for k in _FE_COMPONENT_ORDER}

# Número de hechos a verificar por par.
_N_FACTS = 6


def _compute_score_fe(components):
    """Media ponderada con pesos del frontend; componente nulo → 50 (neutro).

    Réplica de computeScore() de app.js restringida a los 5 componentes.
    """
    num = den = 0.0
    for k in _FE_COMPONENT_ORDER:
        w = _FE_WEIGHTS[k]
        c = components.get(k)
        num += w * (50.0 if c is None else c)
        den += w
    return num / den if den else 0.0


def _fmt_eur(v):
    """Réplica de fmtEur() de app.js: valor compacto en es-ES.

    Reglas:
      v >= 100 M€  → entero M€           (nf0 escalado)
      v >= 1 M€    → 1 decimal M€        (nf1 escalado)
      v >= 100 k€  → entero k€
      v >= 1 k€    → 1 decimal k€
      resto        → entero €
    Devuelve 'n/d' si v es None.
    """
    if v is None:
        return 'n/d'
    a = abs(v)
    if a >= 1e6:
        if a >= 1e8:
            return str(round(v / 1e6)) + ' M€'
        return f'{v / 1e6:.1f}'.replace('.', ',') + ' M€'
    if a >= 1e3:
        if a >= 1e5:
            return str(round(v / 1e3)) + ' k€'
        return f'{v / 1e3:.1f}'.replace('.', ',') + ' k€'
    return str(round(v)) + ' €'


def _fmt_pct(v):
    """Réplica de fmtPct(v) de app.js: 1 decimal es-ES + ' %', o 'n/d'."""
    if v is None:
        return 'n/d'
    return f'{v * 100:.1f}'.replace('.', ',') + ' %'


def _extract_r_summary(html):
    """Devuelve el contenido de <section class='r-summary'>...</section>, o ''."""
    m = re.search(
        r'class=["\']r-summary["\'][^>]*>(.*?)</section',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    return m.group(1) if m else ''


def _check_pair(taric, html, api_product):
    """Comprueba los 6 hechos para un par (taric, country_code).

    Devuelve dict {hecho: bool} y la lista de hechos fallados.
    """
    summary = _extract_r_summary(html)

    countries = api_product.get('countries') or []
    total = api_product.get('total_exports_12m')
    aragon = api_product.get('aragon_share')
    zarago = api_product.get('zaragoza_share')
    n_cand = api_product.get('n_candidates')
    desc = api_product.get('description') or ''

    # (a) Producto: taric o descripción en el HTML completo del informe
    #     (el informe los muestra en r-product, fuera del r-summary).
    ok_a = str(taric) in html or (bool(desc) and desc[:10] in html)

    # (b) Total exportaciones 12 m formateado correctamente en el r-summary.
    exp_total = _fmt_eur(total)
    ok_b = exp_total in summary

    # (c) Cuotas Aragón y Zaragoza (ambas deben coincidir).
    exp_aragon = _fmt_pct(aragon)
    exp_zarago = _fmt_pct(zarago)
    ok_c = exp_aragon in summary and exp_zarago in summary

    # (d) Nº de mercados candidatos como entero en el r-summary.
    ok_d = (n_cand is not None) and (str(n_cand) in summary)

    # (e) Perfil de pesos: los 5 componentes del frontend con su % redondeado.
    ok_e = all(
        f'{_FE_LABELS[k]} {_FE_PCTS[k]}%' in summary
        for k in _FE_COMPONENT_ORDER
    )

    # (f) Top-5 de mercados: re-rankear países con pesos del frontend y
    #     comprobar que nombre y score aparecen en el r-summary.
    #     Si hay menos de 5 candidatos, se comprueban los que haya.
    ranked = sorted(
        [(c, _compute_score_fe(c['components'])) for c in countries],
        key=lambda x: (x[1], x[0]['metrics'].get('size_eur_12m') or 0.0),
        reverse=True,
    )
    top5 = ranked[:5]
    if top5:
        ok_f = all(
            c['name'] in summary and f'score {round(sc)}' in summary
            for c, sc in top5
        )
    else:
        # Sin candidatos no hay top-5 que mostrar: hecho no verificable.
        ok_f = False

    results = {
        'a_producto': ok_a,
        'b_total_12m': ok_b,
        'c_cuotas': ok_c,
        'd_n_candidatos': ok_d,
        'e_pesos': ok_e,
        'f_top5': ok_f,
    }
    failed = [k for k, v in results.items() if not v]
    return results, failed


def check(bundle, con):
    """Scorer de Executive Summary Validity.

    bundle: {"evidence": [item...], ...}
    item:   {"taric", "country_code", "report_html", "api_product", ...}
    con:    conexión DuckDB (no se usa; verdad de referencia = api_product).

    Ignora items con clave 'error'.
    """
    evidence = bundle.get('evidence', [])
    items = [ev for ev in evidence if 'error' not in ev]

    if not items:
        return kpi(
            'exec_summary_validity',
            'Informes',
            'Executive Summary Validity',
            'guardrail',
            score=None,
            value={},
            target={},
            detail='sin evidencias válidas',
        )

    total_facts = 0
    total_ok = 0
    # Contadores globales por hecho (para diagnóstico).
    fact_ok = {
        'a_producto': 0,
        'b_total_12m': 0,
        'c_cuotas': 0,
        'd_n_candidatos': 0,
        'e_pesos': 0,
        'f_top5': 0,
    }
    missing_by_pair = []
    no_summary = []

    for item in items:
        taric = item.get('taric', '?')
        cc = item.get('country_code', '?')
        html = item.get('report_html', '')
        api_p = item.get('api_product', {})
        pair_label = f'{taric}/{cc}'

        if not html or 'r-summary' not in html:
            # Sin resumen ejecutivo: todos los hechos fallan.
            no_summary.append(pair_label)
            total_facts += _N_FACTS
            continue

        results, failed = _check_pair(taric, html, api_p)

        n_ok_pair = sum(results.values())
        total_ok += n_ok_pair
        total_facts += _N_FACTS

        for k, v in results.items():
            if v:
                fact_ok[k] += 1

        if failed:
            missing_by_pair.append({'pair': pair_label, 'failed': failed})

    score = pct(total_ok, total_facts)
    n = len(items)

    facts_not_perfect = {
        k: f'{v}/{n}' for k, v in fact_ok.items() if v < n
    }

    detail_parts = [f'{total_ok}/{total_facts} hechos correctos en {n} pares']
    if no_summary:
        detail_parts.append(f'sin r-summary: {no_summary}')
    if facts_not_perfect:
        detail_parts.append(
            'hechos fallidos en algún par: ' + ', '.join(facts_not_perfect.keys())
        )
    else:
        detail_parts.append('todos los hechos correctos en todos los pares')

    return kpi(
        'exec_summary_validity',
        'Informes',
        'Executive Summary Validity',
        'guardrail',
        score=score,
        value={
            'pairs_checked': n,
            'facts_ok': total_ok,
            'facts_total': total_facts,
            'fact_ok_per_pair': {k: f'{v}/{n}' for k, v in fact_ok.items()},
            'missing_by_pair': missing_by_pair[:10],
            'no_summary': no_summary,
        },
        target={
            'score': 100.0,
            'all_facts_correct': True,
        },
        detail='; '.join(detail_parts),
    )
