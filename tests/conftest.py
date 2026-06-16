"""Fixtures compartidas: DuckDB temporal con el esquema de la spec §4 y datos
sintéticos PEQUEÑOS conocidos a mano.

Diseño de los datos (todos los valores mensuales son constantes dentro de cada
año para poder calcular los agregados a mano; el rango global es 2015-01 →
2026-03, por lo que la ventana de 12 meses es 2025-04 → 2026-03 y los últimos
años completos son 2023, 2024 y 2025):

Producto 2204 (vino) — 6 países candidatos:
  país  valor mensual por año (euros)                kilos        12m   anual 2021-2025
  FR    2021-23: 100 · 2024: 110 · 2025-26: 120      euros/4      1440  1200,1200,1200,1320,1440
  DE    2021-26: 200                                 euros/2      2400  2400 × 5
  PT    2021: 50 · 2022: 60 · 2023: 50 · 2024: 40
        2025-26: 50                                  euros/1       600  600,720,600,480,600
  US    2021-22: 40 · 2023: 50 · 2024: 40 ·
        2025-26: 30                                  euros/5       360  480,480,600,480,360
  JP    2023-26: 20                                  kilos = 0     240  —,—,240,240,240
  GB    solo 2025-07 → 2026-03: 30                   euros/3       270  (2025 parcial = 180)
        → 9 meses con dato en 5 años → low_data; sin 2023/24 → cagr null;
          un solo año → cv null.

  Provincial 2204 (solo 2025-01 → 2026-03, país FR):
  prov 50 (Zaragoza): 10/mes → 12m = 120 · prov 22 (Huesca): 5/mes → 12m = 60
  → total nacional 12m = 1440+2400+600+360+240+270 = 5310
  → aragon_share = 180/5310 · zaragoza_share = 120/5310

  Operadores 2204 (flow X): FR 2024 (8, 1320), FR 2025 (10, 1440),
  DE 2025 (NULL ← secreto estadístico, 2400), PT 2025 (6, 600),
  US 2025 (4, 360), JP 2025 (2, 240). GB sin fila.
  → €/operador (último año con dato): FR 144, PT 100, US 90, JP 120,
    DE null (NULL nunca es 0), GB null.

Producto 0203 (porcino) — 3 candidatos (FR, JP, MA), 100/mes desde 2024-01
  → warning por <5 candidatos; cagr/cv null (sin histórico).

Producto 8703 (automóviles) — 1 candidato (DE), 1000/mes desde 2015-01
  → n=1: todos los percentiles = 50.

Fila 'M' (importación) en 2204/FR con 99999 € para verificar que los cálculos
filtran flow='X'.

Datos 2024+ → is_provisional = TRUE.
"""

import sys
from datetime import date
from pathlib import Path

import duckdb
import pytest

# El proyecto no se instala como paquete: añadimos la raíz al path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

COUNTRY_NAMES = {
    "FR": "Francia",
    "DE": "Alemania",
    "PT": "Portugal",
    "GB": "Reino Unido",
    "CH": "Suiza",
    "US": "Estados Unidos",
    "JP": "Japón",
    "MA": "Marruecos",
}

COUNTRIES = [
    ("FR", "Francia", "FR", "Europa occidental", True, "UE"),
    ("DE", "Alemania", "DE", "Europa occidental", True, "UE"),
    ("PT", "Portugal", "PT", "Europa occidental", True, "UE"),
    ("GB", "Reino Unido", "GB", "Europa occidental", False, "EFTA/Acuerdo UE"),
    ("CH", "Suiza", "CH", "Europa occidental", False, "EFTA/Acuerdo UE"),
    ("US", "Estados Unidos", "US", "América del Norte", False, "Resto"),
    ("JP", "Japón", "JP", "Asia oriental", False, "Resto"),
    ("MA", "Marruecos", "MA", "Norte de África", False, "Resto"),
]

NOMENCLATURE = [
    ("22", "Bebidas, líquidos alcohólicos y vinagre", 2),
    ("2204", "Vino de uvas frescas, incluso encabezado; mosto de uva", 4),
    ("2205", "Vermut y demás vinos de uvas frescas preparados con plantas", 4),
    ("02", "Carne y despojos comestibles", 2),
    ("0203", "Carne de animales de la especie porcina, fresca, refrigerada o congelada", 4),
    ("8703", "Automóviles de turismo y demás vehículos para el transporte de personas", 4),
]

OPERATORS = [
    (2024, "X", "FR", "2204", 8, 1320.0),
    (2025, "X", "FR", "2204", 10, 1440.0),
    (2025, "X", "DE", "2204", None, 2400.0),  # secreto estadístico → NULL
    (2025, "X", "PT", "2204", 6, 600.0),
    (2025, "X", "US", "2204", 4, 360.0),
    (2025, "X", "JP", "2204", 2, 240.0),
]

PROVISIONAL_FROM = date(2024, 1, 1)
DATA_END = date(2026, 3, 1)


def _series(rows, taric, country, monthly_by_year, kilo_div, start=None, province=None):
    """Añade filas mensuales constantes por año entre start (o enero del primer
    año) y DATA_END. kilo_div=None → kilos = 0 (caso valor unitario null)."""
    for year, value in monthly_by_year.items():
        for month in range(1, 13):
            d = date(year, month, 1)
            if start and d < start:
                continue
            if d > DATA_END:
                continue
            kilos = 0.0 if kilo_div is None else value / kilo_div
            rows.append((d, "X", country, COUNTRY_NAMES[country], taric, province,
                         value, kilos, d >= PROVISIONAL_FROM))


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "brujula_test.duckdb"
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)

    rows = []
    # --- 2204 vino ---
    _series(rows, "2204", "FR", {2021: 100.0, 2022: 100.0, 2023: 100.0,
                                 2024: 110.0, 2025: 120.0, 2026: 120.0}, 4)
    _series(rows, "2204", "DE", {y: 200.0 for y in range(2021, 2027)}, 2)
    _series(rows, "2204", "PT", {2021: 50.0, 2022: 60.0, 2023: 50.0,
                                 2024: 40.0, 2025: 50.0, 2026: 50.0}, 1)
    _series(rows, "2204", "US", {2021: 40.0, 2022: 40.0, 2023: 50.0,
                                 2024: 40.0, 2025: 30.0, 2026: 30.0}, 5)
    _series(rows, "2204", "JP", {y: 20.0 for y in range(2023, 2027)}, None)  # kilos = 0
    _series(rows, "2204", "GB", {2025: 30.0, 2026: 30.0}, 3, start=date(2025, 7, 1))
    # Provincial 2204 (Aragón), 2025-01 → 2026-03:
    _series(rows, "2204", "FR", {2025: 10.0, 2026: 10.0}, 4,
            start=date(2025, 1, 1), province="50")
    _series(rows, "2204", "FR", {2025: 5.0, 2026: 5.0}, 4,
            start=date(2025, 1, 1), province="22")
    # Fila de importación: debe quedar EXCLUIDA de todos los cálculos (flow='X').
    rows.append((date(2025, 5, 1), "M", "FR", "Francia", "2204", None,
                 99999.0, 1.0, True))

    # --- 0203 porcino: 3 candidatos desde 2024-01 ---
    for c in ("FR", "JP", "MA"):
        _series(rows, "0203", c, {2024: 100.0, 2025: 100.0, 2026: 100.0}, 2)

    # --- 8703 automóviles: 1 candidato con histórico largo ---
    _series(rows, "8703", "DE", {y: 1000.0 for y in range(2015, 2027)}, 2)

    con.executemany("INSERT INTO trade VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO operators VALUES (?,?,?,?,?,?)", OPERATORS)
    con.executemany("INSERT INTO nomenclature VALUES (?,?,?)", NOMENCLATURE)
    con.executemany("INSERT INTO countries VALUES (?,?,?,?,?,?)", COUNTRIES)
    con.close()
    return str(path)
