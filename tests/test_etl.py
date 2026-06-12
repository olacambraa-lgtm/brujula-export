"""Tests del ETL (etl/datacomex_client.py, etl/load.py).

OFFLINE por defecto: las fixtures son strings de respuestas REALES capturadas
el 2026-06-11 contra DataComex. Los tests de red solo corren con
BRUJULA_NETWORK_TESTS=1.
"""

import json
import os
from datetime import date

import duckdb
import pytest

from etl.datacomex_client import CsvChainError, parse_csv
from etl.load import api_rows, build_db, clean_description, map_flow, taric4

# ---------------------------------------------------------------------------
# Fixtures: respuestas reales capturadas (latin-1, sep ';', decimal coma, CRLF)
# ---------------------------------------------------------------------------

CSV_HEADER = ('"flujo_codigo";"flujo_nombre";"periodo_anio";"periodo_mes";'
              '"periodo_provisional";"pais_codigo";"pais_nombre";"taric";'
              '"euros";"kilos";')

CSV_REAL = CSV_HEADER + "\r\n" + "\r\n".join([
    '"E";"Exportación";"2024";"01";"D";"001";"Francia";"2204";"20276521,71";"36575300,44";',
    '"I";"Importación";"2024";"01";"D";"001";"Francia";"2204";"9273425,74";"1090869,90";',
    '"E";"Exportación";"2025";"03";"P";"004";"Alemania";"2204";"34283239,12";"39724169,00";',
    # celda oculta / sin dato → vacía (NULL, nunca 0)
    '"E";"Exportación";"2025";"03";"P";"732";"Japón";"2204";"";"";',
    # agregado anual (mes vacío) como el que devuelve year_[2024]
    '"E";"Exportación";"2024";"";"P";"001";"Francia";"Total Taric";"57592098769,34";"26546382369,96";',
]) + "\r\n"


def test_parse_csv_real():
    rows = parse_csv(CSV_REAL)
    assert len(rows) == 5
    r = rows[0]
    assert r["flow"] == "E"
    assert (r["year"], r["month"]) == (2024, 1)
    assert r["is_provisional"] is False
    assert r["country_code"] == "001"
    assert r["euros"] == pytest.approx(20276521.71)  # decimal coma → float
    assert r["kilos"] == pytest.approx(36575300.44)
    assert rows[2]["is_provisional"] is True  # 'P'


def test_parse_csv_null_nunca_cero():
    rows = parse_csv(CSV_REAL)
    japon = rows[3]
    assert japon["euros"] is None
    assert japon["kilos"] is None


def test_parse_csv_agregado_anual_sin_mes():
    anual = parse_csv(CSV_REAL)[4]
    assert anual["month"] is None
    assert anual["taric"] == "Total Taric"


def test_parse_csv_cabecera_inesperada():
    with pytest.raises(CsvChainError):
        parse_csv('"otra";"cosa"\r\n"x";"y"\r\n')


def test_map_flow():
    assert map_flow("E") == "X"
    assert map_flow("Exportación") == "X"
    assert map_flow("EXPORT") == "X"
    assert map_flow("I") == "M"
    assert map_flow("Importación") == "M"
    with pytest.raises(ValueError):
        map_flow("Z")


def test_taric4_agrega_y_descarta():
    assert taric4("2204") == "2204"
    assert taric4("22041010") == "2204"   # detalle 8d → 4d
    assert taric4("22SS") == "22SS"       # nodo especial de 4 caracteres
    assert taric4("22") is None           # capítulo: no es serie TARIC-4
    assert taric4("Total Taric") is None  # agregado del formulario web


def test_clean_description():
    assert clean_description("2204", "2204 Vino de uvas frescas") == "Vino de uvas frescas"
    assert clean_description("22", "22 BEBIDAS") == "BEBIDAS"
    assert clean_description("0203", "Carne de porcino") == "Carne de porcino"


def test_api_rows_mapeo():
    prov_flags = {"202401": False, "202501": True}
    rec = {"flujo": "E", "periodo": "202401", "pais": "Francia", "id_pais": "1",
           "prov": "", "id_prov": "", "taric": "22041010", "euros": 5.0,
           "kilos": None, "mensaje": "Datos definitivos"}
    row = api_rows(rec, "202401", None, prov_flags)
    assert row == (date(2024, 1, 1), "X", "001", "Francia", "2204", None,
                   5.0, None, False)
    # mensaje provisional manda; sin mensaje, decide la maestra de periodos
    rec["mensaje"] = "Datos provisionales"
    assert api_rows(rec, "202401", None, prov_flags)[8] is True
    rec["mensaje"] = ""
    assert api_rows(rec, "202501", "50", prov_flags)[8] is True
    assert api_rows(rec, "202501", "50", prov_flags)[5] == "50"


# ---------------------------------------------------------------------------
# End-to-end: raw sintético → build_db → DuckDB
# ---------------------------------------------------------------------------

@pytest.fixture()
def raw_dir(tmp_path):
    masters = tmp_path / "masters"
    masters.mkdir()
    # Maestra de países: las agrupaciones (Total Mundo, avituallamiento) deben
    # quedar excluidas; el resto se rellena para superar la validación de
    # nº de países (~250) con códigos presentes en countries_meta.csv.
    import csv as csv_mod
    from etl.load import META_CSV
    with open(META_CSV, encoding="utf-8") as fh:
        meta_codes = [r["datacomex_code"]
                      for r in csv_mod.DictReader(fh, delimiter=";")]
    paises = [{"Id": "0", "Pais": "Total Mundo", "UE": ""},
              {"Id": "950", "Pais": "Avituallamiento y combustible", "UE": "Extra UE27"},
              {"Id": "001", "Pais": "Francia", "UE": "UE27"},
              {"Id": "004", "Pais": "Alemania", "UE": "UE27"},
              {"Id": "732", "Pais": "Japón", "UE": "Extra UE27"}]
    paises += [{"Id": c, "Pais": f"País {c}", "UE": "Extra UE27"}
               for c in meta_codes if c not in {"001", "004", "732"}]
    (masters / "paises.json").write_text(json.dumps(paises), encoding="utf-8")

    tarics = [{"Taric": "22", "TaricPadre": "", "Nombre": "22 BEBIDAS", "Nivel": "1"},
              {"Taric": "2204", "TaricPadre": "22",
               "Nombre": "2204 Vino de uvas frescas", "Nivel": "2"},
              {"Taric": "220410", "TaricPadre": "2204",
               "Nombre": "220410 Vino espumoso", "Nivel": "3"}]
    # Relleno para superar la validación de nomenclatura (~1.200 códigos 4d).
    tarics += [{"Taric": f"{i:04d}", "TaricPadre": f"{i:04d}"[:2],
                "Nombre": f"{i:04d} Producto {i}", "Nivel": "2"}
               for i in range(5000, 6300)]
    (masters / "tarics.json").write_text(json.dumps(tarics), encoding="utf-8")

    periodos = [{"Periodo": "Enero de 2024", "CodPeriodo": "202401", "Nivel": "2",
                 "DatosDefinitivos": True},
                {"Periodo": "Febrero de 2024", "CodPeriodo": "202402", "Nivel": "2",
                 "DatosDefinitivos": True},
                {"Periodo": "Marzo de 2025", "CodPeriodo": "202503", "Nivel": "2",
                 "DatosDefinitivos": False},
                {"Periodo": "Abril de 2025", "CodPeriodo": "202504", "Nivel": "2",
                 "DatosDefinitivos": False}]
    (masters / "periodos.json").write_text(json.dumps(periodos), encoding="utf-8")
    (masters / "provincias.json").write_text(
        json.dumps([{"Provincia": "Zaragoza", "CodProvincia": "50"}]), encoding="utf-8")
    (masters / "flujos.json").write_text(
        json.dumps([{"Flujo": "EXPORT", "CodFlujo": "E"},
                    {"Flujo": "IMPORT", "CodFlujo": "I"}]), encoding="utf-8")

    # Vía API (nacional, 2024-01): detalle 8d a agregar a 4d; euros NULL;
    # fila Total Mundo a excluir; sin mensaje → decide la maestra de periodos.
    nacional = [
        {"flujo": "E", "periodo": "202401", "pais": "Francia", "id_pais": "001",
         "taric": "22041010", "euros": 100.0, "kilos": 10.0, "mensaje": ""},
        {"flujo": "E", "periodo": "202401", "pais": "Francia", "id_pais": "001",
         "taric": "22042020", "euros": 50.0, "kilos": None, "mensaje": ""},
        {"flujo": "I", "periodo": "202401", "pais": "Alemania", "id_pais": "004",
         "taric": "2204", "euros": None, "kilos": None, "mensaje": ""},
        {"flujo": "E", "periodo": "202401", "pais": "Total Mundo", "id_pais": "0",
         "taric": "2204", "euros": 999999.0, "kilos": 1.0, "mensaje": ""},
    ]
    (tmp_path / "trade" / "nacional").mkdir(parents=True)
    (tmp_path / "trade" / "nacional" / "202401.json").write_text(
        json.dumps(nacional), encoding="utf-8")
    prov = [{"flujo": "E", "periodo": "202401", "pais": "Francia", "id_pais": "001",
             "taric": "2204", "euros": 7.0, "kilos": 1.0,
             "mensaje": "Datos definitivos"}]
    (tmp_path / "trade" / "prov50").mkdir(parents=True)
    (tmp_path / "trade" / "prov50" / "202401.json").write_text(
        json.dumps(prov), encoding="utf-8")

    # Vía CSV (nacional): 2024-01 debe IGNORARSE (lo cubre la API); 2025-03
    # entra con flag provisional 'P'; fila de agregación '000 Total País'
    # excluida; acentos en latin-1.
    csv_text = CSV_HEADER + "\r\n" + "\r\n".join([
        '"E";"Exportación";"2024";"01";"D";"001";"Francia";"2204";"11111,00";"1,00";',
        '"E";"Exportación";"2025";"03";"P";"732";"Japón";"2204";"20,50";"2,00";',
        '"E";"Exportación";"2025";"03";"P";"000";"Total País";"2204";"77777,00";"7,00";',
        # El portal marca 'D' meses que la maestra declara provisionales: manda la maestra
        '"E";"Exportación";"2025";"04";"D";"732";"Japón";"2204";"30,00";"3,00";',
    ]) + "\r\n"
    (tmp_path / "trade_csv" / "2025").mkdir(parents=True)
    (tmp_path / "trade_csv" / "2025" / "22_00.csv").write_text(
        csv_text, encoding="latin-1")
    return tmp_path


def test_build_db_end_to_end(raw_dir, tmp_path):
    db = tmp_path / "out.duckdb"
    counts = build_db(db, raw_dir=raw_dir)
    assert counts["operators"] == 0  # creada y vacía a propósito
    con = duckdb.connect(str(db))

    # Agregación 8d → 4d con suma y NULL de kilos conservado en la suma parcial
    fr = con.execute("SELECT euros, kilos FROM trade WHERE country_code='001' "
                     "AND flow='X' AND province_code IS NULL "
                     "AND period='2024-01-01'").fetchone()
    assert fr[0] == pytest.approx(150.0)   # 100 + 50
    assert fr[1] == pytest.approx(10.0)    # 10 + NULL = 10 (no 0 fantasma)

    # NULL nunca 0
    de = con.execute("SELECT euros, kilos FROM trade WHERE country_code='004' "
                     "AND flow='M'").fetchone()
    assert de == (None, None)

    # Exclusión de agregados no-país: Total Mundo ('0') y Total País ('000')
    assert con.execute("SELECT count(*) FROM trade WHERE country_code IN "
                       "('0','000')").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM countries WHERE country_code IN "
                       "('0','000','950')").fetchone()[0] == 0

    # Dedup: 2024-01 nacional viene de la API (150), no del CSV (11111)
    assert con.execute("SELECT count(*) FROM trade WHERE euros=11111").fetchone()[0] == 0

    # CSV 2025-03 entra con provisional=TRUE; latin-1 conserva acentos
    jp = con.execute("SELECT euros, is_provisional, country_name FROM trade "
                     "WHERE country_code='732'").fetchone()
    assert jp[0] == pytest.approx(20.5)
    assert jp[1] is True
    assert jp[2] == "Japón"

    # CSV con flag 'D' en mes que la maestra declara provisional → provisional
    # (verificado empíricamente: el CSV del portal marca 'D' incluso 2026)
    assert con.execute("SELECT is_provisional FROM trade WHERE country_code='732' "
                       "AND period='2025-04-01'").fetchone()[0] is True

    # API sin mensaje → flag de la maestra de periodos (202401 definitivo)
    assert con.execute("SELECT is_provisional FROM trade WHERE country_code='001' "
                       "AND period='2024-01-01' AND province_code IS NULL "
                       "AND flow='X'").fetchone()[0] is False

    # Provincial con province_code; nacional con NULL
    assert con.execute("SELECT euros FROM trade WHERE province_code='50'"
                       ).fetchone()[0] == pytest.approx(7.0)

    # Nomenclatura: solo niveles 2 y 4 (longitud de código), descripción limpia
    assert con.execute("SELECT DISTINCT level FROM nomenclature ORDER BY 1"
                       ).fetchall() == [(2,), (4,)]
    assert con.execute("SELECT description FROM nomenclature WHERE taric='2204'"
                       ).fetchone()[0] == "Vino de uvas frescas"
    assert con.execute("SELECT count(*) FROM nomenclature WHERE taric='220410'"
                       ).fetchone()[0] == 0

    # countries enriquecida con metadatos estáticos
    assert con.execute("SELECT iso2, region, eu_member, access_tier FROM countries "
                       "WHERE country_code='001'").fetchone() == \
        ("FR", "Europa occidental", True, "UE")
    assert con.execute("SELECT access_tier FROM countries WHERE country_code='732'"
                       ).fetchone()[0] == "EFTA/Acuerdo UE"
    con.close()


# ---------------------------------------------------------------------------
# Tests de red (solo con BRUJULA_NETWORK_TESTS=1)
# ---------------------------------------------------------------------------

network = pytest.mark.skipif(os.environ.get("BRUJULA_NETWORK_TESTS") != "1",
                             reason="tests de red desactivados "
                                    "(exporta BRUJULA_NETWORK_TESTS=1)")


@network
def test_red_maestras():
    from etl.datacomex_client import get_flujos, get_paises
    assert {f["CodFlujo"] for f in get_flujos()} == {"E", "I"}
    assert len(get_paises()) > 250


@network
def test_red_cadena_csv():
    from etl.datacomex_client import CsvSession
    rows = parse_csv(CsvSession().query(["202401"], taric_codes=["2204"],
                                        countries=["001"]))
    assert rows and rows[0]["taric"] == "2204"
    assert all(r["country_code"] == "001" for r in rows)
