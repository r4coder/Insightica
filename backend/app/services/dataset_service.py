"""Dataset ingestion pipeline: validate -> read -> clean/type -> profile -> load into DuckDB -> store metadata."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import log_event, timed
from app.ingestion.file_validation import FileValidationError, sanitize_filename, validate_extension, validate_upload
from app.ingestion.loaders import infer_types, make_table_name, new_dataset_id, normalize_columns, read_dataset
from app.ingestion.profiler import build_schema_context, profile_dataframe
from app.models.orm import Dataset, DatasetProfile
from app.orchestration.deps import DatasetContext

logger = logging.getLogger("datasets")
_STATUS = {"unsupported_type": 415, "file_too_large": 413, "too_many_rows": 413}
CHUNK = 1024 * 1024


def _file_error(exc: FileValidationError) -> AppError:
    return AppError(_STATUS.get(exc.code, 422), exc.code, exc.message)


def dataset_to_dict(d: Dataset) -> Dict[str, Any]:
    return {"id": d.id, "name": d.name, "file_type": d.file_type, "row_count": d.row_count, "column_count": d.column_count,
            "size_bytes": d.size_bytes, "columns": d.columns, "created_at": d.created_at.isoformat()}


class DatasetService:
    def __init__(self, settings: Settings, engine: Any):
        self.settings, self.engine = settings, engine

    def upload(self, db: Session, filename: str, stream: BinaryIO) -> Dataset:
        s = self.settings
        try:
            safe_name = sanitize_filename(filename)
            ext = validate_extension(safe_name)
        except FileValidationError as exc:
            raise _file_error(exc) from None
        s.upload_dir.mkdir(parents=True, exist_ok=True)
        tmp = s.upload_dir / f"{uuid.uuid4().hex}{ext}.part"  # server-generated name: user input never touches the path
        try:
            size, head = 0, b""
            with open(tmp, "wb") as out:
                while chunk := stream.read(CHUNK):
                    if not head:
                        head = chunk[:16]
                    size += len(chunk)
                    if size > s.max_file_size_bytes:
                        raise FileValidationError("file_too_large", f"File exceeds the {s.max_file_size_mb} MB limit.")
                    out.write(chunk)
            validate_upload(safe_name, size, head, s.max_file_size_bytes)
            with timed() as t:
                df = read_dataset(tmp, ext, s.max_rows_per_dataset)
                df, mapping = normalize_columns(df)
                df = infer_types(df)
                profile = profile_dataframe(df)
            dataset_id = new_dataset_id()
            table = make_table_name(safe_name, dataset_id)
            self.engine.load_dataframe(table, df)
            schema = self.engine.table_schema(table)
        except FileValidationError as exc:
            raise _file_error(exc) from None
        finally:
            shutil.rmtree(tmp, ignore_errors=True) if tmp.is_dir() else tmp.unlink(missing_ok=True)

        types = {c["name"]: c["type"] for c in schema}
        roles = {c["name"]: c for c in profile["columns"]}
        originals = {m["name"]: m["original"] for m in mapping}
        columns = [{"name": n, "original_name": originals.get(n, n), "duckdb_type": types.get(n, ""), "dtype": roles[n]["dtype"], "role": roles[n]["role"]}
                   for n in df.columns]
        dataset = Dataset(id=dataset_id, name=safe_name, file_type=ext.lstrip("."), table_name=table, row_count=len(df),
                          column_count=len(df.columns), size_bytes=size, columns=columns)
        dataset.profile = DatasetProfile(profile=profile)
        db.add(dataset)
        db.commit()
        log_event(logger, "dataset_uploaded", dataset_id=dataset_id, rows=len(df), columns=len(df.columns), size_bytes=size, ingest_ms=t["ms"])
        return dataset

    def get(self, db: Session, dataset_id: str) -> Dataset:
        dataset = db.get(Dataset, dataset_id)
        if dataset is None:
            raise AppError(404, "dataset_not_found", "Dataset not found.")
        return dataset

    def list(self, db: Session) -> List[Dataset]:
        return list(db.scalars(select(Dataset).order_by(Dataset.created_at.desc())))

    def delete(self, db: Session, dataset_id: str) -> None:
        dataset = self.get(db, dataset_id)
        self.engine.drop_table(dataset.table_name)
        db.delete(dataset)
        db.commit()
        log_event(logger, "dataset_deleted", dataset_id=dataset_id)

    def context(self, db: Session, dataset_id: str) -> DatasetContext:
        d = self.get(db, dataset_id)
        if not self.engine.table_exists(d.table_name):
            raise AppError(410, "dataset_data_missing", "The dataset's analytical data is no longer available. Please upload it again.")
        profile = d.profile.profile
        schema = self.engine.table_schema(d.table_name)
        return DatasetContext(d.id, d.name, d.table_name, build_schema_context(d.table_name, schema, profile),
                              {c["name"]: c["role"] for c in profile["columns"]}, profile)
