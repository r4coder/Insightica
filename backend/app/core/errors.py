from __future__ import annotations


class AppError(Exception):
    """Domain error carrying an HTTP status and a stable machine-readable code."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
