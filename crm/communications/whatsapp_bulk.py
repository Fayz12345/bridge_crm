import logging
from datetime import datetime, timezone

from flask import flash, g, render_template

from bridge_crm.config import get_settings
from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.whatsapp.queries import create_whatsapp_message
from bridge_crm.crm.whatsapp.template_queries import list_approved_templates
from bridge_crm.integrations.wati import outreach_parameters
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    _extract_message_id,
    normalize_whatsapp_number,
    provider_name,
    send_outreach_template,
    send_template_broadcast,
    templates_ready,
    whatsapp_configured,
)

logger = logging.getLogger(__name__)


def render_bulk_whatsapp_page(
    *,
    records: list[dict],
    return_to: str,
    body_text: str = "",
    entity_label: str,
    compose_endpoint: str,
    send_endpoint: str,
    broadcast_name: str = "",
    template_name: str = "",
    entity: str = "",
):
    ready = whatsapp_configured()
    settings = get_settings()
    approved_templates = list_approved_templates() if ready else []
    templates_are_ready = templates_ready() or bool(approved_templates)
    return render_template(
        "communications/bulk_whatsapp.html",
        records=records,
        return_to=return_to,
        body_text=body_text,
        broadcast_name=broadcast_name,
        template_name=template_name or settings.whatsapp_default_template,
        available_count=sum(1 for row in records if row.get("whatsapp_number")),
        entity_label=entity_label,
        compose_endpoint=compose_endpoint,
        send_endpoint=send_endpoint,
        entity=entity,
        whatsapp_api_ready=ready,
        whatsapp_templates_ready=templates_are_ready,
        whatsapp_provider=provider_name() if ready else "",
        default_template=settings.whatsapp_default_template if ready else "",
        approved_templates=approved_templates,
    )


def send_bulk_whatsapp(
    *,
    records: list[dict],
    body_text: str = "",
    related_type: str,
    return_to: str,
    broadcast_name: str = "",
    template_name: str = "",
):
    if not whatsapp_configured():
        flash(
            "Wati is not configured. Set WHATSAPP_PROVIDER=wati, "
            "WATI_API_ENDPOINT, and WATI_ACCESS_TOKEN.",
            "warning",
        )
        return False

    body_text = (body_text or "").strip()

    settings = get_settings()
    template = (template_name or settings.whatsapp_default_template).strip()
    if not template:
        flash("Choose an approved WhatsApp template before broadcasting.", "danger")
        return False
    campaign = (broadcast_name or "").strip() or _default_broadcast_name(related_type)
    rep_name = (g.user or {}).get("full_name") or "Bridge Wireless"
    skipped_count = sum(1 for record in records if not record.get("whatsapp_number"))
    ready_records = [record for record in records if record.get("whatsapp_number")]

    if not ready_records:
        flash("None of the selected records have a WhatsApp number.", "warning")
        return False

    sent = False
    if provider_name() == "wati":
        sent = _send_wati_broadcast(
            ready_records,
            related_type=related_type,
            body_text=body_text,
            template=template,
            campaign=campaign,
            rep_name=rep_name,
        )
    if not sent:
        sent = _send_one_by_one(
            ready_records,
            related_type=related_type,
            body_text=body_text,
            template=template,
            campaign=campaign,
            rep_name=rep_name,
        )

    if skipped_count:
        flash(f"Skipped {skipped_count} record(s) without a WhatsApp number.", "warning")
    return sent


def _default_broadcast_name(related_type: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return f"crm_{related_type}_{stamp}"[:100]


def _send_wati_broadcast(
    records: list[dict],
    *,
    related_type: str,
    body_text: str,
    template: str,
    campaign: str,
    rep_name: str,
) -> bool:
    receivers = []
    for record in records:
        number = normalize_whatsapp_number(record.get("whatsapp_number"))
        if not number:
            continue
        receivers.append(
            {
                "whatsapp_number": number,
                "parameters": outreach_parameters(
                    record.get("display_name") or "there",
                    rep_name,
                    body_text,
                ),
                "record": record,
            }
        )
    if not receivers:
        return False

    try:
        send_template_broadcast(
            receivers,
            template_name=template,
            broadcast_name=campaign,
        )
    except WhatsAppAPIError as exc:
        logger.warning("Wati bulk broadcast failed (%s); sending one by one.", exc)
        return False

    for item in receivers:
        record = item["record"]
        create_whatsapp_message(
            direction="outbound",
            related_type=related_type,
            related_id=int(record["id"]),
            to_number=item["whatsapp_number"],
            from_number=None,
            message_type="template",
            body=body_text or f"Template {template}",
            template_name=template,
            status="sent",
            wa_message_id=None,
            sent_by=g.user["id"] if g.user else None,
        )
        log_activity(
            related_type,
            int(record["id"]),
            "whatsapp_sent",
            f"WhatsApp broadcast '{campaign}' sent to {item['whatsapp_number']}.",
            g.user["id"] if g.user else None,
            {"template": True, "broadcast": campaign},
        )
    flash(f"Broadcast '{campaign}' sent to {len(receivers)} recipient(s) via Wati.", "success")
    return True


def _send_one_by_one(
    records: list[dict],
    *,
    related_type: str,
    body_text: str,
    template: str,
    campaign: str,
    rep_name: str,
) -> bool:
    sent_count = 0
    failed_count = 0
    for record in records:
        phone = record.get("whatsapp_number")
        contact_name = record.get("display_name") or "there"
        try:
            response = send_outreach_template(
                phone,
                contact_name=contact_name,
                rep_name=rep_name,
                message_body=body_text,
                template_name=template,
                broadcast_name=campaign,
            )
            wa_message_id = _extract_message_id(response)
            create_whatsapp_message(
                direction="outbound",
                related_type=related_type,
                related_id=int(record["id"]),
                to_number=phone,
                from_number=None,
                message_type="template",
                body=body_text or f"Template {template}",
                template_name=template,
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
                {"wa_message_id": wa_message_id, "template": True, "broadcast": campaign},
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
                body=body_text or f"Template {template}",
                template_name=template,
                status="failed",
                wa_message_id=None,
                sent_by=g.user["id"] if g.user else None,
            )
            failed_count += 1
            flash(f"Failed for {contact_name}: {exc}", "warning")

    if sent_count:
        flash(f"Sent {sent_count} WhatsApp message(s) in campaign '{campaign}'.", "success")
    if failed_count and not sent_count:
        flash("No WhatsApp messages were sent.", "danger")
    return sent_count > 0
