"""Construcción de data/brujula.duckdb desde data/raw/ (esquema spec §4).

Uso:
    .venv/bin/python -m etl.load [--db data/brujula.duckdb]

Fuentes:
- data/raw/masters/*.json            → nomenclature, countries
- data/raw/trade/{nacional,provXX}/  → trade (vía API, un JSON por mes)
- data/raw/trade_csv/{año}/*.csv     → trade (vía CSV pública, solo nacional;
  se ignoran los meses ya cubiertos por la vía API para no duplicar)

Reglas de oro: celda oculta/sin dato → NULL nunca 0; flag is_provisional
propagado desde el origen; agrupaciones no-país excluidas (solo códigos
presentes en etl/static/countries_meta.csv).
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from .datacomex_client import parse_csv

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
META_CSV = Path(__file__).resolve().parent / "static" / "countries_meta.csv"
DEFAULT_DB = ROOT / "data" / "brujula.duckdb"

SCHEMA = """
CREATE TABLE trade (
  period        DATE NOT NULL,
  flow          CHAR(1) NOT NULL,
  country_code  VARCHAR NOT NULL,
  country_name  VARCHAR NOT NULL,
  taric         VARCHAR NOT NULL,
  province_code VARCHAR,
  euros         DOUBLE,
  kilos         DOUBLE,
  is_provisional BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE operators (
  year          INTEGER NOT NULL,
  flow          CHAR(1) NOT NULL,
  country_code  VARCHAR NOT NULL,
  taric         VARCHAR NOT NULL,
  num_operators INTEGER,
  euros         DOUBLE
);
CREATE TABLE nomenclature (
  taric       VARCHAR PRIMARY KEY,
  description VARCHAR NOT NULL,
  level       INTEGER NOT NULL
);
CREATE TABLE countries (
  country_code VARCHAR PRIMARY KEY,
  name         VARCHAR,
  iso2         VARCHAR,
  region       VARCHAR,
  eu_member    BOOLEAN,
  access_tier  VARCHAR
);
"""

STAGE_COLUMNS = ["period", "flow", "country_code", "country_name", "taric",
                 "province_code", "euros", "kilos", "is_provisional"]


def map_flow(value):
    """'E'/'EXPORT'/'Exportación' → 'X' · 'I'/'IMPORT'/'Importación' → 'M'."""
    v = str(value).strip().upper()
    if v.startswith("E"):
        return "X"
    if v.startswith("I"):
        return "M"
    raise ValueError(f"Flujo desconocido: {value!r}")


def taric4(code):
    """Agrega a 4 dígitos; None si el código no es un nodo TARIC-4 válido
    (agregados tipo 'Total Taric' o capítulos de 2 dígitos se descartan)."""
    c = str(code).strip()
    if len(c) > 4:
        c = c[:4]
    return c if len(c) == 4 else None


def clean_description(code, nombre):
    """La maestra repite el código al inicio del nombre ('2204 Vino…')."""
    n = nombre.strip()
    if n.startswith(code):
        n = n[len(code):].strip()
    return n


def load_countries_meta(meta_csv):
    with open(meta_csv, encoding="utf-8") as fh:
        return {r["datacomex_code"]: r for r in csv.DictReader(fh, delimiter=";")}


def provisional_map(periodos):
    """CodPeriodo mensual → True si el periodo NO tiene datos definitivos."""
    return {p["CodPeriodo"]: not p["DatosDefinitivos"]
            for p in periodos if p["Nivel"] == "2"}


def api_rows(record, period, province_code, prov_flags):
    """Mapea una fila JSON de ObtenerDatos al esquema de staging."""
    t4 = taric4(record.get("taric", ""))
    code = str(record.get("id_pais", "")).strip()
    if code.isdigit():
        code = code.zfill(3)
    if t4 is None or not code:
        return None
    mensaje = str(record.get("mensaje") or "").lower()
    if "provisional" in mensaje:
        provisional = True
    elif "definitivo" in mensaje:
        provisional = False
    else:
        provisional = prov_flags.get(period, False)
    return (date(int(period[:4]), int(period[4:6]), 1),
            map_flow(record.get("flujo", "")),
            code,
            str(record.get("pais", "")).strip(),
            t4,
            province_code,
            record.get("euros"),
            record.get("kilos"),
            provisional)


def _stage_insert(con, rows):
    if not rows:
        return 0
    df = pd.DataFrame(rows, columns=STAGE_COLUMNS)
    df["period"] = pd.to_datetime(df["period"])
    df["euros"] = df["euros"].astype("float64")   # None → NaN → NULL (nunca 0)
    df["kilos"] = df["kilos"].astype("float64")
    df["is_provisional"] = df["is_provisional"].astype(bool)
    con.register("df_stage", df)
    con.execute("INSERT INTO trade_stage SELECT * FROM df_stage")
    con.unregister("df_stage")
    return len(df)


def load_trade(con, raw_dir, prov_flags, included_codes):
    """Carga trade desde raw API y raw CSV a una staging y agrega a TARIC-4."""
    con.execute(f"CREATE TEMP TABLE trade_stage AS "
                f"SELECT * FROM trade LIMIT 0")
    staged = 0
    api_national_months = set()

    trade_dir = raw_dir / "trade"
    if trade_dir.is_dir():
        for target_dir in sorted(trade_dir.iterdir()):
            if not target_dir.is_dir():
                continue
            province = target_dir.name.removeprefix("prov")
            province = None if target_dir.name == "nacional" else province
            for path in sorted(target_dir.glob("*.json")):
                period = path.stem  # YYYYMM
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    continue
                rows = []
                for rec in data:
                    row = api_rows(rec, period, province, prov_flags)
                    if row and row[2] in included_codes:
                        rows.append(row)
                staged += _stage_insert(con, rows)
                if target_dir.name == "nacional":
                    api_national_months.add(period)

    csv_dir = raw_dir / "trade_csv"
    if csv_dir.is_dir():
        for path in sorted(csv_dir.rglob("*.csv")):
            rows = []
            for rec in parse_csv(path.read_text(encoding="latin-1")):
                if rec["month"] is None:  # agregado anual: no es serie mensual
                    continue
                period = f"{rec['year']}{rec['month']:02d}"
                if period in api_national_months:  # ya cubierto por la API
                    continue
                t4 = taric4(rec["taric"])
                if t4 is None or rec["country_code"] not in included_codes:
                    continue
                rows.append((date(rec["year"], rec["month"], 1),
                             map_flow(rec["flow"]),
                             rec["country_code"],
                             rec["country_name"],
                             t4,
                             None,
                             rec["euros"],
                             rec["kilos"],
                             rec["is_provisional"]))
            staged += _stage_insert(con, rows)

    # Agregación a TARIC-4: SUM conserva NULL si todas las celdas son NULL.
    con.execute("""
        INSERT INTO trade
        SELECT period, flow, country_code, country_name, taric, province_code,
               SUM(euros), SUM(kilos), bool_or(is_provisional)
        FROM trade_stage
        GROUP BY ALL
    """)
    con.execute("DROP TABLE trade_stage")
    return staged


def build_db(db_path, raw_dir=RAW_DIR, meta_csv=META_CSV):
    raw_dir = Path(raw_dir)
    masters_dir = raw_dir / "masters"
    if not masters_dir.is_dir():
        sys.exit(f"No existe {masters_dir}; ejecuta antes etl.download")

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA)

    paises = json.loads((masters_dir / "paises.json").read_text(encoding="utf-8"))
    tarics = json.loads((masters_dir / "tarics.json").read_text(encoding="utf-8"))
    periodos = json.loads((masters_dir / "periodos.json").read_text(encoding="utf-8"))

    # --- countries: maestra × metadatos estáticos (excluye agrupaciones) ---
    meta = load_countries_meta(meta_csv)
    rows = []
    for p in paises:
        m = meta.get(p["Id"])
        if m is None:  # agrupación no-país (Total Mundo, zonas, avituallamiento…)
            continue
        rows.append((p["Id"], p["Pais"], m["iso2"] or None, m["region"],
                     p["UE"] == "UE27", m["access_tier"]))
    con.executemany("INSERT INTO countries VALUES (?,?,?,?,?,?)", rows)
    included_codes = {r[0] for r in rows}

    # --- nomenclature: niveles 2 y 4 dígitos (maestra Nivel 1 y 2) ---
    LEVELS = {"1": 2, "2": 4}
    nom = [(t["Taric"], clean_description(t["Taric"], t["Nombre"]), LEVELS[t["Nivel"]])
           for t in tarics if t["Nivel"] in LEVELS]
    con.executemany("INSERT INTO nomenclature VALUES (?,?,?)", nom)

    # --- trade ---
    staged = load_trade(con, raw_dir, provisional_map(periodos), included_codes)

    # --- validaciones ---
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("trade", "operators", "nomenclature", "countries")}
    errors = []
    if counts["countries"] == 0 or counts["nomenclature"] == 0:
        errors.append("countries/nomenclature vacías con maestras presentes")
    if not 200 <= counts["countries"] <= 300:
        errors.append(f"nº de países sospechoso: {counts['countries']}")
    if counts["nomenclature"] < 1200:
        errors.append(f"nomenclatura incompleta: {counts['nomenclature']} códigos")

    has_raw_trade = any((raw_dir / d).is_dir() and any((raw_dir / d).rglob("*"))
                        for d in ("trade", "trade_csv"))
    if has_raw_trade and counts["trade"] == 0:
        errors.append("trade vacía con raw de comercio presente")
    if counts["trade"]:
        last = con.execute("SELECT max(period) FROM trade").fetchone()[0]
        window_start = date(last.year - 1, last.month, 1)
        total = con.execute(
            "SELECT sum(euros) FROM trade WHERE flow='X' AND taric='2204' "
            "AND province_code IS NULL AND period > ?", [window_start]).fetchone()[0]
        if not total or total <= 0:
            errors.append("exportación nacional 12m del TARIC 2204 no es > 0")
        else:
            print(f"[check] export nacional 12m TARIC 2204: {total:,.0f} €")

    print(f"[resumen] trade={counts['trade']} (staging {staged}) · "
          f"operators={counts['operators']} (vacía a propósito) · "
          f"nomenclature={counts['nomenclature']} · countries={counts['countries']}")
    con.close()
    if errors:
        sys.exit("VALIDACIÓN FALLIDA:\n- " + "\n- ".join(errors))
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="Construye el DuckDB de Brújula Export")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args(argv)
    build_db(args.db)


if __name__ == "__main__":
    main()
