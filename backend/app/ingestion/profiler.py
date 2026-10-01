"""Dataset profiling: shape, types, roles, missing values, ranges, top categories."""
from __future__ import annotations

import re
from typing import Any, Dict, List

import pandas as pd

from app.core.serialization import to_jsonable

ROLES = ("numeric", "categorical", "date", "boolean", "text", "id")


def _dtype_label(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_integer_dtype(s):
        return "integer"
    if pd.api.types.is_float_dtype(s):
        return "float"
    return "string"


def _role(name: str, s: pd.Series, dtype: str, n_rows: int) -> str:
    unique = int(s.nunique(dropna=True))
    if re.search(r"(^|_)id$", name):
        return "id"
    if dtype == "datetime":
        return "date"
    if dtype == "boolean":
        return "boolean"
    if dtype in ("integer", "float"):
        return "numeric"
    non_null = int(s.notna().sum()) or 1
    if unique <= max(50, int(0.05 * n_rows)):
        return "categorical"
    if unique / non_null > 0.9:
        return "id" if unique == non_null and n_rows > 50 else "text"
    return "categorical" if unique <= 200 else "text"


def profile_dataframe(df: pd.DataFrame, sample_rows: int = 5) -> Dict[str, Any]:
    n_rows = int(len(df))
    columns: List[Dict[str, Any]] = []
    for name in df.columns:
        s = df[name]
        dtype = _dtype_label(s)
        role = _role(str(name), s, dtype, n_rows)
        missing = int(s.isna().sum())
        col: Dict[str, Any] = {
            "name": str(name), "dtype": dtype, "role": role, "missing": missing,
            "missing_pct": round(missing / n_rows * 100, 2) if n_rows else 0.0,
            "unique": int(s.nunique(dropna=True)),
        }
        valid = s.dropna()
        if dtype in ("integer", "float") and len(valid):
            v = valid.astype(float)
            col.update(min=float(v.min()), max=float(v.max()), mean=float(v.mean()), std=float(v.std()) if len(v) > 1 else 0.0,
                       median=float(v.median()), q25=float(v.quantile(0.25)), q75=float(v.quantile(0.75)))
        elif dtype == "datetime" and len(valid):
            col.update(min=valid.min().isoformat(), max=valid.max().isoformat())
        elif role in ("categorical", "boolean") and len(valid):
            top = valid.astype(str).value_counts().head(8)
            col["top_values"] = [{"value": k, "count": int(v)} for k, v in top.items()]
        columns.append(col)
    return to_jsonable({
        "rows": n_rows,
        "n_columns": len(columns),
        "duplicate_rows": int(df.duplicated().sum()),
        "columns": columns,
        "numeric_columns": [c["name"] for c in columns if c["role"] == "numeric"],
        "categorical_columns": [c["name"] for c in columns if c["role"] == "categorical"],
        "date_columns": [c["name"] for c in columns if c["role"] == "date"],
        "sample_rows": df.head(sample_rows).to_dict(orient="records"),
    })


def build_schema_context(table: str, duckdb_schema: List[Dict[str, str]], profile: Dict[str, Any]) -> str:
    """Compact, LLM-friendly description of the real schema (used by every prompt)."""
    by_name = {c["name"]: c for c in profile.get("columns", [])}
    lines = [f"Table: {table}  ({profile.get('rows'):,} rows)", "Columns (name | duckdb_type | role | details):"]
    for col in duckdb_schema:
        p = by_name.get(col["name"], {})
        detail = ""
        if p.get("role") == "numeric" and "min" in p:
            detail = f"range {p['min']:.6g}..{p['max']:.6g}, mean {p['mean']:.6g}"
        elif p.get("role") == "date":
            detail = f"from {str(p.get('min'))[:10]} to {str(p.get('max'))[:10]}"
        elif p.get("top_values"):
            detail = f"{p['unique']} distinct, e.g. " + ", ".join(t["value"] for t in p["top_values"][:6])
        if p.get("missing"):
            detail += f" ({p['missing_pct']}% missing)"
        lines.append(f"- {col['name']} | {col['type']} | {p.get('role', '?')} | {detail}".rstrip(" |"))
    return "\n".join(lines)
