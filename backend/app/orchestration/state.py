from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, TypedDict


class AnalysisState(TypedDict, total=False):
    """Shared LangGraph state. Plain JSON-safe dicts/lists so it can be persisted and traced."""

    question: str
    resolved_question: str
    context_turns: List[Dict[str, Any]]
    plan: Dict[str, Any]
    sql_results: List[Dict[str, Any]]
    sql_generation: int
    tool_records: List[Dict[str, Any]]
    analyst_done: bool
    charts: List[Dict[str, Any]]
    charts_generation: int
    feedback: Dict[str, List[Dict[str, Any]]]
    data_retries: int
    report: Dict[str, Any]
    report_retries: int
    review_done: bool
    validation: Dict[str, Any]
    report_valid: bool
    route: str
    fatal_error: str
    result: Dict[str, Any]
    trace: Annotated[List[Dict[str, Any]], operator.add]
    warnings: Annotated[List[str], operator.add]
