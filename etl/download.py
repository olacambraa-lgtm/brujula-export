"""Descarga de datos DataComex a data/raw/.

Uso:
    .venv/bin/python -m etl.download [--from 2015-01] [--to auto] [--mode auto|api|csv]

- Siempre descarga las 5 maestras a data/raw/masters/*.json.
- mode=api (requiere DATACOMEX_EMAIL y DATACOMEX_PASSWORD en el entorno):
  nacional por mes (pe=YYYYMM, f=I/E, pa=ALL, ta=AT4) y provincial Aragón por
  mes × provincia (pr=50|22|44). Un fichero JSON por mes; idempotente.
- mode=csv (sin cuenta): solo nacional, por lotes año × capítulo TARIC-2 en
  trozos de códigos 4d que respetan el límite de ~30.000 combinaciones del
  formulario público (hallazgo empírico, ver docs/etl-runbook.md).
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import datacomex_client as dcx

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
PROVINCES = ("50", "22", "44")  # Zaragoza, Huesca, Teruel
SAFE_COMBOS = 28000  # margen bajo el límite empírico de 30.000

MASTERS = {
    "paises.json": dcx.get_paises,
    "provincias.json": dcx.get_provincias,
    "periodos.json": dcx.get_periodos,
    "tarics.json": dcx.get_tarics,
    "flujos.json": dcx.get_flujos,
}


def download_masters(raw_dir):
    masters_dir = raw_dir / "masters"
    masters_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, fetch in MASTERS.items():
        data = fetch()
        path = masters_dir / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        out[name] = data
        print(f"[maestras] {name}: {len(data)} filas")
    return out


def month_range(start, end):
    """'2015-01', '2026-03' → ['201501', ..., '202603']"""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    months = []
    while (y, m) <= (ey, em):
        months.append(f"{y}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months


def resolve_to(to_arg, periodos):
    if to_arg != "auto":
        return to_arg
    last = max(p["CodPeriodo"] for p in periodos if p["Nivel"] == "2")
    return f"{last[:4]}-{last[4:]}"


def _valid_json(path):
    """True si el fichero existe y contiene una lista JSON (no null)."""
    if not path.exists():
        return False
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), list)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False


def _log_failure(raw_dir, line):
    with open(raw_dir / "failed.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"  FALLO: {line}", file=sys.stderr)


def download_api(raw_dir, months, email, password):
    """Vía API: nacional + provincial Aragón, un JSON por mes y objetivo."""
    token = dcx.login(email, password)
    print(f"[api] sesión iniciada ({email})")
    calls = rows = skipped = failed = 0

    targets = [("nacional", None)] + [(f"prov{p}", p) for p in PROVINCES]
    for target, pr in targets:
        out_dir = raw_dir / "trade" / target
        out_dir.mkdir(parents=True, exist_ok=True)
        for pe in months:
            path = out_dir / f"{pe}.json"
            if _valid_json(path):
                skipped += 1
                continue
            data = dcx.obtener_datos("I/E", pe, "ALL", "AT4", token, pr=pr)
            calls += 1
            if data is None:
                # Límite de filas excedido → cortar el mes en dos llamadas.
                parts = []
                ok = True
                for f in ("E", "I"):
                    part = dcx.obtener_datos(f, pe, "ALL", "AT4", token, pr=pr)
                    calls += 1
                    if part is None:
                        ok = False
                        break
                    parts.extend(part)
                if not ok:
                    failed += 1
                    _log_failure(raw_dir, f"api {target} {pe} respuesta null "
                                          f"incluso con f=E/f=I por separado")
                    continue
                data = parts
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            rows += len(data)
            print(f"[api] {target} {pe}: {len(data)} filas")
    return calls, rows, skipped, failed


def _chapter_chunks(tarics, months_per_call, n_countries):
    """Lotes (capítulo, [códigos 4d]) que respetan el límite de combinaciones."""
    per_call = max(1, SAFE_COMBOS // (2 * months_per_call * n_countries))
    chapters = sorted(t["Taric"] for t in tarics if t["Nivel"] == "1")
    chunks = []
    for ch in chapters:
        codes = sorted(t["Taric"] for t in tarics
                       if t["Nivel"] == "2" and t["Taric"].startswith(ch))
        for i in range(0, len(codes), per_call):
            chunks.append((ch, i // per_call, codes[i:i + per_call]))
    return chunks


def download_csv(raw_dir, months, tarics):
    """Vía CSV pública: solo nacional, lotes año × capítulo × trozo de códigos."""
    session = dcx.CsvSession()
    n_countries = len(session.country_fields)
    print(f"[csv] sesión abierta; {n_countries} países en el formulario")
    calls = rows = skipped = failed = 0

    by_year = {}
    for pe in months:
        by_year.setdefault(pe[:4], []).append(pe)

    for year, year_months in sorted(by_year.items()):
        out_dir = raw_dir / "trade_csv" / year
        out_dir.mkdir(parents=True, exist_ok=True)
        chunks = _chapter_chunks(tarics, len(year_months), n_countries)
        for chapter, idx, codes in chunks:
            path = out_dir / f"{chapter}_{idx:02d}.csv"
            if path.exists():
                skipped += 1
                continue
            try:
                text = session.query(year_months, taric_codes=codes)
            except dcx.CsvLimitError as exc:
                failed += 1
                _log_failure(raw_dir, f"csv {year} {chapter}_{idx:02d}: {exc}")
                continue
            except dcx.CsvChainError as exc:
                # Reintento único con sesión nueva (cookie/caché corrupta).
                print(f"[csv] reintento con sesión nueva: {exc}")
                session = dcx.CsvSession()
                try:
                    text = session.query(year_months, taric_codes=codes)
                except (dcx.CsvLimitError, dcx.CsvChainError) as exc2:
                    failed += 1
                    _log_failure(raw_dir, f"csv {year} {chapter}_{idx:02d}: {exc2}")
                    continue
            calls += 1
            n = len(dcx.parse_csv(text))
            path.write_text(text, encoding="latin-1")
            rows += n
            print(f"[csv] {year} cap.{chapter} trozo {idx} "
                  f"({len(codes)} códigos): {n} filas")
    return calls, rows, skipped, failed


def main(argv=None):
    parser = argparse.ArgumentParser(description="Descarga DataComex → data/raw/")
    parser.add_argument("--from", dest="from_", default="2015-01",
                        metavar="YYYY-MM")
    parser.add_argument("--to", default="auto", metavar="YYYY-MM|auto")
    parser.add_argument("--mode", choices=("auto", "api", "csv"), default="auto")
    args = parser.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    masters = download_masters(RAW_DIR)

    to = resolve_to(args.to, masters["periodos.json"])
    months = month_range(args.from_, to)
    print(f"[plan] rango {args.from_} → {to} ({len(months)} meses)")

    email = os.environ.get("DATACOMEX_EMAIL")
    password = os.environ.get("DATACOMEX_PASSWORD")
    mode = args.mode
    if mode == "auto":
        mode = "api" if (email and password) else "csv"
        print(f"[plan] modo auto → {mode}")
    if mode == "api" and not (email and password):
        sys.exit("mode=api requiere DATACOMEX_EMAIL y DATACOMEX_PASSWORD en el entorno")

    if mode == "api":
        calls, rows, skipped, failed = download_api(RAW_DIR, months, email, password)
    else:
        calls, rows, skipped, failed = download_csv(RAW_DIR, months,
                                                    masters["tarics.json"])

    print(f"\n[resumen] llamadas: {calls} · filas: {rows} · "
          f"saltados (ya descargados): {skipped} · fallos: {failed}")
    if failed:
        print(f"[resumen] revisa {RAW_DIR / 'failed.log'}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
