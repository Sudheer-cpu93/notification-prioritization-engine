"""
Rules Engine — evaluates human-configurable rules loaded from rules.json.
No code deployment needed; just update the JSON file.
"""

import json
import os
from typing import Optional, Tuple


# Built-in default rules (in production these live in DB / rules.json)
DEFAULT_RULES = [
    {
        "name": "always_send_security_alerts",
        "priority": 100,
        "conditions": [{"field": "event_type", "op": "eq", "value": "security_alert"}],
        "action": "NOW",
        "reason": "Security alerts always sent immediately"
    },
    {
        "name": "always_send_critical",
        "priority": 99,
        "conditions": [{"field": "priority_hint", "op": "eq", "value": "critical"}],
        "action": "NOW",
        "reason": "Critical priority always sent immediately"
    },
    {
        "name": "suppress_promos_low_priority",
        "priority": 50,
        "conditions": [
            {"field": "event_type", "op": "eq", "value": "promotion"},
            {"field": "priority_hint", "op": "in", "value": ["low", None]}
        ],
        "action": "NEVER",
        "reason": "Low-priority promotions suppressed to reduce noise"
    },
    {
        "name": "defer_updates_to_digest",
        "priority": 40,
        "conditions": [{"field": "event_type", "op": "eq", "value": "update"}],
        "action": "LATER",
        "reason": "Updates batched into daily digest"
    },
]


class RulesEngine:
    def __init__(self, rules_file: Optional[str] = None):
        self.rules = list(DEFAULT_RULES)
        if rules_file and os.path.exists(rules_file):
            with open(rules_file) as f:
                self.rules.extend(json.load(f))
        # Sort by priority descending
        self.rules.sort(key=lambda r: r.get("priority", 0), reverse=True)

    def evaluate(self, event) -> Optional[Tuple[str, str, str]]:
        """
        Returns (action, reason, rule_name) if a rule matches, else None.
        """
        for rule in self.rules:
            if self._matches(rule["conditions"], event):
                return rule["action"], rule["reason"], rule["name"]
        return None

    def _matches(self, conditions: list, event) -> bool:
        for cond in conditions:
            field = cond["field"]
            op = cond["op"]
            expected = cond["value"]
            actual = self._get_field(field, event)

            if op == "eq" and actual != expected:
                return False
            elif op == "in" and actual not in expected:
                return False
            elif op == "neq" and actual == expected:
                return False
        return True

    def _get_field(self, field: str, event) -> any:
        return getattr(event, field, event.metadata.get(field))

    def add_rule(self, rule: dict):
        """Dynamically add a rule (simulates DB update)."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.get("priority", 0), reverse=True)
        return rule
