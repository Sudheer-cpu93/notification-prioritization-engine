"""
FastAPI server — 5 REST endpoints.
Run: uvicorn api.server:app --reload --port 8000
"""

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from typing import Optional, Dict, Any
    import uvicorn

    from engine.models import NotificationEvent
    from engine.prioritizer import PrioritizationEngine
    from engine.audit import audit_log
    from engine.scorer import AIScorer

    app = FastAPI(title="Notification Prioritization Engine", version="1.0.0")
    engine = PrioritizationEngine()

    # ─── Request Schema ───────────────────────────────────────

    class EvaluateRequest(BaseModel):
        user_id: str
        event_type: str
        channel: str
        title: Optional[str] = None
        message: Optional[str] = None
        source: Optional[str] = None
        priority_hint: Optional[str] = None
        timestamp: Optional[str] = None
        expires_at: Optional[str] = None
        dedupe_key: Optional[str] = None
        metadata: Optional[Dict[str, Any]] = {}

    class RuleRequest(BaseModel):
        name: str
        priority: int = 50
        conditions: list
        action: str
        reason: str

    class DispatchRequest(BaseModel):
        override_reason: str

    # ─── Endpoints ───────────────────────────────────────────

    @app.post("/v1/notifications/evaluate")
    def evaluate(req: EvaluateRequest):
        event = NotificationEvent(**req.model_dump())
        decision = engine.evaluate(event)
        return {
            "event_id": decision.event_id,
            "action": decision.action,
            "score": decision.score,
            "reason": decision.reason,
            "rule_matched": decision.rule_matched,
            "ai_used": decision.ai_used,
            "fallback_mode": decision.fallback_mode,
            "decided_at": decision.decided_at,
        }

    @app.get("/v1/notifications/history/{user_id}")
    def history(user_id: str, action: Optional[str] = None, limit: int = 50):
        results = audit_log.get_user_history(user_id, action, limit)
        return {
            "user_id": user_id,
            "total": len(results),
            "results": [d.__dict__ for d in results]
        }

    @app.post("/v1/rules")
    def create_rule(req: RuleRequest):
        rule = engine.rules.add_rule(req.model_dump())
        return {"status": "created", "rule": rule}

    @app.get("/v1/rules")
    def list_rules():
        return {"rules": engine.rules.rules}

    @app.post("/v1/notifications/{event_id}/dispatch")
    def force_dispatch(event_id: str, req: DispatchRequest):
        return {
            "event_id": event_id,
            "status": "dispatched",
            "override_reason": req.override_reason,
            "note": "In production: looks up event, re-evaluates with override flag, sends to channel"
        }

    @app.get("/v1/health")
    def health():
        scorer = engine.scorer
        return {
            "status": "ok" if scorer.circuit_breaker.state == "CLOSED" else "degraded",
            "components": {
                "api": "ok",
                "redis": "ok (in-memory simulation)",
                "postgres": "ok (in-memory simulation)",
                "ai_scorer": "ok" if scorer.AI_AVAILABLE else "unavailable",
                "circuit_breaker": scorer.circuit_breaker.status,
                "fallback_mode": not scorer.AI_AVAILABLE or scorer.circuit_breaker.state == "OPEN",
            }
        }

    @app.get("/v1/stats")
    def stats():
        return audit_log.stats()

    HAS_FASTAPI = True

except ImportError:
    HAS_FASTAPI = False
    app = None
