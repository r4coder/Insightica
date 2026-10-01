"""Visualization Agent: Gemini picks a chart *spec*; controlled Python/Plotly code builds the figure."""
from __future__ import annotations

from typing import Any, Dict

from app.agents.base import BaseAgent, set_feedback
from app.agents.prompts import VIZ_SYSTEM
from app.schemas.llm import ChartPlan
from app.tools.visualization_tools import ChartError, build_chart_sources, create_chart

MAX_CHARTS = 3


def describe_sources(sources: Dict[str, list]) -> str:
    lines = []
    for sid, rows in sources.items():
        sample = "; ".join(str(r) for r in rows[:3])
        lines.append(f"- {sid}: {len(rows)} rows, columns {list(rows[0].keys())}\n  sample: {sample}")
    return "\n".join(lines)


class VisualizationAgent(BaseAgent):
    name, label = "visualization_agent", "Visualization Agent"

    def execute(self, state) -> Dict[str, Any]:
        d, plan = self.deps, state["plan"]
        feedback = (state.get("feedback") or {}).get("viz", [])
        if not plan.get("needs_visualization"):
            return {"charts": [], "_status": "skipped", "_message": "No visualization needed"}
        sources = build_chart_sources(state.get("sql_results", []), state.get("tool_records", []))
        if not sources:
            return {"charts": [], "_status": "skipped", "_message": "No tabular results available to chart"}
        generation = state.get("sql_generation", 0)
        if state.get("charts") and not feedback and state.get("charts_generation") == generation:
            return {"_status": "skipped", "_message": "Reused previous charts"}

        prompt = (f"Question: {state.get('resolved_question') or state['question']}\n"
                  f"Suggested chart types: {plan.get('visualizations')}\nData sources:\n{describe_sources(sources)}")
        if feedback:
            prompt += "\n\nPrevious chart problems to fix:\n" + "\n".join(f"- {f['message']}" for f in feedback)
        chart_plan = d.gemini.generate_structured(prompt, ChartPlan, system=VIZ_SYSTEM)

        charts = []
        for i, spec in enumerate(chart_plan.charts[:MAX_CHARTS]):
            s = spec.model_dump()
            entry: Dict[str, Any] = {"id": f"chart{i}", "title": s["title"], "source": s["source"], "spec": s,
                                     "figure": None, "error": None}
            rows = sources.get(s["source"])
            try:
                if rows is None:
                    raise ChartError(f"Unknown data source '{s['source']}'. Available: {list(sources)}")
                built = create_chart(s, rows)
                entry.update(spec=built["spec"], figure=built["figure"])
            except ChartError as exc:
                entry["error"] = str(exc)
            charts.append(entry)
        good = sum(1 for c in charts if not c["error"])
        return {"charts": charts, "charts_generation": generation, "feedback": set_feedback(state, "viz", []),
                "_message": f"{good} chart(s) created"}
