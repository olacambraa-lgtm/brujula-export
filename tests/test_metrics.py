"""Tests unitarios del motor de métricas (app/metrics.py).

Todos los valores esperados están calculados a mano y documentados en
comentarios. Los tests de motor usan la fixture de conftest.py (ver allí el
diseño completo de los datos).
"""

import math

import pytest

from app.metrics import (
    Database,
    cagr_3y,
    coef_variation,
    percentile_ranks,
    score_product,
    winsorize,
)


@pytest.fixture(scope="module")
def db(db_path):
    return Database(db_path)


# ---------------------------------------------------------------- winsorize

def test_winsorize_clips_tails():
    # valores 1..20 → p5 con interpolación lineal: pos = 0.05·19 = 0.95
    #   → 1 + 0.95·(2−1) = 1.95
    # p95: pos = 0.95·19 = 18.05 → 19 + 0.05·(20−19) = 19.05
    values = [float(v) for v in range(1, 21)]
    w = winsorize(values)
    assert w[0] == pytest.approx(1.95)
    assert w[-1] == pytest.approx(19.05)
    # los valores interiores no cambian y se conserva el orden
    assert w[1:-1] == values[1:-1]
    assert len(w) == 20


def test_winsorize_constant_and_empty():
    assert winsorize([10.0] * 5) == [10.0] * 5
    assert winsorize([]) == []


# ----------------------------------------------------------------- cagr_3y

def test_cagr_exact():
    # (121/100)^(1/2) − 1 = 1.1 − 1 = 0.1 exacto
    assert cagr_3y([100.0, 110.0, 121.0]) == pytest.approx(0.1)


def test_cagr_requires_three_years():
    assert cagr_3y([100.0, 121.0]) is None


def test_cagr_null_year_is_not_zero():
    # un año sin dato (NULL) no se trata como 0: el CAGR es incalculable
    assert cagr_3y([None, 100.0, 121.0]) is None
    assert cagr_3y([100.0, None, 121.0]) is None


def test_cagr_needs_positive_values():
    # años completos con valor > 0; un 0 invalida el cálculo
    assert cagr_3y([0.0, 100.0, 121.0]) is None


# ---------------------------------------------------------- coef_variation

def test_cv_exact():
    # valores 600,720,600,480,600 → media 600
    # desv: 0,120,0,−120,0 → var poblacional = (14400+14400)/5 = 5760
    # std = √5760 = 75.8946… → CV = 0.1264911064
    assert coef_variation([600.0, 720.0, 600.0, 480.0, 600.0]) == pytest.approx(0.1264911064)


def test_cv_minimum_three_values():
    assert coef_variation([100.0, 100.0]) is None


def test_cv_excludes_nulls():
    # NULL se excluye, no se trata como 0: quedan 600,600,480,600
    # media 570; desv 30,30,−90,30 → var = 10800/4 = 2700
    # CV = √2700/570 = 0.0911605688
    assert coef_variation([600.0, None, 600.0, 480.0, 600.0]) == pytest.approx(0.0911605688)


def test_cv_zero_mean_is_none():
    assert coef_variation([0.0, 0.0, 0.0]) is None


# --------------------------------------------------------- percentile_ranks

def test_percentile_basic():
    # ranks 0,1,2 → /(3−1)·100 → 0, 50, 100
    assert percentile_ranks([10.0, 20.0, 30.0]) == [0.0, 50.0, 100.0]


def test_percentile_single_value_is_50():
    assert percentile_ranks([5.0]) == [50.0]


def test_percentile_ties_use_average_rank():
    # 10,10,20 → ranks medios (0+1)/2=0.5, 0.5, 2 → /(2)·100 → 25, 25, 100
    assert percentile_ranks([10.0, 10.0, 20.0]) == [25.0, 25.0, 100.0]


def test_percentile_none_is_neutral_50():
    # los None reciben 50 y NO participan en el ranking de los demás
    assert percentile_ranks([10.0, None, 30.0]) == [0.0, 50.0, 100.0]
    assert percentile_ranks([None, None]) == [50.0, 50.0]


# ------------------------------------------------------------ motor: 2204

def _country(result, code):
    return next(c for c in result["countries"] if c["country_code"] == code)


def test_score_header(db):
    r = score_product(db, "2204")
    # total nacional 12m = 1440+2400+600+360+240+270 = 5310
    assert r["taric"] == "2204"
    assert r["total_exports_12m"] == pytest.approx(5310.0)
    assert r["period_window"] == {"from": "2025-04", "to": "2026-03"}
    assert r["n_candidates"] == 6
    assert r["warning"] is None
    # cuotas provinciales: Aragón = (120+60)/5310 · Zaragoza = 120/5310
    assert r["aragon_share"] == pytest.approx(180 / 5310)
    assert r["zaragoza_share"] == pytest.approx(120 / 5310)


def test_score_fr_metrics(db):
    m = _country(score_product(db, "2204"), "FR")["metrics"]
    assert m["size_eur_12m"] == pytest.approx(1440.0)
    # CAGR = (1440/1200)^(1/2) − 1 = √1.2 − 1 = 0.0954451150
    # (la winsorización p5-p95 del pool no toca los valores de FR)
    assert m["cagr_3y"] == pytest.approx(math.sqrt(1.2) - 1)
    # CV: 1200,1200,1200,1320,1440 → media 1272, std poblacional 96
    # → CV = 96/1272 = 0.0754716981
    assert m["stability_cv"] == pytest.approx(96 / 1272)
    # €/kg 12m = 1440/360 = 4.0 · mediana de candidatos [1,2,3,4,5] = 3
    assert m["unit_value_eur_kg"] == pytest.approx(4.0)
    assert m["unit_value_rel"] == pytest.approx(4 / 3)
    # último año con dato de operadores: 2025 → 1440/10 = 144
    assert m["eur_per_operator"] == pytest.approx(144.0)
    assert m["num_operators"] == 10
    assert m["access"] == "UE"


def test_score_size_components(db):
    # 12m: JP 240, GB 270, US 360, PT 600, FR 1440, DE 2400
    # → ranks 0..5 → /(5)·100 → 0, 20, 40, 60, 80, 100
    r = score_product(db, "2204")
    expected = {"JP": 0, "GB": 20, "US": 40, "PT": 60, "FR": 80, "DE": 100}
    for code, comp in expected.items():
        assert _country(r, code)["components"]["size"] == pytest.approx(comp), code


def test_score_growth_components(db):
    # CAGR: US −0.2254, DE 0, PT 0, JP 0 (empate → rank medio 2), FR 0.0954
    # GB null → 50 neutro. Percentiles /(4)·100: US 0, empate 50, FR 100.
    r = score_product(db, "2204")
    expected = {"US": 0, "DE": 50, "PT": 50, "JP": 50, "FR": 100, "GB": 50}
    for code, comp in expected.items():
        assert _country(r, code)["components"]["growth"] == pytest.approx(comp), code


def test_score_stability_components(db):
    # CV: DE 0, JP 0 (rank medio 0.5), FR 0.0755, PT 0.1265, US 0.1581
    # percentil(cv): 12.5, 12.5, 50, 75, 100 → componente = 100 − percentil
    r = score_product(db, "2204")
    expected = {"DE": 87.5, "JP": 87.5, "FR": 50, "PT": 25, "US": 0, "GB": 50}
    for code, comp in expected.items():
        assert _country(r, code)["components"]["stability"] == pytest.approx(comp), code


def test_score_unit_value_components(db):
    # €/kg relativos: PT 1/3, DE 2/3, GB 1, FR 4/3, US 5/3 → 0,25,50,75,100
    # JP kilos=0 → null → 50 neutro
    r = score_product(db, "2204")
    expected = {"PT": 0, "DE": 25, "GB": 50, "FR": 75, "US": 100, "JP": 50}
    for code, comp in expected.items():
        assert _country(r, code)["components"]["unit_value"] == pytest.approx(comp), code


def test_score_competition_components(db):
    # €/operador: US 90, PT 100, JP 120, FR 144 → 0, 33.33, 66.67, 100
    # DE (NULL secreto) y GB (sin fila) → 50 neutro
    r = score_product(db, "2204")
    expected = {"US": 0, "PT": 100 / 3, "JP": 200 / 3, "FR": 100, "DE": 50, "GB": 50}
    for code, comp in expected.items():
        assert _country(r, code)["components"]["competition"] == pytest.approx(comp), code


def test_score_access_components(db):
    # UE → 100 · EFTA/Acuerdo UE → 75 · Resto → 40
    r = score_product(db, "2204")
    assert _country(r, "FR")["components"]["access"] == 100
    assert _country(r, "GB")["components"]["access"] == 75
    assert _country(r, "US")["components"]["access"] == 40


def test_score_flags(db):
    r = score_product(db, "2204")
    gb = _country(r, "GB")
    # GB: 9 meses con dato en 60 meses → low_data; sin histórico → nd_growth
    # y nd_stability; sin operadores → nd_operators
    for flag in ("low_data", "nd_growth", "nd_stability", "nd_operators"):
        assert flag in gb["flags"]
    assert _country(r, "JP")["flags"] == ["nd_unit_value"]
    assert _country(r, "DE")["flags"] == ["nd_operators"]
    assert _country(r, "FR")["flags"] == []


def test_score_nulls_never_zero(db):
    # las celdas NULL llegan como null en metrics, jamás como 0
    r = score_product(db, "2204")
    de = _country(r, "DE")["metrics"]
    assert de["num_operators"] is None
    assert de["eur_per_operator"] is None
    jp = _country(r, "JP")["metrics"]
    assert jp["unit_value_eur_kg"] is None
    assert jp["unit_value_rel"] is None
    gb = _country(r, "GB")["metrics"]
    assert gb["cagr_3y"] is None
    assert gb["stability_cv"] is None


def test_score_few_candidates_warning(db):
    r = score_product(db, "0203")
    assert r["n_candidates"] == 3
    assert r["warning"] is not None
    assert len(r["countries"]) == 3
    # sin datos provinciales → null, nunca 0
    assert r["aragon_share"] is None
    assert r["zaragoza_share"] is None


def test_score_single_candidate_neutral(db):
    # n=1 → todos los percentiles valen 50; el acceso sigue siendo el del país
    r = score_product(db, "8703")
    assert r["n_candidates"] == 1
    assert r["warning"] is not None
    de = r["countries"][0]
    for key in ("size", "growth", "stability", "unit_value", "competition"):
        assert de["components"][key] == pytest.approx(50), key
    assert de["components"]["access"] == 100


def test_score_unknown_taric(db):
    assert score_product(db, "9999") is None


# --------------------------------------------------- celdas provinciales NULL
# Hallazgo de la review: una provincia cuyas celdas 12m están TODAS ocultas por
# secreto estadístico (euros NULL) producía TypeError → HTTP 500. La provincia
# oculta debe desaparecer del desglose (n/d implícito), nunca romper ni
# convertirse en 0 dentro de la serie.

@pytest.fixture()
def db_null_prov(db_path, tmp_path):
    """Copia de la base de la fixture + filas provinciales con euros NULL."""
    import shutil
    import duckdb
    path = tmp_path / "null_prov.duckdb"
    shutil.copy(db_path, path)
    con = duckdb.connect(str(path))
    from datetime import date
    rows = [(date(2025, 5, 1), "X", "FR", "Francia", "2204", "44", None, None, True),
            (date(2025, 6, 1), "X", "FR", "Francia", "2204", "44", None, None, True)]
    con.executemany("INSERT INTO trade VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    return Database(str(path))


def test_score_product_with_hidden_provincial_cells(db_null_prov):
    # Teruel (44) oculta por completo: no debe romper; las cuotas se calculan
    # con las provincias visibles (50: 120, 22: 60 → aragon 180/5310)
    r = score_product(db_null_prov, "2204")
    assert r["aragon_share"] == pytest.approx(180 / 5310)
    assert r["zaragoza_share"] == pytest.approx(120 / 5310)


def test_market_detail_with_hidden_provincial_cells(db_null_prov):
    from app.metrics import market_detail
    r = market_detail(db_null_prov, "2204", "FR")
    codes = [p["province_code"] for p in r["provinces"]]
    assert "44" not in codes          # la oculta no aparece como 0 ni rompe
    assert "50" in codes and "22" in codes
    for p in r["provinces"]:
        assert p["euros_12m"] is not None and p["share"] is not None


def test_coef_variation_media_no_positiva():
    # Media negativa (devoluciones aduaneras) o cero → None, nunca un CV
    # negativo que convierta al país más errático en el más "estable"
    from app.metrics import coef_variation
    assert coef_variation([-100.0, -200.0, -300.0]) is None
    assert coef_variation([100.0, -100.0, 0.0]) is None  # media 0


@pytest.fixture()
def db_hidden_national(db_path, tmp_path):
    """MA como candidato de 2204 con TODA la ventana 12m oculta (euros NULL)."""
    import shutil
    import duckdb
    from datetime import date
    path = tmp_path / "hidden_nat.duckdb"
    shutil.copy(db_path, path)
    con = duckdb.connect(str(path))
    rows = [(date(2024, m, 1), "X", "MA", "Marruecos", "2204", None, 50.0, 10.0, True)
            for m in range(1, 7)]                 # candidato: export > 0 en 3 años
    rows += [(date(2025, 3 + i, 1) if 3 + i <= 12 else date(2026, i - 9, 1),
              "X", "MA", "Marruecos", "2204", None, None, None, True)
             for i in range(1, 13)]               # 2025-04 → 2026-03 todo oculto
    con.executemany("INSERT INTO trade VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    return Database(str(path))


def test_hidden_12m_size_is_null_neutral_flagged(db_hidden_national):
    # Filas presentes con suma NULL → size null, componente 50 neutro, nd_size;
    # un país SIN filas en la ventana sigue siendo 0 legítimo sin flag
    r = score_product(db_hidden_national, "2204")
    ma = next(c for c in r["countries"] if c["country_code"] == "MA")
    assert ma["metrics"]["size_eur_12m"] is None
    assert ma["components"]["size"] == 50.0
    assert "nd_size" in ma["flags"]


def test_yearly_all_hidden_year_is_null(db_hidden_national):
    # Año con todos los meses ocultos → euros null en la serie anual, nunca 0
    from app.metrics import market_detail
    r = market_detail(db_hidden_national, "2204", "MA")
    y2026 = next(y for y in r["yearly"] if y["year"] == 2026)
    assert y2026["euros"] is None
