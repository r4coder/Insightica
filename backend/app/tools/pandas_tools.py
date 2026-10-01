"""AnalystToolkit: the registry of deterministic analysis tools exposed to the Data Analyst Agent.

Every tool validates its column arguments against the real dataset schema, pulls only the columns
it needs through a `frame_provider` (DuckDB in production, a DataFrame in tests) and delegates the
maths to statistics_tools. Results are plain JSON-safe dicts.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from app.core.serialization import to_jsonable
from app.tools import statistics_tools as st
from app.tools.statistics_tools import ToolError

FrameProvider = Callable[[List[str]], pd.DataFrame]

TOOL_NAMES = (
    "dataset_profile", "describe_column", "calculate_statistics", "calculate_percentage_change",
    "detect_outliers", "calculate_correlation", "group_by_analysis", "time_series_analysis",
    "contribution_analysis",
)


class AnalystToolkit:
    def __init__(self, columns: Dict[str, str], frame_provider: FrameProvider, profile: Optional[dict] = None):
        """columns: name -> role ('numeric' | 'categorical' | 'date' | ...)."""
        self.columns = columns
        self._frames = frame_provider
        self._profile = profile or {}

    # -- helpers ---------------------------------------------------------------------------
    def _require(self, name: str, roles: Optional[tuple] = None, label: str = "column") -> str:
        if name not in self.columns:
            raise ToolError(f"Unknown {label} '{name}'. Available columns: {sorted(self.columns)}")
        if roles and self.columns[name] not in roles:
            raise ToolError(f"{label} '{name}' has role '{self.columns[name]}' but one of {list(roles)} is required.")
        return name

    def _frame(self, *cols: str) -> pd.DataFrame:
        return self._frames(list(dict.fromkeys(cols)))

    # -- public entry point ----------------------------------------------------------------
    def call(self, tool: str, **kwargs: Any) -> Dict[str, Any]:
        if tool not in TOOL_NAMES:
            raise ToolError(f"Unknown tool '{tool}'. Available tools: {list(TOOL_NAMES)}")
        return to_jsonable(getattr(self, tool)(**kwargs))

    def timed_call(self, tool: str, **kwargs: Any) -> Dict[str, Any]:
        """Run a tool and return a record with result/error and timing (never raises ToolError)."""
        start = time.perf_counter()
        record: Dict[str, Any] = {"tool": tool, "args": to_jsonable(kwargs), "result": None, "error": None}
        try:
            record["result"] = self.call(tool, **kwargs)
        except ToolError as exc:
            record["error"] = str(exc)
        except TypeError as exc:
            record["error"] = f"Invalid arguments for {tool}: {exc}"
        record["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 1)
        return record

    # -- tools -----------------------------------------------------------------------------
    def dataset_profile(self) -> Dict[str, Any]:
        p = self._profile
        return {
            "rows": p.get("rows"), "n_columns": len(self.columns),
            "columns": [
                {k: c.get(k) for k in ("name", "role", "dtype", "missing", "unique", "min", "max", "mean")}
                for c in p.get("columns", [])
            ],
        }

    def describe_column(self, column: str) -> Dict[str, Any]:
        self._require(column)
        return st.describe_series(self._frame(column)[column], column)

    def calculate_statistics(self, column: str, group_by: str = "") -> Dict[str, Any]:
        self._require(column)
        if group_by:
            self._require(group_by, label="group_by")
            return st.group_statistics(self._frame(column, group_by), column, group_by)
        return st.describe_series(self._frame(column)[column], column)

    def calculate_percentage_change(self, old_value: float, new_value: float) -> Dict[str, Any]:
        return st.percentage_change(old_value, new_value)

    def detect_outliers(self, column: str, method: str = "iqr", threshold: float = 0.0) -> Dict[str, Any]:
        self._require(column, ("numeric",))
        return st.detect_outliers(self._frame(column)[column], column, method, threshold)

    def calculate_correlation(self, column_a: str, column_b: str, method: str = "pearson") -> Dict[str, Any]:
        self._require(column_a, ("numeric",))
        self._require(column_b, ("numeric",))
        df = self._frame(column_a, column_b)
        return st.correlation(df[column_a], df[column_b], column_a, column_b, method)

    def group_by_analysis(self, metric: str, dimension: str, agg: str = "sum", top_n: int = 10) -> Dict[str, Any]:
        self._require(metric, label="metric")
        self._require(dimension, label="dimension")
        return st.group_by_analysis(self._frame(metric, dimension), metric, dimension, agg, int(top_n))

    def time_series_analysis(self, metric: str, date_column: str, freq: str = "month", agg: str = "sum") -> Dict[str, Any]:
        self._require(metric, label="metric")
        self._require(date_column, ("date",), label="date_column")
        return st.time_series_analysis(self._frame(metric, date_column), metric, date_column, freq, agg)

    def contribution_analysis(
        self, metric: str, dimension: str, date_column: str, freq: str, period_a: str, period_b: str,
        agg: str = "sum", top_n: int = 10,
    ) -> Dict[str, Any]:
        self._require(metric, label="metric")
        self._require(dimension, label="dimension")
        self._require(date_column, ("date",), label="date_column")
        df = self._frame(metric, dimension, date_column)
        return st.contribution_analysis(df, metric, dimension, date_column, freq, period_a, period_b, agg, int(top_n))
