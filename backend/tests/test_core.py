import json
import logging

from app.core.config import DEFAULT_MODEL, load_settings
from app.core.logging import JsonFormatter, redact
from app.core.serialization import to_jsonable
from app.core.sessions import SessionStore


def test_settings_defaults_and_overrides():
    s = load_settings({"GEMINI_MODEL": "", "API_KEY_SESSION_TTL_MINUTES": "5", "MAX_FILE_SIZE_MB": "abc"})
    assert s.gemini_model == DEFAULT_MODEL and s.api_key_session_ttl_minutes == 5 and s.max_file_size_mb == 50
    assert s.max_file_size_bytes == 50 * 1024 * 1024


def test_session_lifecycle_and_expiry():
    now = [1000.0]
    store = SessionStore(ttl_seconds=60, clock=lambda: now[0])
    sess = store.create("AIza-test-key", "m")
    assert store.get(sess.token).api_key == "AIza-test-key"
    assert "AIza" not in repr(sess)  # key never appears in repr/logs
    assert store.get("nope") is None and store.get(None) is None
    now[0] += 61
    assert store.get(sess.token) is None and len(store) == 0
    s2 = store.create("k", "m")
    store.delete(s2.token)
    assert store.get(s2.token) is None


def test_session_tokens_are_unique_and_do_not_contain_key():
    store = SessionStore(60)
    a, b = store.create("secretkey1", "m"), store.create("secretkey1", "m")
    assert a.token != b.token and "secretkey1" not in a.token


def test_redaction_of_api_keys_in_logs():
    key = "AIzaSyD-1234567890abcdefghijklmnopqrstu"
    assert key not in redact(f"failed with key {key}")
    assert "s3cretvalue" not in redact("api_key=s3cretvalue")
    rec = logging.LogRecord("t", logging.INFO, "f", 1, f"boom {key}", None, None)
    rec.fields = {"api_key": key, "note": f"x {key}", "n": 3}
    out = json.loads(JsonFormatter().format(rec))
    assert key not in json.dumps(out) and out["api_key"] == "[REDACTED]" and out["n"] == 3


def test_to_jsonable_handles_numpy_pandas_and_nan():
    import numpy as np
    import pandas as pd

    data = {"a": np.int64(3), "b": np.float64("nan"), "c": pd.Timestamp("2024-01-02"), "d": [np.float32(1.5)], "e": pd.NaT}
    out = to_jsonable(data)
    assert out["a"] == 3 and out["b"] is None and out["c"].startswith("2024-01-02") and out["d"] == [1.5]
    json.dumps(out)
