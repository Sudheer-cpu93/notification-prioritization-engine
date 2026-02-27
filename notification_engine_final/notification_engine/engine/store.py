"""
In-memory store simulating Redis behavior.
In production: swap this with redis-py calls.
"""

import time
import hashlib
import re
from typing import Optional
from collections import defaultdict


class InMemoryStore:
    def __init__(self):
        self._store: dict = {}          # key -> (value, expire_at)
        self._counters: dict = {}       # key -> (count, expire_at)
        self._lists: dict = defaultdict(list)

    def _is_expired(self, expire_at: Optional[float]) -> bool:
        return expire_at is not None and time.time() > expire_at

    def set_nx(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Set only if not exists. Returns True if set, False if key existed."""
        entry = self._store.get(key)
        if entry and not self._is_expired(entry[1]):
            return False
        self._store[key] = (value, time.time() + ttl_seconds)
        return True

    def get(self, key: str) -> Optional[str]:
        entry = self._store.get(key)
        if entry and not self._is_expired(entry[1]):
            return entry[0]
        return None

    def incr(self, key: str, ttl_seconds: int) -> int:
        """Increment counter. Sets TTL only on first increment."""
        entry = self._counters.get(key)
        if not entry or self._is_expired(entry[1]):
            self._counters[key] = (1, time.time() + ttl_seconds)
            return 1
        count = entry[0] + 1
        self._counters[key] = (count, entry[1])
        return count

    def get_count(self, key: str) -> int:
        entry = self._counters.get(key)
        if entry and not self._is_expired(entry[1]):
            return entry[0]
        return 0

    def push_list(self, key: str, value: str):
        self._lists[key].append(value)

    def get_list(self, key: str) -> list:
        return self._lists.get(key, [])


# Singleton store
store = InMemoryStore()


class DedupChecker:
    EXACT_TTL = 86400   # 24 hours
    NEAR_TTL = 3600     # 1 hour

    @staticmethod
    def _fingerprint(event) -> str:
        text = f"{event.event_type}:{event.title or ''}:{event.message or ''}"
        normalized = re.sub(r'[^\w\s]', '', text.lower().strip())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def check(self, event) -> Optional[str]:
        # Layer 1: Exact dedup via dedupe_key
        if event.dedupe_key:
            key = f"dedup:{event.user_id}:{event.dedupe_key}"
            set_ok = store.set_nx(key, event.id, self.EXACT_TTL)
            if not set_ok:
                return f"Exact duplicate — dedupe_key '{event.dedupe_key}' already seen in last 24h"

        # Layer 2: Near-dedup via content fingerprint
        fp = self._fingerprint(event)
        key = f"fingerprint:{event.user_id}:{fp}"
        set_ok = store.set_nx(key, event.id, self.NEAR_TTL)
        if not set_ok:
            return f"Near-duplicate detected — very similar content sent in last 1h"

        return None  # No duplicate


class FrequencyChecker:
    CAPS = {
        "promotion":    {"max": 2,  "window": 3600},
        "update":       {"max": 5,  "window": 3600},
        "reminder":     {"max": 3,  "window": 3600},
        "message":      {"max": 20, "window": 3600},
        "system_event": {"max": 10, "window": 3600},
        "alert":        {"max": 10, "window": 3600},
        "default":      {"max": 8,  "window": 3600},
    }

    DAILY_CHANNEL_CAPS = {
        "push":   20,
        "sms":    5,
        "email":  10,
        "in_app": 50,
    }

    def check_frequency(self, event) -> Optional[str]:
        cap = self.CAPS.get(event.event_type, self.CAPS["default"])
        key = f"freq:{event.user_id}:{event.event_type}"
        count = store.incr(key, cap["window"])
        if count > cap["max"]:
            return f"Frequency cap exceeded ({count}/{cap['max']} '{event.event_type}' events in last hour)"
        return None

    def check_daily_cap(self, event) -> Optional[str]:
        from datetime import date
        cap = self.DAILY_CHANNEL_CAPS.get(event.channel, 20)
        today = date.today().isoformat()
        key = f"daily_cap:{event.user_id}:{event.channel}:{today}"
        count = store.incr(key, 86400)
        if count > cap:
            return f"Daily {event.channel} cap reached ({count}/{cap})"
        return None
