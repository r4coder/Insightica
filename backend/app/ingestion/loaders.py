"""Read CSV / XLSX / Parquet into a clean, typed DataFrame ready for DuckDB."""
from __future__ import annotations

import csv
import re
import uuid
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from app.ingestion.file_validation import FileValidationError

MAX_COLUMNS = 200


def read_dataset(path: Path, ext: str, max_rows: int) -> pd.DataFrame:
    try:
        if ext == ".csv":
            df = _read_csv(path, max_rows)
        elif ext == ".xlsx":
            df = pd.read_excel(path, engine="openpyxl", nrows=max_rows + 1)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        else:  # pragma: no cover - guarded by validate_extension
            raise FileValidationError("unsupported_type", f"Unsupported file type {ext}.")
    except FileValidationError:
        raise
    except Exception as exc:  # parser errors are user-facing "could not read" problems
        raise FileValidationError("unreadable", f"Could not read the file: {type(exc).__name__}.") from exc
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty or len(df.columns) == 0:
        raise FileValidationError("empty_dataset", "The file contains no data rows.")
    if len(df) > max_rows:
        raise FileValidationError("too_many_rows", f"Dataset exceeds the {max_rows:,} row limit.")
    if len(df.columns) > MAX_COLUMNS:
        raise FileValidationError("too_many_columns", f"Dataset exceeds the {MAX_COLUMNS} column limit.")
    return df.reset_index(drop=True)


def _read_csv(path: Path, max_rows: int) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=encoding, newline="") as fh:
                sample = fh.read(8192)
            try:
                sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                sep = ","
            return pd.read_csv(path, sep=sep, encoding=encoding, nrows=max_rows + 1, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise FileValidationError("unreadable", "Could not decode the CSV file.")


def normalize_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
    """snake_case, unique, SQL-friendly column names. Returns (df, [{original, name}])."""
    mapping, seen = [], set()
    for original in df.columns:
        name = re.sub(r"[^0-9a-zA-Z]+", "_", str(original).strip()).strip("_").lower() or "column"
        if name[0].isdigit():
            name = f"col_{name}"
        base, n = name, 2
        while name in seen:
            name, n = f"{base}_{n}", n + 1
        seen.add(name)
        mapping.append({"original": str(original), "name": name})
    out = df.copy()
    out.columns = [m["name"] for m in mapping]
    return out, mapping


def _is_stringy(s: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def infer_types(df: pd.DataFrame) -> pd.DataFrame:
    """Upgrade string columns that are really numbers or dates. Conservative: needs >=95% clean parse."""
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if not _is_stringy(s):
            continue
        non_null = s.dropna().astype(str).str.strip()
        if non_null.empty:
            continue
        if non_null.str.fullmatch(r"0\d+").any():  # zero-padded identifiers stay text
            continue
        numeric = pd.to_numeric(non_null.str.replace(r"[,$€£₹%\s]", "", regex=True), errors="coerce")
        if numeric.notna().mean() >= 0.95:
            cleaned = s.astype("string").str.strip().str.replace(r"[,$€£₹%\s]", "", regex=True)
            out[col] = pd.to_numeric(cleaned, errors="coerce")
            continue
        sample = non_null.head(200)
        if sample.str.contains(r"\d").mean() > 0.95 and sample.str.contains(r"[-/:.]|[A-Za-z]{3}").mean() > 0.95:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                parsed_sample = pd.to_datetime(sample, errors="coerce")
                if parsed_sample.notna().mean() >= 0.95:
                    full = pd.to_datetime(s, errors="coerce")
                    if full.notna().sum() >= 0.9 * s.notna().sum():
                        out[col] = full
    return out


def make_table_name(filename: str, dataset_id: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", Path(filename).stem.lower()).strip("_")[:32] or "dataset"
    if not stem[0].isalpha():
        stem = f"d_{stem}"
    return f"{stem}_{dataset_id.replace('-', '')[:8]}"


def new_dataset_id() -> str:
    return str(uuid.uuid4())
