#!/usr/bin/env python3
"""Run datasets/questions.json against the real agent graph and check objective, mechanical
criteria (did SQL run, did stats run, did a chart get built, are there root-cause findings...).
See evaluation/README.md for --live vs mocked mode.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import os as _os
if _os.environ.get("MADATA_USE_STUBS"):
    sys.path.insert(0, "/tmp/stubs")

from app.core.config import load_settings
from app.ingestion.loaders import infer_types, make_table_name, new_dataset_id, normalize_columns, read_dataset
from app.ingestion.profiler import build_schema_context, profile_dataframe
from app.orchestration.deps import AgentDeps, DatasetContext
from app.orchestration.runner import run_analysis
from app.tools.duckdb_tools import DuckDBEngine

SALES_CSV = ROOT / "sample_data" / "sales.csv"


def load_dataset(engine: DuckDBEngine) -> DatasetContext:
    df = read_dataset(SALES_CSV, ".csv", max_rows=100_000)
    df, _ = normalize_columns(df)
    df = infer_types(df)
    profile = profile_dataframe(df)
    dataset_id = new_dataset_id()
    table = make_table_name("sales.csv", dataset_id)
    engine.load_dataframe(table, df)
    schema = engine.table_schema(table)
    return DatasetContext(dataset_id, "sales.csv", table, build_schema_context(table, schema, profile),
                          {c["name"]: c["role"] for c in profile["columns"]}, profile)


def make_mock_gemini():
    sys.path.insert(0, str(ROOT / "backend" / "tests"))
    from fakes import FakeGemini

    plan = {"resolved_question": "", "intent": "root_cause_analysis", "metric": "revenue", "time_dimension": "quarter",
            "date_column": "order_date", "target_period": "2024-Q3", "comparison_period": "2024-Q2",
            "dimensions": ["region", "customer_segment"], "analysis_tasks": ["compare quarters", "break down by region"],
            "needs_sql": True, "needs_statistics": True, "needs_visualization": True, "visualizations": ["line", "bar"]}

    def manager(prompt):
        p = dict(plan)
        p["resolved_question"] = prompt.splitlines()[-1].replace("User question: ", "")
        return p

    sql = {"queries": [{"purpose": "revenue by quarter", "sql":
           "SELECT CAST(year(order_date) AS VARCHAR) || '-Q' || CAST(quarter(order_date) AS VARCHAR) AS quarter, "
           "SUM(revenue) AS revenue FROM {table} GROUP BY 1 ORDER BY 1"}]}

    def sql_plan(prompt):
        table = [l for l in prompt.splitlines() if l.startswith("Table:")][0].split()[1]
        return {"queries": [{"purpose": q["purpose"], "sql": q["sql"].format(table=table)} for q in sql["queries"]]}

    charts = {"charts": [{"source": "sql0", "chart_type": "line", "x": "quarter", "y": "revenue", "color": "",
                          "title": "Revenue by quarter", "x_label": "Quarter", "y_label": "Revenue ($)"}]}

    def tool_script(prompt):
        return [("contribution_analysis", dict(metric="revenue", dimension="region", date_column="order_date",
                                               freq="quarter", period_a="2024-Q2", period_b="2024-Q3")),
                ("detect_outliers", dict(column="revenue"))]

    def report(prompt):
        import re

        m = re.search(r"sql0\[\d+\]\.revenue = (-?[\d.]+)", prompt)
        val = float(m.group(1)) if m else 0.0
        return {"title": "Q3 2024 revenue", "executive_summary": f"Revenue for the most recent period was {val:.2f}.",
                "key_findings": [{"statement": f"Revenue for the most recent period was {val:.2f}.", "kind": "observed",
                                  "evidence": [{"ref": "sql0[-1].revenue" if False else "sql0[4].revenue", "claimed_value": val, "unit": "currency"}]}],
                "detailed_analysis": "", "conclusion": "", "methodology": "Quarterly aggregation."}

    return FakeGemini({"ManagerPlan": manager, "SQLPlan": sql_plan, "ChartPlan": [charts], "ReportDraft": report}, tool_script)


def make_live_gemini(model: str):
    from app.gemini.service import GeminiService

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set; cannot run in --live mode.", file=sys.stderr)
        sys.exit(2)
    return GeminiService(key, model)


CHECKS = {
    "sql_success": lambda r: any(not q["error"] and q["row_count"] > 0 for q in r["queries"]),
    "numeric_answer": lambda r: bool(r["report"]) and any(f["evidence"] for f in r["report"]["key_findings"]),
    "grouping_answer": lambda r: any(q["row_count"] > 1 for q in r["queries"]),
    "stats_success": lambda r: any(not t["error"] for t in r["tools"]),
    "chart_success": lambda r: len(r["charts"]) > 0,
    "root_cause_findings": lambda r: bool(r["report"]) and len(r["report"]["key_findings"]) >= 2,
    "outlier_findings": lambda r: any(t["tool"] == "detect_outliers" and not t["error"] for t in r["tools"]),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use the real Gemini API (requires GEMINI_API_KEY).")
    parser.add_argument("--questions", default=str(ROOT / "evaluation" / "datasets" / "questions.json"))
    parser.add_argument("--out", default=str(ROOT / "evaluation" / "results" / "latest.json"))
    args = parser.parse_args()

    settings = load_settings({"ENABLE_LLM_REVIEW": "false" if not args.live else "true"})
    engine = DuckDBEngine(":memory:")
    dataset = load_dataset(engine)
    gemini = make_live_gemini(settings.gemini_model) if args.live else make_mock_gemini()

    questions = json.loads(Path(args.questions).read_text())
    report = {"mode": "live" if args.live else "mocked", "results": []}
    for q in questions:
        deps = AgentDeps(gemini, engine, settings, dataset, on_progress=lambda e: None)
        try:
            result = run_analysis(deps, q["question"])
        except Exception as exc:  # an eval run should never crash on one bad question
            report["results"].append({"id": q["id"], "question": q["question"], "error": str(exc), "checks": {}})
            continue
        checks = {name: bool(CHECKS[name](result)) for name in q["checks"]}
        report["results"].append({
            "id": q["id"], "question": q["question"], "status": result["status"], "checks": checks,
            "all_passed": all(checks.values()), "validation_issues": result["validation"]["issues"],
            "trace": [{"agent": t["agent"], "status": t["status"]} for t in result["trace"]],
        })
    engine.close()

    total = len(report["results"])
    passed = sum(1 for r in report["results"] if r.get("all_passed"))
    report["summary"] = {"total": total, "passed": passed, "pass_rate": round(passed / total, 3) if total else 0.0}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["summary"], indent=2))
    for r in report["results"]:
        mark = "PASS" if r.get("all_passed") else "FAIL"
        print(f"  [{mark}] {r['id']}: {r['question']}  {r.get('checks')}")


if __name__ == "__main__":
    main()
