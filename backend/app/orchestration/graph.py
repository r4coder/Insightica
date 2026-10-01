"""LangGraph workflow.

manager -> [sql_agent] -> [analyst_agent] -> [visualization_agent] -> validate_data
validate_data --ok--------------------------------------------> report_agent
validate_data --stage failed, retries left------------------------> sql_agent | analyst_agent | visualization_agent
validate_data --retries exhausted, nothing usable------------------> finalize (failed)
report_agent -> validate_report --ok--> finalize
validate_report --claims unsupported, retries left--> report_agent
validate_report --retries exhausted--> finalize (unverified content removed)

Any node that hits a fatal error (Gemini outage, crash) sets `fatal_error`, and every router sends the run to finalize.
All loops are bounded by MAX_AGENT_RETRIES counters carried in the state.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from langgraph.graph import END, START, StateGraph

from app.agents.analyst_agent import AnalystAgent
from app.agents.finalize import FinalizeNode
from app.agents.manager import ManagerAgent
from app.agents.report_agent import ReportAgent
from app.agents.sql_agent import SQLAgent
from app.agents.validation_agent import ValidationAgent
from app.agents.visualization_agent import VisualizationAgent
from app.orchestration.deps import AgentDeps
from app.orchestration.state import AnalysisState


def _guard(next_node: str) -> Callable[[AnalysisState], str]:
    return lambda state: "finalize" if state.get("fatal_error") else next_node


def route_after_manager(state: AnalysisState) -> str:
    if state.get("fatal_error"):
        return "finalize"
    return "sql_agent" if state["plan"].get("needs_sql") else "analyst_agent"


def route_from_validation(state: AnalysisState) -> str:
    if state.get("fatal_error"):
        return "finalize"
    return state.get("route", "finalize")


def build_graph(deps: AgentDeps):
    g = StateGraph(AnalysisState)
    nodes: Dict[str, Any] = {
        "manager": ManagerAgent(deps), "sql_agent": SQLAgent(deps), "analyst_agent": AnalystAgent(deps),
        "visualization_agent": VisualizationAgent(deps), "validate_data": ValidationAgent(deps, "data"),
        "report_agent": ReportAgent(deps), "validate_report": ValidationAgent(deps, "report"), "finalize": FinalizeNode(deps),
    }
    for name, node in nodes.items():
        g.add_node(name, node)
    g.add_edge(START, "manager")
    g.add_conditional_edges("manager", route_after_manager, {"sql_agent": "sql_agent", "analyst_agent": "analyst_agent", "finalize": "finalize"})
    g.add_conditional_edges("sql_agent", _guard("analyst_agent"), {"analyst_agent": "analyst_agent", "finalize": "finalize"})
    g.add_conditional_edges("analyst_agent", _guard("visualization_agent"), {"visualization_agent": "visualization_agent", "finalize": "finalize"})
    g.add_conditional_edges("visualization_agent", _guard("validate_data"), {"validate_data": "validate_data", "finalize": "finalize"})
    g.add_conditional_edges("validate_data", route_from_validation, {
        "report_agent": "report_agent", "sql_agent": "sql_agent", "analyst_agent": "analyst_agent",
        "visualization_agent": "visualization_agent", "finalize": "finalize"})
    g.add_conditional_edges("report_agent", _guard("validate_report"), {"validate_report": "validate_report", "finalize": "finalize"})
    g.add_conditional_edges("validate_report", route_from_validation, {"report_agent": "report_agent", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()
