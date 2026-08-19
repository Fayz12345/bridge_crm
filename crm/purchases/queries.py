from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, func, insert, select, update

from bridge_crm.crm.purchases.constants import (
    DEFAULT_PURCHASE_CURRENCY,
    purchase_total_cad_expression,
)
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_contacts,
    crm_purchase_lines,
    crm_purchase_stages,
    crm_purchases,
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


def list_purchases(stage: str | None = None) -> list[dict]:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_purchases,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("owner_name"),
            purchase_total_cad_expression().label("estimated_total_cad"),
        )
        .select_from(
            crm_purchases.join(account, crm_purchases.c.account_id == account.c.id).outerjoin(
                owner, crm_purchases.c.owner_id == owner.c.id
            )
        )
        .order_by(crm_purchases.c.created_at.desc(), crm_purchases.c.id.desc())
    )
    if stage:
        statement = statement.where(crm_purchases.c.stage == stage)

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_purchase(purchase_id: int) -> dict | None:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    contact = crm_contacts.alias("contact")
    statement = (
        select(
            crm_purchases,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("owner_name"),
            account.c.email.label("account_email"),
            account.c.phone.label("account_phone"),
            account.c.phone_prefix.label("account_phone_prefix"),
            account.c.address_line_1.label("account_address_line_1"),
            account.c.address_line_2.label("account_address_line_2"),
            account.c.city.label("account_city"),
            account.c.state_province.label("account_state_province"),
            account.c.postal_code.label("account_postal_code"),
            account.c.country.label("account_country"),
            contact.c.first_name.label("contact_first_name"),
            contact.c.last_name.label("contact_last_name"),
            contact.c.email.label("contact_email"),
            contact.c.phone.label("contact_phone"),
            contact.c.phone_prefix.label("contact_phone_prefix"),
            purchase_total_cad_expression().label("estimated_total_cad"),
        )
        .select_from(
            crm_purchases.join(account, crm_purchases.c.account_id == account.c.id)
            .outerjoin(owner, crm_purchases.c.owner_id == owner.c.id)
            .outerjoin(contact, crm_purchases.c.contact_id == contact.c.id)
        )
        .where(crm_purchases.c.id == purchase_id)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def create_purchase(payload: dict) -> int:
    clean = {
        "title": payload["title"].strip(),
        "account_id": payload["account_id"],
        "contact_id": payload.get("contact_id"),
        "stage": payload.get("stage", "prospecting"),
        "estimated_total": _normalize_decimal(payload.get("estimated_total")),
        "currency": payload.get("currency", DEFAULT_PURCHASE_CURRENCY),
        "conversion_rate_to_cad": _normalize_decimal(payload.get("conversion_rate_to_cad"))
        or Decimal(1),
        "expected_delivery_date": _normalize_date(payload.get("expected_delivery_date")),
        "close_date": _normalize_date(payload.get("close_date")),
        "close_reason": payload.get("close_reason"),
        "supplier_quote_number": payload.get("supplier_quote_number"),
        "owner_id": payload.get("owner_id"),
        "notes": payload.get("notes"),
        "custom_fields": payload.get("custom_fields") or {},
        "created_by": payload.get("created_by"),
    }
    statement = insert(crm_purchases).values(**clean).returning(crm_purchases.c.id)
    with get_connection() as connection:
        purchase_id = connection.execute(statement).scalar_one()
    return int(purchase_id)


def update_purchase(purchase_id: int, payload: dict) -> None:
    clean = {
        "title": payload["title"].strip(),
        "account_id": payload["account_id"],
        "contact_id": payload.get("contact_id"),
        "stage": payload.get("stage", "prospecting"),
        "estimated_total": _normalize_decimal(payload.get("estimated_total")),
        "currency": payload.get("currency", DEFAULT_PURCHASE_CURRENCY),
        "conversion_rate_to_cad": _normalize_decimal(payload.get("conversion_rate_to_cad"))
        or Decimal(1),
        "expected_delivery_date": _normalize_date(payload.get("expected_delivery_date")),
        "close_date": _normalize_date(payload.get("close_date")),
        "close_reason": payload.get("close_reason"),
        "supplier_quote_number": payload.get("supplier_quote_number"),
        "owner_id": payload.get("owner_id"),
        "notes": payload.get("notes"),
        "custom_fields": payload.get("custom_fields") or {},
        "updated_at": datetime.now(timezone.utc),
    }
    statement = update(crm_purchases).where(crm_purchases.c.id == purchase_id).values(**clean)
    with get_connection() as connection:
        connection.execute(statement)


def update_purchase_stage(purchase_id: int, stage: str) -> None:
    statement = (
        update(crm_purchases)
        .where(crm_purchases.c.id == purchase_id)
        .values(stage=stage, updated_at=datetime.now(timezone.utc))
    )
    with get_connection() as connection:
        connection.execute(statement)


def delete_purchase(purchase_id: int) -> None:
    with get_connection() as connection:
        connection.execute(delete(crm_purchase_lines).where(crm_purchase_lines.c.purchase_id == purchase_id))
        connection.execute(delete(crm_purchases).where(crm_purchases.c.id == purchase_id))


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
        select(crm_contacts.c.id, crm_contacts.c.first_name, crm_contacts.c.last_name)
        .where(crm_contacts.c.account_id == account_id)
        .order_by(crm_contacts.c.last_name, crm_contacts.c.first_name)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_purchase_stages() -> list[dict]:
    statement = (
        select(crm_purchase_stages)
        .where(crm_purchase_stages.c.is_active.is_(True))
        .order_by(crm_purchase_stages.c.display_order)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_purchase_stage(stage_key: str) -> dict | None:
    statement = select(crm_purchase_stages).where(crm_purchase_stages.c.stage_key == stage_key)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def upsert_purchase_stage(payload: dict) -> int:
    existing = get_purchase_stage(payload["stage_key"])
    if existing:
        statement = (
            update(crm_purchase_stages)
            .where(crm_purchase_stages.c.id == existing["id"])
            .values(
                display_name=payload["display_name"],
                display_order=payload["display_order"],
                default_probability=payload["default_probability"],
                is_active=payload["is_active"],
            )
            .returning(crm_purchase_stages.c.id)
        )
    else:
        statement = insert(crm_purchase_stages).values(**payload).returning(crm_purchase_stages.c.id)
    with get_connection() as connection:
        stage_id = connection.execute(statement).scalar_one()
    return int(stage_id)


def purchases_by_stage() -> list[dict]:
    account = crm_accounts.alias("account")
    statement = (
        select(
            crm_purchases,
            account.c.company_name.label("account_name"),
            purchase_total_cad_expression().label("estimated_total_cad"),
        )
        .select_from(crm_purchases.join(account, crm_purchases.c.account_id == account.c.id))
        .order_by(
            crm_purchases.c.stage,
            crm_purchases.c.expected_delivery_date,
            crm_purchases.c.id.desc(),
        )
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_purchase_line_items(purchase_id: int) -> list[dict]:
    statement = (
        select(crm_purchase_lines)
        .where(crm_purchase_lines.c.purchase_id == purchase_id)
        .order_by(crm_purchase_lines.c.created_at.asc(), crm_purchase_lines.c.id.asc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def create_purchase_line(payload: dict) -> int:
    clean = {
        "purchase_id": payload["purchase_id"],
        "brand": payload["brand"],
        "model": payload["model"],
        "grade": payload.get("grade"),
        "category": payload.get("category"),
        "storage": payload.get("storage"),
        "quantity": int(payload["quantity"]),
        "unit_cost": _normalize_decimal(payload["unit_cost"]),
        "notes": payload.get("notes"),
    }
    statement = insert(crm_purchase_lines).values(**clean).returning(crm_purchase_lines.c.id)
    with get_connection() as connection:
        line_id = connection.execute(statement).scalar_one()
    _recalculate_purchase_total(payload["purchase_id"])
    return int(line_id)


def get_purchase_line(purchase_id: int, line_id: int) -> dict | None:
    statement = select(crm_purchase_lines).where(
        crm_purchase_lines.c.id == line_id,
        crm_purchase_lines.c.purchase_id == purchase_id,
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def update_purchase_line(purchase_id: int, line_id: int, payload: dict) -> None:
    clean = {
        "brand": payload["brand"],
        "model": payload["model"],
        "grade": payload.get("grade"),
        "category": payload.get("category"),
        "storage": payload.get("storage"),
        "quantity": int(payload["quantity"]),
        "unit_cost": _normalize_decimal(payload["unit_cost"]),
        "notes": payload.get("notes"),
        "updated_at": datetime.now(timezone.utc),
    }
    statement = (
        update(crm_purchase_lines)
        .where(
            crm_purchase_lines.c.id == line_id,
            crm_purchase_lines.c.purchase_id == purchase_id,
        )
        .values(**clean)
    )
    with get_connection() as connection:
        connection.execute(statement)
    _recalculate_purchase_total(purchase_id)


def delete_purchase_line(purchase_id: int, line_id: int) -> None:
    statement = delete(crm_purchase_lines).where(
        crm_purchase_lines.c.id == line_id,
        crm_purchase_lines.c.purchase_id == purchase_id,
    )
    with get_connection() as connection:
        connection.execute(statement)
    _recalculate_purchase_total(purchase_id)


def _recalculate_purchase_total(purchase_id: int) -> None:
    total_statement = select(
        func.coalesce(func.sum(crm_purchase_lines.c.quantity * crm_purchase_lines.c.unit_cost), 0)
    ).where(crm_purchase_lines.c.purchase_id == purchase_id)
    with get_connection() as connection:
        total = connection.execute(total_statement).scalar_one()
        connection.execute(
            update(crm_purchases)
            .where(crm_purchases.c.id == purchase_id)
            .values(estimated_total=total, updated_at=datetime.now(timezone.utc))
        )
