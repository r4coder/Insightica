"""Controlled chart construction. The model only picks a *spec*; Python builds the Plotly figure.

`chart_series` is pure (no Plotly import) and is used both to build figures and to verify them
against the source rows, so a chart can never silently diverge from the data behind it.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

CHART_TYPES = ("line", "bar", "horizontal_bar", "histogram", "scatter", "pie", "donut")
MAX_CATEGORIES = 30
MAX_COLOR_GROUPS = 8
MAX_HIST_VALUES = 5000
PIE_MAX_SLICES = 8


class ChartError(ValueError):
    pass


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    return list(rows[0].keys()) if rows else []


def normalize_spec(spec: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate a chart spec against the source rows, applying safe fallbacks (e.g. pie -> bar)."""
    if not rows:
        raise ChartError("Source has no rows to chart.")
    cols = _columns(rows)
    chart_type = spec.get("chart_type")
    if chart_type not in CHART_TYPES:
        raise ChartError(f"chart_type must be one of {CHART_TYPES}.")
    out = {
        "chart_type": chart_type, "x": spec.get("x") or "", "y": spec.get("y") or "", "color": spec.get("color") or "",
        "title": (spec.get("title") or "").strip(), "x_label": spec.get("x_label") or "", "y_label": spec.get("y_label") or "",
        "source": spec.get("source", ""),
    }
    if out["x"] not in cols:
        raise ChartError(f"x column '{out['x']}' not in source columns {cols}.")
    if chart_type != "histogram":
        if out["y"] not in cols:
            raise ChartError(f"y column '{out['y']}' not in source columns {cols}.")
        if not any(_num(r.get(out["y"])) is not None for r in rows):
            raise ChartError(f"y column '{out['y']}' has no numeric values.")
    elif not any(_num(r.get(out["x"])) is not None for r in rows):
        raise ChartError(f"histogram column '{out['x']}' has no numeric values.")
    if out["color"] and out["color"] not in cols:
        out["color"] = ""
    if chart_type in ("pie", "donut"):
        slices = {str(r.get(out["x"])) for r in rows}
        negative = any((_num(r.get(out["y"])) or 0) < 0 for r in rows)
        if len(slices) > PIE_MAX_SLICES or negative:
            out["chart_type"], out["fallback_from"] = "bar", chart_type
        out["color"] = ""
    if chart_type == "scatter" and not any(_num(r.get(out["x"])) is not None for r in rows):
        raise ChartError("scatter x column must be numeric.")
    return out


def chart_series(rows: List[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deterministically derive the plotted traces [{name, x, y}] from source rows and a normalized spec."""
    t, x, y, color = spec["chart_type"], spec["x"], spec["y"], spec.get("color", "")
    if t == "histogram":
        values = [v for v in (_num(r.get(x)) for r in rows) if v is not None][:MAX_HIST_VALUES]
        return [{"name": x, "x": values, "y": None}]
    if t == "line":
        rows = sorted(rows, key=lambda r: str(r.get(x)))
    groups: Dict[str, List[Dict[str, Any]]] = {}
    if color:
        for r in rows:
            groups.setdefault(str(r.get(color)), []).append(r)
        if len(groups) > MAX_COLOR_GROUPS:
            raise ChartError(f"color column '{color}' has more than {MAX_COLOR_GROUPS} groups.")
    else:
        groups[y] = list(rows)
    traces = []
    for name, grp in groups.items():
        if t in ("bar", "horizontal_bar") and len(grp) > MAX_CATEGORIES:
            grp = sorted(grp, key=lambda r: abs(_num(r.get(y)) or 0), reverse=True)[:MAX_CATEGORIES]
        pts = [(r.get(x), _num(r.get(y))) for r in grp]
        pts = [(a, b) for a, b in pts if b is not None and (t != "scatter" or _num(a) is not None)]
        traces.append({"name": name, "x": [a for a, _ in pts], "y": [b for _, b in pts]})
    return traces


def create_chart(spec: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a Plotly figure (JSON dict) from a validated spec and source rows."""
    import plotly.graph_objects as go  # lazy: keeps pure helpers importable without plotly

    norm = normalize_spec(spec, rows)
    traces = chart_series(rows, norm)
    t = norm["chart_type"]
    fig = go.Figure()
    for tr in traces:
        if t == "line":
            fig.add_trace(go.Scatter(x=tr["x"], y=tr["y"], mode="lines+markers", name=tr["name"]))
        elif t == "bar":
            fig.add_trace(go.Bar(x=tr["x"], y=tr["y"], name=tr["name"]))
        elif t == "horizontal_bar":
            fig.add_trace(go.Bar(x=tr["y"], y=tr["x"], orientation="h", name=tr["name"]))
        elif t == "histogram":
            fig.add_trace(go.Histogram(x=tr["x"], name=tr["name"]))
        elif t == "scatter":
            fig.add_trace(go.Scatter(x=tr["x"], y=tr["y"], mode="markers", name=tr["name"]))
        else:
            fig.add_trace(go.Pie(labels=tr["x"], values=tr["y"], hole=0.45 if t == "donut" else 0, name=tr["name"]))
    x_title = norm["x_label"] or norm["x"]
    y_title = norm["y_label"] or norm["y"]
    layout: Dict[str, Any] = {
        "title": {"text": norm["title"]}, "template": "plotly_white", "margin": {"l": 60, "r": 20, "t": 60, "b": 60},
        "showlegend": len(traces) > 1 or t in ("pie", "donut"),
    }
    if t not in ("pie", "donut"):
        if t == "horizontal_bar":
            layout["xaxis"], layout["yaxis"] = {"title": {"text": y_title}}, {"title": {"text": x_title}, "autorange": "reversed"}
        elif t == "histogram":
            layout["xaxis"], layout["yaxis"] = {"title": {"text": x_title}}, {"title": {"text": "count"}}
        else:
            layout["xaxis"], layout["yaxis"] = {"title": {"text": x_title}}, {"title": {"text": y_title}}
    fig.update_layout(**layout)
    return {"spec": norm, "figure": json.loads(fig.to_json()), "points": sum(len(tr["x"]) for tr in traces)}


def _close(a: Any, b: Any) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return math.isclose(fa, fb, rel_tol=1e-9, abs_tol=1e-9)
    return str(a) == str(b)


def verify_chart(chart: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    """Return a list of problems (empty = chart faithfully reflects its source rows)."""
    issues: List[str] = []
    try:
        expected = chart_series(rows, chart["spec"])
    except ChartError as exc:
        return [str(exc)]
    data = chart.get("figure", {}).get("data", [])
    if len(data) != len(expected):
        return [f"Chart has {len(data)} traces but source implies {len(expected)}."]
    t = chart["spec"]["chart_type"]
    for tr, trace in zip(expected, data):
        if t == "horizontal_bar":
            got_x, got_y = trace.get("y", []), trace.get("x", [])
        elif t in ("pie", "donut"):
            got_x, got_y = trace.get("labels", []), trace.get("values", [])
        else:
            got_x, got_y = trace.get("x", []), trace.get("y")
        if len(got_x) != len(tr["x"]) or not all(_close(a, b) for a, b in zip(got_x, tr["x"])):
            issues.append(f"Trace '{tr['name']}' x-values differ from source data.")
        if tr["y"] is not None and (got_y is None or len(got_y) != len(tr["y"]) or not all(_close(a, b) for a, b in zip(got_y, tr["y"]))):
            issues.append(f"Trace '{tr['name']}' y-values differ from source data.")
    return issues


def build_chart_sources(sql_results: List[Dict[str, Any]], tool_records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Tabular data that charts may be built from: successful SQL results and tool results with a 'table'."""
    sources: Dict[str, List[Dict[str, Any]]] = {}
    for i, res in enumerate(sql_results):
        if not res.get("error") and res.get("rows"):
            sources[res.get("id", f"sql{i}")] = res["rows"]
    for i, rec in enumerate(tool_records):
        table = (rec.get("result") or {}).get("table") if not rec.get("error") else None
        if isinstance(table, list) and table and isinstance(table[0], dict):
            sources[rec.get("id", f"tool{i}")] = table
    return sources
