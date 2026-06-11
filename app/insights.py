"""Carga de análisis ejecutivos pregenerados con IA (insights/<taric>.md)."""

from datetime import date
from pathlib import Path


def load_insight(base_dir, taric):
    """Devuelve el insight pregenerado o None si no existe.

    Solo acepta TARIC numérico (evita rutas arbitrarias).
    """
    if not taric.isdigit():
        return None
    path = Path(base_dir) / f"{taric}.md"
    if not path.is_file():
        return None
    return {
        "taric": taric,
        "markdown": path.read_text(encoding="utf-8"),
        "generated_at": date.fromtimestamp(path.stat().st_mtime).isoformat(),
    }
