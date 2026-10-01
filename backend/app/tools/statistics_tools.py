"""Deterministic statistics. Pure pandas/numpy - no LLM, no I/O. All numbers reported to users originate here or in SQL."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.core.serialization import to_jsonable


class ToolError(ValueError):
    """A tool was called with invalid arguments (message is safe to show to the model)."""


AGGREGATIONS = ("sum", "mean", "count", "min", "max", "median")
FREQUENCIES = ("day", "month", "quarter", "year")


def _r(x: Any, digits: int = 6) -> Optional[float]:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, digits) if math.isfinite(f) else None


def percentage_change(old: Any, new: Any) -> Dict[str, Any]:
    o, n = _r(old, 12), _r(new, 12)
    if o is None or n is None:
        raise ToolError("old_value and new_value must be finite numbers.")
    out: Dict[str, Any] = {"old": o, "new": n, "abs_change": _r(n - o)}
    if o == 0:
        out["pct_change"] = None
        out["note"] = "Baseline is zero; percentage change is undefined."
    else:
        out["pct_change"] = _r((n - o) / abs(o) * 100)
    return out


def period_labels(dates: pd.Series, freq: str) -> pd.Series:
    if freq not in FREQUENCIES:
        raise ToolError(f"freq must be one of {FREQUENCIES}.")
    d = pd.to_datetime(dates, errors="coerce")
    if freq == "day":
        return d.dt.strftime("%Y-%m-%d")
    if freq == "month":
        return d.dt.strftime("%Y-%m")
    if freq == "year":
        return d.dt.strftime("%Y")
    return d.dt.year.astype("Int64").astype(str) + "-Q" + d.dt.quarter.astype("Int64").astype(str)


def _aggregate(grouped, agg: str):
    if agg not in AGGREGATIONS:
        raise ToolError(f"agg must be one of {AGGREGATIONS}.")
    return getattr(grouped, agg)()


def _numeric(series: pd.Series, name: str) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() == 0:
        raise ToolError(f"Column '{name}' has no numeric values.")
    return s


def describe_series(series: pd.Series, name: str) -> Dict[str, Any]:
    total = int(len(series))
    missing = int(series.isna().sum())
    base: Dict[str, Any] = {"column": name, "count": total - missing, "missing": missing}
    if pd.api.types.is_datetime64_any_dtype(series):
        s = series.dropna()
        base.update(kind="datetime", min=to_jsonable(s.min()) if len(s) else None, max=to_jsonable(s.max()) if len(s) else None)
    elif pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        s = series.dropna().astype(float)
        base.update(
            kind="numeric", sum=_r(s.sum()), mean=_r(s.mean()), std=_r(s.std()), min=_r(s.min()),
            q25=_r(s.quantile(0.25)), median=_r(s.median()), q75=_r(s.quantile(0.75)), max=_r(s.max()),
        )
    else:
        s = series.dropna().astype(str)
        top = s.value_counts().head(5)
        base.update(kind="categorical", unique=int(s.nunique()),
                    top_values=[{"value": str(k), "count": int(v)} for k, v in top.items()])
    return base


def group_statistics(df: pd.DataFrame, column: str, group_by: str, top_n: int = 20) -> Dict[str, Any]:
    d = df[[group_by, column]].copy()
    d[column] = _numeric(d[column], column)
    g = d.groupby(group_by, dropna=False)[column].agg(["count", "sum", "mean", "median", "min", "max", "std"])
    g = g.sort_values("sum", ascending=False).head(top_n)
    table = [{group_by: to_jsonable(idx), **{k: _r(v) for k, v in row.items()}} for idx, row in g.iterrows()]
    return {"column": column, "group_by": group_by, "table": table}


def detect_outliers(series: pd.Series, name: str, method: str = "iqr", threshold: float = 0.0) -> Dict[str, Any]:
    s = _numeric(series, name).dropna().astype(float)
    if len(s) < 4:
        raise ToolError("Need at least 4 values to detect outliers.")
    if method == "iqr":
        k = threshold if threshold > 0 else 1.5
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - k * iqr, q3 + k * iqr
        mask = (s < lower) | (s > upper)
        bounds = {"lower_bound": _r(lower), "upper_bound": _r(upper), "k": k}
    elif method == "zscore":
        z_limit = threshold if threshold > 0 else 3.0
        std = s.std()
        z = (s - s.mean()) / std if std and not math.isnan(std) else s * 0
        mask = z.abs() > z_limit
        bounds = {"z_threshold": z_limit}
    else:
        raise ToolError("method must be 'iqr' or 'zscore'.")
    out = s[mask]
    extremes = out.reindex(out.abs().sort_values(ascending=False).index).head(10)
    return {
        "column": name, "method": method, "n": int(len(s)), "outlier_count": int(mask.sum()),
        "outlier_pct": _r(mask.mean() * 100), **bounds,
        "extreme_values": [_r(v) for v in extremes.values],
    }


def correlation(a: pd.Series, b: pd.Series, name_a: str, name_b: str, method: str = "pearson") -> Dict[str, Any]:
    if method not in ("pearson", "spearman"):
        raise ToolError("method must be 'pearson' or 'spearman'.")
    pair = pd.DataFrame({"a": _numeric(a, name_a), "b": _numeric(b, name_b)}).dropna()
    if len(pair) < 3:
        raise ToolError("Need at least 3 paired values to compute a correlation.")
    r = pair["a"].corr(pair["b"], method=method)
    r = _r(r)
    strength = None
    if r is not None:
        m = abs(r)
        strength = "negligible" if m < 0.1 else "weak" if m < 0.3 else "moderate" if m < 0.5 else "strong" if m < 0.7 else "very strong"
    return {"column_a": name_a, "column_b": name_b, "method": method, "n": int(len(pair)),
            "correlation": r, "strength": strength}


def group_by_analysis(df: pd.DataFrame, metric: str, dimension: str, agg: str = "sum", top_n: int = 10) -> Dict[str, Any]:
    d = df[[dimension, metric]].copy()
    d[metric] = _numeric(d[metric], metric) if agg != "count" else d[metric]
    g = _aggregate(d.groupby(dimension, dropna=False)[metric], agg).sort_values(ascending=False)
    counts = d.groupby(dimension, dropna=False)[metric].size()
    total = g.sum() if agg in ("sum", "count") else None
    rows = []
    for key, value in g.head(top_n).items():
        row = {"dimension_value": to_jsonable(key), "value": _r(value), "n_rows": int(counts.get(key, 0))}
        if total not in (None, 0):
            row["share_pct"] = _r(value / total * 100)
        rows.append(row)
    return {"metric": metric, "dimension": dimension, "agg": agg, "n_groups": int(len(g)),
            "total": _r(total) if total is not None else None, "table": rows}


def time_series_analysis(df: pd.DataFrame, metric: str, date_column: str, freq: str = "month", agg: str = "sum") -> Dict[str, Any]:
    d = df[[date_column, metric]].copy()
    d[date_column] = pd.to_datetime(d[date_column], errors="coerce")
    d = d.dropna(subset=[date_column])
    if d.empty:
        raise ToolError(f"Column '{date_column}' has no valid dates.")
    if agg != "count":
        d[metric] = _numeric(d[metric], metric)
    d["_period"] = period_labels(d[date_column], freq)
    grouped = d.groupby("_period")[metric]
    values = _aggregate(grouped, agg).sort_index()
    sizes = grouped.size().sort_index()
    table: List[Dict[str, Any]] = []
    prev: Optional[float] = None
    for period, value in values.items():
        row: Dict[str, Any] = {"period": str(period), "value": _r(value), "n_rows": int(sizes[period])}
        if prev is not None:
            change = percentage_change(prev, value)
            row["abs_change_vs_prev"] = change["abs_change"]
            row["pct_change_vs_prev"] = change["pct_change"]
        table.append(row)
        prev = float(value)
    overall: Dict[str, Any] = {"n_periods": len(table), "freq": freq, "agg": agg}
    if len(table) >= 2:
        first, last = table[0]["value"], table[-1]["value"]
        overall["first_to_last_pct_change"] = percentage_change(first, last)["pct_change"]
        slope = np.polyfit(np.arange(len(values)), values.astype(float).values, 1)[0]
        overall["trend_slope_per_period"] = _r(slope)
    best = max(table, key=lambda r: r["value"] if r["value"] is not None else -math.inf)
    worst = min(table, key=lambda r: r["value"] if r["value"] is not None else math.inf)
    overall["best_period"] = best["period"]
    overall["worst_period"] = worst["period"]
    return {"metric": metric, "date_column": date_column, "table": table, "overall": overall}


def contribution_analysis(
    df: pd.DataFrame, metric: str, dimension: str, date_column: str,
    freq: str, period_a: str, period_b: str, agg: str = "sum", top_n: int = 10,
) -> Dict[str, Any]:
    """How much each dimension value contributed to the change of `metric` from period_a to period_b."""
    if agg not in ("sum", "count"):
        raise ToolError("contribution_analysis supports agg 'sum' or 'count' only.")
    d = df[[date_column, dimension, metric]].copy()
    d[date_column] = pd.to_datetime(d[date_column], errors="coerce")
    d = d.dropna(subset=[date_column])
    if agg == "sum":
        d[metric] = _numeric(d[metric], metric)
    d["_period"] = period_labels(d[date_column], freq)
    available = sorted(d["_period"].unique().tolist())
    for p in (period_a, period_b):
        if p not in available:
            raise ToolError(f"Period '{p}' not found for freq '{freq}'. Available periods: {available[:8]}...{available[-4:]}")
    fn = "sum" if agg == "sum" else "count"
    a = d[d["_period"] == period_a].groupby(dimension, dropna=False)[metric].agg(fn)
    b = d[d["_period"] == period_b].groupby(dimension, dropna=False)[metric].agg(fn)
    frame = pd.concat([a.rename("value_a"), b.rename("value_b")], axis=1).fillna(0.0)
    frame["delta"] = frame["value_b"] - frame["value_a"]
    total_a, total_b = float(frame["value_a"].sum()), float(frame["value_b"].sum())
    total_delta = total_b - total_a
    # biggest contributors to the overall direction of change come first
    frame = frame.sort_values("delta", ascending=total_delta < 0)
    rows = []
    for key, row in frame.head(top_n).iterrows():
        change = percentage_change(row["value_a"], row["value_b"])
        rows.append({
            "dimension_value": to_jsonable(key), "value_a": _r(row["value_a"]), "value_b": _r(row["value_b"]),
            "delta": _r(row["delta"]), "pct_change": change["pct_change"],
            "share_of_total_change_pct": _r(row["delta"] / total_delta * 100) if total_delta else None,
        })
    return {
        "metric": metric, "dimension": dimension, "period_a": period_a, "period_b": period_b, "agg": agg,
        "total": {"value_a": _r(total_a), "value_b": _r(total_b), "delta": _r(total_delta),
                  "pct_change": percentage_change(total_a, total_b)["pct_change"]},
        "table": rows,
    }
