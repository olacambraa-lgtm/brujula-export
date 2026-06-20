"""Actualización de datos en un solo comando: DataComex → data/brujula.duckdb.

Es la pieza que hace los datos DINÁMICOS: cuando DataComex publica un mes nuevo,
`etl.update` lo trae y reconstruye el DuckDB. Pensado para que cualquiera que
clone el repo lo ejecute sin fricción.

Uso:
    .venv/bin/python -m etl.update                  # hasta el último mes publicado
    .venv/bin/python -m etl.update --force          # reconstruye aunque esté al día
    .venv/bin/python -m etl.update --mode csv       # fuerza la vía pública (sin cuenta)
    .venv/bin/python -m etl.update --from 2022-01    # primer vistazo más rápido

Modo (auto por defecto):
- Vía pública CSV (sin credenciales): datos NACIONALES. Funciona para cualquiera.
- Vía API (DATACOMEX_EMAIL/PASSWORD o DATACOMEX_TOKEN): añade el desglose
  PROVINCIAL de Aragón (cuotas Aragón/Zaragoza, ficha provincial).

La app sigue siendo 100% offline en runtime: actualizar es una acción deliberada
que SÍ usa la red; servir los datos ya construidos, no. El swap de la base de
datos es atómico (no corrompe la BD vigente ante un fallo) pero NO refresca un
proceso ya arrancado: hay que reiniciar la app para servir los datos nuevos.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import duckdb

from . import datacomex_client as dcx
from . import download, load

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "brujula.duckdb"
RAW_DIR = ROOT / "data" / "raw"


def _ym(d):
    return f"{d.year:04d}-{d.month:02d}" if d else None


# --------------------------------------------------------------- estado actual

def coverage(db_path):
    """Estado de la BD vigente o None si no existe / no es legible.

    Devuelve {min, max, rows, extracted_at, is_synthetic}. `is_synthetic` se lee
    de meta_info de forma tolerante: tabla o columna ausente → False (nunca tratar
    una BD posiblemente real como demo)."""
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception:
        return None
    try:
        pmin, pmax = con.execute(
            "SELECT min(period), max(period) FROM trade WHERE flow='X'").fetchone()
        rows = con.execute("SELECT count(*) FROM trade WHERE flow='X'").fetchone()[0]
        extracted, is_syn = None, False
        try:
            row = con.execute(
                "SELECT extracted_at, is_synthetic FROM meta_info").fetchone()
            if row:
                extracted, is_syn = row[0], bool(row[1])
        except Exception:  # meta_info antigua (solo extracted_at) o ausente
            try:
                extracted = con.execute(
                    "SELECT extracted_at FROM meta_info").fetchone()[0]
            except Exception:
                extracted = None
        return {"min": pmin, "max": pmax, "rows": rows,
                "extracted_at": extracted, "is_synthetic": is_syn}
    finally:
        con.close()


# --------------------------------------------------------------- delta / lógica

def latest_available_period(periodos):
    """'YYYYMM' del último periodo MENSUAL disponible en DataComex.

    Filtra SIEMPRE Nivel == '2' (mensuales): los anuales son códigos de 4 dígitos
    ('2026') que por orden lexicográfico quedarían por debajo de '202601'; nunca
    fiarse del orden sin filtrar."""
    months = [p["CodPeriodo"] for p in periodos if p.get("Nivel") == "2"]
    return max(months) if months else None


def _months_between(a, b):
    """Lista 'YYYY-MM' de meses estrictamente posteriores a `a` y hasta `b` (dates)."""
    out = []
    if not a or not b:
        return out
    y, m = a.year, a.month
    while (y, m) < (b.year, b.month):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def needs_update(cov, latest_ym, force=False):
    """¿Hay que descargar? Una BD sintética o de origen desconocido NUNCA
    cortocircuita (evita dejar datos demo creídos reales)."""
    if force:
        return True
    if cov is None:
        return True
    if cov.get("is_synthetic"):
        return True
    if latest_ym is None:  # no se pudo consultar: por prudencia, actualizar
        return True
    db_max = cov.get("max")
    if db_max is None:
        return True
    return _ym(db_max) < f"{latest_ym[:4]}-{latest_ym[4:6]}"


# --------------------------------------------------------- descarga / reconstr.

def clean_year_csv(raw_dir, year):
    """Borra data/raw/trade_csv/<year> antes de re-descargar el año en curso.

    El raw CSV puede contener descargas previas con otro esquema de nombres (p.ej.
    'star_*.csv' sin manifiesto): mezclarlas con las nuevas haría que etl.load
    aborte por solape o sume celdas duplicadas. Los años anteriores (completos y
    definitivos) no se tocan."""
    d = Path(raw_dir) / "trade_csv" / str(year)
    if d.is_dir():
        shutil.rmtree(d)
        return True
    return False


def _cleanup_tmp(tmp):
    for p in (Path(tmp), Path(str(tmp) + ".wal")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def rebuild(db_path, raw_dir=None):
    """Reconstruye con swap atómico: build a PATH.tmp y, solo si la carga y sus
    validaciones pasan, os.replace(PATH.tmp, PATH). Un fallo de red o validación
    deja INTACTA y servible la BD vigente (no más unlink de la BD viva)."""
    db_path = Path(db_path)
    tmp = str(db_path) + ".tmp"
    _cleanup_tmp(tmp)
    try:
        if raw_dir is None:
            load.build_db(tmp)
        else:
            load.build_db(tmp, raw_dir=raw_dir)
    except BaseException:
        _cleanup_tmp(tmp)
        raise
    os.replace(tmp, str(db_path))
    # build_db cierra limpiamente (sin .wal). Si quedara uno, va con su BD; si no,
    # se purga un .wal huérfano de la BD anterior (emparejado mal al inode nuevo).
    tmp_wal, db_wal = Path(str(tmp) + ".wal"), Path(str(db_path) + ".wal")
    if tmp_wal.exists():
        os.replace(str(tmp_wal), str(db_wal))
    elif db_wal.exists():
        db_wal.unlink()
    return db_path


# ------------------------------------------------------------------- runner

def main(argv=None):
    ap = argparse.ArgumentParser(description="Actualiza los datos de DataComex")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--from", dest="from_", default="2015-01", metavar="YYYY-MM")
    ap.add_argument("--to", default="auto", metavar="YYYY-MM|auto")
    ap.add_argument("--mode", choices=("auto", "api", "csv"), default="auto")
    ap.add_argument("--force", action="store_true",
                    help="reconstruye aunque la BD ya esté al día")
    args = ap.parse_args(argv)

    before = coverage(args.db)
    if before:
        tag = "  ·  SINTÉTICOS (demo)" if before.get("is_synthetic") else ""
        print(f"[update] datos actuales: {_ym(before['min'])} → {_ym(before['max'])} "
              f"· {before['rows']:,} filas X{tag}")
    else:
        print("[update] sin datos previos: primera construcción completa "
              "(la primera vez por la vía pública puede tardar; ver runbook).")

    latest_ym = None
    try:
        latest_ym = latest_available_period(dcx.get_periodos())
        if latest_ym:
            print(f"[update] último periodo publicado en DataComex: "
                  f"{latest_ym[:4]}-{latest_ym[4:6]}")
    except Exception as e:  # noqa: BLE001
        print(f"[update] aviso: no se pudo consultar el último periodo ({e!r}); "
              "se intentará actualizar igualmente.", file=sys.stderr)

    if not needs_update(before, latest_ym, args.force):
        print(f"[update] ✓ Ya al día (último periodo {latest_ym[:4]}-{latest_ym[4:6]}). "
              "Nada que descargar.")
        return before

    # Modo efectivo (replica la auto-detección de download) para decidir si hay
    # que limpiar el año en curso por la vía CSV.
    mode = args.mode
    if mode == "auto":
        has_creds = bool((os.environ.get("DATACOMEX_EMAIL") and
                          os.environ.get("DATACOMEX_PASSWORD"))
                         or os.environ.get("DATACOMEX_TOKEN"))
        mode = "api" if has_creds else "csv"
    if mode == "csv" and latest_ym and clean_year_csv(RAW_DIR, latest_ym[:4]):
        print(f"[update] año {latest_ym[:4]}: CSV re-descargado limpio "
              "(evita solapes con descargas previas).")

    print("\n[update] 1/2 descargando de DataComex (usa la red)…")
    try:
        download.main(["--from", args.from_, "--to", args.to, "--mode", args.mode])
    except SystemExit as e:
        if e.code:  # descarga con fallos: no reconstruir sobre datos parciales
            print(f"\n[update] descarga incompleta (código {e.code}); no se "
                  "reconstruye la BD. Revisa data/raw/failed.log y reintenta.",
                  file=sys.stderr)
            raise

    print("\n[update] 2/2 reconstruyendo la base de datos (swap atómico)…")
    rebuild(args.db)

    after = coverage(args.db)
    print()
    if not after:
        sys.exit("[update] la reconstrucción no produjo una BD válida.")
    if before and not before.get("is_synthetic") and after["max"] > before["max"]:
        nuevos = _months_between(before["max"], after["max"])
        print(f"[update] ✓ ACTUALIZADO: {_ym(before['max'])} → {_ym(after['max'])} "
              f"(+{len(nuevos)} mes(es): {', '.join(nuevos)}).")
    elif before and not before.get("is_synthetic"):
        print(f"[update] ✓ Reconstruido; último mes: {_ym(after['max'])} "
              "(sin meses nuevos en DataComex).")
    else:
        print(f"[update] ✓ Datos REALES de DataComex: {_ym(after['min'])} → "
              f"{_ym(after['max'])} · {after['rows']:,} filas X.")
    print(f"[update] extracción: {after['extracted_at']}.")
    print("[update] ⚠ Reinicia la app (./run.sh) para servir los datos nuevos: "
          "un proceso ya arrancado sigue sirviendo los datos anteriores.")
    return after


if __name__ == "__main__":
    main()
