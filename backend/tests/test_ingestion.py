import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from app.ingestion.file_validation import FileValidationError, sanitize_filename, validate_upload
from app.ingestion.loaders import infer_types, make_table_name, normalize_columns, read_dataset
from app.ingestion.profiler import build_schema_context, profile_dataframe

MB = 1024 * 1024


def test_sanitize_filename_strips_paths_and_unsafe_chars():
    assert sanitize_filename("../../etc/passwd.csv") == "passwd.csv"
    assert sanitize_filename("C:\\temp\\my sales (v2).csv") == "my sales _v2_.csv"
    with pytest.raises(FileValidationError):
        sanitize_filename("   ")


def test_validate_upload_rules():
    assert validate_upload("a.csv", 10, b"a,b\n1,2", MB) == ("a.csv", ".csv")
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.exe", 10, b"MZ", MB)
    assert e.value.code == "unsupported_type"
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.csv", 2 * MB, b"a,b", MB)
    assert e.value.code == "file_too_large"
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.xlsx", 10, b"not a zip", MB)
    assert e.value.code == "content_mismatch"
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.parquet", 10, b"nope", MB)
    assert e.value.code == "content_mismatch"
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.csv", 10, b"PK\x03\x04zipdata", MB)
    assert e.value.code == "content_mismatch"
    with pytest.raises(FileValidationError) as e:
        validate_upload("a.csv", 0, b"", MB)
    assert e.value.code == "empty_file"


def test_normalize_columns_unique_and_sql_friendly():
    df = pd.DataFrame([[1, 2, 3, 4]], columns=["Order Date", "order_date", "2024 Sales", "Unit Price ($)"])
    out, mapping = normalize_columns(df)
    assert list(out.columns) == ["order_date", "order_date_2", "col_2024_sales", "unit_price"]
    assert mapping[0] == {"original": "Order Date", "name": "order_date"}


def test_infer_types_numbers_and_dates_but_not_padded_ids():
    df = pd.DataFrame({
        "amount": ["$1,200.50", "300", "45.5", "10", "20"],
        "day": ["2024-01-05", "2024-02-11", "2024-03-01", "2024-03-09", "2024-04-30"],
        "zip": ["01234", "02345", "03456", "04567", "05678"],
        "name": ["a", "b", "c", "d", "e"],
    })
    out = infer_types(df)
    assert pd.api.types.is_numeric_dtype(out["amount"]) and out["amount"].iloc[0] == 1200.5
    assert pd.api.types.is_datetime64_any_dtype(out["day"])
    assert not pd.api.types.is_numeric_dtype(out["zip"])
    assert not pd.api.types.is_numeric_dtype(out["name"])


def test_read_csv_and_row_limit_and_profile_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x.csv"
        pd.DataFrame({
            "Order ID": range(1, 121), "Order Date": pd.date_range("2024-01-01", periods=120).strftime("%Y-%m-%d"),
            "Region": ["N", "S", "E", "W"] * 30, "Revenue": [float(i) for i in range(120)],
        }).to_csv(path, index=False)
        df = read_dataset(path, ".csv", max_rows=1000)
        df, _ = normalize_columns(df)
        df = infer_types(df)
        prof = profile_dataframe(df)
        roles = {c["name"]: c["role"] for c in prof["columns"]}
        assert roles == {"order_id": "id", "order_date": "date", "region": "categorical", "revenue": "numeric"}
        assert prof["rows"] == 120 and prof["date_columns"] == ["order_date"]
        rev = next(c for c in prof["columns"] if c["name"] == "revenue")
        assert rev["min"] == 0.0 and rev["max"] == 119.0 and rev["missing"] == 0
        with pytest.raises(FileValidationError) as e:
            read_dataset(path, ".csv", max_rows=50)
        assert e.value.code == "too_many_rows"
        ctx = build_schema_context("x_1234", [{"name": "region", "type": "VARCHAR"}, {"name": "revenue", "type": "DOUBLE"}], prof)
        assert "x_1234" in ctx and "revenue | DOUBLE | numeric" in ctx and "N, S, E, W" in ctx


def test_read_xlsx_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x.xlsx"
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(path, index=False)
        df = read_dataset(path, ".xlsx", max_rows=100)
        assert len(df) == 3 and list(df.columns) == ["a", "b"]


def test_unreadable_and_empty_files_rejected():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "bad.xlsx"
        path.write_bytes(b"PK\x03\x04garbage")
        with pytest.raises(FileValidationError) as e:
            read_dataset(path, ".xlsx", 100)
        assert e.value.code == "unreadable"
        empty = Path(d) / "e.csv"
        empty.write_text("a,b\n")
        with pytest.raises(FileValidationError):
            read_dataset(empty, ".csv", 100)


def test_table_name_is_safe():
    name = make_table_name("My Sales (2024)!.csv", "abcd1234-0000-0000-0000-000000000000")
    assert name == "my_sales_2024_abcd1234"
    assert make_table_name("123.csv", "abcd1234-x").startswith("d_123_")
