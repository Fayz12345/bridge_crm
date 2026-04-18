from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_emails


def list_emails(related_type: str, related_id: int) -> list[dict]:
    statement = (
        select(crm_emails)
        .where(
            crm_emails.c.related_type == related_type,
            crm_emails.c.related_id == related_id,
        )
        .order_by(crm_emails.c.created_at.desc(), crm_emails.c.id.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def create_email(payload: dict) -> int:
    statement = insert(crm_emails).values(**payload).returning(crm_emails.c.id)
    with get_connection() as connection:
        email_id = connection.execute(statement).scalar_one()
    return int(email_id)


def mark_email_sent(email_id: int) -> None:
    statement = (
        update(crm_emails)
        .where(crm_emails.c.id == email_id)
        .values(status="sent", sent_at=datetime.now(timezone.utc))
    )
    with get_connection() as connection:
        connection.execute(statement)


def mark_email_failed(email_id: int, error_message: str) -> None:
    statement = (
        update(crm_emails)
        .where(crm_emails.c.id == email_id)
        .values(status="failed", error_message=error_message)
    )
    with get_connection() as connection:
        connection.execute(statement)
