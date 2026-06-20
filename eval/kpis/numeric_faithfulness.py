"""KPI: Numeric Faithfulness Rate — capa Informes, tier guardrail.

Compara los números visibles en el informe HTML (report_html) con la fuente
de verdad: api_product y api_market del bundle.

Qué se verifica por cada evidence:
  1. Exportación total 12 m del resumen  → api_product.total_exports_12m
     El informe usa fmtEur que ABREVIA (M€ / k€ / €), se valida la abreviatura.
  2. Cuota Aragón                        → api_product.aragon_share  (en %)
  3. Cuota Zaragoza                      → api_product.zaragoza_share (en %)
  4. N.º países candidatos               → api_product.n_candidates
  5. Tabla top-10: por cada fila del informe se busca el país en api_product.countries
     por NOMBRE (limpiando el marcador ▲) y se verifica:
       - Export. 12 m por país           → countries[name].metrics.size_eur_12m
       - CAGR 3a                         → countries[name].metrics.cagr_3y
     Adicionalmente se verifica consistencia interna: el score mostrado en el
     informe debe ser decreciente fila a fila (orden descendente).

Reglas de tolerancia:
  - Euros abreviados: tolerancia ±0,5 % relativa + 50 k€ absolutos (3 sig figs).
  - Cuotas en %: ±0,1 pp (display a 1 decimal).
  - CAGR en %:   ±0,1 pp (display a 1 decimal).
  - «>+500 %» en HTML es correcto si api cagr_3y > 5 (tope de display).
  - «n/d» en CAGR es correcto si api cagr_3y es None.
  - null nunca es 0 (regla dura del proyecto).
"""

import html as _html_mod
import re

from eval.kpis._util import kpi, pct


# ---------------------------------------------------------------------------
# Helpers de parseo del HTML
# ---------------------------------------------------------------------------

def _strip_html(s):
    """Elimina etiquetas HTML de una cadena (para nombres de país con spans).

    Primero quita los spans de flag (r-warn) junto con su contenido (p.ej. '▲'),
    luego elimina cualquier etiqueta HTML restante y desescapa entidades HTML.
    """
    # Quitar el span de advertencia y su contenido (p.ej. <span class="r-warn">▲</span>)
    s = re.sub(r'<span[^>]*class="r-warn"[^>]*>.*?</span>', '', s, flags=re.DOTALL)
    # Quitar etiquetas HTML restantes
    s = re.sub(r'<[^>]+>', '', s)
    # Desescapar entidades HTML (&gt; → >, &amp; → &, etc.)
    return _html_mod.unescape(s).strip()


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
    """Parsea '+35,6 %', '>+500 %', '-2,2 %', 'n/d' → float (fracción) o None.

    El prefijo '>' se ignora: se parsea el número que le sigue.
    """
    s2 = s.strip().lstrip('>').replace('%', '').replace('+', '').replace(',', '.').strip()
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
    """Verifica CAGR ('+35,6 %', '>+500 %' o 'n/d') contra api cagr_3y (float o None).

    Casos especiales:
      - «n/d»      → correcto si api_cagr is None.
      - «>+500 %»  → correcto si api_cagr > 5 (el frontend muestra este tope cuando
                     el CAGR real supera el 500 %, que en fracción es > 5.0).
      - Resto      → tolerancia ±0,1 pp.
    """
    s2 = html_str.strip()
    if api_cagr is None:
        ok = s2 in ('n/d', 'nd', '—', '-', '–')
        return ok, "null→n/d"
    # Tope de display: «>+500 %» (o con entidades: «&gt;+500 %» ya desescapado)
    if s2.startswith('>'):
        ok = api_cagr > 5.0
        return ok, f">+500% tope: api={api_cagr:.4f} {'≥' if ok else '<'}5"
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

_RE_WEIGHT_CHIP = re.compile(r'(\w[\w\s]+?)\s+(\d+)%')


def _extract_summary(html):
    """Devuelve (total_str, aragon_str, zaragoza_str, ncand_str) o None."""
    m = _RE_KPIS.search(html)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()


def _extract_table_rows(html):
    """Lista de (rank_int, name_str_clean, score_int, export_str, cagr_str).

    Parsea cada <tr> del <tbody> extrayendo celdas por posición:
      col 0: r-rank   → rank
      col 1: r-country → nombre del país (con posible span r-warn que se limpia)
      col 2: r-scorecell → score numérico (extraído de r-score-n)
      col 3: r-stackcell → (se omite)
      col 4: r-num    → exportación 12 m
      col 5: r-num    → CAGR 3a

    Las entidades HTML (&gt;, etc.) se desescapan en _strip_html.
    """
    tbody_m = re.search(r'<tbody>(.*?)</tbody>', html, re.DOTALL)
    if not tbody_m:
        return []

    rows = []
    for tr_frag in re.split(r'<tr\b', tbody_m.group(1))[1:]:  # [0] es texto vacío previo
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_frag, re.DOTALL)
        if len(tds) < 6:
            continue
        try:
            rank = int(tds[0].strip())
        except ValueError:
            continue
        name = _strip_html(tds[1])
        # Score: buscar el <span class="r-score-n">NN</span>
        score_m = re.search(r'r-score-n[^>]*>(\d+)<', tds[2])
        score = int(score_m.group(1)) if score_m else None
        export_str = _strip_html(tds[4])
        cagr_str = _strip_html(tds[5])
        rows.append((rank, name, score, export_str, cagr_str))
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
            # Construir índice nombre → datos de API para emparejar por nombre
            countries_by_name = {c['name']: c for c in ap.get('countries', [])}

            prev_score = None  # para verificar orden descendente

            for rank, name_html, score_html, exp_str, cagr_str in rows:
                c_api = countries_by_name.get(name_html)

                # 2a. Nombre del país: debe existir en la API
                total_checks += 1
                if c_api is not None:
                    ok_checks += 1
                else:
                    fails.append((taric, cc, f'top{rank}_name',
                                  f"html={name_html!r} no encontrado en api_product.countries"))
                    # Sin datos de API para este país → saltamos export y CAGR
                    # pero sí contamos el orden si tenemos score
                    if score_html is not None and prev_score is not None:
                        total_checks += 1
                        if score_html <= prev_score:
                            ok_checks += 1
                        else:
                            fails.append((taric, cc, f'top{rank}_order',
                                          f"score {score_html} > anterior {prev_score}"))
                    prev_score = score_html
                    continue

                size_api = c_api['metrics'].get('size_eur_12m')
                cagr_api = c_api['metrics'].get('cagr_3y')

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

                # 2d. Orden descendente por score (consistencia interna)
                if score_html is not None and prev_score is not None:
                    total_checks += 1
                    if score_html <= prev_score:
                        ok_checks += 1
                    else:
                        fails.append((taric, cc, f'top{rank}_order',
                                      f"score {score_html} > anterior {prev_score}"))
                prev_score = score_html

    score = pct(ok_checks, total_checks)

    # Resumen de lo verificado
    n_ev = len(bundle.get('evidence', [])) - skipped
    fail_sample = [f"{t}/{c} {campo}: {det}" for t, c, campo, det in fails[:5]]
    detail = (
        f"{ok_checks}/{total_checks} comprobaciones correctas en {n_ev} pares "
        f"({skipped} evidences omitidos). "
        "Secciones: resumen (total 12m, cuota Aragón, cuota Zaragoza, n_candidatos) + "
        "tabla top-10 (nombre por nombre, export 12m, CAGR 3a, orden descendente)."
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
