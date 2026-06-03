import json
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.db.models import AuditLog


def audit(db: Session, action: str, claim_id: Optional[str] = None, actor: str = "system", **details: Any) -> None:
    db.add(AuditLog(claim_id=claim_id, actor=actor, action=action, details=json.dumps(details, ensure_ascii=False)))
