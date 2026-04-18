from datetime import datetime, timezone

from sqlalchemy import func, insert, or_, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_leads, crm_users


VALID_LEAD_STATUSES = {"new", "contacted", "qualified", "unqualified", "converted"}


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def list_leads(status: str | None = None, search_term: str | None = None) -> list[dict]:
    owner = crm_users.alias("owner")
    statement = (
        select(crm_leads, owner.c.full_name.label("owner_name"))
        .select_from(crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id))
        .order_by(crm_leads.c.created_at.desc(), crm_leads.c.id.desc())
    )

    if status and status in VALID_LEAD_STATUSES:
        statement = statement.where(crm_leads.c.status == status)

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

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_lead(lead_id: int) -> dict | None:
    owner = crm_users.alias("owner")
    statement = (
        select(crm_leads, owner.c.full_name.label("owner_name"))
        .select_from(crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id))
        .where(crm_leads.c.id == lead_id)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


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
