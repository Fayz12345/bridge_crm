"""Wati webhook receiver for inbound messages and delivery status."""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from bridge_crm.config import get_settings
from bridge_crm.crm.whatsapp.inbound import (
    INBOUND_EVENTS,
    event_type,
    extract_message_ids,
    looks_like_inbound,
    store_wati_payload,
)
from bridge_crm.crm.whatsapp.queries import update_whatsapp_message_status

logger = logging.getLogger(__name__)

wati_webhook_bp = Blueprint("wati_webhook", __name__, url_prefix="/api/wati")

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
    events = payload if isinstance(payload, list) else [payload]
    for event in events:
        if not isinstance(event, dict):
            continue
        _process_event(event)

    return jsonify({"ok": True}), 200


def _process_event(payload: dict[str, Any]) -> None:
    kind = event_type(payload)
    logger.info("Wati webhook event=%s", kind)
    try:
        if kind in STATUS_EVENTS:
            _handle_status(payload, STATUS_EVENTS[kind])
        elif kind in INBOUND_EVENTS or looks_like_inbound(payload):
            stored = store_wati_payload(payload)
            if not stored and looks_like_inbound(payload):
                logger.info("Wati inbound not stored: %s", list(payload.keys()))
        else:
            status = _status_from_payload(payload)
            if status:
                _handle_status(payload, status)
            elif looks_like_inbound(payload):
                store_wati_payload(payload)
    except Exception:
        current_app.logger.exception("Failed processing Wati webhook")


def _status_from_payload(payload: dict[str, Any]) -> str | None:
    raw = str(payload.get("status") or payload.get("messageStatus") or payload.get("statusString") or "").lower()
    mapping = {
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
        "error": "failed",
    }
    return mapping.get(raw)


def _handle_status(payload: dict[str, Any], status: str) -> None:
    message_ids = extract_message_ids(payload)
    if not message_ids:
        return
    for message_id in message_ids:
        update_whatsapp_message_status(message_id, status)
