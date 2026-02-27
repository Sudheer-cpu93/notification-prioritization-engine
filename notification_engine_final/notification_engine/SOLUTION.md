# Notification Prioritization Engine — Solution Design

**Candidate Submission | Cyepro Solutions — Round 1**

---

## Table of Contents

1. [Problem Summary](#problem-summary)
2. [High-Level Architecture](#high-level-architecture)
3. [Decision Logic — Now / Later / Never](#decision-logic)
4. [Data Model](#data-model)
5. [API Interfaces](#api-interfaces)
6. [Duplicate Prevention](#duplicate-prevention)
7. [Alert Fatigue Strategy](#alert-fatigue-strategy)
8. [Fallback Strategy](#fallback-strategy)
9. [Metrics & Monitoring](#metrics--monitoring)
10. [Key Tradeoffs](#key-tradeoffs)

---

## 1. Problem Summary

Users receive too many notifications — many are repetitive, poorly timed, or low-value. The engine must:

- Classify each incoming event as **Now**, **Later**, or **Never**
- Prevent duplicates (exact and near)
- Reduce alert fatigue
- Handle edge cases gracefully (expired, conflicting priority, AI unavailable)
- Be auditable and explainable

---

## 2. High-Level Architecture

```
Incoming Event
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                   INGESTION LAYER                           │
│  API Gateway → Event Validator → Kafka Topic (raw_events)   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               PRIORITIZATION ENGINE (Core)                  │
│                                                             │
│  ┌──────────────┐   ┌────────────────┐   ┌──────────────┐  │
│  │  Dedup Check │ → │  Rules Engine  │ → │  AI Scorer   │  │
│  │  (Redis)     │   │  (Configurable)│   │  (LLM/ML)    │  │
│  └──────────────┘   └────────────────┘   └──────────────┘  │
│              └──────────────┬───────────────┘               │
│                             ▼                               │
│                   ┌──────────────────┐                      │
│                   │  Decision Merger │                      │
│                   │  (Now/Later/Never│                      │
│                   └────────┬─────────┘                      │
└────────────────────────────┼────────────────────────────────┘
                             │
           ┌─────────────────┼──────────────────┐
           ▼                 ▼                  ▼
    ┌────────────┐   ┌──────────────┐   ┌──────────────┐
    │  Dispatch  │   │  Defer Queue │   │  Audit Log   │
    │  Service   │   │  (Scheduler) │   │  (Postgres)  │
    └────────────┘   └──────────────┘   └──────────────┘
           │
    ┌──────┴───────┐
    │  Channels    │
    │  push/email/ │
    │  SMS/in-app  │
    └──────────────┘
```

### Components

| Component | Role | Technology |
|-----------|------|------------|
| API Gateway | Ingests events, validates schema | FastAPI / Kong |
| Kafka | Decouples ingestion from processing | Apache Kafka |
| Redis | Dedup store, frequency counters, user history | Redis 7 |
| Rules Engine | Human-configurable rules, no deploy needed | JSON/YAML rules + OPA or custom eval |
| AI Scorer | Contextual scoring using LLM or trained classifier | OpenAI / fine-tuned model |
| Decision Merger | Combines signals into final classification | Python service |
| Defer Queue | Schedules Later notifications | Redis sorted set / Celery Beat |
| Audit Log | Immutable record of every decision + reason | PostgreSQL |
| Dispatch Service | Sends Now notifications to channels | Push/Email/SMS adapters |

---

## 3. Decision Logic — Now / Later / Never

### Classification Flow

```
Event Arrives
      │
      ▼
[1] EXPIRED CHECK
  expires_at < now?  → NEVER (reason: "expired before processing")
      │
      ▼
[2] DUPLICATE CHECK
  Exact or near-duplicate found in Redis?  → NEVER (reason: "duplicate of {original_id}")
      │
      ▼
[3] HARD RULES (from Rules Engine)
  Rule matches → immediate verdict (overrides AI)
  Examples:
    - event_type = "security_alert"  → NOW
    - event_type = "promo" AND user.do_not_disturb = true  → NEVER
      │
      ▼
[4] FATIGUE CHECK
  User received > N notifications in last T minutes?
    AND this event is non-critical?  → LATER or NEVER
      │
      ▼
[5] AI SCORING (with fallback)
  AI returns: priority_score (0.0–1.0) + suggested_action + explanation
  If AI unavailable → use deterministic fallback scorer
      │
      ▼
[6] DECISION MERGER
  Combine rule verdict + fatigue state + AI score:
    score >= 0.75 → NOW
    score 0.35–0.74 → LATER (scheduled at optimal time)
    score < 0.35 → NEVER
      │
      ▼
[7] WRITE AUDIT LOG  →  DISPATCH or ENQUEUE or SUPPRESS
```

### Priority Score Computation

```python
def compute_priority_score(event: NotificationEvent, context: UserContext) -> float:
    score = 0.0

    # Base score from priority_hint
    base = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25, None: 0.4}
    score += base.get(event.priority_hint, 0.4) * 0.4  # 40% weight

    # Recency of similar events (lower score if many recent)
    recent_count = context.recent_event_count(event.event_type, window_minutes=60)
    recency_penalty = min(recent_count * 0.1, 0.3)
    score -= recency_penalty

    # Time-sensitivity
    if event.expires_at:
        minutes_to_expire = (event.expires_at - now()).total_seconds() / 60
        if minutes_to_expire < 10:
            score += 0.3  # Urgent: push it now
        elif minutes_to_expire < 60:
            score += 0.1

    # User context: quiet hours / DND
    if context.is_quiet_hours():
        score -= 0.2

    # Channel weight
    channel_weights = {"push": 1.0, "sms": 0.9, "email": 0.7, "in_app": 0.5}
    score *= channel_weights.get(event.channel, 0.7)

    return max(0.0, min(1.0, score))
```

### AI Prompt Design (for LLM-based scoring)

```python
SYSTEM_PROMPT = """
You are a notification prioritization assistant. 
Given a notification event and user context, classify it as: NOW, LATER, or NEVER.
Return JSON: {"action": "NOW|LATER|NEVER", "score": 0.0-1.0, "reason": "..."}
Be concise. Prioritize safety and security events. Suppress repetitive low-value content.
"""

def build_ai_prompt(event, history):
    return f"""
Event: {event.model_dump_json()}
User's last 5 notifications: {history}
User timezone: {event.metadata.get('timezone', 'UTC')}
Current time: {datetime.utcnow().isoformat()}

Classify this notification.
"""
```

---

## 4. Data Model

### `notification_events` (PostgreSQL)

```sql
CREATE TABLE notification_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(128) NOT NULL,
    event_type      VARCHAR(64) NOT NULL,
    title           TEXT,
    message         TEXT,
    source          VARCHAR(64),
    priority_hint   VARCHAR(16),      -- critical/high/medium/low
    channel         VARCHAR(16),      -- push/email/sms/in_app
    metadata        JSONB,
    dedupe_key      VARCHAR(256),
    expires_at      TIMESTAMPTZ,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    INDEX idx_user_received (user_id, received_at),
    INDEX idx_dedupe (dedupe_key, user_id)
);
```

### `notification_decisions` (PostgreSQL — Audit Log)

```sql
CREATE TABLE notification_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        UUID REFERENCES notification_events(id),
    user_id         VARCHAR(128) NOT NULL,
    action          VARCHAR(8) NOT NULL,    -- NOW / LATER / NEVER
    reason          TEXT NOT NULL,          -- Human-readable explanation
    score           FLOAT,
    rule_matched    VARCHAR(128),           -- which rule triggered, if any
    ai_used         BOOLEAN DEFAULT FALSE,
    ai_response     JSONB,
    decided_at      TIMESTAMPTZ DEFAULT NOW(),
    sent_at         TIMESTAMPTZ,            -- null if never sent
    deferred_until  TIMESTAMPTZ,            -- null if not deferred
    INDEX idx_user_action (user_id, action, decided_at)
);
```

### `suppression_rules` (PostgreSQL — Human Configurable)

```sql
CREATE TABLE suppression_rules (
    id              UUID PRIMARY KEY,
    name            VARCHAR(128),
    rule_json       JSONB NOT NULL,   -- DSL: {"event_type": "promo", "action": "NEVER"}
    priority        INT DEFAULT 0,    -- Higher = evaluated first
    enabled         BOOLEAN DEFAULT TRUE,
    created_by      VARCHAR(64),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Redis Keys

```
# Exact dedup
dedup:{user_id}:{dedupe_key}            → TTL: 24h

# Near-dedup fingerprint
fingerprint:{user_id}:{content_hash}    → TTL: 1h

# Frequency counter
freq:{user_id}:{event_type}             → Counter, TTL: 1h

# User-level daily cap
daily_cap:{user_id}:{date}              → Counter, TTL: 24h

# Defer queue (sorted set, score = scheduled_timestamp)
defer_queue:{channel}                   → Sorted set of event_ids
```

---

## 5. API Interfaces

### Endpoint 1: Submit Notification Event

```
POST /v1/notifications/evaluate
```

**Request:**
```json
{
  "user_id": "usr_abc123",
  "event_type": "message",
  "title": "You have a new message",
  "message": "Hey, are you free tomorrow?",
  "source": "messaging_service",
  "priority_hint": "medium",
  "channel": "push",
  "timestamp": "2025-02-25T10:00:00Z",
  "expires_at": "2025-02-25T18:00:00Z",
  "dedupe_key": "msg_789xyz",
  "metadata": { "sender_id": "usr_def456", "thread_id": "thread_001" }
}
```

**Response:**
```json
{
  "event_id": "evt_550e8400",
  "action": "NOW",
  "score": 0.81,
  "reason": "High-priority message from active thread. No recent duplicates. User not in quiet hours.",
  "rule_matched": null,
  "decided_at": "2025-02-25T10:00:00.123Z"
}
```

---

### Endpoint 2: Get Decision History for a User

```
GET /v1/notifications/history/{user_id}?limit=50&action=NOW&from=2025-02-01
```

**Response:**
```json
{
  "user_id": "usr_abc123",
  "total": 142,
  "results": [
    {
      "event_id": "evt_123",
      "action": "NEVER",
      "reason": "Duplicate of evt_110 sent 3 minutes ago",
      "decided_at": "2025-02-25T09:55:00Z"
    }
  ]
}
```

---

### Endpoint 3: Manage Suppression Rules

```
POST   /v1/rules               → Create a new rule
GET    /v1/rules               → List all rules
PUT    /v1/rules/{rule_id}     → Update a rule
DELETE /v1/rules/{rule_id}     → Disable a rule
```

**Create Rule Request:**
```json
{
  "name": "Suppress promos during quiet hours",
  "rule": {
    "conditions": [
      { "field": "event_type", "op": "eq", "value": "promotion" },
      { "field": "user.quiet_hours_active", "op": "eq", "value": true }
    ],
    "action": "NEVER",
    "reason": "User in quiet hours — promo suppressed"
  },
  "priority": 10
}
```

---

### Endpoint 4: Retry / Force-Send Deferred Notification

```
POST /v1/notifications/{event_id}/dispatch
```

**Request:**
```json
{ "override_reason": "User manually requested resend" }
```

**Response:**
```json
{
  "event_id": "evt_550e8400",
  "status": "dispatched",
  "channel": "push",
  "sent_at": "2025-02-25T12:00:00Z"
}
```

---

### Endpoint 5: Health + Fallback Status

```
GET /v1/health
```

**Response:**
```json
{
  "status": "degraded",
  "components": {
    "api": "ok",
    "redis": "ok",
    "postgres": "ok",
    "ai_scorer": "unavailable",
    "fallback_mode": true
  },
  "uptime_seconds": 84320
}
```

---

## 6. Duplicate Prevention

### Two-Layer Approach

**Layer 1 — Exact Dedup (dedupe_key)**

```python
def check_exact_duplicate(event: NotificationEvent) -> bool:
    if not event.dedupe_key:
        return False
    redis_key = f"dedup:{event.user_id}:{event.dedupe_key}"
    # SET NX with TTL — atomic check-and-set
    result = redis.set(redis_key, event.id, nx=True, ex=86400)
    return result is None  # None means key already existed → duplicate
```

**Layer 2 — Near-Dedup (content fingerprint)**

```python
import hashlib
from difflib import SequenceMatcher

def content_fingerprint(event: NotificationEvent) -> str:
    # Normalize: lowercase, strip punctuation, trim whitespace
    text = f"{event.event_type}:{event.title or ''}:{event.message or ''}"
    normalized = re.sub(r'[^\w\s]', '', text.lower().strip())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]

def check_near_duplicate(event: NotificationEvent) -> bool:
    fingerprint = content_fingerprint(event)
    redis_key = f"fingerprint:{event.user_id}:{fingerprint}"
    
    existing = redis.get(redis_key)
    if existing:
        return True  # Near-duplicate found
    
    redis.set(redis_key, event.id, ex=3600)  # 1 hour window
    return False
```

**Why two layers?** Exact dedup handles producer-level duplicates (same event fired twice). Near-dedup handles semantic duplicates — e.g. "Your order is ready!" and "Order ready!" from different services within a short window.

---

## 7. Alert Fatigue Strategy

### Frequency Caps

```python
FREQUENCY_CAPS = {
    "promotion":     {"max": 2,  "window_minutes": 60},
    "update":        {"max": 5,  "window_minutes": 60},
    "reminder":      {"max": 3,  "window_minutes": 60},
    "message":       {"max": 20, "window_minutes": 60},  # high cap — messages are important
    "system_event":  {"max": 10, "window_minutes": 60},
    "default":       {"max": 8,  "window_minutes": 60},
}

def check_frequency_cap(event: NotificationEvent) -> str | None:
    cap = FREQUENCY_CAPS.get(event.event_type, FREQUENCY_CAPS["default"])
    redis_key = f"freq:{event.user_id}:{event.event_type}"
    
    count = redis.incr(redis_key)
    if count == 1:
        redis.expire(redis_key, cap["window_minutes"] * 60)
    
    if count > cap["max"]:
        return f"Frequency cap exceeded ({count}/{cap['max']} in {cap['window_minutes']}min)"
    return None
```

### Daily Cap

```python
DAILY_CAP_PER_CHANNEL = {"push": 20, "sms": 5, "email": 10, "in_app": 50}

def check_daily_cap(event: NotificationEvent) -> str | None:
    cap = DAILY_CAP_PER_CHANNEL.get(event.channel, 20)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    redis_key = f"daily_cap:{event.user_id}:{event.channel}:{today}"
    
    count = redis.incr(redis_key)
    if count == 1:
        redis.expireat(redis_key, end_of_day_timestamp())
    
    if count > cap:
        return f"Daily {event.channel} cap reached ({count}/{cap})"
    return None
```

### Digest Batching (for Low-Priority Events)

Rather than suppressing entirely, low-priority events during noisy periods are collected and sent as a digest:

```python
def batch_for_digest(event: NotificationEvent):
    digest_key = f"digest:{event.user_id}:{event.channel}:{today_date()}"
    redis.rpush(digest_key, event.id)
    redis.expireat(digest_key, next_digest_time())  # e.g. 8 PM daily
    
    # Schedule digest send job
    schedule_digest_delivery(event.user_id, event.channel, deliver_at=next_digest_time())
```

### Quiet Hours

Configurable per-user or globally. Non-critical notifications are deferred, not dropped:

```python
def apply_quiet_hours(event: NotificationEvent, user_prefs: UserPrefs) -> str | None:
    if user_prefs.quiet_hours_active() and event.priority_hint not in ("critical", "high"):
        resume_time = user_prefs.quiet_hours_end()
        return f"Deferred — user in quiet hours until {resume_time}"
    return None
```

---

## 8. Fallback Strategy

### AI Unavailability

The AI scorer is an enhancement, not a dependency. If it's slow or down, the system falls back gracefully:

```python
async def get_ai_score(event, context, timeout=1.5):
    try:
        async with asyncio.timeout(timeout):
            return await ai_service.score(event, context)
    except (asyncio.TimeoutError, AIServiceError) as e:
        logger.warning(f"AI scorer unavailable: {e}. Using fallback.")
        return deterministic_fallback_score(event, context)

def deterministic_fallback_score(event, context) -> AIScoreResult:
    """Rule-based fallback when AI is unavailable."""
    score_map = {"critical": 0.9, "high": 0.75, "medium": 0.5, "low": 0.2}
    score = score_map.get(event.priority_hint, 0.4)
    
    # Apply basic penalties
    if context.recent_count > 5:
        score -= 0.15
    if context.is_quiet_hours():
        score -= 0.2
    
    return AIScoreResult(
        score=max(0.0, min(1.0, score)),
        action="NOW" if score >= 0.75 else "LATER" if score >= 0.35 else "NEVER",
        reason="[Fallback mode] Rule-based score — AI unavailable",
        ai_used=False
    )
```

### Circuit Breaker Pattern

```python
class AICircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=30):
        self.failures = 0
        self.state = "CLOSED"  # CLOSED = normal, OPEN = bypassed
        self.last_failure_time = None
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
    
    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
            logger.error("AI circuit breaker OPEN — all requests using fallback")
    
    def can_attempt(self) -> bool:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "HALF-OPEN"
                return True
            return False
        return True
```

### Critical Notification Safety Net

Important notifications (critical/high priority) are **never silently dropped**, even in fallback:

```python
def safe_fallback_decision(event, context) -> Decision:
    if event.priority_hint in ("critical", "high"):
        return Decision(action="NOW", reason="[Safety net] High priority — sent despite service degradation")
    
    return deterministic_fallback_decision(event, context)
```

---

## 9. Metrics & Monitoring

### Key Metrics

| Metric | Type | Alert Threshold |
|--------|------|-----------------|
| `notifications.evaluated.total` | Counter | — |
| `notifications.decision.now` | Counter | — |
| `notifications.decision.later` | Counter | — |
| `notifications.decision.never` | Counter | — |
| `notifications.ai_scorer.latency_p99` | Histogram | > 500ms |
| `notifications.ai_scorer.fallback_rate` | Gauge | > 5% |
| `notifications.dedup.hit_rate` | Gauge | — |
| `notifications.daily_cap.hit_rate` | Gauge | > 20% (too aggressive) |
| `notifications.critical_suppressed` | Counter | > 0 (should never be non-zero) |
| `notifications.dispatch.failure_rate` | Gauge | > 1% |

### Monitoring Stack

- **Metrics**: Prometheus + Grafana dashboards
- **Logs**: Structured JSON → Elasticsearch / Loki
- **Tracing**: OpenTelemetry → Jaeger (trace per event through all stages)
- **Alerting**: PagerDuty for critical_suppressed > 0, AI fallback_rate > 10%

### Sample Audit Log Entry

```json
{
  "event_id": "evt_550e8400",
  "user_id": "usr_abc123",
  "action": "NEVER",
  "score": 0.18,
  "reason": "Promotional notification suppressed: frequency cap exceeded (8/5 in 60min). User also in quiet hours.",
  "rule_matched": "promo_quiet_hours_rule",
  "ai_used": true,
  "ai_response": { "action": "NEVER", "score": 0.18, "reason": "Low-value promo during noisy period" },
  "decided_at": "2025-02-25T22:15:00.042Z",
  "fallback_mode": false
}

