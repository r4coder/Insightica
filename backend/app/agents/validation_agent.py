"""Validation Agent: deterministic gatekeeper (data checks, chart fidelity, numeric claim verification)
plus an advisory Gemini review for over-claiming. Deterministic checks are authoritative."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.agents.base import BaseAgent, set_feedback
from app.agents.prompts import REVIEW_SYSTEM
from app.gemini.service import GeminiError
from app.schemas.llm import ReviewResult
from app.tools.visualization_tools import build_chart_sources, verify_chart
from app.validation.claims import validate_report
from app.validation.evidence import build_evidence_store, render_for_prompt

logger = logging.getLogger("agents.validation")
NODE_FOR_TARGET = {"sql": "sql_agent", "analyst": "analyst_agent", "viz": "visualization_agent"}


class ValidationAgent(BaseAgent):
    name, label = "validation", "Validation Agent"

    def __init__(self, deps, phase: str):
        super().__init__(deps)
        assert phase in ("data", "report")
        self.phase = phase

    def execute(self, state) -> Dict[str, Any]:
        return self._validate_data(state) if self.phase == "data" else self._validate_report(state)

    # -- phase 1: did the tools actually produce usable, faithful data? ------------------------
    def _validate_data(self, state) -> Dict[str, Any]:
        plan, max_retries = state["plan"], self.deps.settings.max_agent_retries
        retries = state.get("data_retries", 0)
        sql_results, tool_records, charts = state.get("sql_results", []), state.get("tool_records", []), state.get("charts", [])
        issues: Dict[str, List[Dict[str, Any]]] = {"sql": [], "analyst": [], "viz": []}
        notes: List[str] = []

        if plan.get("needs_sql") and not sql_results:
            issues["sql"].append({"index": None, "message": "No SQL queries were produced."})
        for i, r in enumerate(sql_results):
            if r.get("error"):
                issues["sql"].append({"index": i, "message": r["error"]})
            elif r.get("row_count", 0) == 0:
                issues["sql"].append({"index": i, "message": "The query returned 0 rows; check filters and period labels."})

        good_tools = [r for r in tool_records if not r.get("error")]
        if plan.get("needs_statistics"):
            if not good_tools:
                errs = "; ".join(r["error"] for r in tool_records if r.get("error")) or "no tool calls were made"
                issues["analyst"].append({"index": None, "message": f"No analysis tool succeeded: {errs}"})
            else:
                notes += [f"Tool {r['tool']} failed: {r['error']}" for r in tool_records if r.get("error")]

        sources = build_chart_sources(sql_results, tool_records)
        valid_charts = 0
        for c in charts:
            problems = [c["error"]] if c.get("error") else verify_chart(c, sources.get(c["source"], []))
            if problems:
                c["error"] = c.get("error") or "; ".join(problems)
                notes.append(f"Chart '{c.get('title', c['id'])}' dropped: {c['error']}")
            else:
                valid_charts += 1
        if plan.get("needs_visualization") and sources and valid_charts == 0:
            issues["viz"].append({"index": None, "message": "; ".join(c["error"] for c in charts if c.get("error")) or "No chart was produced."})

        blocking = {k: v for k, v in issues.items() if v}
        validation = {"phase": "data", "valid": not blocking, "issues": [{"scope": k, **i} for k, v in blocking.items() for i in v]}
        if not blocking:
            return {"route": "report_agent", "validation": validation, "warnings": notes,
                    "_message": f"Data checks passed: {len(sql_results)} queries, {len(good_tools)} tool results, {valid_charts} chart(s) verified"}
        if retries < max_retries:
            target = next(k for k in ("sql", "analyst", "viz") if k in blocking)
            return {"route": NODE_FOR_TARGET[target], "data_retries": retries + 1, "validation": validation,
                    "feedback": set_feedback(state, target, blocking[target]),
                    "_status": "retry", "_message": f"Issue in {target} stage; retry {retries + 1}/{max_retries}: {blocking[target][0]['message'][:160]}"}
        usable = any(not r.get("error") and r.get("row_count", 0) > 0 for r in sql_results) or bool(good_tools)
        detail = "; ".join(f"{k}: {v[0]['message']}" for k, v in blocking.items())
        if usable:
            return {"route": "report_agent", "validation": validation, "warnings": notes + [f"Proceeding with partial results after {max_retries} retries ({detail})"],
                    "_status": "partial", "_message": "Retry limit reached; continuing with the usable results"}
        return {"route": "finalize", "validation": validation, "fatal_error": "The analysis could not produce usable results after several attempts. Try rephrasing the question.",
                "_status": "failed", "_message": f"Retry limit reached without usable data ({detail[:200]})"}

    # -- phase 2: is every claim in the report supported by computed data? ---------------------
    def _validate_report(self, state) -> Dict[str, Any]:
        d = self.deps
        report = state["report"]
        store = build_evidence_store(state.get("sql_results", []), state.get("tool_records", []))
        outcome = validate_report(report, store)
        validation = {"phase": "report", **outcome}
        n = len(report.get("key_findings", []))
        if outcome["valid"]:
            notes: List[str] = []
            if d.settings.enable_llm_review and not state.get("review_done"):
                notes = self._llm_review(state, report)
            return {"route": "finalize", "report_valid": True, "validation": validation, "review_done": True, "warnings": notes,
                    "_message": f"All {n} findings verified against computed data"}
        retries, max_retries = state.get("report_retries", 0), d.settings.max_agent_retries
        first = outcome["issues"][0]["message"][:160]
        if retries < max_retries:
            feedback = [{"message": f"[{i['scope']}{'' if i['index'] is None else ' #' + str(i['index'])}] {i['message']}"} for i in outcome["issues"]]
            return {"route": "report_agent", "report_retries": retries + 1, "validation": validation,
                    "feedback": set_feedback(state, "report", feedback), "_status": "retry",
                    "_message": f"Draft rejected ({len(outcome['issues'])} issue(s)): {first}. Requesting a corrected report ({retries + 1}/{max_retries})"}
        return {"route": "finalize", "report_valid": False, "validation": validation, "_status": "partial",
                "_message": f"Draft still has unsupported claims after {max_retries} retries; unverified content will be removed"}

    def _llm_review(self, state, report) -> List[str]:
        try:
            prompt = (f"REPORT:\n{json.dumps(report)[:6000]}\n\nEVIDENCE:\n"
                      f"{render_for_prompt(state.get('sql_results', []), state.get('tool_records', []), max_rows=10, max_tool_items=60)}")
            review = self.deps.gemini.generate_structured(prompt, ReviewResult, system=REVIEW_SYSTEM)
        except GeminiError:
            return []  # advisory only
        return [f"Reviewer note{'' if i.finding_index < 0 else f' (finding {i.finding_index + 1})'}: {i.problem}" for i in review.issues[:3]]
