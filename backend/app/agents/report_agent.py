"""Report Agent: turns computed evidence into a business report where every number is cited."""
from __future__ import annotations

import json
from typing import Any, Dict

from app.agents.base import BaseAgent, set_feedback
from app.agents.prompts import REPORT_SYSTEM
from app.schemas.llm import ReportDraft
from app.validation.evidence import render_for_prompt


class ReportAgent(BaseAgent):
    name, label = "report_agent", "Report Agent"

    def execute(self, state) -> Dict[str, Any]:
        d = self.deps
        evidence = render_for_prompt(state.get("sql_results", []), state.get("tool_records", []))
        charts = [f"- {c['title']} ({c['spec']['chart_type']})" for c in state.get("charts", []) if not c.get("error")]
        feedback = (state.get("feedback") or {}).get("report", [])
        prompt = (f"Question: {state.get('resolved_question') or state['question']}\n"
                  f"Plan: {json.dumps(state['plan'])}\n\nEVIDENCE (cite these refs):\n{evidence}\n\n"
                  f"Charts shown to the reader:\n" + ("\n".join(charts) or "none"))
        if state.get("warnings"):
            prompt += "\n\nKnown caveats to mention if relevant:\n" + "\n".join(f"- {w}" for w in state["warnings"][:5])
        if feedback:
            prompt += ("\n\nYOUR PREVIOUS DRAFT WAS REJECTED by the validator. Fix every problem, using only cited evidence values:\n"
                       + "\n".join(f"- {f['message']}" for f in feedback))
        draft = d.gemini.generate_structured(prompt, ReportDraft, system=REPORT_SYSTEM).model_dump()
        return {"report": draft, "feedback": set_feedback(state, "report", []),
                "_message": f"Report drafted with {len(draft['key_findings'])} findings"
                            + (" (revision)" if feedback else "")}
