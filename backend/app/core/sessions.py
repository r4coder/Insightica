"""Temporary, in-memory, server-side Gemini sessions.

The API key is held only in this process's memory, keyed by an opaque random token.
The browser receives the token in an HttpOnly cookie - never the key. Sessions have an
absolute TTL and are never written to disk or the database.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass
class GeminiSession:
    token: str
    api_key: str = field(repr=False)
    model: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0


class SessionStore:
    def __init__(self, ttl_seconds: int, clock: Callable[[], float] = time.time):
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._sessions: Dict[str, GeminiSession] = {}
        self._lock = threading.Lock()

    def create(self, api_key: str, model: str) -> GeminiSession:
        now = self._clock()
        session = GeminiSession(
            token=secrets.token_urlsafe(32),
            api_key=api_key,
            model=model,
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        with self._lock:
            self._purge_locked(now)
            self._sessions[session.token] = session
        return session

    def get(self, token: Optional[str]) -> Optional[GeminiSession]:
        if not token:
            return None
        now = self._clock()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.expires_at <= now:
                del self._sessions[token]
                return None
            return session

    def delete(self, token: Optional[str]) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_locked(self._clock())

    def _purge_locked(self, now: float) -> int:
        expired = [t for t, s in self._sessions.items() if s.expires_at <= now]
        for token in expired:
            del self._sessions[token]
        return len(expired)

    def __len__(self) -> int:
        return len(self._sessions)
