"""Genera data/brujula.duckdb con datos sintéticos PLAUSIBLES para la demo.

Fallback mientras no haya datos reales de DataComex: 10 productos
reconocibles, 35 países, series mensuales 2015-01 → 2026-03 con tendencia +
estacionalidad + ruido determinista (seed fija), desglose provincial
(Aragón + 4 provincias más) y operadores anuales con NULL por secreto
estadístico.

Uso: .venv/bin/python scripts/make_synthetic_db.py [--out RUTA]
"""

import argparse
import math
import random
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

SEED = 20260611
START = date(2015, 1, 1)
END = date(2026, 3, 1)
PROVISIONAL_FROM = date(2024, 1, 1)

# taric → (descripción, exportación anual aproximada en € (2015), €/kg base)
PRODUCTS = {
    "2204": ("Vino de uvas frescas, incluso encabezado; mosto de uva", 2.6e9, 2.8),
    "0203": ("Carne de animales de la especie porcina, fresca, refrigerada o congelada", 4.0e9, 2.2),
    "8703": ("Automóviles de turismo y demás vehículos para el transporte de personas", 2.4e10, 14.0),
    "8708": ("Partes y accesorios de tractores y vehículos automóviles", 7.0e9, 9.0),
    "4819": ("Cajas, sacos, bolsas y demás envases de papel, cartón o guata de celulosa", 1.1e9, 1.5),
    "8418": ("Refrigeradores, congeladores y demás material para producción de frío", 1.3e9, 4.5),
    "8479": ("Máquinas y aparatos mecánicos con función propia, no expresados en otra parte", 1.8e9, 12.0),
    "3004": ("Medicamentos dosificados o acondicionados para la venta al por menor", 8.5e9, 60.0),
    "1905": ("Productos de panadería, pastelería o galletería; hostias y obleas", 1.4e9, 2.6),
    "6203": ("Trajes, conjuntos, chaquetas y pantalones para hombres o niños", 1.6e9, 18.0),
}

CHAPTERS = {
    "02": "Carne y despojos comestibles",
    "19": "Preparaciones a base de cereales, harina, almidón, fécula o leche",
    "22": "Bebidas, líquidos alcohólicos y vinagre",
    "30": "Productos farmacéuticos",
    "48": "Papel y cartón; manufacturas de pasta de celulosa, papel o cartón",
    "62": "Prendas y complementos de vestir, excepto los de punto",
    "84": "Máquinas, aparatos y artefactos mecánicos y sus partes",
    "87": "Vehículos automóviles, tractores y demás vehículos terrestres",
}

# (código, nombre, iso2, región, miembro UE, access_tier — mapeo estático)
COUNTRIES = [
    ("FR", "Francia", "FR", "Europa occidental", True, "UE"),
    ("DE", "Alemania", "DE", "Europa occidental", True, "UE"),
    ("IT", "Italia", "IT", "Europa del Sur", True, "UE"),
    ("PT", "Portugal", "PT", "Europa del Sur", True, "UE"),
    ("NL", "Países Bajos", "NL", "Europa occidental", True, "UE"),
    ("BE", "Bélgica", "BE", "Europa occidental", True, "UE"),
    ("PL", "Polonia", "PL", "Europa del Este", True, "UE"),
    ("AT", "Austria", "AT", "Europa occidental", True, "UE"),
    ("IE", "Irlanda", "IE", "Europa occidental", True, "UE"),
    ("SE", "Suecia", "SE", "Europa del Norte", True, "UE"),
    ("DK", "Dinamarca", "DK", "Europa del Norte", True, "UE"),
    ("FI", "Finlandia", "FI", "Europa del Norte", True, "UE"),
    ("CZ", "Chequia", "CZ", "Europa del Este", True, "UE"),
    ("RO", "Rumanía", "RO", "Europa del Este", True, "UE"),
    ("HU", "Hungría", "HU", "Europa del Este", True, "UE"),
    ("GR", "Grecia", "GR", "Europa del Sur", True, "UE"),
    ("SK", "Eslovaquia", "SK", "Europa del Este", True, "UE"),
    ("BG", "Bulgaria", "BG", "Europa del Este", True, "UE"),
    ("HR", "Croacia", "HR", "Europa del Sur", True, "UE"),
    ("LT", "Lituania", "LT", "Europa del Norte", True, "UE"),
    ("GB", "Reino Unido", "GB", "Europa occidental", False, "EFTA/Acuerdo UE"),
    ("CH", "Suiza", "CH", "Europa occidental", False, "EFTA/Acuerdo UE"),
    ("NO", "Noruega", "NO", "Europa del Norte", False, "EFTA/Acuerdo UE"),
    ("TR", "Turquía", "TR", "Oriente Medio", False, "EFTA/Acuerdo UE"),
    ("MX", "México", "MX", "América Latina", False, "EFTA/Acuerdo UE"),
    ("CA", "Canadá", "CA", "América del Norte", False, "EFTA/Acuerdo UE"),
    ("KR", "Corea del Sur", "KR", "Asia oriental", False, "EFTA/Acuerdo UE"),
    ("JP", "Japón", "JP", "Asia oriental", False, "EFTA/Acuerdo UE"),
    ("US", "Estados Unidos", "US", "América del Norte", False, "Resto"),
    ("CN", "China", "CN", "Asia oriental", False, "Resto"),
    ("MA", "Marruecos", "MA", "Norte de África", False, "Resto"),
    ("BR", "Brasil", "BR", "América Latina", False, "Resto"),
    ("AE", "Emiratos Árabes Unidos", "AE", "Oriente Medio", False, "Resto"),
    ("SA", "Arabia Saudí", "SA", "Oriente Medio", False, "Resto"),
    ("IN", "India", "IN", "Asia meridional", False, "Resto"),
]

PROVINCES = ["50", "22", "44", "08", "28", "46", "43"]  # Aragón + 4 más
PROVINCE_SHARE_RANGES = {
    "50": (0.02, 0.10), "22": (0.005, 0.03), "44": (0.002, 0.015),
    "08": (0.10, 0.25), "28": (0.08, 0.20), "46": (0.05, 0.15),
    "43": (0.03, 0.10),
}

# pares producto-país con kilos = 0 (caso valor unitario no calculable)
ZERO_KILOS_PAIRS = {("3004", "CH"), ("8479", "NO")}

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
CREATE TABLE meta_info (
  extracted_at DATE NOT NULL,
  is_synthetic BOOLEAN NOT NULL DEFAULT FALSE
);
"""


def month_range(start, end):
    d = start
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def build(out_path):
    rng = random.Random(SEED)
    months = list(month_range(START, END))
    trade_rows = []      # (period, flow, cc, name, taric, prov, euros, kilos, provisional)
    operator_rows = []

    for taric, (_, annual_scale, uv_base) in PRODUCTS.items():
        # país: peso lognormal (cola pesada, como el comercio real)
        participants = []
        for code, name, *_ in COUNTRIES:
            if rng.random() > 0.88:
                continue  # este país no compra este producto
            start = START
            if rng.random() < 0.08:  # mercado nuevo → histórico corto
                start = date(rng.choice([2023, 2024, 2025]), rng.randint(1, 12), 1)
            participants.append({
                "code": code, "name": name, "start": start,
                "weight": rng.lognormvariate(0, 1.3),
                "growth": rng.uniform(-0.06, 0.14),
                "uv": uv_base * rng.uniform(0.7, 1.4),
            })
        total_weight = sum(p["weight"] for p in participants)
        amp = rng.uniform(0.08, 0.30)
        phase = rng.uniform(0, 12)
        prov_shares = {p: rng.uniform(*PROVINCE_SHARE_RANGES[p]) for p in PROVINCES}
        top_codes = {p["code"] for p in sorted(
            participants, key=lambda p: p["weight"], reverse=True)[:12]}

        yearly_pair_euros = {}  # (código, año) → € exportados (para operadores)
        for p in participants:
            base_monthly = annual_scale * p["weight"] / total_weight / 12
            zero_kilos = (taric, p["code"]) in ZERO_KILOS_PAIRS
            for m in months:
                if m < p["start"]:
                    continue
                t_years = (m.year - START.year) + (m.month - 1) / 12
                season = 1 + amp * math.sin(2 * math.pi * (m.month - phase) / 12)
                noise = max(0.5, 1 + rng.gauss(0, 0.07))
                euros = base_monthly * (1 + p["growth"]) ** t_years * season * noise
                kilos = 0.0 if zero_kilos else euros / (p["uv"] * max(0.6, 1 + rng.gauss(0, 0.05)))
                provisional = m >= PROVISIONAL_FROM
                trade_rows.append((m, "X", p["code"], p["name"], taric, None,
                                   euros, kilos, provisional))
                key = (p["code"], m.year)
                yearly_pair_euros[key] = yearly_pair_euros.get(key, 0.0) + euros
                if p["code"] in top_codes:
                    for prov, share in prov_shares.items():
                        pe = euros * share * max(0.5, 1 + rng.gauss(0, 0.05))
                        pk = 0.0 if zero_kilos else pe / p["uv"]
                        trade_rows.append((m, "X", p["code"], p["name"], taric,
                                           prov, pe, pk, provisional))

        # operadores anuales: ≤5 → NULL (secreto estadístico)
        for p in participants:
            ops_scale = p["weight"] / total_weight * 800
            for year in range(START.year, END.year):
                euros_year = yearly_pair_euros.get((p["code"], year))
                if not euros_year:
                    continue
                n_ops = max(1, round(ops_scale * rng.uniform(0.7, 1.3)))
                operator_rows.append((year, "X", p["code"], taric,
                                      None if n_ops <= 5 else n_ops, euros_year))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    con = duckdb.connect(str(out_path))
    con.execute(SCHEMA)

    trade_df = pd.DataFrame(trade_rows, columns=[
        "period", "flow", "country_code", "country_name", "taric",
        "province_code", "euros", "kilos", "is_provisional"])
    con.execute("""
        INSERT INTO trade
        SELECT CAST(period AS DATE), flow, country_code, country_name, taric,
               province_code, euros, kilos, is_provisional
        FROM trade_df
    """)
    con.executemany("INSERT INTO operators VALUES (?,?,?,?,?,?)", operator_rows)
    nomen = [(t, d, 2) for t, d in CHAPTERS.items()]
    nomen += [(t, desc, 4) for t, (desc, _, _) in PRODUCTS.items()]
    con.executemany("INSERT INTO nomenclature VALUES (?,?,?)", nomen)
    con.executemany("INSERT INTO countries VALUES (?,?,?,?,?,?)", COUNTRIES)
    # is_synthetic=TRUE: la app muestra el banner «Datos de demostración» y la
    # actualización (etl.update) nunca cortocircuita sobre una BD sintética.
    con.execute("INSERT INTO meta_info VALUES (current_date, TRUE)")

    n_trade = con.execute("SELECT count(*) FROM trade").fetchone()[0]
    pmin, pmax = con.execute("SELECT min(period), max(period) FROM trade").fetchone()
    con.close()
    print(f"Base de datos sintética generada en {out_path}")
    print(f"  filas trade: {n_trade:,} · operadores: {len(operator_rows):,}")
    print(f"  productos: {len(PRODUCTS)} · países: {len(COUNTRIES)} · "
          f"periodo: {pmin} → {pmax}")


if __name__ == "__main__":
    default_out = Path(__file__).resolve().parents[1] / "data" / "brujula.duckdb"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=default_out,
                        help="ruta del DuckDB de salida")
    args = parser.parse_args()
    build(args.out)
