from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
import uuid


@dataclass
class NotificationEvent:
    user_id: str
    event_type: str
    channel: str
    title: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = None
    priority_hint: Optional[str] = None   # critical / high / medium / low
    timestamp: Optional[str] = None
    expires_at: Optional[str] = None
    dedupe_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return exp < datetime.now(exp.tzinfo)
        except Exception:
            return False


@dataclass
class Decision:
    event_id: str
    user_id: str
    action: str           # NOW / LATER / NEVER
    score: float
    reason: str
    rule_matched: Optional[str] = None
    ai_used: bool = False
    fallback_mode: bool = False
    decided_at: str = field(default_factory=lambda: datetime.now().isoformat())
    deferred_until: Optional[str] = None
