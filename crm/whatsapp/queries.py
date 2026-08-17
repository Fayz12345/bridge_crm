from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_accounts, crm_contacts, crm_leads, crm_whatsapp_messages


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
) -> int:
    now = datetime.now(timezone.utc)
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
            sent_at=now if direction == "outbound" else None,
            sent_by=sent_by,
        )
        .returning(crm_whatsapp_messages.c.id)
    )
    with get_connection() as connection:
        message_id = connection.execute(statement).scalar_one()
    return int(message_id)


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


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _phone_matches(stored: str | None, prefix: str | None, inbound_digits: str) -> bool:
    combined = _digits_only(f"{prefix or ''}{stored or ''}") or _digits_only(stored)
    if not combined or len(inbound_digits) < 8:
        return False
    suffix = inbound_digits[-10:]
    return combined.endswith(suffix) or inbound_digits.endswith(combined[-10:])


def find_related_entity_by_phone(phone: str) -> dict | None:
    """Match inbound WhatsApp number to a lead or account (via contact)."""
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
            )
        ).mappings().all()

        for lead in leads:
            if _phone_matches(lead["phone"], lead["phone_prefix"], inbound_digits):
                name = f"{lead['first_name']} {lead['last_name']}".strip()
                return {
                    "related_type": "lead",
                    "related_id": int(lead["id"]),
                    "display_name": name,
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
                }

    return None
