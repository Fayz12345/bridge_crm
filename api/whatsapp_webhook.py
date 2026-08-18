import logging

from flask import Blueprint, current_app, request

from bridge_crm.config import get_settings
from bridge_crm.crm.whatsapp.inbound import record_inbound_message
from bridge_crm.crm.whatsapp.queries import update_whatsapp_message_status

logger = logging.getLogger(__name__)

whatsapp_webhook_bp = Blueprint("whatsapp_webhook", __name__, url_prefix="/api/whatsapp")


@whatsapp_webhook_bp.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    expected = get_settings().whatsapp_webhook_verify_token

    if mode == "subscribe" and token and token == expected:
        logger.info("WhatsApp webhook verified")
        return challenge or "", 200

    logger.warning("WhatsApp webhook verification failed")
    return "Forbidden", 403


@whatsapp_webhook_bp.route("/webhook", methods=["POST"])
def receive_webhook():
    payload = request.get_json(silent=True) or {}
    if payload.get("object") != "whatsapp_business_account":
        return "ignored", 200

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            _process_status_updates(value.get("statuses") or [])
            _process_inbound_messages(value.get("messages") or [], value.get("contacts") or [])

    return "ok", 200


def _process_status_updates(statuses: list) -> None:
    for item in statuses:
        wa_message_id = item.get("id")
        status = item.get("status")
        if wa_message_id and status in {"sent", "delivered", "read", "failed"}:
            try:
                update_whatsapp_message_status(wa_message_id, status)
            except Exception:
                current_app.logger.exception("Failed to update WhatsApp status %s", wa_message_id)


def _process_inbound_messages(messages: list, contacts: list) -> None:
    contact_names = {
        item.get("wa_id"): item.get("profile", {}).get("name")
        for item in contacts
        if item.get("wa_id")
    }

    for message in messages:
        if message.get("type") != "text":
            continue

        from_number = message.get("from")
        body = (message.get("text") or {}).get("body", "")
        wa_message_id = message.get("id")
        if not from_number or not body:
            continue

        record_inbound_message(
            from_number=from_number,
            body=body,
            wa_message_id=wa_message_id,
            sender_name=contact_names.get(from_number),
            message_type="text",
            notify=True,
            log=True,
        )
