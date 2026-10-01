"""Environment-driven settings. Infrastructure config only - the Gemini key never lives here."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_MODEL = "gemini-3.6-flash"


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    return value if value not in (None, "") else default


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(_get(env, name, str(default)))
    except ValueError:
        return default


def _valid_samesite(value: str) -> str:
    """Cookie SameSite policy: 'lax' works for same-site local dev; a split-origin deployment
    (frontend and backend on different domains, e.g. separate Render services) needs 'none',
    which browsers only honor when Secure=true - so set COOKIE_SECURE=true alongside it."""
    v = (value or "lax").strip().lower()
    return v if v in ("lax", "strict", "none") else "lax"


@dataclass(frozen=True)
class Settings:
    gemini_model: str
    database_url: str
    data_dir: Path
    duckdb_path: Path
    cors_origins: tuple
    cookie_secure: bool
    cookie_samesite: str
    api_key_session_ttl_minutes: int
    max_file_size_mb: int
    max_agent_retries: int
    max_rows_per_dataset: int
    max_analysis_steps: int
    sql_timeout_seconds: int
    sql_max_result_rows: int
    context_turns: int
    enable_llm_review: bool
    log_level: str

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    data_dir = Path(_get(env, "DATA_DIR", "./data")).resolve()
    origins = _get(env, "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return Settings(
        gemini_model=_get(env, "GEMINI_MODEL", DEFAULT_MODEL),
        database_url=_get(env, "DATABASE_URL", f"sqlite:///{data_dir / 'app.db'}"),
        data_dir=data_dir,
        duckdb_path=Path(_get(env, "DUCKDB_PATH", str(data_dir / "analytics.duckdb"))),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        cookie_secure=_get(env, "COOKIE_SECURE", "false").lower() == "true",
        cookie_samesite=_valid_samesite(_get(env, "COOKIE_SAMESITE", "lax")),
        api_key_session_ttl_minutes=_get_int(env, "API_KEY_SESSION_TTL_MINUTES", 60),
        max_file_size_mb=_get_int(env, "MAX_FILE_SIZE_MB", 50),
        max_agent_retries=_get_int(env, "MAX_AGENT_RETRIES", 3),
        max_rows_per_dataset=_get_int(env, "MAX_ROWS_PER_DATASET", 100000),
        max_analysis_steps=_get_int(env, "MAX_ANALYSIS_STEPS", 8),
        sql_timeout_seconds=_get_int(env, "SQL_TIMEOUT_SECONDS", 30),
        sql_max_result_rows=_get_int(env, "SQL_MAX_RESULT_ROWS", 500),
        context_turns=_get_int(env, "CONTEXT_TURNS", 3),
        enable_llm_review=_get(env, "ENABLE_LLM_REVIEW", "true").lower() == "true",
        log_level=_get(env, "LOG_LEVEL", "INFO").upper(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
