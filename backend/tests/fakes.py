"""Test doubles: a scripted Gemini and a SQLite-backed engine so orchestration tests need no network or DuckDB."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd

from app.core.serialization import to_jsonable
from app.tools.sql_validator import validate_sql, wrap_with_limit
from app.tools.duckdb_tools import SQLExecutionError


class FakeGemini:
    """structured: {SchemaName: [responses...] | callable(prompt)}. The last response repeats once the list has one item left.
    tool_script: callable(prompt) -> [(tool_name, kwargs), ...] executed through the real tool callables."""

    def __init__(self, structured: Dict[str, Any], tool_script: Callable[[str], List[tuple]] = None):
        self.structured, self.tool_script = structured, tool_script
        self.call_count = 0
        self.log: List[str] = []

    def generate_structured(self, prompt: str, schema, system: str = None):
        self.call_count += 1
        name = schema.__name__
        self.log.append(name)
        handler = self.structured[name]
        item = handler(prompt) if callable(handler) else (handler.pop(0) if len(handler) > 1 else handler[0])
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, schema) else schema.model_validate(item)

    def generate_with_tools(self, prompt: str, tools: list, system: str = None, max_calls: int = 8) -> str:
        self.call_count += 1
        self.log.append("tools")
        by_name = {t.__name__: t for t in tools}
        for name, kwargs in (self.tool_script(prompt) if self.tool_script else []):
            by_name[name](**kwargs)
        return "done"

    def generate(self, prompt: str, system: str = None, max_output_tokens: int = None) -> str:
        self.call_count += 1
        return "ok"


class SqliteEngine:
    """Same interface as DuckDBEngine for the methods the agents use (SQL dialect: SQLite)."""

    def __init__(self):
        self._con = sqlite3.connect(":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        self._frames: Dict[str, pd.DataFrame] = {}

    def load_dataframe(self, table: str, df: pd.DataFrame) -> None:
        stored = df.copy()
        for c in stored.columns:
            if pd.api.types.is_datetime64_any_dtype(stored[c]):
                stored[c] = stored[c].dt.strftime("%Y-%m-%d")
        stored.to_sql(table, self._con, index=False, if_exists="replace")
        self._frames[table] = df

    def fetch_frame(self, table: str, columns: Iterable[str]) -> pd.DataFrame:
        return self._frames[table][list(columns)].copy()

    def table_schema(self, table: str):
        return [{"name": c, "type": "TEXT"} for c in self._frames[table].columns]

    def execute_sql(self, sql: str, allowed_tables: Iterable[str], max_rows: int = 500, timeout: float = 30.0) -> Dict[str, Any]:
        clean = validate_sql(sql, allowed_tables)
        try:
            with self._lock:
                cur = self._con.execute(wrap_with_limit(clean, max_rows))
                cols = [d[0] for d in cur.description]
                fetched = cur.fetchall()
        except sqlite3.Error as exc:
            raise SQLExecutionError(str(exc)) from exc
        rows = [dict(zip(cols, (to_jsonable(v) for v in r))) for r in fetched[:max_rows]]
        return {"sql": clean, "columns": cols, "rows": rows, "row_count": len(rows), "truncated": len(fetched) > max_rows, "elapsed_ms": 0.1}
