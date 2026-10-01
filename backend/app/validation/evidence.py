"""Evidence store: every number an agent computed, addressable by a stable reference.

Refs look like `sql0[3].revenue` (row 3, column 'revenue' of SQL result 0) or
`tool1.table[0].pct_change` (a path inside tool result 1). The Report Agent must cite refs;
the Validation Agent resolves them against this store and compares the claimed values.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

MAX_LIST_ITEMS = 100
MAX_DEPTH = 6


def flatten(prefix: str, obj: Any, out: Dict[str, Any], depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            flatten(f"{prefix}.{key}" if prefix else str(key), value, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj[:MAX_LIST_ITEMS]):
            flatten(f"{prefix}[{i}]", value, out, depth + 1)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        if math.isfinite(float(obj)):
            out[prefix] = float(obj)
    elif isinstance(obj, str):
        out[prefix] = obj


def build_evidence_store(sql_results: List[Dict[str, Any]], tool_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    store: Dict[str, Any] = {}
    for i, res in enumerate(sql_results):
        if res.get("error"):
            continue
        rid = res.get("id", f"sql{i}")
        for r, row in enumerate(res.get("rows", [])[:MAX_LIST_ITEMS]):
            for col, value in row.items():
                flatten(f"{rid}[{r}].{col}", value, store)
    for i, rec in enumerate(tool_records):
        if rec.get("error") or rec.get("result") is None:
            continue
        flatten(rec.get("id", f"tool{i}"), rec["result"], store)
    return store


def resolve(store: Dict[str, Any], ref: str) -> Tuple[bool, Any]:
    ref = (ref or "").strip()
    if ref in store:
        return True, store[ref]
    lowered = {k.lower(): v for k, v in store.items()}
    if ref.lower() in lowered:
        return True, lowered[ref.lower()]
    return False, None


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def render_for_prompt(sql_results: List[Dict[str, Any]], tool_records: List[Dict[str, Any]],
                      max_rows: int = 25, max_tool_items: int = 120) -> str:
    """Compact text view of the evidence for the Report Agent, with citable refs."""
    blocks: List[str] = []
    for i, res in enumerate(sql_results):
        if res.get("error"):
            continue
        rid = res.get("id", f"sql{i}")
        rows = res.get("rows", [])
        header = f"## {rid}: {res.get('purpose', '')} ({min(len(rows), max_rows)} of {res.get('row_count', len(rows))} rows). Cite as {rid}[ROW].column"
        lines = [header, "columns: " + ", ".join(res.get("columns", []))]
        for r, row in enumerate(rows[:max_rows]):
            lines.append(f"[{r}] " + "; ".join(f"{k}={_fmt(v)}" for k, v in row.items()))
        blocks.append("\n".join(lines))
    for i, rec in enumerate(tool_records):
        if rec.get("error") or rec.get("result") is None:
            continue
        rid = rec.get("id", f"tool{i}")
        flat: Dict[str, Any] = {}
        flatten(rid, rec["result"], flat)
        items = list(flat.items())[:max_tool_items]
        lines = [f"## {rid}: {rec['tool']}({rec.get('args')}). Cite by the exact key on the left."]
        lines += [f"{k} = {_fmt(v)}" for k, v in items]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
