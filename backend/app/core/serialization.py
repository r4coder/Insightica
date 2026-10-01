"""Convert arbitrary Python/pandas/numpy values into JSON-safe values."""
from __future__ import annotations

import datetime as dt
import decimal
import math
from typing import Any


def to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    if isinstance(value, decimal.Decimal):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    item = getattr(value, "item", None)  # numpy scalar
    if callable(item):
        try:
            return to_jsonable(item())
        except Exception:  # pragma: no cover - defensive
            pass
    isoformat = getattr(value, "isoformat", None)  # pandas Timestamp / NaT
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:  # pragma: no cover
            return None
    return str(value)
