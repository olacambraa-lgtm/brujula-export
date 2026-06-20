"""KPI: Numeric Faithfulness Rate — capa Informes, tier guardrail.

Compara los números visibles en el informe HTML (report_html) con la fuente
de verdad: api_product y api_market del bundle.

Qué se verifica por cada evidence:
  1. Exportación total 12 m del resumen  → api_product.total_exports_12m
     El informe usa fmtEur que ABREVIA (M€ / k€ / €), se valida la abreviatura.
  2. Cuota Aragón                        → api_product.aragon_share  (en %)
  3. Cuota Zaragoza                      → api_product.zaragoza_share (en %)
  4. N.º países candidatos               → api_product.n_candidates
  5. Tabla top-10 (hasta los países disponibles):
       - Nombre del país (ignorando spans HTML de flags)
       - Export. 12 m por país           → countries[i].metrics.size_eur_12m
       - CAGR 3a                         → countries[i].metrics.cagr_3y
     OJO: el informe puede usar pesos distintos a default_weights (los extrae del
     propio HTML), así que el orden del top-10 se verifica contra el ranking
     recalculado con esos pesos, no contra el orden original de la API.

Reglas de tolerancia:
  - Euros abreviados: tolerancia ±0,5 % relativa + 50 k€ absolutos (3 sig figs).
  - Cuotas en %: ±0,1 pp (display a 1 decimal).
  - CAGR en %:   ±0,1 pp (display a 1 decimal).
  - null nunca es 0 (regla dura del proyecto).
"""

import re

from eval.kpis._util import kpi, pct


# ---------------------------------------------------------------------------
# Helpers de parseo del HTML
# ---------------------------------------------------------------------------

def _strip_html(s):
    """Elimina etiquetas HTML de una cadena (para nombres de país con spans).

    Primero quita los spans de flag (r-warn) junto con su contenido (p.ej. '▲'),
    luego elimina cualquier etiqueta HTML restante.
    """
    # Quitar el span de advertencia y su contenido (p.ej. <span class="r-warn">▲</span>)
    s = re.sub(r'<span[^>]*class="r-warn"[^>]*>.*?</span>', '', s, flags=re.DOTALL)
    # Quitar etiquetas HTML restantes
    return re.sub(r'<[^>]+>', '', s).strip()


def _parse_fmteur(s):
    """Parsea una cadena fmtEur en es-ES ('59,0 M€', '421 k€', '0 €') → float.

    Réplica de la lógica JS: si v>=1e8 → nf0+' M€', si v>=1e6 → nf1+' M€',
    si v>=1e5 → nf0+' k€', si v>=1e3 → nf1+' k€', sino nf0+' €'.
    El separador de miles es '.' y el decimal es ',' (es-ES).
    Devuelve None si la cadena es 'n/d' o no parseable.
    """
    s2 = s.strip()
    if s2 in ('n/d', 'nd', '—', '-', '–', ''):
        return None
    try:
        if 'G€' in s2:
            # No debería aparecer (fmtEur no genera G€) pero por robustez
            num = float(s2.replace('G€', '').replace('.', '').replace(',', '.').strip())
            return num * 1e9
        if 'M€' in s2:
            num = float(s2.replace('M€', '').replace('.', '').replace(',', '.').strip())
            return num * 1e6
        if 'k€' in s2:
            num = float(s2.replace('k€', '').replace('.', '').replace(',', '.').strip())
            return num * 1e3
        if '€' in s2:
            num = float(s2.replace('€', '').replace('.', '').replace(',', '.').strip())
            return num
    except (ValueError, AttributeError):
        pass
    return None


def _parse_pct(s):
    """Parsea '1,7 %' o 'n/d' → float (0.017) o None."""
    s2 = s.strip().replace('%', '').replace('+', '').replace(',', '.').strip()
    if s2 in ('n/d', 'nd', '—', '-', '–', ''):
        return None
    try:
        return float(s2) / 100.0
    except ValueError:
        return None


def _eur_ok(html_str, api_val):
    """Verifica que el valor abreviado html_str corresponde a api_val.

    Tolerancia: ±0,5 % relativo + 50 000 € absolutos (cubre el redondeo a
    3 cifras significativas del fmtEur).
    Caso especial: null de API nunca es 0 (regla dura del proyecto).
    """
    parsed = _parse_fmteur(html_str)

    # API null → display 'n/d'
    if api_val is None:
        return html_str.strip() == 'n/d', "null→n/d"

    # API 0 → display '0 €'
    if api_val == 0.0 and parsed == 0.0:
        return True, "0€"

    if parsed is None:
        return False, f"no parseable: {html_str!r}"

    tol_rel = abs(api_val) * 0.005   # 0,5 %
    tol_abs = 50_000.0
    tol = max(tol_rel, tol_abs)
    ok = abs(parsed - api_val) <= tol
    return ok, f"{html_str}→{parsed:.0f} vs {api_val:.0f} (tol {tol:.0f})"


def _pct_ok(html_str, api_ratio):
    """Verifica que la cuota en % del informe corresponde a api_ratio (0-1).

    Tolerancia: ±0,1 pp (el informe muestra 1 decimal).
    """
    if api_ratio is None:
        ok = html_str.strip() in ('n/d', 'nd', '—')
        return ok, "null→n/d"
    parsed = _parse_pct(html_str)
    if parsed is None:
        return False, f"no parseable: {html_str!r}"
    ok = abs(parsed - api_ratio) <= 0.001   # 0,1 pp
    return ok, f"{html_str}→{parsed:.4f} vs {api_ratio:.4f}"


def _cagr_ok(html_str, api_cagr):
    """Verifica CAGR ('+35,6 %' o 'n/d') contra api cagr_3y (float o None)."""
    s2 = html_str.strip()
    if api_cagr is None:
        ok = s2 in ('n/d', 'nd', '—', '-', '–')
        return ok, "null→n/d"
    parsed = _parse_pct(s2)
    if parsed is None:
        return False, f"no parseable: {s2!r}"
    ok = abs(parsed - api_cagr) <= 0.001   # 0,1 pp
    return ok, f"{s2}→{parsed:.4f} vs {api_cagr:.4f}"


# ---------------------------------------------------------------------------
# Extracción de datos del HTML
# ---------------------------------------------------------------------------

_RE_KPIS = re.compile(
    r'Exportación España · 12 m.*?<strong>(.*?)</strong>'
    r'.*?Cuota Aragón.*?<strong>(.*?)</strong>'
    r'.*?Cuota Zaragoza.*?<strong>(.*?)</strong>'
    r'.*?Países candidatos.*?<strong>(.*?)</strong>',
    re.DOTALL
)

_RE_TABLE_ROW = re.compile(
    r'<td class="r-rank">(\d+)</td>\s*<td class="r-country">(.*?)</td>'
    r'.*?<td class="r-num">(.*?)</td>\s*<td class="r-num[^"]*">(.*?)</td>',
    re.DOTALL
)

_RE_WEIGHT_CHIP = re.compile(r'(\w[\w\s]+?)\s+(\d+)%')


def _extract_summary(html):
    """Devuelve (total_str, aragon_str, zaragoza_str, ncand_str) o None."""
    m = _RE_KPIS.search(html)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()


def _extract_table_rows(html):
    """Lista de (rank_int, name_str_clean, export_str, cagr_str)."""
    rows = []
    for m in _RE_TABLE_ROW.finditer(html):
        rank = int(m.group(1))
        name = _strip_html(m.group(2))
        export_str = _strip_html(m.group(3))
        cagr_str = _strip_html(m.group(4))
        rows.append((rank, name, export_str, cagr_str))
    return rows


def _extract_report_weights(html):
    """Extrae los pesos del informe tal como los muestra la UI.

    Los r-wchip del informe enumeran los criterios activos con su porcentaje,
    p.ej. 'Tamaño 28%'. Devuelve un dict {key: weight_float} normalizado,
    o None si no se encuentran.

    Mapeo nombre en español → clave de componente de la API:
      Tamaño          → size
      Crecimiento     → growth
      Estabilidad     → stability
      Valor unitario  → unit_value
      Competencia     → competition
      Accesibilidad   → access
    """
    name_map = {
        'Tamaño': 'size',
        'Crecimiento': 'growth',
        'Estabilidad': 'stability',
        'Valor unitario': 'unit_value',
        'Competencia': 'competition',
        'Accesibilidad': 'access',
    }
    # Buscar la sección de r-wchip
    chips_section = re.search(r'r-weights(.*?)</div>', html, re.DOTALL)
    if not chips_section:
        return None
    section = chips_section.group(1)
    raw = _RE_WEIGHT_CHIP.findall(section)
    weights = {}
    total = 0
    for label, pct_str in raw:
        label = label.strip()
        for esp, key in name_map.items():
            if esp.lower() in label.lower():
                w = int(pct_str)
                weights[key] = w
                total += w
                break
    if not weights:
        return None
    # Normalizar a proporciones (suman 1.0)
    return {k: v / total for k, v in weights.items()}


def _compute_score(components, weights):
    """Réplica de la fórmula del frontend: Σ(w·c)/Σ(w), null→50."""
    num = den = 0.0
    for k, w in weights.items():
        w = w or 0.0
        c = components.get(k)
        num += w * (50.0 if c is None else c)
        den += w
    return num / den if den else 0.0


def _rank_countries_by_weights(countries, weights):
    """Devuelve la lista de países ordenada por score desc, desempate por size desc."""
    scored = sorted(
        countries,
        key=lambda c: (
            _compute_score(c['components'], weights),
            c['metrics'].get('size_eur_12m') or 0.0
        ),
        reverse=True
    )
    return scored


# ---------------------------------------------------------------------------
# Checker principal
# ---------------------------------------------------------------------------

def check(bundle, con):
    """Verifica la fidelidad numérica de los informes generados.

    Compara los números visibles en report_html con api_product / api_market.
    Devuelve un dict kpi() con score 0-100 (% de comprobaciones correctas).
    """
    total_checks = 0
    ok_checks = 0
    fails = []       # (taric, cc, campo, detalle)
    skipped = 0      # evidences sin informe (con clave 'error' o report_html vacío)

    for ev in bundle.get('evidence', []):
        # Ignorar evidences con error de captura
        if 'error' in ev:
            skipped += 1
            continue

        taric = ev.get('taric', '?')
        cc = ev.get('country_code', '?')
        html = ev.get('report_html', '')
        ap = ev.get('api_product')

        if not html or not ap:
            skipped += 1
            continue

        # --- 1. Sección de KPIs del resumen -----------------------------------
        summary = _extract_summary(html)
        if summary:
            total_str, aragon_str, zaragoza_str, ncand_str = summary

            # 1a. Exportación total 12 m
            total_checks += 1
            ok_total, det = _eur_ok(total_str, ap.get('total_exports_12m'))
            if ok_total:
                ok_checks += 1
            else:
                fails.append((taric, cc, 'total_exports_12m', det))

            # 1b. Cuota Aragón
            total_checks += 1
            ok_ar, det = _pct_ok(aragon_str, ap.get('aragon_share'))
            if ok_ar:
                ok_checks += 1
            else:
                fails.append((taric, cc, 'aragon_share', det))

            # 1c. Cuota Zaragoza
            total_checks += 1
            ok_zar, det = _pct_ok(zaragoza_str, ap.get('zaragoza_share'))
            if ok_zar:
                ok_checks += 1
            else:
                fails.append((taric, cc, 'zaragoza_share', det))

            # 1d. N.º candidatos
            total_checks += 1
            try:
                nc_html = int(ncand_str.replace('.', ''))
                nc_api = ap.get('n_candidates')
                ok_nc = (nc_html == nc_api)
            except (ValueError, TypeError):
                ok_nc = False
            if ok_nc:
                ok_checks += 1
            else:
                fails.append((taric, cc, 'n_candidates',
                               f"html={ncand_str!r} vs api={ap.get('n_candidates')}"))

        # --- 2. Tabla top-10 --------------------------------------------------
        rows = _extract_table_rows(html)
        if rows:
            # Obtener los pesos activos en el informe (pueden diferir de default_weights)
            report_weights = _extract_report_weights(html)
            if report_weights is None:
                # Fallback a los pesos por defecto de la API
                report_weights = ap.get('default_weights', {})

            # Reordenar los países con los pesos del informe para comparar el orden
            countries_ranked = _rank_countries_by_weights(ap.get('countries', []), report_weights)
            top_n = min(len(rows), len(countries_ranked))

            for i in range(top_n):
                rank, name_html, exp_str, cagr_str = rows[i]
                c_api = countries_ranked[i]
                name_api = c_api.get('name', '')
                size_api = c_api['metrics'].get('size_eur_12m')
                cagr_api = c_api['metrics'].get('cagr_3y')

                # 2a. Nombre del país (posición i del ranking recalculado)
                total_checks += 1
                ok_name = (name_html == name_api)
                if ok_name:
                    ok_checks += 1
                else:
                    fails.append((taric, cc, f'top{rank}_name',
                                  f"html={name_html!r} vs api={name_api!r}"))

                # 2b. Export. 12 m del país
                total_checks += 1
                ok_exp, det = _eur_ok(exp_str, size_api)
                if ok_exp:
                    ok_checks += 1
                else:
                    fails.append((taric, cc, f'top{rank}_export', det))

                # 2c. CAGR 3a del país
                total_checks += 1
                ok_cagr, det = _cagr_ok(cagr_str, cagr_api)
                if ok_cagr:
                    ok_checks += 1
                else:
                    fails.append((taric, cc, f'top{rank}_cagr', det))

    score = pct(ok_checks, total_checks)

    # Resumen de lo verificado
    n_ev = len(bundle.get('evidence', [])) - skipped
    fail_sample = [f"{t}/{c} {campo}: {det}" for t, c, campo, det in fails[:5]]
    detail = (
        f"{ok_checks}/{total_checks} comprobaciones correctas en {n_ev} pares "
        f"({skipped} evidences omitidos). "
        "Secciones: resumen (total 12m, cuota Aragón, cuota Zaragoza, n_candidatos) + "
        "tabla top-10 (nombre, export 12m, CAGR 3a por país, orden según pesos del informe)."
    )
    if fails:
        detail += f" Fallos ({len(fails)}): " + "; ".join(fail_sample)
        if len(fails) > 5:
            detail += f" … (+{len(fails)-5} más)"

    return kpi(
        "numeric_faithfulness",
        "Informes",
        "Numeric Faithfulness Rate",
        "guardrail",
        score,
        value={
            "ok": ok_checks,
            "total": total_checks,
            "fails": len(fails),
            "evidences_checked": n_ev,
            "evidences_skipped": skipped,
        },
        target={"rate": 1.0},
        detail=detail,
    )
