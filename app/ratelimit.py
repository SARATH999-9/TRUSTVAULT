"""Tiny in-process sliding-window limiter (per worker). Enough to blunt scripted sign-up/sign-in abuse;
put a real limiter in front (CDN / reverse proxy) for multi-instance deployments."""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: int) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def enforce(name: str, ip: str | None, limit: int, window_s: int) -> None:
    if not limiter.allow(f"{name}:{ip or 'unknown'}", limit, window_s):
        raise HTTPException(429, "Too many attempts. Please wait a while and try again.")
