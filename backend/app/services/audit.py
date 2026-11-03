from sqlalchemy.orm import Session

from app.models import AuditLog


def log_audit(db: Session, org_id: str, actor_id: str | None, entity_type: str, entity_id: str, action: str,
              before: dict | None = None, after: dict | None = None) -> None:
    """Never pass passwords, tokens or raw document text here."""
    db.add(AuditLog(organization_id=org_id, actor_user_id=actor_id, entity_type=entity_type, entity_id=entity_id,
                    action=action, before_state=before, after_state=after))


def jsonable(v):
    from datetime import date, datetime
    from decimal import Decimal
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v
