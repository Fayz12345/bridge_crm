from flask import flash, g, render_template

from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.whatsapp.queries import create_whatsapp_message
from bridge_crm.config import get_settings
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    _extract_message_id,
    provider_name,
    send_outreach_template,
    whatsapp_configured,
)


def render_bulk_whatsapp_page(
    *,
    records: list[dict],
    return_to: str,
    body_text: str,
    entity_label: str,
    compose_endpoint: str,
    send_endpoint: str,
):
    ready = whatsapp_configured()
    return render_template(
        "communications/bulk_whatsapp.html",
        records=records,
        return_to=return_to,
        body_text=body_text,
        available_count=sum(1 for row in records if row.get("whatsapp_number")),
        entity_label=entity_label,
        compose_endpoint=compose_endpoint,
        send_endpoint=send_endpoint,
        whatsapp_api_ready=ready,
        whatsapp_provider=provider_name() if ready else "",
        default_template=get_settings().whatsapp_default_template if ready else "",
    )


def send_bulk_whatsapp(
    *,
    records: list[dict],
    body_text: str,
    related_type: str,
    return_to: str,
):
    if not whatsapp_configured():
        flash(
            "Wati is not configured. Set WHATSAPP_PROVIDER=wati, "
            "WATI_API_ENDPOINT, WATI_ACCESS_TOKEN, and WHATSAPP_DEFAULT_TEMPLATE.",
            "warning",
        )
        return False

    if not body_text.strip():
        flash("Message body is required for bulk WhatsApp sends.", "danger")
        return False

    rep_name = (g.user or {}).get("full_name") or "Bridge Wireless"
    sent_count = 0
    skipped_count = 0
    failed_count = 0

    for record in records:
        phone = record.get("whatsapp_number")
        if not phone:
            skipped_count += 1
            continue

        contact_name = record.get("display_name") or "there"
        try:
            response = send_outreach_template(
                phone,
                contact_name=contact_name,
                rep_name=rep_name,
                message_body=body_text,
            )
            wa_message_id = _extract_message_id(response)
            template_name = get_settings().whatsapp_default_template
            create_whatsapp_message(
                direction="outbound",
                related_type=related_type,
                related_id=int(record["id"]),
                to_number=phone,
                from_number=None,
                message_type="template",
                body=body_text,
                template_name=template_name,
                status="sent",
                wa_message_id=wa_message_id,
                sent_by=g.user["id"] if g.user else None,
            )
            log_activity(
                related_type,
                int(record["id"]),
                "whatsapp_sent",
                f"WhatsApp template sent to {phone}.",
                g.user["id"] if g.user else None,
                {"wa_message_id": wa_message_id, "template": True},
            )
            sent_count += 1
        except WhatsAppAPIError as exc:
            create_whatsapp_message(
                direction="outbound",
                related_type=related_type,
                related_id=int(record["id"]),
                to_number=phone,
                from_number=None,
                message_type="template",
                body=body_text,
                template_name=get_settings().whatsapp_default_template,
                status="failed",
                wa_message_id=None,
                sent_by=g.user["id"] if g.user else None,
            )
            failed_count += 1
            flash(f"Failed for {contact_name}: {exc}", "warning")

    if sent_count:
        flash(f"Sent {sent_count} WhatsApp message(s) via API.", "success")
    if skipped_count:
        flash(f"Skipped {skipped_count} record(s) without a WhatsApp number.", "warning")
    if failed_count and not sent_count:
        flash("No WhatsApp messages were sent.", "danger")
    return sent_count > 0
