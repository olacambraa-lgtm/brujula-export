"""API FastAPI de Brújula Export: endpoints del contrato + frontend estático.

Configuración por variables de entorno:
- BRUJULA_DB: ruta del DuckDB (default: data/brujula.duckdb)
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.metrics import (Database, chapter_index, get_meta, market_detail,
                         score_product, search)

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BASE_DIR / "web"


def create_app():
    db_path = os.environ.get("BRUJULA_DB", str(BASE_DIR / "data" / "brujula.duckdb"))
    if not os.path.isfile(db_path):
        raise RuntimeError(
            f"No existe la base de datos {db_path}. "
            "Ejecuta ./run.sh (genera datos sintéticos de demo si faltan).")
    db = Database(db_path)
    app = FastAPI(title="Brújula Export", docs_url=None, redoc_url=None)

    # Sin caché: evita que el navegador sirva un app.js/styles.css/index.html
    # antiguos (cacheados) tras actualizar la app — el síntoma típico es "veo los
    # cambios de estilo pero la feature nueva no responde" (JS viejo). En localhost
    # la revalidación es instantánea.
    @app.middleware("http")
    async def _no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    # Los errores por defecto de Starlette llegan en inglés ('Not Found'):
    # el contrato exige mensajes en español también para rutas inexistentes.
    DEFAULT_DETAILS = {"Not Found": "Recurso no encontrado",
                       "Method Not Allowed": "Método no permitido"}

    @app.exception_handler(StarletteHTTPException)
    async def _detail_es(request, exc):
        detail = DEFAULT_DETAILS.get(exc.detail, exc.detail)
        return JSONResponse({"detail": detail}, status_code=exc.status_code)

    @app.get("/api/meta")
    def api_meta():
        return get_meta(db)

    @app.get("/api/search")
    def api_search(q: str = ""):
        return search(db, q)

    @app.get("/api/chapter/{code}")
    def api_chapter(code: str):
        result = chapter_index(db, code)
        if result is None:
            raise HTTPException(404, "Capítulo no encontrado en la nomenclatura.")
        return result

    @app.get("/api/score/{taric}")
    def api_score(taric: str):
        result = score_product(db, taric)
        if result is None:
            raise HTTPException(404, "Código TARIC no encontrado en la nomenclatura.")
        return result

    @app.get("/api/market/{taric}/{country_code}")
    def api_market(taric: str, country_code: str):
        result = market_detail(db, taric, country_code)
        if result is None:
            raise HTTPException(404, "Sin datos de exportación para ese producto y país.")
        return result

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    return app


app = create_app()
