from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_notifications


def create_notification(payload: dict) -> int:
    statement = insert(crm_notifications).values(**payload).returning(crm_notifications.c.id)
    with get_connection() as connection:
        notification_id = connection.execute(statement).scalar_one()
    return int(notification_id)


def list_notifications_for_user(user_id: int, unread_only: bool = False, limit: int | None = None) -> list[dict]:
    statement = (
        select(crm_notifications)
        .where(crm_notifications.c.user_id == user_id)
        .order_by(crm_notifications.c.created_at.desc(), crm_notifications.c.id.desc())
    )
    if unread_only:
        statement = statement.where(crm_notifications.c.is_read.is_(False))
    if limit:
        statement = statement.limit(limit)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def count_unread_notifications(user_id: int) -> int:
    statement = select(func.count()).select_from(crm_notifications).where(
        crm_notifications.c.user_id == user_id,
        crm_notifications.c.is_read.is_(False),
    )
    with get_connection() as connection:
        return int(connection.execute(statement).scalar_one())


def mark_notification_read(notification_id: int, user_id: int) -> None:
    statement = (
        update(crm_notifications)
        .where(
            crm_notifications.c.id == notification_id,
            crm_notifications.c.user_id == user_id,
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )
    with get_connection() as connection:
        connection.execute(statement)


def mark_all_notifications_read(user_id: int) -> None:
    statement = (
        update(crm_notifications)
        .where(
            crm_notifications.c.user_id == user_id,
            crm_notifications.c.is_read.is_(False),
        )
        .values(is_read=True, read_at=datetime.now(timezone.utc))
    )
    with get_connection() as connection:
        connection.execute(statement)
