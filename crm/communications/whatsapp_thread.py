from flask import abort, flash, g, redirect, url_for

from bridge_crm.config import get_settings
from bridge_crm.crm.accounts.queries import get_account, list_contacts_for_account
from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.leads.queries import get_lead
from bridge_crm.crm.whatsapp.inbound import sync_conversation_from_provider
from bridge_crm.crm.whatsapp.queries import create_whatsapp_message, list_whatsapp_messages
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    _extract_message_id,
    normalize_whatsapp_number,
    provider_name,
    send_outreach_template,
    send_session_message,
    templates_ready,
    whatsapp_configured,
)


def conversation_context(
    related_type: str,
    related_id: int,
    phone: str | None,
    *,
    sync: bool = False,
    min_interval_seconds: int = 0,
) -> dict:
    if sync:
        sync_conversation_from_provider(
            related_type,
            related_id,
            phone,
            min_interval_seconds=min_interval_seconds,
        )
    messages = list(reversed(list_whatsapp_messages(related_type, related_id)))
    return {
        "whatsapp_messages": messages,
        "whatsapp_phone": phone or "",
        "whatsapp_api_ready": whatsapp_configured(),
        "whatsapp_templates_ready": templates_ready(),
        "whatsapp_provider": provider_name(),
        "whatsapp_default_template": get_settings().whatsapp_default_template,
        "whatsapp_messages_url": url_for(
            "communications.thread_messages_view",
            related_type=related_type,
            related_id=related_id,
        ),
    }


def resolve_thread_phone(related_type: str, related_id: int) -> str | None:
    if related_type == "lead":
        lead = get_lead(related_id)
        if not lead:
            return None
        return _format_phone(lead.get("phone_prefix"), lead.get("phone"))
    if related_type == "account":
        account = get_account(related_id)
        if not account:
            return None
        contacts = list_contacts_for_account(related_id)
        for contact in contacts:
            phone = contact.get("whatsapp_number") or _format_phone(
                contact.get("phone_prefix"), contact.get("phone")
            )
            if phone:
                return phone
        return _format_phone(account.get("phone_prefix"), account.get("phone"))
    return None


def require_thread_entity(related_type: str, related_id: int) -> str | None:
    phone = resolve_thread_phone(related_type, related_id)
    if related_type == "lead" and not get_lead(related_id):
        abort(404)
    if related_type == "account" and not get_account(related_id):
        abort(404)
    return phone


def _format_phone(phone_prefix: str | None, phone: str | None) -> str | None:
    raw = f"{phone_prefix or ''}{phone or ''}".strip()
    if not raw:
        return None
    normalized = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    return normalized or None


def send_entity_whatsapp(
    *,
    related_type: str,
    related_id: int,
    phone: str | None,
    message_type: str,
    body_text: str,
    contact_name: str,
    redirect_endpoint: str,
    redirect_kwargs: dict,
):
    if not whatsapp_configured():
        flash("Wati is not configured. Set WATI_API_ENDPOINT and WATI_ACCESS_TOKEN in .env.", "warning")
        return redirect(url_for(redirect_endpoint, **redirect_kwargs))

    digits = normalize_whatsapp_number(phone)
    if not digits:
        flash("No valid WhatsApp number on this record.", "danger")
        return redirect(url_for(redirect_endpoint, **redirect_kwargs))

    body = (body_text or "").strip()
    if not body:
        flash("Message text is required.", "danger")
        return redirect(url_for(redirect_endpoint, **redirect_kwargs))

    rep_name = (g.user or {}).get("full_name") or "Bridge Wireless"
    use_template = message_type == "template"
    try:
        if use_template:
            response = send_outreach_template(
                digits,
                contact_name=contact_name or "there",
                rep_name=rep_name,
                message_body=body,
            )
            description = f"WhatsApp template sent to {digits}."
            stored_type = "template"
            template_name = get_settings().whatsapp_default_template
        else:
            response = send_session_message(digits, body)
            description = f"WhatsApp session message sent to {digits}."
            stored_type = "text"
            template_name = None

        wa_message_id = _extract_message_id(response)
        create_whatsapp_message(
            direction="outbound",
            related_type=related_type,
            related_id=related_id,
            to_number=digits,
            from_number=None,
            message_type=stored_type,
            body=body,
            template_name=template_name,
            status="sent",
            wa_message_id=wa_message_id,
            sent_by=g.user["id"] if g.user else None,
        )
        log_activity(
            related_type,
            related_id,
            "whatsapp_sent",
            description,
            g.user["id"] if g.user else None,
            {"wa_message_id": wa_message_id, "provider": provider_name(), "type": stored_type},
        )
        flash("WhatsApp message sent.", "success")
    except WhatsAppAPIError as exc:
        create_whatsapp_message(
            direction="outbound",
            related_type=related_type,
            related_id=related_id,
            to_number=digits,
            from_number=None,
            message_type="template" if use_template else "text",
            body=body,
            template_name=get_settings().whatsapp_default_template if use_template else None,
            status="failed",
            wa_message_id=None,
            sent_by=g.user["id"] if g.user else None,
        )
        flash(f"WhatsApp send failed: {exc}", "danger")

    return redirect(url_for(redirect_endpoint, **redirect_kwargs))
