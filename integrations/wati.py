"""Wati WhatsApp Business API client for Bridge CRM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib import error, parse, request
from urllib.parse import quote

from bridge_crm.config import get_settings

logger = logging.getLogger(__name__)


class WatiAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def wati_credentials_configured() -> bool:
    settings = get_settings()
    return bool(settings.wati_api_endpoint.strip() and settings.wati_access_token.strip())


def wati_configured() -> bool:
    return wati_credentials_configured()


def wati_templates_ready() -> bool:
    return wati_credentials_configured() and bool(get_settings().whatsapp_default_template.strip())


def normalize_whatsapp_number(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone.strip())
    if len(digits) < 8:
        return None
    return digits


def _base_url() -> str:
    settings = get_settings()
    return settings.wati_api_endpoint.rstrip("/")


def _auth_headers() -> dict[str, str]:
    settings = get_settings()
    token = settings.wati_access_token.strip()
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {
        "Authorization": token,
        "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Cloudflare on Wati blocks the default Python-urllib user-agent (error 1010).
        "User-Agent": "Mozilla/5.0 BridgeCRM/1.0 (+https://crm.bridge-renew.net)",
    }


def _api_request(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    query: dict | None = None,
    form_data: dict | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    if not wati_credentials_configured():
        raise WatiAPIError("Wati API credentials are not configured.")

    url = f"{_base_url()}{path}"
    if query:
        url = f"{url}?{parse.urlencode(query)}"

    headers = _auth_headers()
    data: bytes | None = None
    if form_data is not None:
        data = parse.urlencode(form_data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    api_request = request.Request(url, data=data, method=method, headers=headers)
    try:
        with request.urlopen(api_request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return _parse_json_body(body, status_code=getattr(response, "status", None))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        parsed: dict[str, Any] = {}
        message = detail or str(exc)
        try:
            parsed = json.loads(detail) if detail.strip() else {}
            message = (
                parsed.get("info")
                or parsed.get("message")
                or parsed.get("error")
                or parsed.get("result")
                or detail
            )
            if isinstance(message, dict):
                message = json.dumps(message)
        except json.JSONDecodeError:
            message = _non_json_error(detail, status_code=exc.code)
        raise WatiAPIError(str(message)[:500], status_code=exc.code, payload=parsed) from exc
    except error.URLError as exc:
        raise WatiAPIError(str(getattr(exc, "reason", None) or exc)) from exc


def _parse_json_body(body: str, *, status_code: int | None = None) -> dict[str, Any]:
    text = (body or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WatiAPIError(_non_json_error(text, status_code=status_code), status_code=status_code) from exc
    if isinstance(parsed, dict):
        return parsed
    return {"result": parsed}


def _non_json_error(body: str, *, status_code: int | None = None) -> str:
    text = re.sub(r"\s+", " ", (body or "")).strip()
    prefix = f"Wati HTTP {status_code}: " if status_code else "Wati: "
    if text.lstrip().startswith("<"):
        return (
            f"{prefix}returned an HTML page instead of JSON. "
            "This is often a Cloudflare block or an incorrect WATI_API_ENDPOINT."
        )
    preview = text[:180] or "(empty response)"
    return f"{prefix}returned a non-JSON response: {preview}"


def send_session_message(to_number: str, message: str) -> dict[str, Any]:
    """Send a free-form session message (valid within 24h customer-service window)."""
    recipient = normalize_whatsapp_number(to_number)
    if not recipient:
        raise WatiAPIError("Invalid WhatsApp phone number.")

    body = (message or "").strip()
    if not body:
        raise WatiAPIError("Message body is required.")

    # Wati commonly accepts messageText as form field on this endpoint.
    path = f"/api/v1/sendSessionMessage/{quote(recipient, safe='')}"
    response = _api_request("POST", path, form_data={"messageText": body[:4096]})
    logger.info("Wati session message sent to %s (id=%s)", recipient, extract_message_id(response))
    return response


def send_template_message(
    to_number: str,
    template_name: str,
    *,
    parameters: list[dict[str, str]] | None = None,
    broadcast_name: str | None = None,
) -> dict[str, Any]:
    """Send an approved Wati template message."""
    settings = get_settings()
    recipient = normalize_whatsapp_number(to_number)
    if not recipient:
        raise WatiAPIError("Invalid WhatsApp phone number.")

    template = (template_name or settings.whatsapp_default_template or "").strip()
    if not template:
        raise WatiAPIError("WhatsApp template name is required.")

    payload: dict[str, Any] = {
        "template_name": template,
        "broadcast_name": (broadcast_name or f"crm_{template}")[:100],
        "parameters": parameters or [],
    }
    if settings.wati_channel_number.strip():
        payload["channel_number"] = settings.wati_channel_number.strip()

    response = _api_request(
        "POST",
        "/api/v2/sendTemplateMessage",
        query={"whatsappNumber": recipient},
        payload=payload,
    )
    if response.get("result") is False:
        raise WatiAPIError(
            str(response.get("info") or response.get("message") or "Wati template send failed"),
            payload=response,
        )
    logger.info(
        "Wati template %s sent to %s (id=%s)",
        template,
        recipient,
        extract_message_id(response),
    )
    return response


def send_outreach_template(
    to_number: str,
    *,
    contact_name: str,
    rep_name: str,
    message_body: str,
    template_name: str | None = None,
    broadcast_name: str | None = None,
) -> dict[str, Any]:
    """
    Send CRM outreach template via Wati.

    Default named parameters match a common 3-field marketing template:
    name / rep_name / message (configure your Wati template accordingly).
    Override with WATI_TEMPLATE_PARAM_NAMES=name,rep_name,message if needed.
    """
    settings = get_settings()
    parameters = outreach_parameters(contact_name, rep_name, message_body)
    return send_template_message(
        to_number,
        template_name or settings.whatsapp_default_template,
        parameters=parameters,
        broadcast_name=broadcast_name,
    )


def outreach_parameters(contact_name: str, rep_name: str, message_body: str) -> list[dict[str, str]]:
    settings = get_settings()
    param_names = [
        part.strip()
        for part in (settings.wati_template_param_names or "name,rep_name,message").split(",")
        if part.strip()
    ]
    values = [
        (contact_name or "there").strip()[:256],
        (rep_name or "Bridge Wireless").strip()[:256],
        (message_body or "").strip()[:1024],
    ]
    return [
        {"name": param_names[i] if i < len(param_names) else f"param{i + 1}", "value": values[i]}
        for i in range(min(len(param_names), len(values)))
    ]


def send_template_broadcast(
    receivers: list[dict[str, Any]],
    *,
    template_name: str | None = None,
    broadcast_name: str | None = None,
) -> dict[str, Any]:
    """
    Send one approved template to many numbers as a Wati broadcast.

    Each receiver is: {"whatsapp_number": "...", "parameters": [{"name","value"}]}.
    """
    settings = get_settings()
    template = (template_name or settings.whatsapp_default_template or "").strip()
    if not template:
        raise WatiAPIError("WhatsApp template name is required.")
    if not receivers:
        raise WatiAPIError("At least one recipient is required.")

    payload: dict[str, Any] = {
        "template_name": template,
        "broadcast_name": (broadcast_name or f"crm_{template}")[:100],
        "receivers": [],
    }
    if settings.wati_channel_number.strip():
        payload["channel_number"] = settings.wati_channel_number.strip()

    for receiver in receivers:
        number = normalize_whatsapp_number(receiver.get("whatsapp_number"))
        if not number:
            continue
        payload["receivers"].append(
            {
                "whatsappNumber": number,
                "customParams": receiver.get("parameters") or [],
            }
        )
    if not payload["receivers"]:
        raise WatiAPIError("No valid WhatsApp numbers in this broadcast.")

    response = _api_request("POST", "/api/v1/sendTemplateMessages", payload=payload)
    if response.get("result") is False:
        raise WatiAPIError(
            str(response.get("info") or response.get("message") or "Wati broadcast failed"),
            payload=response,
        )
    logger.info(
        "Wati broadcast %s sent to %s recipient(s)",
        payload["broadcast_name"],
        len(payload["receivers"]),
    )
    return response


def get_messages(whatsapp_number: str, *, page_size: int = 100, page_number: int = 1) -> dict[str, Any]:
    """Fetch recent conversation history for a WhatsApp number from Wati."""
    recipient = normalize_whatsapp_number(whatsapp_number)
    if not recipient:
        raise WatiAPIError("Invalid WhatsApp phone number.")
    path = f"/api/v1/getMessages/{quote(recipient, safe='')}"
    return _api_request(
        "GET",
        path,
        query={"pageSize": max(1, min(page_size, 100)), "pageNumber": max(1, page_number)},
        timeout=8,
    )


def list_message_templates(*, page_size: int = 100, page_number: int = 1) -> dict[str, Any]:
    """Fetch Wati message templates, including approval status."""
    settings = get_settings()
    query: dict[str, Any] = {
        "pageSize": max(1, min(page_size, 100)),
        "pageNumber": max(1, page_number),
    }
    if settings.wati_channel_number.strip():
        query["channelPhoneNumber"] = settings.wati_channel_number.strip()
    return _api_request("GET", "/api/v1/getMessageTemplates", query=query)


def create_message_template(
    *,
    element_name: str,
    category: str,
    language: str,
    body: str,
    footer: str | None = None,
    header_text: str | None = None,
    custom_params: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Submit a new WhatsApp template to Wati/Meta for review."""
    header_value = (header_text or "").strip()
    payload: dict[str, Any] = {
        "type": "template",
        "category": category,
        "subCategory": "STANDARD",
        "buttonsType": "NONE",
        "buttons": [],
        "elementName": element_name,
        "language": language,
        "header": {
            "type": "text" if header_value else "none",
            "text": header_value or None,
            "link": "",
            "mediaFromPC": "",
            "mediaHeaderId": "",
        },
        "body": body,
        "customParams": custom_params or [],
        "creationMethod": 0,
    }
    if (footer or "").strip():
        payload["footer"] = footer.strip()

    response = _api_request("POST", "/api/v1/whatsApp/templates", payload=payload)
    if response.get("ok") is False or response.get("result") is False:
        raise WatiAPIError(
            str(
                response.get("info")
                or response.get("message")
                or response.get("result")
                or "Wati template create failed"
            ),
            payload=response,
        )
    logger.info("Wati template %s submitted", element_name)
    return response


def delete_message_template(element_name: str, *, language: str | None = None) -> dict[str, Any]:
    """Cancel/delete a template in Wati by name (and optional language)."""
    settings = get_settings()
    waba_id = settings.whatsapp_business_account_id.strip()
    if not waba_id:
        raise WatiAPIError("Set WHATSAPP_BUSINESS_ACCOUNT_ID to cancel a template in Wati.")
    path = f"/api/v1/whatsApp/templates/{quote(waba_id, safe='')}/{quote(element_name, safe='')}"
    if language:
        path = f"{path}/{quote(language, safe='')}"
    response = _api_request("DELETE", path)
    if response.get("ok") is False or response.get("result") is False:
        raise WatiAPIError(
            str(
                response.get("info")
                or response.get("message")
                or response.get("result")
                or "Wati template delete failed"
            ),
            payload=response,
        )
    logger.info("Wati template %s cancelled", element_name)
    return response


def extract_message_id(response: dict[str, Any]) -> str | None:
    for key in ("localMessageId", "local_message_id", "messageId", "message_id", "id"):
        value = response.get(key)
        if value:
            return str(value)
    model = response.get("model") or {}
    if isinstance(model, dict):
        for key in ("localMessageId", "id", "messageId"):
            if model.get(key):
                return str(model[key])
        ids = model.get("ids")
        if isinstance(ids, list) and ids:
            return str(ids[0])
    return None
