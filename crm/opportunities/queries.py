from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, insert, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_contacts,
    crm_opportunity_lines,
    crm_opportunities,
    crm_pipeline_stages,
    crm_users,
)


def _normalize_date(value: str | None):
    if not value:
        return None
    return date.fromisoformat(value)


def _normalize_decimal(value: str | None):
    if not value:
        return None
    return Decimal(value)


def list_opportunities(stage: str | None = None) -> list[dict]:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_opportunities,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("owner_name"),
        )
        .select_from(
            crm_opportunities.join(account, crm_opportunities.c.account_id == account.c.id).outerjoin(
                owner, crm_opportunities.c.owner_id == owner.c.id
            )
        )
        .order_by(crm_opportunities.c.created_at.desc(), crm_opportunities.c.id.desc())
    )
    if stage:
        statement = statement.where(crm_opportunities.c.stage == stage)

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_opportunity(opportunity_id: int) -> dict | None:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    contact = crm_contacts.alias("contact")
    statement = (
        select(
            crm_opportunities,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("owner_name"),
            account.c.email.label("account_email"),
            account.c.phone.label("account_phone"),
            contact.c.first_name.label("contact_first_name"),
            contact.c.last_name.label("contact_last_name"),
            contact.c.email.label("contact_email"),
        )
        .select_from(
            crm_opportunities.join(account, crm_opportunities.c.account_id == account.c.id)
            .outerjoin(owner, crm_opportunities.c.owner_id == owner.c.id)
            .outerjoin(contact, crm_opportunities.c.contact_id == contact.c.id)
        )
        .where(crm_opportunities.c.id == opportunity_id)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def get_opportunity_line_items(opportunity_id: int) -> list[dict]:
    statement = (
        select(crm_opportunity_lines)
        .where(crm_opportunity_lines.c.opportunity_id == opportunity_id)
        .order_by(crm_opportunity_lines.c.created_at.asc(), crm_opportunity_lines.c.id.asc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def create_opportunity(payload: dict) -> int:
    clean = {
        "title": payload["title"].strip(),
        "account_id": payload["account_id"],
        "contact_id": payload.get("contact_id"),
        "stage": payload.get("stage", "prospecting"),
        "amount": _normalize_decimal(payload.get("amount")),
        "currency": payload.get("currency", "CAD"),
        "probability": payload.get("probability", 10),
        "expected_close_date": _normalize_date(payload.get("expected_close_date")),
        "close_date": _normalize_date(payload.get("close_date")),
        "close_reason": payload.get("close_reason"),
        "owner_id": payload.get("owner_id"),
        "lead_id": payload.get("lead_id"),
        "notes": payload.get("notes"),
        "custom_fields": payload.get("custom_fields") or {},
        "created_by": payload.get("created_by"),
    }
    statement = insert(crm_opportunities).values(**clean).returning(crm_opportunities.c.id)
    with get_connection() as connection:
        opportunity_id = connection.execute(statement).scalar_one()
    return int(opportunity_id)


def update_opportunity(opportunity_id: int, payload: dict) -> None:
    clean = {
        "title": payload["title"].strip(),
        "account_id": payload["account_id"],
        "contact_id": payload.get("contact_id"),
        "stage": payload.get("stage", "prospecting"),
        "amount": _normalize_decimal(payload.get("amount")),
        "currency": payload.get("currency", "CAD"),
        "probability": payload.get("probability", 10),
        "expected_close_date": _normalize_date(payload.get("expected_close_date")),
        "close_date": _normalize_date(payload.get("close_date")),
        "close_reason": payload.get("close_reason"),
        "owner_id": payload.get("owner_id"),
        "lead_id": payload.get("lead_id"),
        "notes": payload.get("notes"),
        "custom_fields": payload.get("custom_fields") or {},
        "updated_at": datetime.now(timezone.utc),
    }
    statement = (
        update(crm_opportunities)
        .where(crm_opportunities.c.id == opportunity_id)
        .values(**clean)
    )
    with get_connection() as connection:
        connection.execute(statement)


def update_opportunity_stage(opportunity_id: int, stage: str, probability: int) -> None:
    statement = (
        update(crm_opportunities)
        .where(crm_opportunities.c.id == opportunity_id)
        .values(
            stage=stage,
            probability=probability,
            updated_at=datetime.now(timezone.utc),
        )
    )
    with get_connection() as connection:
        connection.execute(statement)


def list_accounts_for_select() -> list[dict]:
    statement = select(crm_accounts.c.id, crm_accounts.c.company_name).order_by(
        func.lower(crm_accounts.c.company_name)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def list_contacts_for_account_select(account_id: int | None) -> list[dict]:
    if not account_id:
        return []

    statement = (
        select(
            crm_contacts.c.id,
            crm_contacts.c.first_name,
            crm_contacts.c.last_name,
        )
        .where(crm_contacts.c.account_id == account_id)
        .order_by(crm_contacts.c.last_name, crm_contacts.c.first_name)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def create_contact(payload: dict) -> int:
    statement = insert(crm_contacts).values(**payload).returning(crm_contacts.c.id)
    with get_connection() as connection:
        contact_id = connection.execute(statement).scalar_one()
    return int(contact_id)


def get_pipeline_stages() -> list[dict]:
    statement = (
        select(crm_pipeline_stages)
        .where(crm_pipeline_stages.c.is_active.is_(True))
        .order_by(crm_pipeline_stages.c.display_order)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_pipeline_stage(stage_key: str) -> dict | None:
    statement = select(crm_pipeline_stages).where(crm_pipeline_stages.c.stage_key == stage_key)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def upsert_pipeline_stage(payload: dict) -> int:
    existing = get_pipeline_stage(payload["stage_key"])
    if existing:
        statement = (
            update(crm_pipeline_stages)
            .where(crm_pipeline_stages.c.id == existing["id"])
            .values(
                display_name=payload["display_name"],
                display_order=payload["display_order"],
                default_probability=payload["default_probability"],
                is_active=payload["is_active"],
            )
            .returning(crm_pipeline_stages.c.id)
        )
    else:
        statement = insert(crm_pipeline_stages).values(**payload).returning(crm_pipeline_stages.c.id)
    with get_connection() as connection:
        stage_id = connection.execute(statement).scalar_one()
    return int(stage_id)


def opportunities_by_stage() -> list[dict]:
    account = crm_accounts.alias("account")
    statement = (
        select(
            crm_opportunities,
            account.c.company_name.label("account_name"),
        )
        .select_from(crm_opportunities.join(account, crm_opportunities.c.account_id == account.c.id))
        .order_by(crm_opportunities.c.stage, crm_opportunities.c.expected_close_date, crm_opportunities.c.id.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def create_opportunity_line(payload: dict) -> int:
    clean = {
        "opportunity_id": payload["opportunity_id"],
        "brand": payload["brand"],
        "model": payload["model"],
        "grade": payload.get("grade"),
        "category": payload.get("category"),
        "storage": payload.get("storage"),
        "quantity": int(payload["quantity"]),
        "unit_price": _normalize_decimal(payload["unit_price"]),
        "notes": payload.get("notes"),
    }
    statement = insert(crm_opportunity_lines).values(**clean).returning(crm_opportunity_lines.c.id)
    with get_connection() as connection:
        line_id = connection.execute(statement).scalar_one()
    _recalculate_opportunity_amount(payload["opportunity_id"])
    return int(line_id)


def _recalculate_opportunity_amount(opportunity_id: int) -> None:
    total_statement = select(
        func.coalesce(func.sum(crm_opportunity_lines.c.quantity * crm_opportunity_lines.c.unit_price), 0)
    ).where(crm_opportunity_lines.c.opportunity_id == opportunity_id)
    with get_connection() as connection:
        total = connection.execute(total_statement).scalar_one()
        connection.execute(
            update(crm_opportunities)
            .where(crm_opportunities.c.id == opportunity_id)
            .values(amount=total, updated_at=datetime.now(timezone.utc))
        )
