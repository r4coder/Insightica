"""Pydantic schemas the agents ask Gemini to fill in (structured output).

No default values on purpose: the Gemini response-schema dialect rejects them, and every field
should be an explicit decision by the model. Empty string / empty list mean "not applicable".
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

ChartType = Literal["line", "bar", "horizontal_bar", "histogram", "scatter", "pie", "donut"]
Intent = Literal["descriptive", "comparison", "trend", "root_cause_analysis", "ranking", "growth",
                 "anomaly_detection", "correlation", "distribution", "other"]


class ManagerPlan(BaseModel):
    resolved_question: str = Field(description="The user's question rewritten to be fully standalone (resolve 'that', 'it', 'those' from context).")
    intent: Intent
    metric: str = Field(description="Exact numeric column name to analyse, or empty string.")
    time_dimension: str = Field(description="One of: day, month, quarter, year, none.")
    date_column: str = Field(description="Exact date column name, or empty string.")
    target_period: str = Field(description="Period of interest as a label: 'YYYY-MM', 'YYYY-Qn' or 'YYYY'; empty if none.")
    comparison_period: str = Field(description="Period to compare against, same label format; empty if none.")
    dimensions: List[str] = Field(description="Exact categorical column names worth breaking the metric down by.")
    analysis_tasks: List[str] = Field(description="2-5 concrete analysis tasks in plain English.")
    needs_sql: bool
    needs_statistics: bool = Field(description="True for root cause, trend, growth, outliers, correlation, distribution questions.")
    needs_visualization: bool
    visualizations: List[ChartType]


class SQLQuery(BaseModel):
    purpose: str = Field(description="What this query establishes, in one short sentence.")
    sql: str = Field(description="A single read-only DuckDB SELECT/WITH statement.")


class SQLPlan(BaseModel):
    queries: List[SQLQuery]


class ChartSpecModel(BaseModel):
    source: str = Field(description="Data source id exactly as listed, e.g. 'sql0' or 'tool2'.")
    chart_type: ChartType
    x: str = Field(description="Exact column name for the x axis (or the values column for a histogram).")
    y: str = Field(description="Exact numeric column name for the y axis; empty string for a histogram.")
    color: str = Field(description="Optional column to split series by; empty string if none.")
    title: str
    x_label: str
    y_label: str


class ChartPlan(BaseModel):
    charts: List[ChartSpecModel]


class EvidenceItem(BaseModel):
    ref: str = Field(description="Exact evidence reference, e.g. sql0[1].pct_change or tool2.total.pct_change.")
    claimed_value: float = Field(description="The value exactly as it appears in the evidence.")
    unit: Literal["percent", "number", "currency", "ratio"]


class Finding(BaseModel):
    statement: str
    kind: Literal["observed", "calculated", "interpretation"]
    evidence: List[EvidenceItem]


class ReportDraft(BaseModel):
    title: str
    executive_summary: str
    key_findings: List[Finding]
    detailed_analysis: str
    conclusion: str
    methodology: str


class ReviewIssue(BaseModel):
    finding_index: int = Field(description="Index of the finding, or -1 for the summary.")
    problem: str


class ReviewResult(BaseModel):
    issues: List[ReviewIssue]
