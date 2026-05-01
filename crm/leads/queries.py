from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, or_, select, update

from bridge_crm.crm.segments.queries import (
    list_lead_product_interests_map,
    list_lead_tags_map,
)
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_lead_product_interests,
    crm_lead_tags,
    crm_leads,
    crm_opportunities,
    crm_users,
)


VALID_LEAD_STATUSES = {"new", "contacted", "qualified", "unqualified", "converted"}


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _attach_lead_segments(leads: list[dict]) -> list[dict]:
    lead_ids = [int(lead["id"]) for lead in leads]
    interests_map = list_lead_product_interests_map(lead_ids)
    tags_map = list_lead_tags_map(lead_ids)
    for lead in leads:
        lead_id = int(lead["id"])
        lead["product_interests"] = interests_map.get(lead_id, [])
        lead["tags"] = tags_map.get(lead_id, [])
    return leads


def list_leads(
    status: str | None = None,
    search_term: str | None = None,
    owner_id: int | None = None,
    product_interest_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
) -> list[dict]:
    owner = crm_users.alias("owner")
    statement = (
        select(crm_leads, owner.c.full_name.label("owner_name"))
        .select_from(crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id))
        .order_by(crm_leads.c.created_at.desc(), crm_leads.c.id.desc())
    )

    if status and status in VALID_LEAD_STATUSES:
        statement = statement.where(crm_leads.c.status == status)

    if owner_id:
        statement = statement.where(crm_leads.c.owner_id == owner_id)

    if search_term:
        pattern = f"%{search_term.strip()}%"
        statement = statement.where(
            or_(
                crm_leads.c.first_name.ilike(pattern),
                crm_leads.c.last_name.ilike(pattern),
                crm_leads.c.email.ilike(pattern),
                crm_leads.c.company_name.ilike(pattern),
                crm_leads.c.interest.ilike(pattern),
            )
        )

    if product_interest_ids:
        statement = statement.where(
            select(crm_lead_product_interests.c.lead_id)
            .where(
                crm_lead_product_interests.c.lead_id == crm_leads.c.id,
                crm_lead_product_interests.c.interest_option_id.in_(product_interest_ids),
            )
            .exists()
        )

    if tag_ids:
        statement = statement.where(
            select(crm_lead_tags.c.lead_id)
            .where(
                crm_lead_tags.c.lead_id == crm_leads.c.id,
                crm_lead_tags.c.tag_id.in_(tag_ids),
            )
            .exists()
        )

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return _attach_lead_segments([dict(row) for row in rows])


def get_lead(lead_id: int) -> dict | None:
    owner = crm_users.alias("owner")
    statement = (
        select(crm_leads, owner.c.full_name.label("owner_name"))
        .select_from(crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id))
        .where(crm_leads.c.id == lead_id)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    if not row:
        return None
    return _attach_lead_segments([dict(row)])[0]


def get_leads_by_ids(lead_ids: list[int]) -> list[dict]:
    if not lead_ids:
        return []
    owner = crm_users.alias("owner")
    statement = (
        select(crm_leads, owner.c.full_name.label("owner_name"))
        .select_from(crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id))
        .where(crm_leads.c.id.in_(lead_ids))
        .order_by(func.lower(crm_leads.c.last_name), func.lower(crm_leads.c.first_name), crm_leads.c.id)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return _attach_lead_segments([dict(row) for row in rows])


def create_lead(payload: dict) -> int:
    clean = {
        "first_name": str(payload["first_name"]).strip(),
        "last_name": str(payload["last_name"]).strip(),
        "email": (_clean(payload.get("email")) or "").lower() or None,
        "phone": _clean(payload.get("phone")),
        "phone_prefix": _clean(payload.get("phone_prefix")),
        "company_name": _clean(payload.get("company_name")),
        "source": payload.get("source", "manual"),
        "status": payload.get("status", "new"),
        "notes": _clean(payload.get("notes")),
        "interest": _clean(payload.get("interest")),
        "custom_fields": payload.get("custom_fields") or {},
        "owner_id": payload.get("owner_id"),
    }
    statement = insert(crm_leads).values(**clean).returning(crm_leads.c.id)
    with get_connection() as connection:
        lead_id = connection.execute(statement).scalar_one()
    return int(lead_id)


def update_lead(lead_id: int, payload: dict) -> None:
    clean = {
        "first_name": str(payload["first_name"]).strip(),
        "last_name": str(payload["last_name"]).strip(),
        "email": (_clean(payload.get("email")) or "").lower() or None,
        "phone": _clean(payload.get("phone")),
        "phone_prefix": _clean(payload.get("phone_prefix")),
        "company_name": _clean(payload.get("company_name")),
        "source": payload.get("source", "manual"),
        "status": payload.get("status", "new"),
        "notes": _clean(payload.get("notes")),
        "interest": _clean(payload.get("interest")),
        "custom_fields": payload.get("custom_fields") or {},
        "owner_id": payload.get("owner_id"),
        "updated_at": datetime.now(timezone.utc),
    }
    statement = update(crm_leads).where(crm_leads.c.id == lead_id).values(**clean)
    with get_connection() as connection:
        connection.execute(statement)


def convert_lead(
    lead_id: int,
    account_id: int,
    opportunity_id: int,
) -> None:
    statement = (
        update(crm_leads)
        .where(crm_leads.c.id == lead_id)
        .values(
            status="converted",
            converted_account_id=account_id,
            converted_opportunity_id=opportunity_id,
            converted_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    with get_connection() as connection:
        connection.execute(statement)


def lead_status_counts() -> dict[str, int]:
    statement = (
        select(crm_leads.c.status, func.count().label("count"))
        .group_by(crm_leads.c.status)
    )
    counts = {status: 0 for status in VALID_LEAD_STATUSES}
    with get_connection() as connection:
        rows = connection.execute(statement)
        for row in rows:
            counts[row.status] = int(row.count)
    return counts


def delete_lead(lead_id: int) -> None:
    with get_connection() as connection:
        connection.execute(
            update(crm_opportunities)
            .where(crm_opportunities.c.lead_id == lead_id)
            .values(lead_id=None)
        )
        connection.execute(
            delete(crm_leads).where(crm_leads.c.id == lead_id)
        )
