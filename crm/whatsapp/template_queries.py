from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_users, crm_whatsapp_templates

TEMPLATE_STATUSES = ("pending", "approved", "cancelled")


def list_whatsapp_templates(status: str | None = None) -> list[dict]:
    creator = crm_users.alias("creator")
    statement = (
        select(
            crm_whatsapp_templates,
            creator.c.full_name.label("created_by_name"),
        )
        .select_from(
            crm_whatsapp_templates.outerjoin(
                creator, creator.c.id == crm_whatsapp_templates.c.created_by
            )
        )
        .order_by(crm_whatsapp_templates.c.updated_at.desc(), crm_whatsapp_templates.c.id.desc())
    )
    if status:
        statement = statement.where(crm_whatsapp_templates.c.status == status)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_whatsapp_template(template_id: int) -> dict | None:
    creator = crm_users.alias("creator")
    statement = (
        select(
            crm_whatsapp_templates,
            creator.c.full_name.label("created_by_name"),
        )
        .select_from(
            crm_whatsapp_templates.outerjoin(
                creator, creator.c.id == crm_whatsapp_templates.c.created_by
            )
        )
        .where(crm_whatsapp_templates.c.id == template_id)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def get_whatsapp_template_by_name(element_name: str, language: str | None = None) -> dict | None:
    statement = select(crm_whatsapp_templates).where(
        crm_whatsapp_templates.c.element_name == element_name
    )
    if language:
        statement = statement.where(crm_whatsapp_templates.c.language == language)
    statement = statement.order_by(crm_whatsapp_templates.c.id.desc()).limit(1)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def list_approved_templates() -> list[dict]:
    return list_whatsapp_templates(status="approved")


def has_approved_template() -> bool:
    statement = (
        select(func.count())
        .select_from(crm_whatsapp_templates)
        .where(crm_whatsapp_templates.c.status == "approved")
    )
    with get_connection() as connection:
        return int(connection.execute(statement).scalar_one() or 0) > 0


def count_templates_by_status() -> dict[str, int]:
    statement = select(
        crm_whatsapp_templates.c.status,
        func.count().label("total"),
    ).group_by(crm_whatsapp_templates.c.status)
    counts = {status: 0 for status in TEMPLATE_STATUSES}
    with get_connection() as connection:
        for row in connection.execute(statement).mappings():
            counts[str(row["status"])] = int(row["total"])
    return counts


def create_whatsapp_template(payload: dict) -> int:
    statement = insert(crm_whatsapp_templates).values(**payload).returning(crm_whatsapp_templates.c.id)
    with get_connection() as connection:
        template_id = connection.execute(statement).scalar_one()
    return int(template_id)


def update_whatsapp_template(template_id: int, payload: dict) -> None:
    values = {**payload, "updated_at": datetime.now(timezone.utc)}
    statement = (
        update(crm_whatsapp_templates)
        .where(crm_whatsapp_templates.c.id == template_id)
        .values(**values)
    )
    with get_connection() as connection:
        connection.execute(statement)


def upsert_whatsapp_template(payload: dict) -> int:
    now = datetime.now(timezone.utc)
    values = {**payload, "updated_at": now}
    statement = pg_insert(crm_whatsapp_templates).values(**values, created_at=now)
    statement = statement.on_conflict_do_update(
        index_elements=[
            crm_whatsapp_templates.c.element_name,
            crm_whatsapp_templates.c.language,
        ],
        set_={
            key: statement.excluded[key]
            for key in (
                "category",
                "header_text",
                "body",
                "footer",
                "custom_params",
                "status",
                "wati_status",
                "wati_template_id",
                "wa_template_id",
                "last_synced_at",
                "updated_at",
            )
        },
    ).returning(crm_whatsapp_templates.c.id)
    with get_connection() as connection:
        template_id = connection.execute(statement).scalar_one()
    return int(template_id)
