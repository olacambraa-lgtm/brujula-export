"""Harness frontend de Brújula Export (Fase 2 del bucle de auto-mejora).

Conduce la app real en Chrome headless (por CDP, ver eval/cdp.py) sobre una
muestra diversa de productos/países, SIEMPRE por el camino del usuario (DOM:
buscar → abrir → elegir país → informe), y vuelca un **bundle de evidencias**
con todo lo que los KPIs de frontend necesitan:

- series de cada gráfica vía el `echarts` global (`getInstanceByDom().getOption()`),
- CSV EXACTO que descarga el usuario (interceptando `URL.createObjectURL`),
- PNG real (`getDataURL`) con firma/dimensiones validadas,
- HTML del informe (`#report`) con resumen ejecutivo, top-10, pesos y metodología,
- inventario de gráficas y log de finalización de tareas.

Junto a cada par se guarda la respuesta de la API (verdad de referencia) para
comprobar paridad gráfica↔dato. app.js es un ES module: sus funciones NO son
globales, por eso todo se conduce por DOM y se lee por `echarts`/`#report`.

Los scorers por KPI (eval/kpis/*.py) leen este bundle; no reabren Chrome.

Uso:
    .venv/bin/python -m eval.frontend
"""

import argparse
import asyncio
import base64
import json
import struct
import time
from datetime import datetime
from pathlib import Path

from app.metrics import Database, market_detail, score_product
from eval.cdp import Chrome, open_page

BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent / "reports" / "frontend"
PNG_DIR = OUT_DIR / "png"
BUNDLE = OUT_DIR / "bundle.json"
CHART_IDS = ["chart-monthly", "chart-yearly", "chart-season", "chart-provinces"]

READY = "!!document.getElementById('search-input') && !!window.echarts"

INSTALL_HOOK = r"""
(function(){
  if (window.__hooked) return true;
  window.__hooked = true; window.__caps = [];
  var orig = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function(blob){
    try { if (blob && blob.type && blob.type.indexOf('csv')>=0)
            blob.text().then(function(t){ window.__caps.push(t); }); } catch(e){}
    return orig(blob);
  };
  return true;
})()
"""

# Fidelidad: una gráfica con `el.hidden` (estado vacío, p.ej. sin estacionalidad o
# sin desglose provincial) muestra al usuario un mensaje "No disponible", NO la
# gráfica. Su instancia ECharts puede conservar datos del producto anterior, pero
# están OCULTOS e inalcanzables (descarga deshabilitada). Por eso solo leemos
# series de gráficas VISIBLES: el bundle refleja lo que el usuario ve, no estado
# interno obsoleto. Así no se confunde "instancia con datos viejos" con "gráfica
# mostrada", y un futuro bug de gráfica VISIBLE con datos erróneos sí se detecta.
EXTRACT_CHARTS = r"""
(function(){
  var ids=['chart-monthly','chart-yearly','chart-season','chart-provinces'];
  var out={charts:{},inventory:{}};
  ids.forEach(function(id){
    var el=document.getElementById(id);
    var visible=!!(el && !el.hidden && el.offsetParent!==null);
    var inst=el && window.echarts && echarts.getInstanceByDom(el);
    if(inst && visible){
      var opt=inst.getOption();
      out.charts[id]={
        series:(opt.series||[]).map(function(s){return {name:s.name,type:s.type,data:s.data};}),
        xAxis:(opt.xAxis||[]).map(function(a){return a.data;}),
        legend:(opt.legend||[]).map(function(l){return l.data||null;})
      };
      out.inventory[id]={present:true,visible:true,
        has_data:(opt.series||[]).some(function(s){return (s.data||[]).length>0;})};
    } else {
      out.inventory[id]={present:false,visible:visible,has_data:false,
        instance_exists:!!inst,container_exists:!!el};
    }
  });
  out.country_panel_visible=!!(document.getElementById('country-panel') &&
                               !document.getElementById('country-panel').hidden);
  out.ranking_rows=document.querySelectorAll('#ranking-body tr').length;
  return out;
})()
"""


def _png_info(data_url, dest):
    if not isinstance(data_url, str) or "," not in data_url:
        return {"ok": False, "reason": "sin dataURL"}
    raw = base64.b64decode(data_url.split(",", 1)[1])
    sig_ok = raw[:8] == b"\x89PNG\r\n\x1a\n"
    width = height = None
    if sig_ok and raw[12:16] == b"IHDR":
        width, height = struct.unpack(">II", raw[16:24])
    dest.write_bytes(raw)
    return {"ok": bool(sig_ok and width and height), "bytes": len(raw),
            "width": width, "height": height, "sig_ok": sig_ok,
            "path": str(dest.relative_to(BASE_DIR))}


# Casos límite curados que SIEMPRE entran en la muestra: estresan los formatos de
# display difíciles del informe/gráficas (CAGR capado «>+500 %», «n/d», €/kg
# atípico, estacionalidad/provincias vacías en productos nicho). Garantizan que
# el KPI sea ESTABLE y verifique de verdad esos casos, no solo productos fáciles.
EDGE_CASES = ("1505",)


def pick_sample(db):
    con = db.con
    def q(sql):
        return [r[0] for r in con.execute(sql).fetchall()]
    # Desempate por taric en todas las consultas → muestra DETERMINISTA (sin él,
    # los empates en nº de candidatos hacían variar la muestra entre ejecuciones
    # y el KPI oscilaba según cayera o no un producto difícil).
    curated = q("SELECT taric FROM nomenclature WHERE level=4 AND taric IN "
                f"({','.join(repr(t) for t in EDGE_CASES)})")
    rich = q("SELECT taric FROM (SELECT taric, count(DISTINCT country_code) nc "
             "FROM trade WHERE flow='X' AND province_code IS NULL GROUP BY taric "
             "ORDER BY nc DESC, taric LIMIT 2)")
    mid = q("SELECT taric FROM (SELECT taric, count(DISTINCT country_code) nc "
            "FROM trade WHERE flow='X' AND province_code IS NULL GROUP BY taric "
            "ORDER BY nc DESC, taric) WHERE nc BETWEEN 10 AND 25 LIMIT 1")
    low = q("SELECT taric FROM (SELECT taric, count(DISTINCT country_code) nc "
            "FROM trade WHERE flow='X' AND province_code IS NULL "
            "AND period >= DATE '2023-04-01' GROUP BY taric "
            "HAVING nc BETWEEN 1 AND 4) ORDER BY taric LIMIT 1")
    seen, products = set(), []
    for t in curated + rich + mid + low:
        if t not in seen:
            seen.add(t)
            products.append(t)
    return products


def country_choices(db, taric):
    res = score_product(db, taric)
    if not res or not res["countries"]:
        return []
    out = [res["countries"][0]["country_code"]]
    for c in res["countries"][1:]:
        if "low_data" in c.get("flags", []) or any(f.startswith("nd_") for f in c.get("flags", [])):
            out.append(c["country_code"])
            break
    if len(out) == 1 and len(res["countries"]) > 1:
        out.append(res["countries"][min(3, len(res["countries"]) - 1)]["country_code"])
    return out[:2]


async def load_product(sess, taric):
    """Camino real: escribe en el buscador y hace click en el resultado exacto.

    Espera a que aparezca el resultado con el CÓDIGO EXACTO (no un item cualquiera)
    para no chocar con resultados obsoletos del query anterior (debounce 200 ms)."""
    await sess.evaluate(
        "(function(){var i=document.getElementById('search-input'); i.focus();"
        "i.value=''; i.dispatchEvent(new Event('input',{bubbles:true}));"
        "i.value=%s; i.dispatchEvent(new Event('input',{bubbles:true}));})()"
        % json.dumps(taric))
    exact = ("Array.from(document.querySelectorAll('#search-results .search-item .code'))"
             ".some(function(c){return c.textContent.trim()===%s;})" % json.dumps(taric))
    if not await sess.poll(exact, 8):
        return False
    clicked = await sess.evaluate(
        "(function(t){var b=document.querySelectorAll('#search-results .search-item');"
        "for(var i=0;i<b.length;i++){var c=b[i].querySelector('.code');"
        "if(c&&c.textContent.trim()===t){b[i].click();return true;}}"
        "return false;})(%s)" % json.dumps(taric))
    if not clicked:
        return False
    return await sess.poll(
        "document.getElementById('product-code') && "
        "document.getElementById('product-code').textContent===%s" % json.dumps(taric), 12)


async def select_country(sess, cc):
    ok = await sess.evaluate(
        "(function(cc){var r=document.querySelector('#ranking-body tr[data-cc=\"'+cc+'\"]');"
        "if(r){r.click();return true;} return false;})(%s)" % json.dumps(cc))
    if not ok:
        return False
    sel = await sess.poll(
        "document.getElementById('country-panel') && "
        "!document.getElementById('country-panel').hidden", 15)
    await sess.evaluate(
        "['chart-monthly','chart-yearly','chart-season','chart-provinces'].forEach("
        "function(id){var el=document.getElementById(id);var i=el&&echarts.getInstanceByDom(el);"
        "if(i){try{i.resize();}catch(e){}}});")
    return sel


async def capture_csv(sess):
    csv = {}
    kinds = await sess.evaluate(
        "Array.from(document.querySelectorAll('.chart-dl button[data-dl][data-fmt=\"csv\"]'))"
        ".filter(function(b){return b.offsetParent!==null;}).map(function(b){return b.dataset.dl;})")
    for kind in (kinds or []):
        await sess.evaluate("window.__caps=[]")
        await sess.evaluate(
            "(function(k){var b=Array.from(document.querySelectorAll("
            "'.chart-dl button[data-fmt=\"csv\"]')).filter(function(x){"
            "return x.dataset.dl===k && x.offsetParent!==null;})[0]; if(b)b.click();})(%s)"
            % json.dumps(kind))
        got = await sess.poll("window.__caps.length>0", 5)
        csv[kind] = (await sess.evaluate("window.__caps[0]")) if got else None
    return csv


async def extract_pair(sess, db, taric, cc):
    flow = {}
    t0 = time.time()
    flow["load_product"] = {"ok": await load_product(sess, taric),
                            "ms": int((time.time() - t0) * 1000)}
    flow["ranking_rendered"] = {
        "ok": await sess.poll("document.querySelectorAll('#ranking-body tr').length>0", 8)}
    t0 = time.time()
    flow["select_country"] = {"ok": await select_country(sess, cc),
                              "ms": int((time.time() - t0) * 1000)}
    flow["charts_rendered"] = {
        "ok": await sess.poll(
            "(function(){var el=document.getElementById('chart-monthly');"
            "var i=el&&echarts.getInstanceByDom(el);"
            "return i && (i.getOption().series||[]).length>0;})()", 10)}

    ch = await sess.evaluate(EXTRACT_CHARTS)
    csv = await capture_csv(sess)

    png = {}
    inv = ch.get("inventory") or {}
    for cid in CHART_IDS:
        kind = cid.replace("chart-", "")
        # Solo se exporta lo que el usuario puede exportar: gráficas VISIBLES (las
        # ocultas tienen la descarga deshabilitada). No aplica ≠ fallo.
        if not (inv.get(cid) or {}).get("visible"):
            png[kind] = {"ok": None, "applicable": False,
                         "reason": "gráfica oculta (estado vacío)", "chartId": cid}
            continue
        data_url = await sess.evaluate(
            "(function(){var el=document.getElementById(%s);"
            "var i=el&&echarts.getInstanceByDom(el); if(!i) return null;"
            "try{return i.getDataURL({type:'png',pixelRatio:2,backgroundColor:'#102236'});}"
            "catch(e){return null;}})()" % json.dumps(cid))
        png[kind] = (_png_info(data_url, PNG_DIR / f"{taric}_{cc}_{kind}.png")
                     if data_url else {"ok": False, "reason": "sin instancia/datos"})
        png[kind]["applicable"] = True
        png[kind]["chartId"] = cid

    await sess.evaluate("var b=document.getElementById('btn-report'); if(b)b.click();")
    report_html = await sess.evaluate(
        "(function(){var el=document.getElementById('report');"
        "return el?el.innerHTML:null;})()")
    await sess.evaluate("document.body.classList.remove('print-mode');")
    flow["report_built"] = {"ok": bool(report_html)}

    return {
        "taric": taric, "country_code": cc, "flow": flow,
        "charts": ch.get("charts"), "chart_inventory": ch.get("inventory"),
        "country_panel_visible": ch.get("country_panel_visible"),
        "ranking_rows": ch.get("ranking_rows"),
        "csv": csv, "png": png,
        "report_html": report_html,
        "api_product": score_product(db, taric),
        "api_market": market_detail(db, taric, cc),
    }


async def task_completion_pass(sess, products):
    """Flujo de usuario completo por DOM (KPI Task Completion)."""
    results = []
    for taric in products:
        steps = {}
        steps["search_and_open"] = await load_product(sess, taric)
        sel = False
        if await sess.poll("document.querySelectorAll('#ranking-body tr').length>0", 8):
            await sess.evaluate("document.querySelector('#ranking-body tr').click()")
            sel = await sess.poll(
                "document.getElementById('country-panel') && "
                "!document.getElementById('country-panel').hidden", 12)
        steps["select_country"] = sel
        steps["charts"] = await sess.poll(
            "(function(){var el=document.getElementById('chart-monthly');"
            "var i=el&&echarts.getInstanceByDom(el);"
            "return i && (i.getOption().series||[]).length>0;})()", 8)
        await sess.evaluate("var b=document.getElementById('btn-report'); if(b)b.click();")
        steps["report"] = await sess.poll(
            "document.getElementById('report').innerHTML.length>0", 8)
        await sess.evaluate("document.body.classList.remove('print-mode');")
        results.append({"taric": taric, "steps": steps, "completed": all(steps.values())})
    return results


async def build_async(db_path, url):
    db = Database(db_path)
    products = pick_sample(db)
    pairs = [(t, cc) for t in products for cc in country_choices(db, t)]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PNG_DIR.mkdir(parents=True, exist_ok=True)

    chrome = Chrome().start()
    try:
        sess, ws = await open_page(chrome, url, ready_expr=READY)
        await sess.evaluate(INSTALL_HOOK)
        extracted = []
        for taric, cc in pairs:
            try:
                extracted.append(await extract_pair(sess, db, taric, cc))
            except Exception as e:  # noqa: BLE001
                extracted.append({"taric": taric, "country_code": cc, "error": repr(e)})
        tasks = await task_completion_pass(sess, products)
        await ws.close()
    finally:
        chrome.stop()

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "url": url, "db": str(db_path),
        "products": products, "pairs": [list(p) for p in pairs],
        "evidence": extracted, "task_completion": tasks,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Harness frontend (CDP) de Brújula Export")
    ap.add_argument("--db", default=str(BASE_DIR / "data" / "brujula.duckdb"))
    ap.add_argument("--url", default="http://localhost:8765")
    args = ap.parse_args(argv)
    bundle = asyncio.run(build_async(args.db, args.url))
    BUNDLE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for e in bundle["evidence"] if "error" not in e)
    tc = sum(1 for t in bundle["task_completion"] if t["completed"])
    print(f"Bundle: {BUNDLE.relative_to(BASE_DIR)}")
    print(f"  pares extraídos: {ok}/{len(bundle['evidence'])}")
    print(f"  task completion: {tc}/{len(bundle['task_completion'])} flujos completos")
    print(f"  productos: {bundle['products']}  ·  pares: {bundle['pairs']}")
    return bundle


if __name__ == "__main__":
    main()
