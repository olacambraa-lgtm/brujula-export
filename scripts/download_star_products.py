"""Descarga real acotada: productos estrella de Aragón vía CSV pública.

Subconjunto demo de docs/research/productos-estrella-aragon.md (sin cuenta API,
solo nacional). Escribe en data/raw/trade_csv/{año}/star_{i}.csv, el mismo
layout que lee etl.load. Si más adelante se hace la descarga completa por API,
load.py deduplica API > CSV por mes; ante una descarga completa por CSV,
eliminar antes los star_*.csv (ver docs/etl-runbook.md).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import datacomex_client as dcx
from etl.download import SAFE_COMBOS

STAR_CODES = [
    "8703", "8708", "0203", "0206", "0103", "8413", "8482", "8536", "8544",
    "3402", "3920", "3923", "8450", "8516", "8422", "4804", "4805", "4810",
    "4819", "2204", "1214", "0809", "6109", "6110", "6203", "6204",
]
YEARS = [str(y) for y in range(2015, 2027)]
MONTHS = {y: [f"{y}{m:02d}" for m in range(1, 13)] for y in YEARS}
MONTHS["2026"] = [f"2026{m:02d}" for m in range(1, 4)]  # hasta 2026-03

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def main():
    session = dcx.CsvSession()
    n_countries = len(session.country_fields)
    per_call = max(1, SAFE_COMBOS // (2 * 12 * n_countries))
    chunks = [STAR_CODES[i:i + per_call]
              for i in range(0, len(STAR_CODES), per_call)]
    print(f"[star] {len(STAR_CODES)} códigos, {n_countries} países, "
          f"{per_call} códigos/lote → {len(chunks) * len(YEARS)} consultas")

    calls = rows = skipped = 0
    for year in YEARS:
        out_dir = RAW / "trade_csv" / year
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, codes in enumerate(chunks):
            path = out_dir / f"star_{i:02d}.csv"
            if path.exists():
                skipped += 1
                continue
            try:
                text = session.query(MONTHS[year], taric_codes=codes)
            except dcx.CsvChainError as exc:
                print(f"[star] reintento con sesión nueva: {exc}")
                session = dcx.CsvSession()
                text = session.query(MONTHS[year], taric_codes=codes)
            n = len(dcx.parse_csv(text))
            path.write_text(text, encoding="latin-1")
            calls += 1
            rows += n
            print(f"[star] {year} lote {i} ({len(codes)} códigos): {n} filas")

    print(f"[star] hecho: {calls} consultas, {rows} filas, {skipped} saltadas")


if __name__ == "__main__":
    main()
