"""Manager Agent: understands the question (incl. follow-ups) and produces a structured analysis plan."""
from __future__ import annotations

from typing import Any, Dict

from app.agents.base import BaseAgent
from app.agents.prompts import MANAGER_SYSTEM, render_context
from app.schemas.llm import ManagerPlan


class ManagerAgent(BaseAgent):
    name, label = "manager", "Manager Agent"

    def execute(self, state) -> Dict[str, Any]:
        d = self.deps
        prompt = (f"{d.dataset.schema_text}\n\n{render_context(state.get('context_turns', []))}\n\n"
                  f"User question: {state['question']}")
        plan = d.gemini.generate_structured(prompt, ManagerPlan, system=MANAGER_SYSTEM).model_dump()

        cols, warnings = d.dataset.columns, []
        if plan["metric"] and plan["metric"] not in cols:
            warnings.append(f"Planned metric '{plan['metric']}' is not a column in this dataset; ignoring it.")
            plan["metric"] = ""
        if plan["date_column"] and plan["date_column"] not in cols:
            warnings.append(f"Planned date column '{plan['date_column']}' does not exist; ignoring it.")
            plan["date_column"] = ""
        plan["dimensions"] = [c for c in plan["dimensions"] if c in cols]
        if not (plan["needs_sql"] or plan["needs_statistics"]):
            plan["needs_sql"] = True
        return {
            "plan": plan,
            "resolved_question": plan["resolved_question"] or state["question"],
            "warnings": warnings,
            "_message": f"Plan created: {plan['intent'].replace('_', ' ')}"
                        + (f" on {plan['metric']}" if plan["metric"] else "") + f" ({len(plan['analysis_tasks'])} tasks)",
        }
