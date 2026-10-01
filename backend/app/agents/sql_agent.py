"""SQL Agent: writes DuckDB SQL against the *real* schema, validates it, executes it, and repairs failures."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.agents.base import BaseAgent, set_feedback
from app.agents.prompts import SQL_SYSTEM
from app.core.logging import log_event
from app.schemas.llm import SQLPlan
from app.tools.duckdb_tools import SQLExecutionError
from app.tools.sql_validator import SQLValidationError

logger = logging.getLogger("agents.sql")
MAX_QUERIES = 4


class SQLAgent(BaseAgent):
    name, label = "sql_agent", "SQL Agent"

    def execute(self, state) -> Dict[str, Any]:
        d = self.deps
        results: List[Dict[str, Any]] = list(state.get("sql_results") or [])
        failing = sorted({f["index"] for f in (state.get("feedback") or {}).get("sql", []) if f.get("index") is not None})

        if not results or not failing:
            prompt = (f"{d.dataset.schema_text}\n\nAnalysis plan:\n{json.dumps(state['plan'], indent=1)}\n\n"
                      f"Question: {state.get('resolved_question') or state['question']}")
            queries = d.gemini.generate_structured(prompt, SQLPlan, system=SQL_SYSTEM).queries[:MAX_QUERIES]
            results = [self._run(i, q.purpose, q.sql) for i, q in enumerate(queries)]
            action = "generated"
        else:
            problems = [f"Query {i}: purpose={results[i]['purpose']!r}\nSQL:\n{results[i]['sql']}\nError: {results[i]['error'] or 'returned 0 rows'}"
                        for i in failing if i < len(results)]
            prompt = (f"{d.dataset.schema_text}\n\nThese queries failed. Return corrected replacements, one per failed query, in the same order "
                      f"(exactly {len(problems)} queries). Fix the cause; do not repeat the same mistake.\n\n" + "\n\n".join(problems))
            fixed = d.gemini.generate_structured(prompt, SQLPlan, system=SQL_SYSTEM).queries
            for idx, q in zip(failing, fixed):
                results[idx] = self._run(idx, q.purpose, q.sql)
            action = "repaired"
        ok = sum(1 for r in results if not r["error"])
        return {
            "sql_results": results,
            "sql_generation": state.get("sql_generation", 0) + 1,
            "feedback": set_feedback(state, "sql", []),
            "_message": f"SQL {action}: {ok}/{len(results)} queries executed successfully",
        }

    def _run(self, index: int, purpose: str, sql: str) -> Dict[str, Any]:
        d = self.deps
        base = {"id": f"sql{index}", "purpose": purpose, "sql": sql, "columns": [], "rows": [], "row_count": 0,
                "truncated": False, "elapsed_ms": 0.0, "error": None}
        try:
            res = d.engine.execute_sql(sql, [d.dataset.table], max_rows=d.settings.sql_max_result_rows,
                                       timeout=d.settings.sql_timeout_seconds)
            base.update(res)
            log_event(logger, "sql_executed", sql_id=base["id"], rows=res["row_count"], sql_ms=res["elapsed_ms"])
        except (SQLValidationError, SQLExecutionError) as exc:
            base["error"] = str(exc)
            log_event(logger, "sql_failed", logging.WARNING, sql_id=base["id"], error_type=type(exc).__name__)
        return base
