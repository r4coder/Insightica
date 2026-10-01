import pandas as pd
import pytest

from app.tools import statistics_tools as st
from app.tools.pandas_tools import AnalystToolkit
from app.tools.statistics_tools import ToolError


def make_df():
    dates = pd.to_datetime(["2024-01-15", "2024-02-10", "2024-04-05", "2024-05-05", "2024-07-01", "2024-08-20", "2024-08-21"])
    return pd.DataFrame({
        "order_date": dates,
        "region": ["W", "E", "W", "E", "W", "E", "E"],
        "revenue": [100.0, 50.0, 100.0, 60.0, 40.0, 60.0, 40.0],
    })


def test_percentage_change_basic_and_zero_baseline():
    assert st.percentage_change(200, 150)["pct_change"] == -25.0
    assert st.percentage_change(0, 5)["pct_change"] is None
    with pytest.raises(ToolError):
        st.percentage_change(float("nan"), 1)


def test_time_series_quarterly_totals_and_change():
    out = st.time_series_analysis(make_df(), "revenue", "order_date", "quarter", "sum")
    values = {r["period"]: r["value"] for r in out["table"]}
    assert values == {"2024-Q1": 150.0, "2024-Q2": 160.0, "2024-Q3": 140.0}
    q3 = out["table"][2]
    assert q3["pct_change_vs_prev"] == round((140 - 160) / 160 * 100, 6)
    assert out["overall"]["worst_period"] == "2024-Q3"


def test_contribution_analysis_sums_to_total_change():
    out = st.contribution_analysis(make_df(), "revenue", "region", "order_date", "quarter", "2024-Q2", "2024-Q3")
    assert out["total"]["delta"] == -20.0
    assert sum(r["delta"] for r in out["table"]) == pytest.approx(-20.0)
    west = next(r for r in out["table"] if r["dimension_value"] == "W")
    assert west["delta"] == -60.0 and west["pct_change"] == -60.0
    assert out["table"][0]["dimension_value"] == "W"  # biggest negative contributor first
    with pytest.raises(ToolError):
        st.contribution_analysis(make_df(), "revenue", "region", "order_date", "quarter", "2023-Q1", "2024-Q3")


def test_group_by_shares_add_to_100():
    out = st.group_by_analysis(make_df(), "revenue", "region", "sum")
    assert sum(r["share_pct"] for r in out["table"]) == pytest.approx(100.0, abs=1e-3)
    assert out["table"][0]["dimension_value"] in ("W", "E")


def test_outliers_iqr_detects_extreme_value():
    s = pd.Series([10, 11, 9, 10, 12, 11, 10, 500.0])
    out = st.detect_outliers(s, "x")
    assert out["outlier_count"] == 1 and out["extreme_values"][0] == 500.0
    with pytest.raises(ToolError):
        st.detect_outliers(pd.Series([1, 2]), "x")


def test_correlation_perfect_and_strength():
    a = pd.Series([1, 2, 3, 4, 5.0])
    out = st.correlation(a, a * 2, "a", "b")
    assert out["correlation"] == 1.0 and out["strength"] == "very strong"


def test_describe_series_numeric_and_categorical():
    num = st.describe_series(pd.Series([1.0, 2.0, 3.0, None]), "n")
    assert num["kind"] == "numeric" and num["missing"] == 1 and num["mean"] == 2.0
    cat = st.describe_series(pd.Series(["a", "a", "b"]), "c")
    assert cat["kind"] == "categorical" and cat["top_values"][0] == {"value": "a", "count": 2}


def test_toolkit_validates_columns_and_records_errors():
    df = make_df()
    tk = AnalystToolkit(
        {"order_date": "date", "region": "categorical", "revenue": "numeric"},
        lambda cols: df[cols].copy(),
    )
    rec = tk.timed_call("time_series_analysis", metric="revenue", date_column="order_date", freq="quarter")
    assert rec["error"] is None and rec["result"]["overall"]["n_periods"] == 3
    bad = tk.timed_call("group_by_analysis", metric="revnue", dimension="region")
    assert bad["error"] and "Available columns" in bad["error"]
    wrong_role = tk.timed_call("time_series_analysis", metric="revenue", date_column="region")
    assert wrong_role["error"]
    assert "Unknown tool" in tk.timed_call("nope")["error"]
