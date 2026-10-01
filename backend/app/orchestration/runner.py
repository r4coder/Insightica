from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.orchestration.deps import AgentDeps
from app.orchestration.graph import build_graph
from app.orchestration.state import AnalysisState

RECURSION_LIMIT = 60  # longest legal path incl. all retries is ~30 node visits


def run_analysis(deps: AgentDeps, question: str, context_turns: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    start = time.perf_counter()
    calls_before = getattr(deps.gemini, "call_count", 0)
    ds = deps.dataset
    inspect_event = {"agent": "inspector", "label": "Dataset inspection", "status": "completed", "elapsed_ms": 0.0,
                     "message": f"Inspected {ds.name}: {ds.profile.get('rows', 0):,} rows, {len(ds.columns)} columns"}
    deps.on_progress(inspect_event)
    initial: AnalysisState = {
        "question": question.strip(), "context_turns": (context_turns or [])[-deps.settings.context_turns:],
        "sql_results": [], "tool_records": [], "charts": [], "feedback": {}, "data_retries": 0, "report_retries": 0,
        "trace": [inspect_event], "warnings": [],
    }
    final = build_graph(deps).invoke(initial, config={"recursion_limit": RECURSION_LIMIT})
    result = final["result"]
    result["trace"] = final.get("trace", [])
    result["stats"] = {"gemini_calls": getattr(deps.gemini, "call_count", 0) - calls_before,
                       "elapsed_ms": round((time.perf_counter() - start) * 1000, 1)}
    return result
