"""Gemini API-key setup: /test-gemini validates a key without ever returning it; /session issues a
short-lived, server-side-only session; /logout clears it. See core/sessions.py for the storage model."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import SESSION_COOKIE, get_optional_gemini_session, get_session_store, get_settings_dep
from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import log_event
from app.core.ratelimit import RateLimiter
from app.core.sessions import GeminiSession, SessionStore
from app.gemini.service import check_api_key
from app.schemas.api import SessionRequest, TestGeminiRequest

router = APIRouter(prefix="/api/v1/config", tags=["config"])
logger = logging.getLogger("config")
_limiter = RateLimiter(max_calls=10, window_seconds=60.0)

_FAILURE_MESSAGES = {
    "invalid_key": "The API key was rejected by Gemini.", "model_not_found": "The configured Gemini model was not found.",
    "rate_limited": "Gemini rate limit reached while testing the key. Please retry shortly.",
    "unavailable": "Gemini is temporarily unavailable.", "network": "Could not reach Gemini. Check the network connection.",
    "bad_request": "Gemini rejected the request (invalid key format).",
}


@router.post("/test-gemini")
def test_gemini(payload: TestGeminiRequest, request: Request, settings: Settings = Depends(get_settings_dep),
                session: GeminiSession = Depends(get_optional_gemini_session)):
    if not _limiter.allow(request.client.host if request.client else "unknown"):
        raise AppError(429, "rate_limited", "Too many attempts. Please wait a minute and try again.")
    api_key = (payload.api_key or (session.api_key if session else "")).strip()
    if not api_key:
        return {"valid": False, "message": "No API key provided."}
    valid, code = check_api_key(api_key, settings.gemini_model)
    log_event(logger, "gemini_key_tested", valid=valid, code=code)  # api_key itself is never logged
    return {"valid": valid, "message": "Gemini connection successful" if valid else _FAILURE_MESSAGES.get(code, "Unable to connect to Gemini.")}


@router.post("/session")
def create_session(payload: SessionRequest, response: Response, settings: Settings = Depends(get_settings_dep),
                   store: SessionStore = Depends(get_session_store)):
    api_key = payload.api_key.strip()
    valid, code = check_api_key(api_key, settings.gemini_model)
    if not valid:
        raise AppError(401, code, _FAILURE_MESSAGES.get(code, "Unable to connect to Gemini."))
    session = store.create(api_key, settings.gemini_model)
    response.set_cookie(SESSION_COOKIE, session.token, max_age=settings.api_key_session_ttl_minutes * 60,
                        httponly=True, samesite=settings.cookie_samesite, secure=settings.cookie_secure, path="/")
    log_event(logger, "gemini_session_created", ttl_minutes=settings.api_key_session_ttl_minutes)
    return {"connected": True, "model": session.model, "expires_at": session.expires_at, "ttl_minutes": settings.api_key_session_ttl_minutes}


@router.get("/session")
def session_status(session: GeminiSession = Depends(get_optional_gemini_session)):
    if session is None:
        return {"connected": False}
    return {"connected": True, "model": session.model, "expires_at": session.expires_at}


@router.post("/logout")
def logout(response: Response, request: Request, settings: Settings = Depends(get_settings_dep),
          store: SessionStore = Depends(get_session_store)):
    store.delete(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/", samesite=settings.cookie_samesite, secure=settings.cookie_secure)
    return {"connected": False}
