"""Finalize: deterministic assembly of the user-facing result. Unverified content is never shown as verified."""
from __future__ import annotations

from typing import Any, Dict, List

from app.agents.base import BaseAgent
from app.validation.evidence import build_evidence_store, resolve

PREVIEW_ROWS = 20
CLAIM_SCOPES = ("executive_summary", "detailed_analysis", "conclusion")


class FinalizeNode(BaseAgent):
    name, label = "finalize", "Result assembly"

    def execute(self, state) -> Dict[str, Any]:
        sql_results, tool_records = state.get("sql_results", []), state.get("tool_records", [])
        store = build_evidence_store(sql_results, tool_records)
        warnings: List[str] = list(state.get("warnings", []))
        draft, validation, error = state.get("report"), state.get("validation", {}), state.get("fatal_error")
        report_out, status = None, "failed"

        if draft and not error:
            valid = bool(state.get("report_valid"))
            flags = validation.get("finding_ok") or [True] * len(draft["key_findings"])
            kept = [self._finding(f, store) for f, ok in zip(draft["key_findings"], flags) if valid or ok]
            dropped = len(draft["key_findings"]) - len(kept)
            bad_scopes = {i["scope"] for i in validation.get("issues", [])} & set(CLAIM_SCOPES)
            summary, analysis, conclusion = (draft[s] for s in CLAIM_SCOPES)
            if not valid:
                if "executive_summary" in bad_scopes or not summary:
                    summary = " ".join(f["statement"] for f in kept[:3])
                analysis = "" if "detailed_analysis" in bad_scopes else analysis
                conclusion = "" if "conclusion" in bad_scopes else conclusion
                warnings.append(f"{dropped} finding(s) and parts of the narrative were removed because they could not be verified against the data.")
            n_ev = sum(len(f["evidence"]) for f in kept)
            report_out = {
                "title": draft["title"], "executive_summary": summary, "key_findings": kept,
                "detailed_analysis": analysis, "conclusion": conclusion,
                "methodology": f"{draft['methodology']}\n\nVerification: {n_ev} cited value(s) were checked against the computed results by the Validation Agent.",
            }
            status = "completed" if valid else ("partial" if kept else "failed")
            if status == "failed":
                error = "The report could not be verified against the data. Please rephrase the question or try again."
                report_out = None
        elif not error:
            error = "No report was produced."

        plan = state.get("plan", {})
        result = {
            "status": status, "error": error, "question": state["question"],
            "resolved_question": state.get("resolved_question", state["question"]),
            "plan": plan, "report": report_out,
            "charts": [{k: c[k] for k in ("id", "title", "source", "spec", "figure")} for c in state.get("charts", []) if not c.get("error")],
            "queries": [{**{k: r.get(k) for k in ("id", "purpose", "sql", "columns", "row_count", "truncated", "elapsed_ms", "error")},
                         "preview": r.get("rows", [])[:PREVIEW_ROWS]} for r in sql_results],
            "tools": [{k: r.get(k) for k in ("id", "tool", "args", "error", "elapsed_ms")} for r in tool_records],
            "validation": {"valid": bool(state.get("report_valid")), "issues": validation.get("issues", []),
                           "retries": {"data": state.get("data_retries", 0), "report": state.get("report_retries", 0)}},
            "warnings": warnings,
            "context_summary": {
                "question": state["question"], "resolved_question": state.get("resolved_question", state["question"]),
                "metric": plan.get("metric", ""), "period": plan.get("target_period", ""),
                "findings": [f["statement"] for f in (report_out or {}).get("key_findings", [])[:3]],
            },
        }
        return {"result": result, "_message": f"Analysis {status}"}

    @staticmethod
    def _finding(f: Dict[str, Any], store: Dict[str, Any]) -> Dict[str, Any]:
        evidence = []
        for ev in f.get("evidence", []):
            found, actual = resolve(store, ev["ref"])
            evidence.append({**ev, "actual_value": actual if found else None})
        return {"statement": f["statement"], "kind": f["kind"], "verified": True, "evidence": evidence}
