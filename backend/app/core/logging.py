"""Structured JSON logging with secret redaction and per-request/analysis context."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

request_id_var: contextvars.ContextVar = contextvars.ContextVar("request_id", default=None)
analysis_id_var: contextvars.ContextVar = contextvars.ContextVar("analysis_id", default=None)
agent_var: contextvars.ContextVar = contextvars.ContextVar("agent", default=None)

_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|x-goog-api-key|authorization|token)([\"']?\s*[:=]\s*[\"']?)([^\s\"',}]{6,})"),
]
_DROP_FIELDS = {"api_key", "apikey", "key", "token", "authorization", "password", "secret"}


def redact(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    return _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in _DROP_FIELDS else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "event": redact(record.getMessage()),
        }
        for name, var in (("request_id", request_id_var), ("analysis_id", analysis_id_var), ("agent", agent_var)):
            value = var.get()
            if value:
                payload[name] = value
        payload.update(_clean(getattr(record, "fields", {})))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"fields": fields})


@contextmanager
def timed() -> Iterator[dict]:
    """Yields a dict whose 'ms' entry is filled in when the block exits."""
    box: dict = {"ms": 0.0}
    start = time.perf_counter()
    try:
        yield box
    finally:
        box["ms"] = round((time.perf_counter() - start) * 1000, 1)
