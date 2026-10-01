"""BaseAgent: uniform tracing, timing, structured logging and failure handling for every graph node."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from app.core.logging import agent_var, log_event
from app.gemini.service import GeminiError
from app.orchestration.deps import AgentDeps
from app.orchestration.state import AnalysisState

logger = logging.getLogger("agents")


def set_feedback(state: AnalysisState, target: str, issues: list) -> Dict[str, list]:
    merged = dict(state.get("feedback") or {})
    merged[target] = issues
    return merged


class BaseAgent:
    name = "agent"
    label = "Agent"

    def __init__(self, deps: AgentDeps):
        self.deps = deps

    def execute(self, state: AnalysisState) -> Dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def __call__(self, state: AnalysisState) -> Dict[str, Any]:
        token = agent_var.set(self.name)
        start = time.perf_counter()
        status, message = "completed", ""
        try:
            update = dict(self.execute(state) or {})
            status = update.pop("_status", "completed")
            message = update.pop("_message", "")
        except GeminiError as exc:
            update, status, message = {"fatal_error": exc.user_message}, "failed", exc.user_message
            log_event(logger, "agent_failed", logging.ERROR, agent=self.name, code=exc.code)
        except Exception as exc:  # keep the graph alive; details go to logs, not to the user
            logger.exception("agent_crashed", extra={"fields": {"agent": self.name, "error_type": type(exc).__name__}})
            message = f"The {self.label} hit an unexpected error."
            update, status = {"fatal_error": message}, "failed"
        finally:
            agent_var.reset(token)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        event = {"agent": self.name, "label": self.label, "status": status, "message": message, "elapsed_ms": elapsed}
        log_event(logger, "agent_step", agent=self.name, status=status, elapsed_ms=elapsed)
        try:
            self.deps.on_progress(event)
        except Exception:  # progress reporting must never break an analysis
            logger.exception("progress_callback_failed")
        update["trace"] = [event]
        return update
