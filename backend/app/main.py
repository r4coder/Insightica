"""FastAPI application factory and lifespan (DuckDB engine, DB init, session-store cleanup thread)."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import analysis, config, datasets, health
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_var
from app.core.sessions import SessionStore
from app.database import session as db_session
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService

logger = logging.getLogger("app")


def _cleanup_loop(store: SessionStore, stop: threading.Event) -> None:
    while not stop.wait(60):
        n = store.purge_expired()
        if n:
            logger.info("expired_sessions_purged", extra={"fields": {"count": n}})


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    from app.tools.duckdb_tools import DuckDBEngine

    engine = DuckDBEngine(settings.duckdb_path)
    db_session.configure(settings.database_url)
    db_session.init_db()

    store = SessionStore(ttl_seconds=settings.api_key_session_ttl_minutes * 60)
    dataset_service = DatasetService(settings, engine)
    app.state.engine, app.state.session_store = engine, store
    app.state.dataset_service = dataset_service
    app.state.analysis_service = AnalysisService(settings, engine, dataset_service)

    stop = threading.Event()
    cleanup = threading.Thread(target=_cleanup_loop, args=(store, stop), daemon=True)
    cleanup.start()
    logger.info("app_started", extra={"fields": {"model": settings.gemini_model}})
    try:
        yield
    finally:
        stop.set()
        engine.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Multi-Agent Data Analyst", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        import uuid

        request_id = uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        logger.info("request", extra={"fields": {"method": request.method, "path": request.url.path,
                    "status": response.status_code, "ms": round((time.perf_counter() - start) * 1000, 1)}})
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        logger.exception("unhandled_exception")
        return JSONResponse(status_code=500, content={"code": "internal_error", "message": "An unexpected error occurred."})

    for router in (config.router, datasets.router, analysis.router, health.router):
        app.include_router(router)
    return app


app = create_app()
