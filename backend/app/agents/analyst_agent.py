"""Data Analyst Agent: Gemini chooses among deterministic tools via native function calling; code does the maths."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from app.agents.base import BaseAgent, set_feedback
from app.agents.prompts import ANALYST_SYSTEM
from app.tools.pandas_tools import AnalystToolkit


def make_tool_callables(toolkit: AnalystToolkit, records: List[Dict[str, Any]], max_calls: int) -> List[Callable]:
    """Wrap toolkit tools as plain typed functions (the SDK derives each tool schema from signature + docstring).
    Every call - success or error - is recorded so the Validation Agent can audit it."""

    def run(name: str, **kwargs: Any) -> Dict[str, Any]:
        if len(records) >= max_calls:
            return {"error": "Tool-call budget exhausted; stop calling tools and finish."}
        rec = toolkit.timed_call(name, **kwargs)
        rec["id"] = f"tool{len(records)}"
        records.append(rec)
        return rec["result"] if rec["error"] is None else {"error": rec["error"]}

    def dataset_profile() -> Dict[str, Any]:
        """Get the dataset shape and per-column type, role, missing count and ranges."""
        return run("dataset_profile")

    def describe_column(column: str) -> Dict[str, Any]:
        """Describe one column: count, missing, and mean/quantiles (numeric) or top values (categorical).

        Args:
            column: Exact column name.
        """
        return run("describe_column", column=column)

    def calculate_statistics(column: str, group_by: str = "") -> Dict[str, Any]:
        """Summary statistics of a column, optionally per group.

        Args:
            column: Exact column name (numeric when grouping).
            group_by: Optional exact categorical column to group by; empty for none.
        """
        return run("calculate_statistics", column=column, group_by=group_by)

    def calculate_percentage_change(old_value: float, new_value: float) -> Dict[str, Any]:
        """Percentage change from old_value to new_value.

        Args:
            old_value: Baseline value.
            new_value: New value.
        """
        return run("calculate_percentage_change", old_value=old_value, new_value=new_value)

    def detect_outliers(column: str, method: str = "iqr", threshold: float = 0.0) -> Dict[str, Any]:
        """Find unusual values in a numeric column.

        Args:
            column: Exact numeric column name.
            method: 'iqr' or 'zscore'.
            threshold: Optional multiplier (IQR k, default 1.5) or z limit (default 3); 0 uses the default.
        """
        return run("detect_outliers", column=column, method=method, threshold=threshold)

    def calculate_correlation(column_a: str, column_b: str, method: str = "pearson") -> Dict[str, Any]:
        """Correlation between two numeric columns.

        Args:
            column_a: Exact numeric column name.
            column_b: Exact numeric column name.
            method: 'pearson' or 'spearman'.
        """
        return run("calculate_correlation", column_a=column_a, column_b=column_b, method=method)

    def group_by_analysis(metric: str, dimension: str, agg: str = "sum", top_n: int = 10) -> Dict[str, Any]:
        """Aggregate a metric by a categorical dimension with share of total.

        Args:
            metric: Exact numeric column name.
            dimension: Exact categorical column name.
            agg: One of sum, mean, count, min, max, median.
            top_n: Number of groups to return.
        """
        return run("group_by_analysis", metric=metric, dimension=dimension, agg=agg, top_n=top_n)

    def time_series_analysis(metric: str, date_column: str, freq: str = "month", agg: str = "sum") -> Dict[str, Any]:
        """Aggregate a metric over time with period-over-period change and trend.

        Args:
            metric: Exact numeric column name.
            date_column: Exact date column name.
            freq: One of day, month, quarter, year.
            agg: One of sum, mean, count, min, max, median.
        """
        return run("time_series_analysis", metric=metric, date_column=date_column, freq=freq, agg=agg)

    def contribution_analysis(metric: str, dimension: str, date_column: str, freq: str, period_a: str,
                              period_b: str, agg: str = "sum", top_n: int = 10) -> Dict[str, Any]:
        """Break down how much each dimension value contributed to the change of a metric between two periods.

        Args:
            metric: Exact numeric column name.
            dimension: Exact categorical column name.
            date_column: Exact date column name.
            freq: One of day, month, quarter, year.
            period_a: Baseline period label ('YYYY-MM', 'YYYY-Qn' or 'YYYY').
            period_b: Period being explained, same label format.
            agg: 'sum' or 'count'.
            top_n: Number of dimension values to return.
        """
        return run("contribution_analysis", metric=metric, dimension=dimension, date_column=date_column, freq=freq,
                   period_a=period_a, period_b=period_b, agg=agg, top_n=top_n)

    return [dataset_profile, describe_column, calculate_statistics, calculate_percentage_change, detect_outliers,
            calculate_correlation, group_by_analysis, time_series_analysis, contribution_analysis]


class AnalystAgent(BaseAgent):
    name, label = "analyst_agent", "Data Analyst Agent"

    def execute(self, state) -> Dict[str, Any]:
        d, plan = self.deps, state["plan"]
        feedback = (state.get("feedback") or {}).get("analyst", [])
        if not plan.get("needs_statistics"):
            return {"tool_records": [], "analyst_done": True, "_status": "skipped", "_message": "No statistical analysis needed"}
        if state.get("analyst_done") and not feedback:
            return {"_status": "skipped", "_message": "Reused previous statistical results"}

        toolkit = AnalystToolkit(d.dataset.columns, lambda cols: d.engine.fetch_frame(d.dataset.table, cols), d.dataset.profile)
        records: List[Dict[str, Any]] = []
        budget = d.settings.max_analysis_steps
        prompt = (f"{d.dataset.schema_text}\n\nAnalysis plan:\n{json.dumps(state['plan'], indent=1)}\n\n"
                  f"Question: {state.get('resolved_question') or state['question']}\n"
                  f"You may make at most {budget} tool calls.")
        if feedback:
            prompt += "\n\nYour previous attempt had problems, avoid them:\n" + "\n".join(f"- {f['message']}" for f in feedback)
        d.gemini.generate_with_tools(prompt, make_tool_callables(toolkit, records, budget), system=ANALYST_SYSTEM, max_calls=budget)
        ok = sum(1 for r in records if not r["error"])
        return {"tool_records": records, "analyst_done": True, "feedback": set_feedback(state, "analyst", []),
                "_message": f"{ok}/{len(records)} analysis tool calls succeeded"}
