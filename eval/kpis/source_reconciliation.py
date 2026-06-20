"""KPI: Source Reconciliation Rate (capa Coherencia con DataComex, tier guardrail,
id source_reconciliation).

Verifica que los importes de exportación nacional almacenados en la DB coinciden
con los ficheros fuente crudos de DataComex en data/raw/.

Estrategia:
- Fuente primaria: data/raw/trade/nacional/<YYYYMM>.json (API DataComex, un JSON
  por mes, cubre los 135 meses del dataset).
- Los CSV en data/raw/trade_csv/ están completamente solapados por la API
  (el ETL los ignora cuando el mes ya existe en la vía API), así que no se usan.
- Para cada mes muestreado se suman los euros de exportación ('flujo'='X') del
  JSON crudo, aplicando los mismos filtros que el ETL:
    · taric4(): solo códigos TARIC de 4 dígitos
    · included_codes: solo países presentes en etl/static/countries_meta.csv
    · _num(): parseo de strings numéricos (coma decimal, vacío→None)
  y se compara con la suma equivalente en trade (province_code IS NULL).
- Tolerancia: max(0.5 €, |suma_db| × 1e-6) para absorber ruido ULP de sumas
  DOUBLE de DuckDB (invisible a cualquier precisión de display).
- score = % de meses muestreados que reconcilian dentro de tolerancia.

El check también detecta discrepancias de cardinalidad (nº de TARIC4 distintos)
y las informa en detail aunque no las penalice por separado (van implícitas en
los mismatches de importe).
"""

import json
from collections import defaultdict
from pathlib import Path

from eval.kpis._util import kpi, status_from, approx, pct

# Raíz del proyecto: dos niveles arriba de este fichero (eval/kpis/)
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
META_CSV = ROOT / "etl" / "static" / "countries_meta.csv"

# Meses que se inspeccionarán: uno representativo por cada año del dataset
# (2015-2026), más el primero y el último mes disponibles.
_SAMPLE_MONTHS = [
    "201501", "201507",   # 2015
    "201601", "201606",   # 2016
    "201701", "201709",   # 2017
    "201801", "201808",   # 2018
    "201901", "201912",   # 2019
    "202001", "202006",   # 2020
    "202101", "202106",   # 2021
    "202201", "202209",   # 2022
    "202301", "202306",   # 2023
    "202401", "202406",   # 2024
    "202501", "202506",   # 2025
    "202601", "202603",   # 2026
]


def _load_included_codes():
    """Carga el conjunto de códigos de país válidos (excluye agrupaciones)."""
    import csv
    with open(META_CSV, encoding="utf-8") as fh:
        return {row["datacomex_code"] for row in csv.DictReader(fh, delimiter=";")}


def _taric4(code):
    """Agrega a 4 dígitos; None si no es un nodo TARIC-4 válido."""
    c = str(code).strip()
    if " " in c:
        return None
    if len(c) > 4:
        c = c[:4]
    return c if len(c) == 4 else None


def _num(value):
    """Convierte número de la API a float; vacío / None → None."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return float(value.replace(".", "").replace(",", "."))
    return float(value)


def _is_export(flujo):
    """True si el registro es una exportación ('E…')."""
    return str(flujo).strip().upper().startswith("E")


def _raw_taric_sums(json_path, included_codes):
    """Suma euros de exportación del JSON crudo, agrupado por TARIC-4.

    Aplica exactamente los mismos filtros que el ETL (etl/load.py: api_rows +
    load_trade): solo exportaciones, solo países incluidos, solo TARIC-4 válidos,
    euros None → no se suma (NULL nunca es 0).

    Devuelve dict {taric4: euros_float}.
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    sums = defaultdict(float)
    for rec in data:
        if not _is_export(rec.get("flujo", "")):
            continue
        t4 = _taric4(rec.get("taric", ""))
        if t4 is None:
            continue
        code = str(rec.get("id_pais", "")).strip()
        if code.isdigit():
            code = code.zfill(3)
        if code not in included_codes:
            continue
        euros = _num(rec.get("euros"))
        if euros is not None:
            sums[t4] += euros
    return dict(sums)


def _db_taric_sums(con, period_yyyymm):
    """Suma euros de exportación de la DB para el mes dado (nacional, sin provincias).

    Devuelve dict {taric4: euros_float | None}.
    """
    rows = con.execute(
        """
        SELECT taric, SUM(euros)
        FROM trade
        WHERE flow = 'X'
          AND province_code IS NULL
          AND strftime(period, '%Y%m') = ?
        GROUP BY taric
        """,
        [period_yyyymm],
    ).fetchall()
    # NULL en suma (cuando todos los euros son NULL) se devuelve como None
    return {r[0]: r[1] for r in rows}


def check(bundle, con):
    """Scorer source_reconciliation.

    Ignora bundle (la reconciliación se hace directamente contra data/raw/ y la DB).
    Devuelve un dict kpi() con:
      score = % de meses muestreados cuya suma total de exportaciones nacionales
              coincide entre el JSON crudo y la DB, dentro de tolerancia.
    """
    # Carga los códigos de país válidos (misma maestra que el ETL)
    try:
        included_codes = _load_included_codes()
    except Exception as e:
        return kpi(
            "source_reconciliation",
            "Coherencia con DataComex",
            "Source Reconciliation Rate",
            "guardrail",
            None,
            value=None,
            target=None,
            detail=f"No se pudo cargar countries_meta.csv: {e!r}",
        )

    nacional_dir = RAW_DIR / "trade" / "nacional"
    if not nacional_dir.is_dir():
        return kpi(
            "source_reconciliation",
            "Coherencia con DataComex",
            "Source Reconciliation Rate",
            "guardrail",
            None,
            value=None,
            target=None,
            detail="data/raw/trade/nacional/ no existe; sin datos crudos para reconciliar.",
        )

    months_ok = 0
    months_checked = 0
    months_skipped = []    # meses del sample sin JSON en data/raw/
    mismatches = []        # meses con discrepancia: (mes, raw_total, db_total, diff)
    taric_card_diffs = []  # meses con diferencia en nº de TARIC4 distintos

    for period in _SAMPLE_MONTHS:
        json_path = nacional_dir / f"{period}.json"
        if not json_path.exists():
            months_skipped.append(period)
            continue

        # Sumas del JSON crudo (aplicando filtros idénticos al ETL)
        raw_sums = _raw_taric_sums(json_path, included_codes)
        raw_total = sum(raw_sums.values())

        # Sumas de la DB
        db_sums = _db_taric_sums(con, period)
        # La suma de db puede incluir None si algún TARIC tiene todos los euros NULL;
        # esos registros se excluyen de la comparación de importes (NULL ≠ 0).
        db_total = sum(v for v in db_sums.values() if v is not None)

        months_checked += 1

        # Diferencia de cardinalidad (informativa, no penaliza por separado)
        if len(raw_sums) != len(db_sums):
            taric_card_diffs.append(
                f"{period}: raw={len(raw_sums)} TARIC4 db={len(db_sums)} TARIC4"
            )

        # Tolerancia: max(0,5 €, |db_total| × 1e-6) — absorbe ruido ULP DuckDB
        tol = max(0.5, abs(db_total) * 1e-6)
        diff = abs(raw_total - db_total)
        if diff <= tol:
            months_ok += 1
        else:
            mismatches.append(
                f"{period}: raw={raw_total:,.2f}€ db={db_total:,.2f}€ diff={diff:,.4f}€"
            )

    # Sin ningún mes medible → score indeterminado
    score = pct(months_ok, months_checked) if months_checked > 0 else None

    # Construir value y detail
    value = {
        "months_ok": months_ok,
        "months_checked": months_checked,
        "months_skipped": months_skipped,
        "mismatch_months": [m.split(":")[0] for m in mismatches],
        "taric_cardinality_diffs": taric_card_diffs,
    }
    target = {"months_ok": months_checked, "score": 100.0}

    alcance = (
        "Muestra de 24 meses (2 por año, 2015-2026) de data/raw/trade/nacional/ "
        "vs tabla trade de la DB (exportaciones nacionales, TARIC-4). "
        "CSV de data/raw/trade_csv/ no usados: todos sus meses están cubiertos "
        "por la vía API y el ETL los descarta."
    )

    if score is None:
        detail = f"Sin meses medibles. {alcance}"
    elif mismatches:
        detail = (
            f"{months_ok}/{months_checked} meses reconcilian (score={score}%). "
            f"Discrepancias: {'; '.join(mismatches[:3])}. {alcance}"
        )
    else:
        detail = (
            f"{months_ok}/{months_checked} meses reconcilian al 100% "
            f"(tolerancia max(0,5€, |total|×1e-6)). {alcance}"
        )

    return kpi(
        "source_reconciliation",
        "Coherencia con DataComex",
        "Source Reconciliation Rate",
        "guardrail",
        score,
        value=value,
        target=target,
        detail=detail,
    )
