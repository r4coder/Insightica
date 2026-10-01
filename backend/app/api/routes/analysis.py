from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_analysis_service, get_db, get_gemini_service
from app.gemini.service import GeminiService
from app.schemas.api import AnalysisRequest
from app.services.analysis_service import AnalysisService, analysis_to_dict

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


@router.post("", status_code=202)
def start_analysis(payload: AnalysisRequest, background: BackgroundTasks, db: Session = Depends(get_db),
                   service: AnalysisService = Depends(get_analysis_service), gemini: GeminiService = Depends(get_gemini_service)):
    analysis = service.create(db, payload.dataset_id, payload.question, payload.session_id)
    background.add_task(service.execute, analysis.id, gemini)
    return analysis_to_dict(analysis, full=False)


@router.get("")
def list_analyses(dataset_id: Optional[str] = Query(default=None), session_id: Optional[str] = Query(default=None),
                  db: Session = Depends(get_db), service: AnalysisService = Depends(get_analysis_service)):
    return service.history(db, dataset_id, session_id)


@router.get("/{analysis_id}")
def get_analysis(analysis_id: str, db: Session = Depends(get_db), service: AnalysisService = Depends(get_analysis_service)):
    return service.get(db, analysis_id)
