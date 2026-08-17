"""Meta WhatsApp Cloud API client for Bridge CRM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib import error, request

from bridge_crm.config import get_settings

logger = logging.getLogger(__name__)


class WhatsAppAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def whatsapp_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.whatsapp_access_token.strip()
        and settings.whatsapp_phone_number_id.strip()
        and settings.whatsapp_default_template.strip()
    )


def normalize_whatsapp_number(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone.strip())
    if len(digits) < 8:
        return None
    return digits


def _api_request(method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise WhatsAppAPIError("WhatsApp API credentials are not configured.")

    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}{path}"
    )
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    api_request = request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(api_request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            message = detail or str(exc)
            parsed = {}
        raise WhatsAppAPIError(
            message,
            status_code=exc.code,
            payload=parsed,
        ) from exc


def send_text_message(to_number: str, message: str) -> dict[str, Any]:
    recipient = normalize_whatsapp_number(to_number)
    if not recipient:
        raise WhatsAppAPIError("Invalid WhatsApp phone number.")

    body = (message or "").strip()
    if not body:
        raise WhatsAppAPIError("Message body is required.")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    return _api_request("POST", "/messages", payload)


def send_template_message(
    to_number: str,
    template_name: str,
    *,
    language_code: str | None = None,
    body_parameters: list[str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    recipient = normalize_whatsapp_number(to_number)
    if not recipient:
        raise WhatsAppAPIError("Invalid WhatsApp phone number.")

    template = template_name.strip() or settings.whatsapp_default_template
    if not template:
        raise WhatsAppAPIError("WhatsApp template name is required.")

    language = (language_code or settings.whatsapp_default_template_language or "en_US").strip()
    components: list[dict[str, Any]] = []
    if body_parameters:
        components.append(
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(value)[:1024]} for value in body_parameters
                ],
            }
        )

    template_payload: dict[str, Any] = {
        "name": template,
        "language": {"code": language},
    }
    if components:
        template_payload["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "template",
        "template": template_payload,
    }
    response = _api_request("POST", "/messages", payload)
    logger.info(
        "WhatsApp template %s sent to %s (message_id=%s)",
        template,
        recipient,
        _extract_message_id(response),
    )
    return response


def send_outreach_template(
    to_number: str,
    *,
    contact_name: str,
    rep_name: str,
    message_body: str,
    template_name: str | None = None,
    language_code: str | None = None,
) -> dict[str, Any]:
    return send_template_message(
        to_number,
        template_name or get_settings().whatsapp_default_template,
        language_code=language_code,
        body_parameters=[
            (contact_name or "there").strip()[:256],
            (rep_name or "Bridge Wireless").strip()[:256],
            (message_body or "").strip()[:1024],
        ],
    )


def _extract_message_id(response: dict[str, Any]) -> str | None:
    messages = response.get("messages") or []
    if messages and isinstance(messages[0], dict):
        return messages[0].get("id")
    return None
