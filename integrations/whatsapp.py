"""WhatsApp provider facade — Meta Cloud API or Wati."""

from __future__ import annotations

from typing import Any

from bridge_crm.config import get_settings
from bridge_crm.integrations import meta_whatsapp, wati


class WhatsAppAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def provider_name() -> str:
    return (get_settings().whatsapp_provider or "meta").strip().lower()


def whatsapp_configured() -> bool:
    provider = provider_name()
    if provider == "wati":
        return wati.wati_configured()
    return meta_whatsapp.whatsapp_configured()


def templates_ready() -> bool:
    if provider_name() == "wati":
        return wati.wati_templates_ready()
    return meta_whatsapp.whatsapp_configured()


def normalize_whatsapp_number(phone: str | None) -> str | None:
    if provider_name() == "wati":
        return wati.normalize_whatsapp_number(phone)
    return meta_whatsapp.normalize_whatsapp_number(phone)


def send_text_message(to_number: str, message: str) -> dict[str, Any]:
    try:
        if provider_name() == "wati":
            return wati.send_session_message(to_number, message)
        return meta_whatsapp.send_text_message(to_number, message)
    except (wati.WatiAPIError, meta_whatsapp.WhatsAppAPIError) as exc:
        raise WhatsAppAPIError(str(exc), status_code=getattr(exc, "status_code", None), payload=getattr(exc, "payload", None)) from exc


def send_session_message(to_number: str, message: str) -> dict[str, Any]:
    return send_text_message(to_number, message)


def send_template_message(
    to_number: str,
    template_name: str,
    *,
    language_code: str | None = None,
    body_parameters: list[str] | None = None,
    parameters: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    try:
        if provider_name() == "wati":
            if parameters is None and body_parameters:
                parameters = [
                    {"name": f"param{i + 1}", "value": str(value)}
                    for i, value in enumerate(body_parameters)
                ]
            return wati.send_template_message(
                to_number,
                template_name,
                parameters=parameters,
            )
        return meta_whatsapp.send_template_message(
            to_number,
            template_name,
            language_code=language_code,
            body_parameters=body_parameters,
        )
    except (wati.WatiAPIError, meta_whatsapp.WhatsAppAPIError) as exc:
        raise WhatsAppAPIError(str(exc), status_code=getattr(exc, "status_code", None), payload=getattr(exc, "payload", None)) from exc


def send_outreach_template(
    to_number: str,
    *,
    contact_name: str,
    rep_name: str,
    message_body: str,
    template_name: str | None = None,
    language_code: str | None = None,
    broadcast_name: str | None = None,
) -> dict[str, Any]:
    try:
        if provider_name() == "wati":
            return wati.send_outreach_template(
                to_number,
                contact_name=contact_name,
                rep_name=rep_name,
                message_body=message_body,
                template_name=template_name,
                broadcast_name=broadcast_name,
            )
        return meta_whatsapp.send_outreach_template(
            to_number,
            contact_name=contact_name,
            rep_name=rep_name,
            message_body=message_body,
            template_name=template_name,
            language_code=language_code,
        )
    except (wati.WatiAPIError, meta_whatsapp.WhatsAppAPIError) as exc:
        raise WhatsAppAPIError(str(exc), status_code=getattr(exc, "status_code", None), payload=getattr(exc, "payload", None)) from exc


def send_template_broadcast(
    receivers: list[dict[str, Any]],
    *,
    template_name: str | None = None,
    broadcast_name: str | None = None,
) -> dict[str, Any]:
    try:
        if provider_name() != "wati":
            raise WhatsAppAPIError("Broadcast campaigns are available when WHATSAPP_PROVIDER=wati.")
        return wati.send_template_broadcast(
            receivers,
            template_name=template_name,
            broadcast_name=broadcast_name,
        )
    except (wati.WatiAPIError, meta_whatsapp.WhatsAppAPIError) as exc:
        raise WhatsAppAPIError(str(exc), status_code=getattr(exc, "status_code", None), payload=getattr(exc, "payload", None)) from exc


def get_conversation_messages(whatsapp_number: str) -> dict[str, Any]:
    try:
        if provider_name() != "wati":
            return {}
        return wati.get_messages(whatsapp_number)
    except (wati.WatiAPIError, meta_whatsapp.WhatsAppAPIError) as exc:
        raise WhatsAppAPIError(
            str(exc),
            status_code=getattr(exc, "status_code", None),
            payload=getattr(exc, "payload", None),
        ) from exc


def _extract_message_id(response: dict[str, Any]) -> str | None:
    if provider_name() == "wati":
        return wati.extract_message_id(response)
    return meta_whatsapp._extract_message_id(response)


def send_whatsapp_message(*args, **kwargs):
    return send_outreach_template(*args, **kwargs)
