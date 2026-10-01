"""FastAPI dependency wiring: settings, engine, DB session, and the current Gemini session."""
from __future__ import annotations

from typing import Iterator, Optional

from fastapi import Cookie, Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.sessions import GeminiSession, SessionStore
from app.gemini.service import GeminiService
from app.services.analysis_service import AnalysisService
from app.services.dataset_service import DatasetService

SESSION_COOKIE = "gemini_session"


def get_engine(request: Request):
    return request.app.state.engine


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def get_dataset_service(request: Request) -> DatasetService:
    return request.app.state.dataset_service


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


def get_db() -> Iterator:
    from app.database.session import get_db as _get_db

    yield from _get_db()


def get_optional_gemini_session(
    token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    store: SessionStore = Depends(get_session_store),
) -> Optional[GeminiSession]:
    return store.get(token)


def require_gemini_session(
    session: Optional[GeminiSession] = Depends(get_optional_gemini_session),
) -> GeminiSession:
    if session is None:
        raise AppError(401, "session_expired", "Your Gemini session has expired. Please configure your API key again.")
    return session


def get_gemini_service(session: GeminiSession = Depends(require_gemini_session)) -> GeminiService:
    return GeminiService(session.api_key, session.model)


def get_settings_dep() -> Settings:
    return get_settings()
