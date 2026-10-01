from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict

from app.core.config import Settings


@dataclass
class DatasetContext:
    dataset_id: str
    name: str
    table: str
    schema_text: str
    columns: Dict[str, str]  # column name -> role
    profile: Dict[str, Any]


@dataclass
class AgentDeps:
    gemini: Any  # GeminiService (or a test double with the same interface)
    engine: Any  # DuckDBEngine
    settings: Settings
    dataset: DatasetContext
    on_progress: Callable[[Dict[str, Any]], None] = field(default=lambda event: None)
