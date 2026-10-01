"""End-to-end LangGraph orchestration tests with a scripted Gemini (no network, no API key)."""
import pandas as pd
import pytest

pytest.importorskip("pydantic")
pytest.importorskip("langgraph")

from app.core.config import load_settings
from app.gemini.service import GeminiError
from app.ingestion.profiler import build_schema_context, profile_dataframe
from app.orchestration.deps import AgentDeps, DatasetContext
from app.orchestration.runner import run_analysis
from fakes import FakeGemini, SqliteEngine

TABLE = "sales_test0001"
Q_EXPR = "substr(order_date,1,4) || '-Q' || ((cast(substr(order_date,6,2) as int)+2)/3)"


def make_df():
    rows = []
    # Q2 total 1000 (West 600, East 400); Q3 total 800 (West 300, East 500)
    for d, region, rev in [("2024-04-10", "West", 300.0), ("2024-05-10", "West", 300.0), ("2024-06-10", "East", 400.0),
                           ("2024-07-10", "West", 300.0), ("2024-08-10", "East", 250.0), ("2024-09-10", "East", 250.0)]:
        rows.append({"order_date": d, "region": region, "revenue": rev})
    df = pd.DataFrame(rows)
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def make_deps(gemini, retries=3):
    df = make_df()
    engine = SqliteEngine()
    engine.load_dataframe(TABLE, df)
    profile = profile_dataframe(df)
    schema = [{"name": c, "type": "TEXT"} for c in df.columns]
    ctx = DatasetContext("d1", "sales.csv", TABLE, build_schema_context(TABLE, schema, profile),
                         {c["name"]: c["role"] for c in profile["columns"]}, profile)
    settings = load_settings({"MAX_AGENT_RETRIES": str(retries), "ENABLE_LLM_REVIEW": "false"})
    events = []
    return AgentDeps(gemini, engine, settings, ctx, on_progress=events.append), events


PLAN = {"resolved_question": "Why did revenue decrease in Q3 2024?", "intent": "root_cause_analysis", "metric": "revenue",
        "time_dimension": "quarter", "date_column": "order_date", "target_period": "2024-Q3", "comparison_period": "2024-Q2",
        "dimensions": ["region", "not_a_column"], "analysis_tasks": ["compare quarters", "break down by region"],
        "needs_sql": True, "needs_statistics": True, "needs_visualization": True, "visualizations": ["line", "bar"]}
GOOD_SQL = {"queries": [{"purpose": "revenue by quarter", "sql":
            f"SELECT {Q_EXPR} AS quarter, SUM(revenue) AS revenue FROM {TABLE} GROUP BY 1 ORDER BY 1"}]}
CHARTS = {"charts": [{"source": "sql0", "chart_type": "bar", "x": "quarter", "y": "revenue", "color": "", "title": "Revenue by quarter",
                      "x_label": "Quarter", "y_label": "Revenue"}]}


def tool_script(prompt):
    return [("contribution_analysis", dict(metric="revenue", dimension="region", date_column="order_date", freq="quarter",
                                           period_a="2024-Q2", period_b="2024-Q3"))]


def report(pct=-20.0, claim=-20.0, text="Revenue declined by 20.0% from Q2 to Q3."):
    return {"title": "Q3 revenue decline", "executive_summary": text,
            "key_findings": [{"statement": text, "kind": "calculated",
                              "evidence": [{"ref": "tool0.total.pct_change", "claimed_value": claim, "unit": "percent"}]},
                             {"statement": "The pattern is consistent with weaker West performance.", "kind": "interpretation", "evidence": []}],
            "detailed_analysis": "West fell while East grew.", "conclusion": "Focus on West.", "methodology": "Quarterly aggregation and contribution analysis."}


def gemini(reports, sql=None):
    return FakeGemini({"ManagerPlan": [PLAN], "SQLPlan": sql or [GOOD_SQL], "ChartPlan": [CHARTS], "ReportDraft": reports}, tool_script)


def test_happy_path_completes_with_verified_numbers():
    g = gemini([report()])
    deps, events = make_deps(g)
    res = run_analysis(deps, "Why did revenue decrease in Q3?")
    assert res["status"] == "completed", res.get("error")
    assert res["plan"]["dimensions"] == ["region"]  # hallucinated column removed by the Manager's schema check
    tool = res["report"]["key_findings"][0]["evidence"][0]
    assert tool["actual_value"] == -20.0  # (800-1000)/1000, computed by code from the data
    assert res["charts"] and res["charts"][0]["spec"]["chart_type"] == "bar"
    assert res["queries"][0]["row_count"] == 2 and res["tools"][0]["error"] is None
    assert res["validation"]["valid"] and res["validation"]["retries"] == {"data": 0, "report": 0}
    agents = [e["agent"] for e in res["trace"]]
    assert agents[:5] == ["inspector", "manager", "sql_agent", "analyst_agent", "visualization_agent"]
    assert agents[-3:] == ["report_agent", "validation", "finalize"]
    assert len(events) == len(res["trace"]) and res["stats"]["gemini_calls"] == g.call_count


def test_fabricated_percentage_is_rejected_then_repaired():
    bad = report(claim=-35.0, text="Revenue declined by 35% from Q2 to Q3.")
    g = gemini([bad, report()])
    deps, _ = make_deps(g)
    res = run_analysis(deps, "Why did revenue decrease in Q3?")
    assert res["status"] == "completed" and res["validation"]["retries"]["report"] == 1
    assert "35" not in res["report"]["executive_summary"] and "20.0%" in res["report"]["executive_summary"]
    assert any(e["status"] == "retry" for e in res["trace"])
    assert g.log.count("ReportDraft") == 2


def test_persistent_fabrication_never_reaches_the_user_as_verified():
    bad = report(claim=-35.0, text="Revenue declined by 35% from Q2 to Q3.")
    g = gemini([bad])
    deps, _ = make_deps(g, retries=2)
    res = run_analysis(deps, "Why did revenue decrease in Q3?")
    assert g.log.count("ReportDraft") == 3  # 1 + 2 retries, bounded
    assert res["status"] == "partial" and res["validation"]["valid"] is False
    text = str(res["report"])
    assert "35%" not in text  # unverified claim removed, not displayed
    kept = [f["statement"] for f in res["report"]["key_findings"]]
    assert kept == ["The pattern is consistent with weaker West performance."]
    assert any("could not be verified" in w for w in res["warnings"])


def test_sql_error_is_repaired_by_second_attempt():
    broken = {"queries": [{"purpose": "revenue by quarter", "sql": f"SELECT quarter_x, SUM(revenue) FROM {TABLE} GROUP BY 1"}]}
    g = gemini([report()], sql=[broken, GOOD_SQL])
    deps, _ = make_deps(g)
    res = run_analysis(deps, "Why did revenue decrease in Q3?")
    assert res["status"] == "completed" and res["validation"]["retries"]["data"] == 1
    assert res["queries"][0]["error"] is None and res["queries"][0]["row_count"] == 2
    assert g.log.count("SQLPlan") == 2
    assert g.log.count("tools") == 1  # analyst results reused on retry (no wasted Gemini call)


def test_unsafe_sql_is_blocked_and_run_stops_after_bounded_retries():
    evil = {"queries": [{"purpose": "x", "sql": f"DROP TABLE {TABLE}"}]}
    g = gemini([report()], sql=[evil])
    deps, _ = make_deps(g, retries=2)
    plan_no_stats = dict(PLAN, needs_statistics=False)
    g.structured["ManagerPlan"] = [plan_no_stats]
    res = run_analysis(deps, "drop everything")
    assert res["status"] == "failed" and "usable results" in res["error"]
    assert g.log.count("SQLPlan") == 3  # 1 + 2 retries, never infinite
    assert deps.engine.fetch_frame(TABLE, ["revenue"]).shape[0] == 6  # table untouched


def test_gemini_outage_is_reported_not_raised():
    g = gemini([report()])
    g.structured["ManagerPlan"] = [GeminiError("rate_limited", "Gemini rate limit reached. Please retry shortly.")]
    deps, _ = make_deps(g)
    res = run_analysis(deps, "anything")
    assert res["status"] == "failed" and "rate limit" in res["error"]
    assert [e["agent"] for e in res["trace"]] == ["inspector", "manager", "finalize"]


def test_follow_up_context_reaches_manager_prompt():
    seen = []
    def manager(prompt):
        seen.append(prompt)
        return PLAN
    g = gemini([report()])
    g.structured["ManagerPlan"] = manager
    deps, _ = make_deps(g)
    ctx = [{"question": "Why did revenue fall in Q3?", "resolved_question": "Why did revenue fall in Q3 2024?", "metric": "revenue",
            "period": "2024-Q3", "findings": ["Revenue declined 20.0%"]}]
    run_analysis(deps, "Which regions caused that?", context_turns=ctx)
    assert "Why did revenue fall in Q3?" in seen[0] and "Which regions caused that?" in seen[0]


def test_statistics_and_visualization_skipped_when_not_needed():
    plan = dict(PLAN, needs_statistics=False, needs_visualization=False)
    r = report()
    r["key_findings"][0]["evidence"] = [{"ref": "sql0[1].revenue", "claimed_value": 800.0, "unit": "currency"}]
    r["key_findings"][0]["statement"] = "Q3 revenue was $800."
    r["executive_summary"] = "Q3 revenue was $800."
    g = gemini([r])
    g.structured["ManagerPlan"] = [plan]
    deps, _ = make_deps(g)
    res = run_analysis(deps, "What was Q3 revenue?")
    assert res["status"] == "completed" and res["charts"] == [] and "tools" not in g.log and "ChartPlan" not in g.log
