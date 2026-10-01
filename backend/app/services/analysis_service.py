"""Analysis lifecycle: create record -> run the agent graph in the background -> persist progress and result."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import analysis_id_var, log_event
from app.database.session import new_session
from app.models.orm import AnalysisMessage, AnalysisResult, AnalysisSession, Dataset
from app.orchestration.deps import AgentDeps
from app.orchestration.runner import run_analysis
from app.services.dataset_service import DatasetService

logger = logging.getLogger("analysis")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def analysis_to_dict(a: AnalysisResult, dataset_name: Optional[str] = None, full: bool = True) -> Dict[str, Any]:
    out = {"id": a.id, "session_id": a.session_id, "dataset_id": a.dataset_id, "dataset_name": dataset_name, "question": a.question,
           "status": a.status, "summary": a.summary, "error": a.error, "trace": a.trace or [],
           "created_at": a.created_at.isoformat(), "completed_at": a.completed_at.isoformat() if a.completed_at else None}
    if full:
        out["result"] = a.result
    return out


class AnalysisService:
    def __init__(self, settings: Settings, engine: Any, datasets: DatasetService):
        self.settings, self.engine, self.datasets = settings, engine, datasets

    def create(self, db: Session, dataset_id: str, question: str, session_id: Optional[str]) -> AnalysisResult:
        dataset = self.datasets.get(db, dataset_id)
        if session_id:
            session = db.get(AnalysisSession, session_id)
            if session is None or session.dataset_id != dataset_id:
                raise AppError(404, "session_not_found", "Conversation not found for this dataset.")
        else:
            session = AnalysisSession(id=str(uuid.uuid4()), dataset_id=dataset.id, title=question[:80])
            db.add(session)
            db.flush()  # ensure the session row exists before rows that reference it are inserted
        analysis = AnalysisResult(id=str(uuid.uuid4()), session_id=session.id, dataset_id=dataset.id, question=question, status="running", trace=[])
        db.add(analysis)
        db.add(AnalysisMessage(session_id=session.id, analysis_id=analysis.id, role="user", content=question))
        db.commit()
        return analysis

    def history(self, db: Session, dataset_id: Optional[str] = None, session_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = select(AnalysisResult, Dataset.name).join(Dataset, Dataset.id == AnalysisResult.dataset_id)
        if dataset_id:
            q = q.where(AnalysisResult.dataset_id == dataset_id)
        if session_id:
            q = q.where(AnalysisResult.session_id == session_id)
        rows = db.execute(q.order_by(AnalysisResult.created_at.desc()).limit(limit)).all()
        return [analysis_to_dict(a, name, full=False) for a, name in rows]

    def get(self, db: Session, analysis_id: str) -> Dict[str, Any]:
        row = db.execute(select(AnalysisResult, Dataset.name).join(Dataset, Dataset.id == AnalysisResult.dataset_id)
                         .where(AnalysisResult.id == analysis_id)).first()
        if row is None:
            raise AppError(404, "analysis_not_found", "Analysis not found.")
        return analysis_to_dict(row[0], row[1])

    def execute(self, analysis_id: str, gemini: Any) -> None:
        """Runs in a background thread with its own DB session. Never raises."""
        token = analysis_id_var.set(analysis_id)
        db = new_session()
        try:
            analysis = db.get(AnalysisResult, analysis_id)
            turns = self._context_turns(db, analysis.session_id, analysis_id)

            def on_progress(event: Dict[str, Any]) -> None:
                analysis.trace = [*(analysis.trace or []), event]
                db.commit()

            deps = AgentDeps(gemini, self.engine, self.settings, self.datasets.context(db, analysis.dataset_id), on_progress)
            result = run_analysis(deps, analysis.question, turns)
            report = result.get("report") or {}
            analysis.status = result["status"]
            analysis.result = result
            analysis.trace = result.get("trace", analysis.trace)
            analysis.error = result.get("error")
            analysis.summary = (report.get("executive_summary") or result.get("error") or "")[:500]
            db.add(AnalysisMessage(session_id=analysis.session_id, analysis_id=analysis_id, role="assistant",
                                   content=analysis.summary, context=result.get("context_summary")))
            log_event(logger, "analysis_finished", status=result["status"], gemini_calls=result["stats"]["gemini_calls"],
                      elapsed_ms=result["stats"]["elapsed_ms"], retries=result["validation"]["retries"])
        except AppError as exc:
            self._fail(db, analysis_id, exc.message)
        except Exception:
            logger.exception("analysis_crashed")
            self._fail(db, analysis_id, "The analysis failed unexpectedly. Please try again.")
        finally:
            try:
                a = db.get(AnalysisResult, analysis_id)
                if a is not None and a.completed_at is None:
                    a.completed_at = _now()
                db.commit()
            finally:
                db.close()
                analysis_id_var.reset(token)

    def _fail(self, db: Session, analysis_id: str, message: str) -> None:
        db.rollback()
        a = db.get(AnalysisResult, analysis_id)
        if a is not None:
            a.status, a.error, a.summary = "failed", message, message

    def _context_turns(self, db: Session, session_id: str, current_analysis_id: str) -> List[Dict[str, Any]]:
        msgs = db.scalars(select(AnalysisMessage).where(AnalysisMessage.session_id == session_id, AnalysisMessage.role == "assistant",
                                                        AnalysisMessage.analysis_id != current_analysis_id).order_by(AnalysisMessage.id.desc())
                          .limit(self.settings.context_turns))
        return [m.context for m in reversed(list(msgs)) if m.context]
