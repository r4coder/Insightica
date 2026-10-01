import pytest

from app.tools.visualization_tools import ChartError, chart_series, normalize_spec, verify_chart

ROWS = [{"quarter": "2024-Q3", "revenue": 8.0, "region": "W"}, {"quarter": "2024-Q1", "revenue": 10.0, "region": "W"},
        {"quarter": "2024-Q2", "revenue": 12.0, "region": "W"}]


def spec(**kw):
    base = {"chart_type": "line", "x": "quarter", "y": "revenue", "color": "", "title": "t", "x_label": "", "y_label": "", "source": "sql0"}
    base.update(kw)
    return base


def test_line_series_sorted_by_x():
    s = chart_series(ROWS, normalize_spec(spec(), ROWS))
    assert s[0]["x"] == ["2024-Q1", "2024-Q2", "2024-Q3"] and s[0]["y"] == [10.0, 12.0, 8.0]


def test_unknown_columns_and_types_rejected():
    for bad in (spec(x="nope"), spec(y="nope"), spec(chart_type="sunburst"), spec(y="quarter")):
        with pytest.raises(ChartError):
            normalize_spec(bad, ROWS)
    with pytest.raises(ChartError):
        normalize_spec(spec(), [])


def test_pie_falls_back_to_bar_when_inappropriate():
    many = [{"c": str(i), "v": 1.0} for i in range(12)]
    n = normalize_spec({"chart_type": "pie", "x": "c", "y": "v"}, many)
    assert n["chart_type"] == "bar" and n["fallback_from"] == "pie"
    neg = [{"c": "a", "v": -1.0}, {"c": "b", "v": 2.0}]
    assert normalize_spec({"chart_type": "donut", "x": "c", "y": "v"}, neg)["chart_type"] == "bar"
    assert normalize_spec({"chart_type": "donut", "x": "c", "y": "v"}, [{"c": "a", "v": 1.0}, {"c": "b", "v": 2.0}])["chart_type"] == "donut"


def test_color_groups_and_histogram():
    rows = [{"q": "a", "v": 1.0, "g": "x"}, {"q": "b", "v": 2.0, "g": "y"}]
    s = chart_series(rows, normalize_spec({"chart_type": "bar", "x": "q", "y": "v", "color": "g"}, rows))
    assert {t["name"] for t in s} == {"x", "y"}
    h = chart_series([{"v": 1.0}, {"v": 2.0}, {"v": None}], normalize_spec({"chart_type": "histogram", "x": "v"}, [{"v": 1.0}, {"v": 2.0}]))
    assert h[0]["x"] == [1.0, 2.0]


def test_verify_chart_detects_tampered_figure():
    n = normalize_spec(spec(), ROWS)
    s = chart_series(ROWS, n)[0]
    good = {"spec": n, "figure": {"data": [{"type": "scatter", "x": s["x"], "y": s["y"]}]}}
    assert verify_chart(good, ROWS) == []
    tampered = {"spec": n, "figure": {"data": [{"type": "scatter", "x": s["x"], "y": [10.0, 12.0, 80.0]}]}}
    assert verify_chart(tampered, ROWS)
