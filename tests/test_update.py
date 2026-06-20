"""Tests de la actualización incremental de datos (etl/update.py) y de la marca
de origen is_synthetic (etl/load.py + app/metrics.get_meta).

OFFLINE: la red (ObtenerPeriodos, descarga) y la reconstrucción se mockean. Los
criterios de éxito de la spec 2026-06-20-datos-dinamicos.md §5 se codifican aquí.
"""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from etl import update
from app.metrics import Database, get_meta


# --------------------------------------------------------------- helpers

def _make_db(path, *, pmax="2026-03", is_synthetic=None, with_meta=True):
    """DuckDB mínima con tabla trade (suficiente para coverage() y get_meta) y,
    opcionalmente, meta_info."""
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE trade (period DATE, flow CHAR(1), "
                "country_code VARCHAR, taric VARCHAR, euros DOUBLE, "
                "is_provisional BOOLEAN)")
    con.execute("INSERT INTO trade VALUES "
                "(DATE '2015-01-01','X','FR','2204',1.0,FALSE), "
                f"(DATE '{pmax}-01','X','DE','2204',2.0,TRUE)")
    if with_meta:
        if is_synthetic is None:
            con.execute("CREATE TABLE meta_info (extracted_at DATE)")
            con.execute("INSERT INTO meta_info VALUES (current_date)")
        else:
            con.execute("CREATE TABLE meta_info "
                        "(extracted_at DATE, is_synthetic BOOLEAN)")
            con.execute("INSERT INTO meta_info VALUES (current_date, ?)",
                        [is_synthetic])
    con.close()
    return str(path)


PERIODOS_202603 = (
    [{"CodPeriodo": "2025", "Nivel": "1", "DatosDefinitivos": True},
     {"CodPeriodo": "2026", "Nivel": "1", "DatosDefinitivos": False}]
    + [{"CodPeriodo": f"2026{m:02d}", "Nivel": "2", "DatosDefinitivos": False}
       for m in range(1, 4)]
    + [{"CodPeriodo": "202512", "Nivel": "2", "DatosDefinitivos": True}]
)


# --------------------------------------------------- funciones puras

def test_latest_available_filtra_nivel_2():
    # Los anuales ('2026', Nivel 1) NO deben ganar al mensual por orden lexicográfico.
    assert update.latest_available_period(PERIODOS_202603) == "202603"


def test_latest_available_sin_mensuales():
    assert update.latest_available_period(
        [{"CodPeriodo": "2026", "Nivel": "1"}]) is None


def test_months_between():
    assert update._months_between(date(2026, 3, 1), date(2026, 5, 1)) == \
        ["2026-04", "2026-05"]
    assert update._months_between(date(2026, 3, 1), date(2026, 3, 1)) == []


def test_needs_update_real_al_dia_no_actualiza():
    cov = {"max": date(2026, 3, 1), "is_synthetic": False}
    assert update.needs_update(cov, "202603", force=False) is False


def test_needs_update_real_atrasada_actualiza():
    cov = {"max": date(2026, 2, 1), "is_synthetic": False}
    assert update.needs_update(cov, "202603", force=False) is True


def test_needs_update_sintetica_siempre_actualiza():
    # Falso positivo peligroso: BD sintética con el mismo max NO debe cortocircuitar.
    cov = {"max": date(2026, 3, 1), "is_synthetic": True}
    assert update.needs_update(cov, "202603", force=False) is True


def test_needs_update_sin_db_actualiza():
    assert update.needs_update(None, "202603", force=False) is True


def test_needs_update_force():
    cov = {"max": date(2026, 3, 1), "is_synthetic": False}
    assert update.needs_update(cov, "202603", force=True) is True


# --------------------------------------------------- coverage()

def test_coverage_lee_is_synthetic(tmp_path):
    real = _make_db(tmp_path / "real.duckdb", is_synthetic=False)
    syn = _make_db(tmp_path / "syn.duckdb", is_synthetic=True)
    legacy = _make_db(tmp_path / "legacy.duckdb", is_synthetic=None)  # meta sin columna
    assert update.coverage(real)["is_synthetic"] is False
    assert update.coverage(real)["max"] == date(2026, 3, 1)
    assert update.coverage(syn)["is_synthetic"] is True
    # meta_info antigua sin columna → False (no marcar datos reales como demo)
    assert update.coverage(legacy)["is_synthetic"] is False


def test_coverage_db_inexistente(tmp_path):
    assert update.coverage(tmp_path / "no.duckdb") is None


# --------------------------------------------------- limpieza año CSV

def test_clean_year_csv_borra_legacy(tmp_path):
    year_dir = tmp_path / "trade_csv" / "2026"
    year_dir.mkdir(parents=True)
    (year_dir / "star_00.csv").write_text("x", encoding="latin-1")
    assert update.clean_year_csv(tmp_path, "2026") is True
    assert not year_dir.exists()
    # idempotente: si no existe, no falla
    assert update.clean_year_csv(tmp_path, "2026") is False


# --------------------------------------------------- swap atómico

def test_rebuild_swap_atomico_falla_conserva_db(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "brujula.duckdb", is_synthetic=False)
    original = Path(db).read_bytes()

    def boom(path, **kw):
        # simula que build_db crea el .tmp y luego la validación aborta
        Path(path).write_bytes(b"parcial")
        raise SystemExit("VALIDACIÓN FALLIDA")

    monkeypatch.setattr(update.load, "build_db", boom)
    with pytest.raises(SystemExit):
        update.rebuild(db)
    # la BD original sigue intacta y servible; sin .tmp huérfano
    assert Path(db).read_bytes() == original
    assert update.coverage(db)["max"] == date(2026, 3, 1)
    assert not Path(str(db) + ".tmp").exists()


def test_rebuild_swap_atomico_exito_reemplaza(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "brujula.duckdb", pmax="2026-03", is_synthetic=False)

    def fake_build(path, **kw):
        _make_db(path, pmax="2026-04", is_synthetic=False)

    monkeypatch.setattr(update.load, "build_db", fake_build)
    update.rebuild(db)
    assert update.coverage(db)["max"] == date(2026, 4, 1)
    assert not Path(str(db) + ".tmp").exists()


# --------------------------------------------------- main() (orquestación)

def _patch_main(monkeypatch, periodos):
    calls = {"download": 0, "rebuild": 0, "clean": 0}
    monkeypatch.setattr(update.dcx, "get_periodos", lambda: periodos)
    monkeypatch.setattr(update.download, "main",
                        lambda argv=None: calls.__setitem__("download", calls["download"] + 1))
    monkeypatch.setattr(update, "rebuild",
                        lambda db_path, **kw: calls.__setitem__("rebuild", calls["rebuild"] + 1))
    monkeypatch.setattr(update, "clean_year_csv",
                        lambda raw, year: calls.__setitem__("clean", calls["clean"] + 1) or False)
    return calls


def test_main_al_dia_no_descarga(tmp_path, monkeypatch, capsys):
    db = _make_db(tmp_path / "brujula.duckdb", pmax="2026-03", is_synthetic=False)
    calls = _patch_main(monkeypatch, PERIODOS_202603)
    update.main(["--db", db])
    assert calls["download"] == 0 and calls["rebuild"] == 0
    assert "al día" in capsys.readouterr().out.lower()


def test_main_sintetica_si_descarga(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "brujula.duckdb", pmax="2026-03", is_synthetic=True)
    calls = _patch_main(monkeypatch, PERIODOS_202603)
    update.main(["--db", db, "--mode", "csv"])
    assert calls["download"] == 1 and calls["rebuild"] == 1


def test_main_force_descarga_aunque_al_dia(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "brujula.duckdb", pmax="2026-03", is_synthetic=False)
    calls = _patch_main(monkeypatch, PERIODOS_202603)
    update.main(["--db", db, "--mode", "csv", "--force"])
    assert calls["download"] == 1 and calls["rebuild"] == 1


# --------------------------------------------------- is_synthetic en get_meta

def _meta_db(path, **kw):
    """DB completa mínima para get_meta (trade con flow X + meta_info opcional)."""
    _make_db(path, **kw)
    return Database(str(path))


def test_get_meta_is_synthetic_real(tmp_path):
    m = get_meta(_meta_db(tmp_path / "r.duckdb", is_synthetic=False))
    assert m["is_synthetic"] is False


def test_get_meta_is_synthetic_demo(tmp_path):
    m = get_meta(_meta_db(tmp_path / "s.duckdb", is_synthetic=True))
    assert m["is_synthetic"] is True


def test_get_meta_sin_meta_info_default_false(tmp_path):
    # Sin tabla meta_info → False (no marcar como demo datos posiblemente reales).
    m = get_meta(_meta_db(tmp_path / "n.duckdb", with_meta=False))
    assert m["is_synthetic"] is False
