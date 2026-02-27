"""
AI Scorer — calls an LLM for contextual scoring.
Falls back to deterministic scorer if AI is unavailable or slow.
Circuit breaker pattern included.
"""

import time
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScoreResult:
    score: float
    action: str
    reason: str
    ai_used: bool
    fallback_mode: bool = False


class CircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=30):
        self.failures = 0
        self.state = "CLOSED"
        self.last_failure_time = None
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout

    def can_attempt(self) -> bool:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "HALF-OPEN"
                return True
            return False
        return True

    def record_success(self):
        self.failures = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"

    @property
    def status(self):
        return self.state


class DeterministicScorer:
    """Fallback scorer — no AI required."""

    PRIORITY_SCORES = {
        "critical": 0.95,
        "high":     0.78,
        "medium":   0.52,
        "low":      0.22,
    }

    CHANNEL_WEIGHTS = {
        "push":   1.0,
        "sms":    0.9,
        "email":  0.7,
        "in_app": 0.5,
    }

    def score(self, event, recent_count=0, is_quiet_hours=False) -> ScoreResult:
        base = self.PRIORITY_SCORES.get(event.priority_hint, 0.40)
        recency_penalty = min(recent_count * 0.08, 0.25)
        base -= recency_penalty

        if event.expires_at:
            try:
                exp = datetime.fromisoformat(event.expires_at.replace("Z", "+00:00"))
                mins = (exp - datetime.now(exp.tzinfo)).total_seconds() / 60
                if mins < 10:
                    base += 0.30
                elif mins < 60:
                    base += 0.10
            except Exception:
                pass

        if is_quiet_hours:
            base -= 0.20

        base *= self.CHANNEL_WEIGHTS.get(event.channel, 0.7)
        score = round(max(0.0, min(1.0, base)), 3)

        if score >= 0.75:
            action, reason = "NOW", f"Score {score:.2f} — high priority, sending immediately"
        elif score >= 0.35:
            action, reason = "LATER", f"Score {score:.2f} — medium priority, deferred"
        else:
            action, reason = "NEVER", f"Score {score:.2f} — low value, suppressed"

        return ScoreResult(score=score, action=action, reason=reason, ai_used=False, fallback_mode=True)


class AIScorer:
    """
    Simulates AI scoring. Replace _call_ai() with real OpenAI/LLM call in production.
    Toggle AI_AVAILABLE=False to demo fallback path.
    """
    AI_AVAILABLE = True

    def __init__(self):
        self.circuit_breaker = CircuitBreaker()
        self.fallback = DeterministicScorer()

    def score(self, event, recent_count=0, is_quiet_hours=False) -> ScoreResult:
        if not self.circuit_breaker.can_attempt() or not self.AI_AVAILABLE:
            return self._fallback(event, recent_count, is_quiet_hours, "AI circuit breaker OPEN")
        try:
            result = self._call_ai(event, recent_count, is_quiet_hours)
            self.circuit_breaker.record_success()
            return result
        except Exception as e:
            self.circuit_breaker.record_failure()
            return self._fallback(event, recent_count, is_quiet_hours, str(e))

    def _call_ai(self, event, recent_count, is_quiet_hours) -> ScoreResult:
        """
        Simulated AI. In production replace with:
            openai.chat.completions.create(model="gpt-4o-mini", messages=[...], timeout=1.5)
        """
        type_scores = {
            "message": 0.70, "security_alert": 0.95, "alert": 0.85,
            "reminder": 0.55, "update": 0.40, "promotion": 0.20, "system_event": 0.60,
        }
        score = type_scores.get(event.event_type, 0.50)
        reasons = [f"event_type='{event.event_type}'"]

        if event.priority_hint == "critical":
            score = max(score, 0.93); reasons.append("critical priority")
        elif event.priority_hint == "high":
            score = max(score, 0.78)
        elif event.priority_hint == "low":
            score = min(score, 0.35)

        if recent_count > 3:
            score -= 0.12 * (recent_count - 3)
            reasons.append(f"{recent_count} recent similar events")

        if is_quiet_hours and event.priority_hint not in ("critical", "high"):
            score -= 0.18; reasons.append("quiet hours")

        score = round(max(0.0, min(1.0, score)), 3)
        action = "NOW" if score >= 0.75 else "LATER" if score >= 0.35 else "NEVER"

        return ScoreResult(
            score=score, action=action,
            reason=f"[AI] Score {score:.2f}: {', '.join(reasons)}",
            ai_used=True, fallback_mode=False
        )

    def _fallback(self, event, recent_count, is_quiet_hours, reason="") -> ScoreResult:
        result = self.fallback.score(event, recent_count, is_quiet_hours)
        result.reason = f"[FALLBACK] {reason} — {result.reason}"
        return result
