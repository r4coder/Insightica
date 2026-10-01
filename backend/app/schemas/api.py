from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TestGeminiRequest(BaseModel):
    api_key: Optional[str] = Field(default=None, max_length=512, description="Key to test; omit to test the current session.")


class SessionRequest(BaseModel):
    api_key: str = Field(min_length=10, max_length=512)


class AnalysisRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=3, max_length=1000)
    session_id: Optional[str] = Field(default=None, max_length=64)
