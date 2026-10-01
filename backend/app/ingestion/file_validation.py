"""Upload validation: extension allowlist, size limit, magic-byte sniffing, filename sanitisation."""
from __future__ import annotations

import os
import re
from typing import Tuple

ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".parquet")


class FileValidationError(ValueError):
    """Raised for uploads we refuse to process. `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def sanitize_filename(name: str) -> str:
    """Strip any path components and unsafe characters. The result is for display only -
    files are stored under server-generated names, never a user-supplied one."""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._\- ]", "_", base)
    base = re.sub(r"\.{2,}", ".", base).lstrip(".").strip()
    if not base:
        raise FileValidationError("invalid_filename", "The file name is empty or invalid.")
    return base[:120]


def validate_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError("unsupported_type", f"Unsupported file type '{ext or 'none'}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}.")
    return ext


def validate_size(size_bytes: int, max_bytes: int) -> None:
    if size_bytes <= 0:
        raise FileValidationError("empty_file", "The file is empty.")
    if size_bytes > max_bytes:
        raise FileValidationError("file_too_large", f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")


def validate_content(ext: str, head: bytes) -> None:
    """Check that the leading bytes are consistent with the claimed extension."""
    if ext == ".xlsx" and not head.startswith(b"PK\x03\x04"):
        raise FileValidationError("content_mismatch", "The file is not a valid .xlsx workbook.")
    if ext == ".parquet" and not head.startswith(b"PAR1"):
        raise FileValidationError("content_mismatch", "The file is not a valid Parquet file.")
    if ext == ".csv":
        if b"\x00" in head:
            raise FileValidationError("content_mismatch", "The file does not look like a text CSV.")
        if head.startswith((b"PK\x03\x04", b"PAR1", b"MZ", b"\x7fELF", b"%PDF")):
            raise FileValidationError("content_mismatch", "The file content does not match a CSV.")


def validate_upload(filename: str, size_bytes: int, head: bytes, max_bytes: int) -> Tuple[str, str]:
    """Return (safe_display_name, extension) or raise FileValidationError."""
    safe = sanitize_filename(filename)
    ext = validate_extension(safe)
    validate_size(size_bytes, max_bytes)
    validate_content(ext, head)
    return safe, ext
