from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, or_, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_contacts,
    crm_leads,
    crm_whatsapp_messages,
)


def create_whatsapp_message(
    *,
    direction: str,
    related_type: str,
    related_id: int,
    to_number: str | None,
    from_number: str | None,
    message_type: str,
    body: str | None,
    template_name: str | None,
    status: str,
    wa_message_id: str | None,
    sent_by: int | None,
    created_at: datetime | None = None,
) -> int:
    now = datetime.now(timezone.utc)
    recorded_at = created_at or now
    statement = (
        insert(crm_whatsapp_messages)
        .values(
            direction=direction,
            related_type=related_type,
            related_id=related_id,
            to_number=to_number,
            from_number=from_number,
            message_type=message_type,
            body=body,
            template_name=template_name,
            status=status,
            wa_message_id=wa_message_id,
            sent_at=recorded_at if direction == "outbound" else None,
            sent_by=sent_by,
            created_at=recorded_at,
        )
        .returning(crm_whatsapp_messages.c.id)
    )
    with get_connection() as connection:
        message_id = connection.execute(statement).scalar_one()
    return int(message_id)


def get_whatsapp_message_by_wa_ids(wa_message_ids: list[str]) -> dict | None:
    ids = [item.strip() for item in wa_message_ids if item and str(item).strip()]
    if not ids:
        return None
    statement = (
        select(crm_whatsapp_messages)
        .where(crm_whatsapp_messages.c.wa_message_id.in_(ids))
        .order_by(crm_whatsapp_messages.c.id.desc())
        .limit(1)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def similar_whatsapp_message_exists(
    *,
    related_type: str,
    related_id: int,
    direction: str,
    body: str,
    created_at: datetime | None = None,
    window_seconds: int = 180,
) -> bool:
    body = (body or "").strip()
    if not body:
        return False
    when = created_at or datetime.now(timezone.utc)
    window = timedelta(seconds=max(window_seconds, 1))
    statement = (
        select(crm_whatsapp_messages.c.id)
        .where(
            crm_whatsapp_messages.c.related_type == related_type,
            crm_whatsapp_messages.c.related_id == related_id,
            crm_whatsapp_messages.c.direction == direction,
            crm_whatsapp_messages.c.body == body,
            crm_whatsapp_messages.c.created_at >= when - window,
            crm_whatsapp_messages.c.created_at <= when + window,
        )
        .limit(1)
    )
    with get_connection() as connection:
        return connection.execute(statement).first() is not None


def link_unlinked_outbound_message(
    *,
    related_type: str,
    related_id: int,
    body: str,
    wa_message_id: str | None,
) -> bool:
    if not wa_message_id or not (body or "").strip():
        return False
    statement = (
        select(crm_whatsapp_messages.c.id)
        .where(
            crm_whatsapp_messages.c.related_type == related_type,
            crm_whatsapp_messages.c.related_id == related_id,
            crm_whatsapp_messages.c.direction == "outbound",
            crm_whatsapp_messages.c.body == body,
            or_(
                crm_whatsapp_messages.c.wa_message_id.is_(None),
                crm_whatsapp_messages.c.wa_message_id == "",
            ),
        )
        .order_by(crm_whatsapp_messages.c.id.desc())
        .limit(1)
    )
    with get_connection() as connection:
        row = connection.execute(statement).first()
        if not row:
            return False
        connection.execute(
            update(crm_whatsapp_messages)
            .where(crm_whatsapp_messages.c.id == row[0])
            .values(wa_message_id=wa_message_id)
        )
    return True


def update_whatsapp_message_status(wa_message_id: str, status: str) -> None:
    statement = (
        update(crm_whatsapp_messages)
        .where(crm_whatsapp_messages.c.wa_message_id == wa_message_id)
        .values(status=status)
    )
    with get_connection() as connection:
        connection.execute(statement)


def list_whatsapp_messages(related_type: str, related_id: int) -> list[dict]:
    statement = (
        select(crm_whatsapp_messages)
        .where(
            crm_whatsapp_messages.c.related_type == related_type,
            crm_whatsapp_messages.c.related_id == related_id,
        )
        .order_by(crm_whatsapp_messages.c.created_at.desc(), crm_whatsapp_messages.c.id.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def list_recent_conversations(limit: int = 40) -> list[dict]:
    latest = (
        select(
            crm_whatsapp_messages.c.related_type,
            crm_whatsapp_messages.c.related_id,
            func.max(crm_whatsapp_messages.c.id).label("max_id"),
        )
        .group_by(crm_whatsapp_messages.c.related_type, crm_whatsapp_messages.c.related_id)
        .subquery()
    )
    statement = (
        select(crm_whatsapp_messages)
        .join(latest, crm_whatsapp_messages.c.id == latest.c.max_id)
        .order_by(crm_whatsapp_messages.c.created_at.desc(), crm_whatsapp_messages.c.id.desc())
        .limit(limit)
    )
    with get_connection() as connection:
        rows = [dict(row) for row in connection.execute(statement).mappings().all()]

    lead_ids = [row["related_id"] for row in rows if row["related_type"] == "lead"]
    account_ids = [row["related_id"] for row in rows if row["related_type"] == "account"]
    lead_names: dict[int, str] = {}
    account_names: dict[int, str] = {}
    with get_connection() as connection:
        if lead_ids:
            for row in connection.execute(
                select(crm_leads.c.id, crm_leads.c.first_name, crm_leads.c.last_name).where(
                    crm_leads.c.id.in_(lead_ids)
                )
            ).mappings():
                lead_names[int(row["id"])] = f"{row['first_name']} {row['last_name']}".strip() or f"Lead #{row['id']}"
        if account_ids:
            for row in connection.execute(
                select(crm_accounts.c.id, crm_accounts.c.company_name).where(crm_accounts.c.id.in_(account_ids))
            ).mappings():
                account_names[int(row["id"])] = row["company_name"] or f"Account #{row['id']}"

    for row in rows:
        if row["related_type"] == "lead":
            row["display_name"] = lead_names.get(int(row["related_id"]), f"Lead #{row['related_id']}")
        elif row["related_type"] == "account":
            row["display_name"] = account_names.get(int(row["related_id"]), f"Account #{row['related_id']}")
        else:
            row["display_name"] = f"{row['related_type'].title()} #{row['related_id']}"
    return rows


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _phone_matches(stored: str | None, prefix: str | None, inbound_digits: str) -> bool:
    combined = _digits_only(f"{prefix or ''}{stored or ''}") or _digits_only(stored)
    if not combined or len(inbound_digits) < 8:
        return False
    suffix = inbound_digits[-10:]
    return combined.endswith(suffix) or inbound_digits.endswith(combined[-10:])


def find_related_entity_by_phone(phone: str) -> dict | None:
    """Match inbound WhatsApp number to a lead or account (via contact or account phone)."""
    inbound_digits = _digits_only(phone)
    if len(inbound_digits) < 8:
        return None

    with get_connection() as connection:
        leads = connection.execute(
            select(
                crm_leads.c.id,
                crm_leads.c.first_name,
                crm_leads.c.last_name,
                crm_leads.c.phone,
                crm_leads.c.phone_prefix,
                crm_leads.c.owner_id,
                crm_leads.c.status,
                crm_leads.c.converted_account_id,
            )
        ).mappings().all()

        for lead in leads:
            if not _phone_matches(lead["phone"], lead["phone_prefix"], inbound_digits):
                continue
            converted_account_id = lead.get("converted_account_id")
            if lead.get("status") == "converted" and converted_account_id:
                account = connection.execute(
                    select(
                        crm_accounts.c.id,
                        crm_accounts.c.company_name,
                        crm_accounts.c.owner_id,
                    ).where(crm_accounts.c.id == int(converted_account_id))
                ).mappings().first()
                if account:
                    return {
                        "related_type": "account",
                        "related_id": int(account["id"]),
                        "display_name": account["company_name"] or f"Account #{account['id']}",
                        "owner_id": account["owner_id"],
                    }
            name = f"{lead['first_name']} {lead['last_name']}".strip()
            return {
                "related_type": "lead",
                "related_id": int(lead["id"]),
                "display_name": name or f"Lead #{lead['id']}",
                "owner_id": lead["owner_id"],
            }

        contacts = connection.execute(
            select(
                crm_contacts.c.account_id,
                crm_contacts.c.first_name,
                crm_contacts.c.last_name,
                crm_contacts.c.phone,
                crm_contacts.c.phone_prefix,
                crm_contacts.c.whatsapp_number,
                crm_contacts.c.is_primary,
                crm_accounts.c.company_name,
                crm_accounts.c.owner_id,
            )
            .select_from(
                crm_contacts.join(crm_accounts, crm_accounts.c.id == crm_contacts.c.account_id)
            )
            .order_by(crm_contacts.c.is_primary.desc(), crm_contacts.c.id)
        ).mappings().all()

        for contact in contacts:
            if _phone_matches(
                contact["whatsapp_number"] or contact["phone"],
                contact["phone_prefix"],
                inbound_digits,
            ):
                contact_name = f"{contact['first_name']} {contact['last_name']}".strip()
                return {
                    "related_type": "account",
                    "related_id": int(contact["account_id"]),
                    "display_name": contact["company_name"] or contact_name,
                    "owner_id": contact["owner_id"],
                }

        accounts = connection.execute(
            select(
                crm_accounts.c.id,
                crm_accounts.c.company_name,
                crm_accounts.c.phone,
                crm_accounts.c.phone_prefix,
                crm_accounts.c.owner_id,
            )
        ).mappings().all()
        for account in accounts:
            if _phone_matches(account["phone"], account["phone_prefix"], inbound_digits):
                return {
                    "related_type": "account",
                    "related_id": int(account["id"]),
                    "display_name": account["company_name"] or f"Account #{account['id']}",
                    "owner_id": account["owner_id"],
                }

    return None
