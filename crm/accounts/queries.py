from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, or_, select, update

from bridge_crm.crm.segments.queries import (
    list_account_product_interests_map,
    list_account_tags_map,
)
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_account_product_interests,
    crm_account_tags,
    crm_contacts,
    crm_leads,
    crm_opportunities,
    crm_opportunity_lines,
    crm_tags,
    crm_users,
)


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_phone_prefix(value, phone=None):
    value = _clean(value)
    phone = _clean(phone)
    if not value:
        return "+1"
    if phone and value == phone:
        return "+1"
    if len(value) > 8:
        return None
    return value


def _attach_account_segments(accounts: list[dict]) -> list[dict]:
    account_ids = [int(account["id"]) for account in accounts]
    interests_map = list_account_product_interests_map(account_ids)
    tags_map = list_account_tags_map(account_ids)
    whatsapp_map = _list_primary_contact_whatsapp_map(account_ids)
    for account in accounts:
        account_id = int(account["id"])
        account["product_interests"] = interests_map.get(account_id, [])
        account["tags"] = tags_map.get(account_id, [])
        account["whatsapp_number"] = whatsapp_map.get(account_id)
    return accounts


def _list_primary_contact_whatsapp_map(account_ids: list[int]) -> dict[int, str]:
    if not account_ids:
        return {}
    statement = (
        select(
            crm_contacts.c.account_id,
            crm_contacts.c.whatsapp_number,
            crm_contacts.c.is_primary,
            crm_contacts.c.updated_at,
            crm_contacts.c.id,
        )
        .where(
            crm_contacts.c.account_id.in_(account_ids),
            crm_contacts.c.whatsapp_number.is_not(None),
        )
        .order_by(
            crm_contacts.c.account_id,
            crm_contacts.c.is_primary.desc(),
            crm_contacts.c.updated_at.desc(),
            crm_contacts.c.id.desc(),
        )
    )
    result: dict[int, str] = {}
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    for row in rows:
        account_id = int(row["account_id"])
        if account_id not in result and row["whatsapp_number"]:
            result[account_id] = row["whatsapp_number"]
    return result


def list_accounts(
    search_term: str | None = None,
    owner_id: int | None = None,
    product_interest_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
) -> list[dict]:
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_accounts,
            owner.c.full_name.label("owner_name"),
        )
        .select_from(crm_accounts.outerjoin(owner, crm_accounts.c.owner_id == owner.c.id))
        .order_by(func.lower(crm_accounts.c.company_name))
    )

    if owner_id:
        statement = statement.where(crm_accounts.c.owner_id == owner_id)

    if search_term:
        pattern = f"%{search_term.strip()}%"
        statement = statement.where(
            or_(
                crm_accounts.c.company_name.ilike(pattern),
                crm_accounts.c.contact_name.ilike(pattern),
                crm_accounts.c.email.ilike(pattern),
                crm_accounts.c.erp_client_id.ilike(pattern),
            )
        )

    if product_interest_ids:
        statement = statement.where(
            select(crm_account_product_interests.c.account_id)
            .where(
                crm_account_product_interests.c.account_id == crm_accounts.c.id,
                crm_account_product_interests.c.interest_option_id.in_(product_interest_ids),
            )
            .exists()
        )

    if tag_ids:
        statement = statement.where(
            select(crm_account_tags.c.account_id)
            .where(
                crm_account_tags.c.account_id == crm_accounts.c.id,
                crm_account_tags.c.tag_id.in_(tag_ids),
            )
            .exists()
        )

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return _attach_account_segments([dict(row) for row in rows])


def get_account(account_id: int) -> dict | None:
    owner = crm_users.alias("owner")
    creator = crm_users.alias("creator")
    statement = (
        select(
            crm_accounts,
            owner.c.full_name.label("owner_name"),
            creator.c.full_name.label("created_by_name"),
        )
        .select_from(
            crm_accounts.outerjoin(owner, crm_accounts.c.owner_id == owner.c.id).outerjoin(
                creator, crm_accounts.c.created_by == creator.c.id
            )
        )
        .where(crm_accounts.c.id == account_id)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    if not row:
        return None
    return _attach_account_segments([dict(row)])[0]


def get_accounts_by_ids(account_ids: list[int]) -> list[dict]:
    if not account_ids:
        return []
    owner = crm_users.alias("owner")
    statement = (
        select(crm_accounts, owner.c.full_name.label("owner_name"))
        .select_from(crm_accounts.outerjoin(owner, crm_accounts.c.owner_id == owner.c.id))
        .where(crm_accounts.c.id.in_(account_ids))
        .order_by(func.lower(crm_accounts.c.company_name), crm_accounts.c.id)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return _attach_account_segments([dict(row) for row in rows])


def list_contacts_for_account(account_id: int) -> list[dict]:
    statement = (
        select(crm_contacts)
        .where(crm_contacts.c.account_id == account_id)
        .order_by(crm_contacts.c.is_primary.desc(), crm_contacts.c.last_name, crm_contacts.c.first_name)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_contact_for_account(account_id: int, contact_id: int) -> dict | None:
    statement = select(crm_contacts).where(
        crm_contacts.c.account_id == account_id,
        crm_contacts.c.id == contact_id,
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def get_account_by_erp_client_id(erp_client_id: str, exclude_account_id: int | None = None):
    statement = select(crm_accounts.c.id).where(crm_accounts.c.erp_client_id == erp_client_id)
    if exclude_account_id:
        statement = statement.where(crm_accounts.c.id != exclude_account_id)
    with get_connection() as connection:
        row = connection.execute(statement).first()
    return row[0] if row else None


def create_account(payload: dict) -> int:
    values = {
        **payload,
        "company_name": str(payload["company_name"]).strip(),
        "contact_name": _clean(payload.get("contact_name")),
        "email": (_clean(payload.get("email")) or "").lower() or None,
        "phone": _clean(payload.get("phone")),
        "phone_prefix": _normalize_phone_prefix(
            payload.get("phone_prefix"), payload.get("phone")
        ),
        "website": _clean(payload.get("website")),
        "notes": _clean(payload.get("notes")),
        "custom_fields": payload.get("custom_fields") or {},
    }
    statement = insert(crm_accounts).values(**values).returning(crm_accounts.c.id)
    with get_connection() as connection:
        account_id = connection.execute(statement).scalar_one()
    return int(account_id)


def update_account(account_id: int, payload: dict) -> None:
    values = {
        **payload,
        "company_name": str(payload["company_name"]).strip(),
        "contact_name": _clean(payload.get("contact_name")),
        "email": (_clean(payload.get("email")) or "").lower() or None,
        "phone": _clean(payload.get("phone")),
        "phone_prefix": _normalize_phone_prefix(
            payload.get("phone_prefix"), payload.get("phone")
        ),
        "website": _clean(payload.get("website")),
        "notes": _clean(payload.get("notes")),
        "custom_fields": payload.get("custom_fields") or {},
        "updated_at": datetime.now(timezone.utc),
    }
    statement = update(crm_accounts).where(crm_accounts.c.id == account_id).values(**values)
    with get_connection() as connection:
        connection.execute(statement)


def _normalize_contact_values(payload: dict) -> dict:
    clean = {
        "account_id": payload["account_id"],
        "first_name": str(payload["first_name"]).strip(),
        "last_name": str(payload["last_name"]).strip(),
        "email": (_clean(payload.get("email")) or "").lower() or None,
        "phone": _clean(payload.get("phone")),
        "phone_prefix": _normalize_phone_prefix(
            payload.get("phone_prefix"), payload.get("phone")
        ),
        "job_title": _clean(payload.get("job_title")),
        "is_primary": bool(payload.get("is_primary")),
        "whatsapp_number": _clean(payload.get("whatsapp_number")),
    }
    return clean


def _has_other_primary_contact(connection, account_id: int, exclude_contact_id: int | None = None) -> bool:
    statement = select(crm_contacts.c.id).where(
        crm_contacts.c.account_id == account_id,
        crm_contacts.c.is_primary.is_(True),
    )
    if exclude_contact_id is not None:
        statement = statement.where(crm_contacts.c.id != exclude_contact_id)
    return connection.execute(statement.limit(1)).first() is not None


def _demote_other_primary_contacts(connection, account_id: int, keep_contact_id: int) -> None:
    statement = (
        update(crm_contacts)
        .where(
            crm_contacts.c.account_id == account_id,
            crm_contacts.c.id != keep_contact_id,
            crm_contacts.c.is_primary.is_(True),
        )
        .values(is_primary=False, updated_at=datetime.now(timezone.utc))
    )
    connection.execute(statement)


def _sync_account_primary_contact(connection, account_id: int) -> None:
    primary_statement = (
        select(crm_contacts)
        .where(crm_contacts.c.account_id == account_id, crm_contacts.c.is_primary.is_(True))
        .order_by(crm_contacts.c.updated_at.desc(), crm_contacts.c.id.desc())
        .limit(1)
    )
    row = connection.execute(primary_statement).mappings().first()

    if not row:
        fallback_statement = (
            select(crm_contacts)
            .where(crm_contacts.c.account_id == account_id)
            .order_by(crm_contacts.c.created_at.asc(), crm_contacts.c.id.asc())
            .limit(1)
        )
        row = connection.execute(fallback_statement).mappings().first()

    if not row:
        return

    primary_contact = dict(row)
    connection.execute(
        update(crm_accounts)
        .where(crm_accounts.c.id == account_id)
        .values(
            contact_name=f"{primary_contact['first_name']} {primary_contact['last_name']}".strip(),
            email=primary_contact["email"],
            phone=primary_contact["phone"],
            phone_prefix=primary_contact["phone_prefix"],
            updated_at=datetime.now(timezone.utc),
        )
    )


def create_contact_for_account(payload: dict) -> int:
    clean = _normalize_contact_values(payload)
    with get_connection() as connection:
        existing_contacts = connection.execute(
            select(func.count()).select_from(crm_contacts).where(crm_contacts.c.account_id == clean["account_id"])
        ).scalar_one()
        if int(existing_contacts) == 0:
            clean["is_primary"] = True

        statement = insert(crm_contacts).values(**clean).returning(crm_contacts.c.id)
        contact_id = int(connection.execute(statement).scalar_one())

        if clean["is_primary"]:
            _demote_other_primary_contacts(connection, clean["account_id"], contact_id)

        _sync_account_primary_contact(connection, clean["account_id"])

    return contact_id


def update_contact_for_account(account_id: int, contact_id: int, payload: dict) -> None:
    clean = _normalize_contact_values(payload)
    clean["updated_at"] = datetime.now(timezone.utc)
    with get_connection() as connection:
        if not clean["is_primary"] and not _has_other_primary_contact(
            connection, account_id, exclude_contact_id=contact_id
        ):
            clean["is_primary"] = True

        connection.execute(
            update(crm_contacts)
            .where(crm_contacts.c.account_id == account_id, crm_contacts.c.id == contact_id)
            .values(**clean)
        )

        if clean["is_primary"]:
            _demote_other_primary_contacts(connection, account_id, contact_id)

        _sync_account_primary_contact(connection, account_id)


def delete_account(account_id: int) -> None:
    with get_connection() as connection:
        opp_ids = [
            row[0]
            for row in connection.execute(
                select(crm_opportunities.c.id).where(
                    crm_opportunities.c.account_id == account_id
                )
            ).all()
        ]
        if opp_ids:
            connection.execute(
                delete(crm_opportunity_lines).where(
                    crm_opportunity_lines.c.opportunity_id.in_(opp_ids)
                )
            )
            connection.execute(
                update(crm_leads)
                .where(crm_leads.c.converted_opportunity_id.in_(opp_ids))
                .values(converted_opportunity_id=None)
            )
            connection.execute(
                delete(crm_opportunities).where(
                    crm_opportunities.c.account_id == account_id
                )
            )
        connection.execute(
            update(crm_leads)
            .where(crm_leads.c.converted_account_id == account_id)
            .values(converted_account_id=None)
        )
        connection.execute(
            delete(crm_contacts).where(crm_contacts.c.account_id == account_id)
        )
        connection.execute(
            delete(crm_accounts).where(crm_accounts.c.id == account_id)
        )


def list_account_tag_options() -> list[dict]:
    statement = select(crm_tags).order_by(func.lower(crm_tags.c.tag_name), crm_tags.c.id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]
