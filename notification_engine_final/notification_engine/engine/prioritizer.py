"""
Core Prioritization Engine — orchestrates all components.
"""

from engine.models import NotificationEvent, Decision
from engine.store import DedupChecker, FrequencyChecker, store
from engine.rules import RulesEngine
from engine.scorer import AIScorer
from engine.audit import audit_log


class PrioritizationEngine:
    def __init__(self):
        self.dedup = DedupChecker()
        self.frequency = FrequencyChecker()
        self.rules = RulesEngine()
        self.scorer = AIScorer()

    def evaluate(self, event: NotificationEvent) -> Decision:
        print(f"\n{'='*55}")
        print(f"  EVENT: [{event.event_type.upper()}] '{event.title or event.message or '(no title)'}'")
        print(f"  User: {event.user_id} | Channel: {event.channel} | Priority: {event.priority_hint or 'none'}")
        print(f"{'='*55}")

        # ── STEP 1: Expiry Check ──────────────────────────────
        if event.is_expired():
            return self._decide(event, "NEVER", 0.0, "Event expired before processing", None, False, False)

        # ── STEP 2: Duplicate Check ───────────────────────────
        dedup_reason = self.dedup.check(event)
        if dedup_reason:
            return self._decide(event, "NEVER", 0.0, dedup_reason, "dedup_check", False, False)

        # ── STEP 3: Hard Rules ────────────────────────────────
        rule_result = self.rules.evaluate(event)
        if rule_result:
            rule_action, rule_reason, rule_name = rule_result
            # Hard NOW rules (security, critical) bypass further checks
            if rule_action == "NOW":
                return self._decide(event, "NOW", 1.0, rule_reason, rule_name, False, False)
            # Hard NEVER rules suppress immediately
            if rule_action == "NEVER":
                return self._decide(event, "NEVER", 0.0, rule_reason, rule_name, False, False)
            # LATER rules noted but still go through AI for final score

        # ── STEP 4: Fatigue / Frequency Checks ───────────────
        freq_reason = self.frequency.check_frequency(event)
        daily_reason = self.frequency.check_daily_cap(event)

        # High priority events are NOT suppressed by fatigue — only deferred
        is_high_priority = event.priority_hint in ("critical", "high")

        if freq_reason and not is_high_priority:
            if event.event_type in ("promotion", "system_event"):
                return self._decide(event, "NEVER", 0.1, freq_reason, "frequency_cap", False, False)
            else:
                return self._decide(event, "LATER", 0.3, freq_reason + " — batched to digest", "frequency_cap", False, False)

        if daily_reason and not is_high_priority:
            return self._decide(event, "LATER", 0.3, daily_reason + " — batched to digest", "daily_cap", False, False)

        # ── STEP 5: AI Scoring ────────────────────────────────
        recent_count = store.get_count(f"freq:{event.user_id}:{event.event_type}")
        is_quiet = event.metadata.get("quiet_hours", False)

        score_result = self.scorer.score(event, recent_count, is_quiet)
        ai_used = score_result.ai_used
        fallback = score_result.fallback_mode

        # ── STEP 6: Merge — rule hint can bump LATER → LATER ──
        final_action = score_result.action
        final_reason = score_result.reason

        # If a rule suggested LATER, don't let AI send it NOW unless critical
        if rule_result and rule_result[0] == "LATER" and final_action == "NOW" and not is_high_priority:
            final_action = "LATER"
            final_reason = f"{rule_result[1]} (overrides AI NOW suggestion)"

        return self._decide(event, final_action, score_result.score, final_reason,
                            rule_result[2] if rule_result else None, ai_used, fallback)

    def _decide(self, event, action, score, reason, rule_matched, ai_used, fallback_mode) -> Decision:
        # Safety net: critical/high are NEVER suppressed
        if action == "NEVER" and event.priority_hint in ("critical", "high"):
            action = "NOW"
            reason = f"[SAFETY NET] High-priority event cannot be suppressed. Original: {reason}"
            score = 0.9

        decision = Decision(
            event_id=event.id,
            user_id=event.user_id,
            action=action,
            score=score,
            reason=reason,
            rule_matched=rule_matched,
            ai_used=ai_used,
            fallback_mode=fallback_mode,
        )

        # Print result
        icons = {"NOW": "✅ NOW", "LATER": "⏰ LATER", "NEVER": "🚫 NEVER"}
        print(f"  Decision : {icons.get(action, action)}")
        print(f"  Score    : {score:.3f}")
        print(f"  Reason   : {reason}")
        if rule_matched:
            print(f"  Rule     : {rule_matched}")
        if fallback_mode:
            print(f"  ⚠️  FALLBACK MODE (AI unavailable)")

        audit_log.record(decision)
        return decision
