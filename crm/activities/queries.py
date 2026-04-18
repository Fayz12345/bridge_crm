from sqlalchemy import insert, select

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_activities, crm_users


def log_activity(
    related_type: str,
    related_id: int,
    activity_type: str,
    description: str,
    created_by: int | None,
    metadata: dict | None = None,
) -> None:
    statement = insert(crm_activities).values(
        related_type=related_type,
        related_id=related_id,
        activity_type=activity_type,
        description=description,
        created_by=created_by,
        metadata=metadata,
    )
    with get_connection() as connection:
        connection.execute(statement)


def list_activities(related_type: str, related_id: int) -> list[dict]:
    creator = crm_users.alias("creator")
    statement = (
        select(crm_activities, creator.c.full_name.label("created_by_name"))
        .select_from(crm_activities.outerjoin(creator, crm_activities.c.created_by == creator.c.id))
        .where(
            crm_activities.c.related_type == related_type,
            crm_activities.c.related_id == related_id,
        )
        .order_by(crm_activities.c.created_at.desc(), crm_activities.c.id.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]
