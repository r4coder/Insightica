"""DuckDB analytical engine: dataset loading and guarded, read-only query execution."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import pandas as pd

from app.core.serialization import to_jsonable
from app.tools.sql_validator import validate_sql, wrap_with_limit

_SAFE_TABLE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class SQLExecutionError(RuntimeError):
    """The query was valid but failed to run (bad column, type error, timeout...)."""


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class DuckDBEngine:
    def __init__(self, path: Union[str, Path] = ":memory:"):
        import duckdb  # imported lazily so pure-logic modules stay importable without it

        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._duckdb = duckdb
        self._con = duckdb.connect(str(path))
        self._lock = threading.RLock()

    def _cursor(self):
        with self._lock:
            return self._con.cursor()

    # -- dataset management ----------------------------------------------------------------
    def load_dataframe(self, table: str, df: pd.DataFrame) -> None:
        if not _SAFE_TABLE.match(table):
            raise ValueError(f"Unsafe table name: {table!r}")
        with self._lock:
            self._con.register("_upload_df", df)
            try:
                self._con.execute(f"CREATE OR REPLACE TABLE {quote_identifier(table)} AS SELECT * FROM _upload_df")
            finally:
                self._con.unregister("_upload_df")

    def drop_table(self, table: str) -> None:
        if not _SAFE_TABLE.match(table):
            raise ValueError(f"Unsafe table name: {table!r}")
        with self._lock:
            self._con.execute(f"DROP TABLE IF EXISTS {quote_identifier(table)}")

    def table_exists(self, table: str) -> bool:
        with self._lock:
            rows = self._con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
            ).fetchone()
        return bool(rows and rows[0])

    def table_schema(self, table: str) -> List[Dict[str, str]]:
        with self._lock:
            rows = self._con.execute(f"DESCRIBE {quote_identifier(table)}").fetchall()
        return [{"name": r[0], "type": r[1]} for r in rows]

    def row_count(self, table: str) -> int:
        with self._lock:
            return int(self._con.execute(f"SELECT count(*) FROM {quote_identifier(table)}").fetchone()[0])

    def fetch_frame(self, table: str, columns: Iterable[str]) -> pd.DataFrame:
        cols = ", ".join(quote_identifier(c) for c in columns)
        cur = self._cursor()
        try:
            return cur.execute(f"SELECT {cols} FROM {quote_identifier(table)}").df()
        finally:
            cur.close()

    # -- guarded query execution -----------------------------------------------------------
    def execute_sql(self, sql: str, allowed_tables: Iterable[str], max_rows: int = 500, timeout: float = 30.0) -> Dict[str, Any]:
        """Validate then run read-only SQL. Raises SQLValidationError or SQLExecutionError."""
        clean = validate_sql(sql, allowed_tables)
        wrapped = wrap_with_limit(clean, max_rows)
        cur = self._cursor()
        timer = threading.Timer(timeout, cur.interrupt)
        start = time.perf_counter()
        timer.start()
        try:
            cur.execute(wrapped)
            columns = [d[0] for d in cur.description]
            fetched = cur.fetchall()
        except self._duckdb.InterruptException as exc:
            raise SQLExecutionError(f"Query exceeded the {timeout:.0f}s time limit.") from exc
        except self._duckdb.Error as exc:
            raise SQLExecutionError(str(exc)) from exc
        finally:
            timer.cancel()
            cur.close()
        truncated = len(fetched) > max_rows
        rows = [dict(zip(columns, (to_jsonable(v) for v in row))) for row in fetched[:max_rows]]
        return {
            "sql": clean, "columns": columns, "rows": rows, "row_count": len(rows),
            "truncated": truncated, "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
        }

    def close(self) -> None:
        with self._lock:
            self._con.close()
