"""Tests de la API FastAPI contra el contrato docs/specs/api-contract.md.

Usa el DuckDB de fixture (ver conftest.py) y un directorio temporal de
insights con un único fichero 2204.md.
"""

import importlib
import os
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(db_path):
    os.environ["BRUJULA_DB"] = db_path
    import app.main as main
    importlib.reload(main)  # garantiza que lee las env vars de este test
    return TestClient(main.app)


# -------------------------------------------------------------------- meta

def test_meta_shape(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    data = r.json()
    assert data["period_min"] == "2015-01"
    assert data["period_max"] == "2026-03"
    assert data["provisional_from"] == "2024-01"
    assert data["n_products"] == 3        # 2204, 0203, 8703 con datos
    assert data["n_countries"] == 7       # FR, DE, PT, US, JP, GB, MA
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["extracted_at"])
    assert isinstance(data["source"], str) and "DataComex" in data["source"]
    assert isinstance(data["disclaimer"], str)


# ------------------------------------------------------------------ search

def test_search_text_without_accents(client):
    # "automoviles" sin acento debe encontrar "Automóviles…"
    r = client.get("/api/search", params={"q": "automoviles"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(item["taric"] == "8703" for item in results)


def test_search_text_with_accents_and_case(client):
    r = client.get("/api/search", params={"q": "AUTOMÓVILES"})
    assert any(item["taric"] == "8703" for item in r.json()["results"])


def test_search_text_orders_by_exports(client):
    # "vino" coincide con 2204 (con datos) y 2205 (sin datos):
    # mismo nivel → primero el de mayor valor exportado
    r = client.get("/api/search", params={"q": "vino"})
    results = r.json()["results"]
    tarics = [item["taric"] for item in results]
    assert tarics[:2] == ["2204", "2205"]
    by_taric = {item["taric"]: item for item in results}
    assert by_taric["2204"]["has_data"] is True
    assert by_taric["2205"]["has_data"] is False
    assert set(results[0]) == {"taric", "description", "level", "has_data"}


def test_search_numeric_prefix(client):
    # "22" → primero la coincidencia exacta (capítulo 22), luego nivel 4
    r = client.get("/api/search", params={"q": "22"})
    tarics = [item["taric"] for item in r.json()["results"]]
    assert tarics == ["22", "2204", "2205"]


def test_search_numeric_prefix_no_exact(client):
    r = client.get("/api/search", params={"q": "220"})
    tarics = [item["taric"] for item in r.json()["results"]]
    assert tarics == ["2204", "2205"]


def test_search_no_results_suggestion(client):
    r = client.get("/api/search", params={"q": "zzzznoexiste"})
    assert r.status_code == 200
    data = r.json()
    assert data["results"] == []
    assert isinstance(data["suggestion"], str) and data["suggestion"]


# ------------------------------------------------------------------ chapter

def test_chapter_index(client):
    # El capítulo 22 lista sus subpartidas de 4 dígitos; 2204 (con datos) antes
    # que 2205 (sin trade en el fixture → total null, al final).
    r = client.get("/api/chapter/22")
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == "22"
    assert data["level"] == 2
    children = data["children"]
    assert [c["taric"] for c in children] == ["2204", "2205"]
    assert children[0]["has_data"] is True
    assert children[0]["total_12m"] == pytest.approx(5310.0)
    assert children[1]["has_data"] is False
    assert children[1]["total_12m"] is None


def test_chapter_not_found(client):
    r = client.get("/api/chapter/99")
    assert r.status_code == 404


# ------------------------------------------------------------------- score

def test_score_contract_shape(client):
    r = client.get("/api/score/2204")
    assert r.status_code == 200
    data = r.json()
    assert data["taric"] == "2204"
    assert data["description"].startswith("Vino")
    assert data["total_exports_12m"] == pytest.approx(5310.0)
    assert data["aragon_share"] == pytest.approx(180 / 5310)
    assert data["zaragoza_share"] == pytest.approx(120 / 5310)
    assert data["period_window"] == {"from": "2025-04", "to": "2026-03"}
    assert data["n_candidates"] == 6
    assert data["warning"] is None
    assert data["default_weights"] == {
        "size": 0.25, "growth": 0.25, "stability": 0.15,
        "unit_value": 0.15, "competition": 0.10, "access": 0.10,
    }
    assert len(data["countries"]) == 6

    fr = next(c for c in data["countries"] if c["country_code"] == "FR")
    assert fr["name"] == "Francia"
    assert fr["iso2"] == "FR"
    assert fr["eu_member"] is True
    assert set(fr["metrics"]) == {
        "size_eur_12m", "cagr_3y", "stability_cv", "unit_value_eur_kg",
        "unit_value_rel", "eur_per_operator", "num_operators", "access",
    }
    assert set(fr["components"]) == {
        "size", "growth", "stability", "unit_value", "competition", "access",
    }
    assert fr["flags"] == []


def test_score_warning_under_five_candidates(client):
    r = client.get("/api/score/0203")
    assert r.status_code == 200
    data = r.json()
    assert data["n_candidates"] == 3
    assert isinstance(data["warning"], str) and data["warning"]


def test_score_taric_without_trade_data(client):
    # 2205 existe en nomenclatura pero no tiene comercio → 200 con aviso
    r = client.get("/api/score/2205")
    assert r.status_code == 200
    data = r.json()
    assert data["n_candidates"] == 0
    assert data["countries"] == []
    assert data["warning"] is not None


def test_score_unknown_taric_404(client):
    r = client.get("/api/score/9999")
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)


# ------------------------------------------------------------------ market

def test_market_contract_shape(client):
    r = client.get("/api/market/2204/FR")
    assert r.status_code == 200
    data = r.json()
    assert data["taric"] == "2204"
    assert data["country"]["name"] == "Francia"

    monthly = data["monthly"]
    # 2021-01 → 2026-03 = 63 meses (la fila de importación queda fuera)
    assert len(monthly) == 63
    assert monthly[0] == {"period": "2021-01", "euros": 100.0, "kilos": 25.0,
                          "is_provisional": False}
    jan24 = next(m for m in monthly if m["period"] == "2024-01")
    assert jan24["is_provisional"] is True

    yearly = {y["year"]: y for y in data["yearly"]}
    assert yearly[2021]["euros"] == pytest.approx(1200.0)
    assert yearly[2021]["kilos"] == pytest.approx(300.0)
    assert yearly[2021]["unit_value"] == pytest.approx(4.0)
    assert yearly[2026]["euros"] == pytest.approx(360.0)

    # estacionalidad: 3 años completos y definitivos (2021-2023) con valores
    # mensuales constantes → cada mes pesa 1/12
    assert len(data["seasonality"]) == 12
    for s in data["seasonality"]:
        assert s["avg_share"] == pytest.approx(1 / 12)

    assert data["operators"] == [
        {"year": 2024, "num_operators": 8, "euros": 1320.0},
        {"year": 2025, "num_operators": 10, "euros": 1440.0},
    ]

    provinces = {p["province_code"]: p for p in data["provinces"]}
    assert provinces["50"]["name"] == "Zaragoza"
    assert provinces["50"]["euros_12m"] == pytest.approx(120.0)
    assert provinces["50"]["share"] == pytest.approx(120 / 5310)
    assert provinces["22"]["euros_12m"] == pytest.approx(60.0)

    assert data["spain_total_12m"] == pytest.approx(5310.0)
    assert data["country_share_12m"] == pytest.approx(1440 / 5310)


def test_market_pair_without_data_404(client):
    r = client.get("/api/market/2204/MA")
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)


def test_market_unknown_taric_404(client):
    assert client.get("/api/market/9999/FR").status_code == 404


# ---------------------------------------------------------------- insights

def test_insights_route_removed(client):
    # La feature de análisis IA se eliminó (ADR-005): la ruta ya no existe.
    r = client.get("/api/insights/2204")
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)


def test_search_gender_and_plural_robust(client):
    # "porcino" debe encontrar "...especie porcina..." (prefijo de palabra con stem ligero)
    r = client.get("/api/search", params={"q": "porcino"})
    assert r.status_code == 200
    tarics = [x["taric"] for x in r.json()["results"]]
    assert "0203" in tarics


def test_search_multiword_all_tokens_required(client):
    # ambas palabras deben aparecer: "carne porcino" → 0203, no el vino
    r = client.get("/api/search", params={"q": "carne porcino"})
    tarics = [x["taric"] for x in r.json()["results"]]
    assert tarics and tarics[0] == "0203"
    assert "2204" not in tarics


def test_search_token_is_word_prefix_not_substring(client):
    # "vino" / "vinos" encuentran el 2204; un token interno de palabra no dispara falsos positivos
    for q in ("vino", "vinos"):
        r = client.get("/api/search", params={"q": q})
        assert "2204" in [x["taric"] for x in r.json()["results"]], q


def test_search_numeric_without_leading_zero(client):
    # Excel come el cero inicial: '203' debe encontrar 0203 igualmente
    r = client.get("/api/search", params={"q": "203"})
    assert "0203" in [x["taric"] for x in r.json()["results"]]


def test_search_data_before_chapters(client):
    # "carne" matchea el capítulo 02 (nivel 2, sin datos) y el producto 0203
    # (nivel 4, con datos) con la misma relevancia: el producto con datos debe
    # ir primero; el capítulo sin datos no debe encabezar (§5.3).
    r = client.get("/api/search", params={"q": "carne"})
    tarics = [x["taric"] for x in r.json()["results"]]
    assert "0203" in tarics and "02" in tarics
    assert tarics.index("0203") < tarics.index("02")
