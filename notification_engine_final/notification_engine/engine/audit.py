"""
Audit Log — in-memory store simulating PostgreSQL.
In production: write to notification_decisions table.
"""

from typing import List, Optional
from engine.models import Decision


class AuditLog:
    def __init__(self):
        self._log: List[Decision] = []

    def record(self, decision: Decision):
        self._log.append(decision)

    def get_user_history(self, user_id: str, action: Optional[str] = None, limit: int = 50) -> List[Decision]:
        results = [d for d in self._log if d.user_id == user_id]
        if action:
            results = [d for d in results if d.action == action]
        return results[-limit:]

    def get_all(self) -> List[Decision]:
        return list(self._log)

    def stats(self) -> dict:
        total = len(self._log)
        by_action = {"NOW": 0, "LATER": 0, "NEVER": 0}
        for d in self._log:
            by_action[d.action] = by_action.get(d.action, 0) + 1
        return {
            "total_evaluated": total,
            "by_action": by_action,
            "suppression_rate": round(by_action["NEVER"] / max(total, 1) * 100, 1),
            "deferred_rate": round(by_action["LATER"] / max(total, 1) * 100, 1),
        }


audit_log = AuditLog()
