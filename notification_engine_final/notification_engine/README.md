# Notification Prioritization Engine

**Cyepro Solutions — Round 1 AI-Native Solution**

## Quick Start (No setup needed — pure Python 3.8+)

```bash
cd notification_engine
python demo.py
```

This runs 8 live scenarios showing every decision path: NOW, LATER, NEVER, dedup, fatigue, quiet hours, and AI fallback.

## Project Structure

```
notification_engine/
├── demo.py               ← Run this for the walkthrough
├── engine/
│   ├── models.py         ← NotificationEvent, Decision dataclasses
│   ├── store.py          ← In-memory Redis simulation (DedupChecker, FrequencyChecker)
│   ├── rules.py          ← Human-configurable rules engine
│   ├── scorer.py         ← AI scorer + deterministic fallback + circuit breaker
│   ├── prioritizer.py    ← Main orchestration engine
│   └── audit.py          ← Audit log (in-memory PostgreSQL simulation)
└── api/
    └── server.py         ← FastAPI server (5 REST endpoints)
```

## API Server (requires FastAPI)

```bash
pip install fastapi uvicorn
uvicorn api.server:app --reload --port 8000
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/notifications/evaluate` | Classify a notification event |
| GET  | `/v1/notifications/history/{user_id}` | Get user's decision history |
| POST | `/v1/rules` | Add a suppression rule (no redeploy needed) |
| GET  | `/v1/rules` | List all active rules |
| POST | `/v1/notifications/{event_id}/dispatch` | Force-send a deferred notification |
| GET  | `/v1/health` | System health + fallback status |
| GET  | `/v1/stats` | Audit stats (NOW/LATER/NEVER counts) |

### Example curl

```bash
# Evaluate a notification
curl -X POST http://localhost:8000/v1/notifications/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_001",
    "event_type": "security_alert",
    "channel": "push",
    "title": "New login detected",
    "priority_hint": "critical"
  }'

# Check health
curl http://localhost:8000/v1/health

# Get stats
curl http://localhost:8000/v1/stats

# Add a custom rule (no deployment!)
curl -X POST http://localhost:8000/v1/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "suppress_weekend_promos",
    "priority": 60,
    "conditions": [{"field": "event_type", "op": "eq", "value": "promotion"}],
    "action": "NEVER",
    "reason": "No promos on weekends"
  }'
```

## Demo Scenarios

| # | Scenario | Expected | Why |
|---|----------|----------|-----|
| 1 | Security alert | NOW | Hard rule: always critical |
| 2 | Low-priority promo | NEVER | Rule: suppress low promos |
| 3 | Direct message | NOW | AI scores high |
| 4 | Exact duplicate (same dedupe_key) | NEVER | Redis SET NX dedup |
| 5 | Near-duplicate (rephrased) | NEVER | Content fingerprint match |
| 6 | Repeated updates (×7) | LATER after cap | Frequency cap exceeded |
| 7 | Reminder during quiet hours | LATER | AI penalizes quiet hours |
| 8 | High-priority + AI offline | NOW | Fallback + safety net |

## Toggle Fallback Mode

In `engine/scorer.py`, set `AIScorer.AI_AVAILABLE = False` to simulate AI downtime.

## Tools Used
- Python 3.8+ (standard library only for demo)
- FastAPI + uvicorn (optional, for API server)
- Design assisted by Claude (Anthropic) — all architecture decisions reviewed and adapted manually
