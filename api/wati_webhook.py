"""Wati webhook receiver for inbound messages and delivery status."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from bridge_crm.config import get_settings
from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.whatsapp.queries import (
    create_whatsapp_message,
    find_related_entity_by_phone,
    update_whatsapp_message_status,
)
from bridge_crm.integrations.whatsapp import normalize_whatsapp_number

logger = logging.getLogger(__name__)

wati_webhook_bp = Blueprint("wati_webhook", __name__, url_prefix="/api/wati")

INBOUND_EVENTS = {
    "message",
    "messages",
    "messageReceived",
    "messageReceived_v2",
    "incomingMessageReceived",
    "sessionMessageReceived",
    "sessionMessageReceived_v2",
    "templateMessageReplied",
    "templateMessageReplied_v2",
}

STATUS_EVENTS = {
    "templateMessageSent": "sent",
    "templateMessageSent_v2": "sent",
    "sentMessageSENT": "sent",
    "sentMessageSENT_v2": "sent",
    "sentMessageDELIVERED": "delivered",
    "sentMessageDELIVERED_v2": "delivered",
    "sentMessageREAD": "read",
    "sentMessageREAD_v2": "read",
    "templateMessageFailed": "failed",
    "templateMessageFailed_v2": "failed",
    "sentMessageFAILED": "failed",
    "sentMessageFAILED_v2": "failed",
}


@wati_webhook_bp.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ok", "provider": "wati"}), 200

    settings = get_settings()
    secret = settings.wati_webhook_secret.strip()
    if secret:
        provided = (
            request.headers.get("X-Wati-Signature")
            or request.headers.get("X-Webhook-Secret")
            or request.args.get("secret")
            or ""
        )
        if provided != secret:
            logger.warning("Wati webhook rejected: invalid secret")
            return "Forbidden", 403

    payload = request.get_json(silent=True) or {}
    event_type = _event_type(payload)
    logger.info("Wati webhook event=%s", event_type)

    try:
        if event_type in STATUS_EVENTS:
            _handle_status(payload, STATUS_EVENTS[event_type])
        elif event_type in INBOUND_EVENTS or _looks_like_inbound(payload):
            _handle_inbound(payload)
        else:
            # Some Wati tenants send status via nested fields without eventType.
            status = _status_from_payload(payload)
            if status:
                _handle_status(payload, status)
            elif _looks_like_inbound(payload):
                _handle_inbound(payload)
    except Exception:
        current_app.logger.exception("Failed processing Wati webhook")

    return jsonify({"ok": True}), 200


def _event_type(payload: dict[str, Any]) -> str:
    for key in ("eventType", "event", "type", "event_type"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _looks_like_inbound(payload: dict[str, Any]) -> bool:
    text = _extract_text(payload)
    wa_id = _extract_wa_id(payload)
    return bool(text and wa_id)


def _status_from_payload(payload: dict[str, Any]) -> str | None:
    raw = str(payload.get("status") or payload.get("messageStatus") or "").lower()
    mapping = {
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
        "error": "failed",
    }
    return mapping.get(raw)


def _extract_wa_id(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("waId"),
        payload.get("whatsappNumber"),
        payload.get("phone"),
        payload.get("from"),
        (payload.get("sender") or {}).get("phone") if isinstance(payload.get("sender"), dict) else None,
        (payload.get("contact") or {}).get("waId") if isinstance(payload.get("contact"), dict) else None,
        (payload.get("contact") or {}).get("phone") if isinstance(payload.get("contact"), dict) else None,
    ]
    for value in candidates:
        digits = normalize_whatsapp_number(str(value) if value is not None else None)
        if digits:
            return digits
    return None


def _extract_text(payload: dict[str, Any]) -> str:
    for key in ("text", "message", "body", "messageText", "reply"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("body") or value.get("text") or value.get("message")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_text(data)
    return ""


def _extract_message_id(payload: dict[str, Any]) -> str | None:
    for key in ("localMessageId", "local_message_id", "whatsappMessageId", "id", "messageId"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_message_id(data)
    return None


def _handle_status(payload: dict[str, Any], status: str) -> None:
    message_id = _extract_message_id(payload)
    if not message_id:
        return
    update_whatsapp_message_status(message_id, status)


def _handle_inbound(payload: dict[str, Any]) -> None:
    from_number = _extract_wa_id(payload)
    body = _extract_text(payload)
    wa_message_id = _extract_message_id(payload)
    if not from_number or not body:
        logger.info("Wati inbound ignored (missing phone/text): %s", list(payload.keys()))
        return

    entity = find_related_entity_by_phone(from_number)
    if not entity:
        logger.info("Wati inbound from unknown number %s", from_number)
        return

    create_whatsapp_message(
        direction="inbound",
        related_type=entity["related_type"],
        related_id=entity["related_id"],
        to_number=None,
        from_number=from_number,
        message_type="text",
        body=body,
        template_name=None,
        status="delivered",
        wa_message_id=wa_message_id,
        sent_by=None,
    )
    log_activity(
        entity["related_type"],
        entity["related_id"],
        "note",
        f"Inbound WhatsApp from {from_number}: {body[:200]}",
        None,
        {"channel": "wati", "wa_message_id": wa_message_id},
    )
