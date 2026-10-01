from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:
    """Tiny in-process sliding-window limiter (protects the key-validation endpoints from being used as a key oracle)."""

    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls, self.window = max_calls, window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            return True
