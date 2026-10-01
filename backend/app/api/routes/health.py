from __future__ import annotations

from fastapi import APIRouter, Request

from app.database.session import ping

router = APIRouter(tags=["health"])


@router.get("/api/v1/health")
def health(request: Request):
    return {"status": "ok", "database": ping(), "active_gemini_sessions": len(request.app.state.session_store)}
