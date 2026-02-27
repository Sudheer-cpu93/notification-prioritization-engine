#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║     Notification Prioritization Engine — Live Demo       ║
║                  Cyepro Solutions                        ║
╚══════════════════════════════════════════════════════════╝

Run: python demo.py
"""

import sys
import time
import os

sys.path.insert(0, os.path.dirname(__file__))

from engine.models import NotificationEvent
from engine.prioritizer import PrioritizationEngine
from engine.audit import audit_log
from engine.scorer import AIScorer

CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RED   = "\033[91m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"

def banner(text):
    print(f"\n{CYAN}{BOLD}{'─'*55}")
    print(f"  {text}")
    print(f"{'─'*55}{RESET}")

def pause(msg="Press ENTER to continue..."):
    input(f"\n{DIM}{msg}{RESET}")

def main():
    engine = PrioritizationEngine()

    print(f"""
{CYAN}{BOLD}
╔══════════════════════════════════════════════════════════╗
║     Notification Prioritization Engine — Live Demo       ║
╚══════════════════════════════════════════════════════════╝{RESET}

This demo walks through 8 real scenarios covering:
  ✅  NOW   — Immediate dispatch
  ⏰  LATER — Deferred / batched
  🚫  NEVER — Suppressed

Each scenario shows WHY the decision was made.
""")
    pause("Press ENTER to start the demo...")

    # ─────────────────────────────────────────────
    banner("SCENARIO 1 — Security Alert (Hard Rule: Always NOW)")
    print("A login was detected from a new device. This is a security event.")
    print("Expected: Hard rule fires → NOW, regardless of anything else.\n")
    pause()
    engine.evaluate(NotificationEvent(
        user_id="user_001",
        event_type="security_alert",
        title="New login from Mumbai, India",
        message="Your account was accessed from a new device.",
        source="auth_service",
        priority_hint="critical",
        channel="push",
    ))

    # ─────────────────────────────────────────────
    banner("SCENARIO 2 — Promotional Notification (Suppressed)")
    print("A promotional 'weekend sale' push notification.")
    print("Expected: Matches 'suppress_promos_low_priority' rule → NEVER.\n")
    pause()
    engine.evaluate(NotificationEvent(
        user_id="user_001",
        event_type="promotion",
        title="Weekend Sale — 30% off!",
        message="Hurry, sale ends Sunday.",
        source="marketing_service",
        priority_hint="low",
        channel="push",
    ))

    # ─────────────────────────────────────────────
    banner("SCENARIO 3 — Direct Message (AI Scoring → NOW)")
    print("A user receives a direct message from another user.")
    print("Expected: AI scores it high → NOW.\n")
    pause()
    engine.evaluate(NotificationEvent(
        user_id="user_002",
        event_type="message",
        title="Sarah: Hey, are you free tomorrow?",
        message="Sarah sent you a message.",
        source="messaging_service",
        priority_hint="medium",
        channel="push",
        dedupe_key="msg_sarah_001",
    ))

    # ─────────────────────────────────────────────
    banner("SCENARIO 4 — Exact Duplicate Prevention")
    print("Same message event fires again (producer retry / bug).")
    print("Expected: Redis dedup catches it → NEVER (duplicate).\n")
    pause()
    engine.evaluate(NotificationEvent(
        user_id="user_002",
        event_type="message",
        title="Sarah: Hey, are you free tomorrow?",
        message="Sarah sent you a message.",
        source="messaging_service",
        priority_hint="medium",
        channel="push",
        dedupe_key="msg_sarah_001",  # same key!
    ))

    # ─────────────────────────────────────────────
    banner("SCENARIO 5 — Near-Duplicate Prevention")
    print("Slightly rephrased version of the same message (different service).")
    print("Expected: Content fingerprint matches → NEVER (near-duplicate).\n")
    pause()
    engine.evaluate(NotificationEvent(
        user_id="user_002",
        event_type="message",
        title="Sarah Hey are you free tomorrow",  # slight variation, no punctuation
        message="Sarah sent you a message",
        source="messaging_service_v2",
        priority_hint="medium",
        channel="push",
        # No dedupe_key — will use fingerprint
    ))

    # ─────────────────────────────────────────────
    banner("SCENARIO 6 — Alert Fatigue: Frequency Cap Hit")
    print("Simulating a user bombarded with 'update' notifications.")
    print("Expected: First few go through, then capped → LATER (digest).\n")
    pause()
    for i in range(1, 8):
        print(f"\n  [Sending update #{i}]")
        engine.evaluate(NotificationEvent(
            user_id="user_003",
            event_type="update",
            title=f"App updated to version 2.{i}",
            message=f"New features in version 2.{i}",
            source="update_service",
            priority_hint="low",
            channel="in_app",
        ))
        time.sleep(0.05)

    # ─────────────────────────────────────────────
    banner("SCENARIO 7 — Quiet Hours (Deferred)")
    print("Reminder arrives while user has quiet hours active in metadata.")
    print("Expected: AI penalizes quiet hours → LATER.\n")
    pause()
    engine.evaluate(NotificationEvent(
        user_id="user_004",
        event_type="reminder",
        title="Team standup in 15 minutes",
        message="Don't forget your 9 AM standup.",
        source="calendar_service",
        priority_hint="medium",
        channel="push",
        metadata={"quiet_hours": True, "timezone": "Asia/Kolkata"},
    ))

    # ─────────────────────────────────────────────
    banner("SCENARIO 8 — AI Fallback Mode (Circuit Breaker)")
    print("Simulating AI scorer going offline mid-operation.")
    print("Expected: Deterministic fallback kicks in, no silent drops.\n")
    pause()

    # Force AI offline
    AIScorer.AI_AVAILABLE = False
    engine.scorer.AI_AVAILABLE = False

    engine.evaluate(NotificationEvent(
        user_id="user_005",
        event_type="alert",
        title="Payment failed",
        message="Your subscription payment failed. Please update billing.",
        source="billing_service",
        priority_hint="high",
        channel="email",
    ))

    # Restore AI
    AIScorer.AI_AVAILABLE = True
    engine.scorer.AI_AVAILABLE = True

    # ─────────────────────────────────────────────
    banner("DEMO COMPLETE — Audit Log Summary")
    stats = audit_log.stats()
    print(f"""
  Total events evaluated : {stats['total_evaluated']}
  ✅  Sent NOW            : {stats['by_action']['NOW']}
  ⏰  Deferred LATER      : {stats['by_action']['LATER']}
  🚫  Suppressed NEVER    : {stats['by_action']['NEVER']}

  Suppression rate        : {stats['suppression_rate']}%
  Deferral rate           : {stats['deferred_rate']}%
""")

    print(f"{DIM}{'─'*55}")
    print("Full audit log (all decisions):")
    print('─'*55)
    for d in audit_log.get_all():
        icon = {"NOW": "✅", "LATER": "⏰", "NEVER": "🚫"}.get(d.action, "?")
        fb = " [FALLBACK]" if d.fallback_mode else ""
        print(f"  {icon} [{d.action}]{fb} user={d.user_id} score={d.score:.2f}")
        print(f"     → {d.reason[:80]}")
    print(f"{'─'*55}{RESET}\n")

    print(f"""
{GREEN}{BOLD}To run as an API server:{RESET}
  pip install fastapi uvicorn
  uvicorn api.server:app --reload --port 8000

Then test with curl:
  curl -X POST http://localhost:8000/v1/notifications/evaluate \\
    -H "Content-Type: application/json" \\
    -d '{{"user_id":"u1","event_type":"message","channel":"push","title":"Hello","priority_hint":"high"}}'

  curl http://localhost:8000/v1/health
  curl http://localhost:8000/v1/stats
""")


if __name__ == "__main__":
    main()
