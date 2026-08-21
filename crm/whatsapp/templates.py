"""Create, sync, and track Wati WhatsApp message templates."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from bridge_crm.crm.whatsapp.template_queries import (
    create_whatsapp_template,
    get_whatsapp_template,
    get_whatsapp_template_by_name,
    update_whatsapp_template,
    upsert_whatsapp_template,
)
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    create_message_template,
    delete_message_template,
    list_message_templates,
    provider_name,
    whatsapp_configured,
)

logger = logging.getLogger(__name__)

TEMPLATE_CATEGORIES = ("MARKETING", "UTILITY", "AUTHENTICATION")
TEMPLATE_LANGUAGES = (
    ("en", "English"),
    ("en_US", "English (US)"),
    ("en_GB", "English (UK)"),
    ("es", "Spanish"),
    ("fr", "French"),
)

WATI_STATUS_CODES = {
    0: "DRAFT",
    1: "PENDING",
    2: "APPROVED",
    3: "REJECTED",
    4: "DELETED",
    5: "PENDING_INTERNAL",
    6: "DISABLED",
    7: "PAUSED",
}

_PENDING_STATUSES = {"DRAFT", "PENDING", "PENDING_INTERNAL"}
_APPROVED_STATUSES = {"APPROVED"}
_CANCELLED_STATUSES = {"REJECTED", "DELETED", "DISABLED", "PAUSED", "CANCELLED", "CANCELED"}


def normalize_template_name(value: str | None) -> str:
    raw = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw)
    return re.sub(r"_+", "_", normalized).strip("_")


def extract_body_params(body: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}", body or ""):
        name = match.strip()
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def custom_params_from_body(body: str, examples: dict[str, str] | None = None) -> list[dict[str, str]]:
    examples = examples or {}
    params = []
    for name in extract_body_params(body):
        sample = (examples.get(name) or name.replace("_", " ").title() or "Sample").strip()[:256]
        params.append({"paramName": name, "paramValue": sample})
    return params


def map_wati_status(raw_status: Any) -> tuple[str, str]:
    if raw_status is None or raw_status == "":
        return "pending", ""
    if isinstance(raw_status, bool):
        return "pending", ""
    if isinstance(raw_status, (int, float)):
        label = WATI_STATUS_CODES.get(int(raw_status), str(int(raw_status)))
        return _crm_status_from_label(label), label
    if isinstance(raw_status, dict):
        nested = raw_status.get("newStatus")
        if nested is None:
            nested = raw_status.get("status") or raw_status.get("value")
        return map_wati_status(nested)
    label = str(raw_status).strip().upper().replace(" ", "_")
    return _crm_status_from_label(label), label


def _crm_status_from_label(label: str) -> str:
    if label in _APPROVED_STATUSES:
        return "approved"
    if label in _CANCELLED_STATUSES:
        return "cancelled"
    return "pending"


def _language_code(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or value.get("key") or value.get("text") or "en").strip() or "en"
    return str(value or "en").strip() or "en"


def _header_text(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, dict):
        text = value.get("text") or value.get("headerOriginal")
        return str(text).strip()[:255] if text else None
    text = str(value).strip()
    return text[:255] if text else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload_from_wati(item: dict[str, Any], *, created_by: int | None = None) -> dict[str, Any]:
    element_name = normalize_template_name(item.get("elementName") or item.get("templateName") or item.get("name"))
    language = _language_code(item.get("language"))
    body = str(item.get("bodyOriginal") or item.get("body") or "").strip()
    status, wati_status = map_wati_status(item.get("status") if "status" in item else item.get("newTemplateStatus"))
    custom_params = item.get("customParams")
    if not isinstance(custom_params, list) or not custom_params:
        custom_params = custom_params_from_body(body)
    category = str(item.get("category") or "MARKETING").strip().upper()
    if category not in TEMPLATE_CATEGORIES:
        category = "MARKETING"
    payload = {
        "element_name": element_name,
        "category": category,
        "language": language[:20],
        "header_text": _header_text(item.get("header")),
        "body": body or element_name,
        "footer": (str(item.get("footer") or "").strip() or None),
        "custom_params": custom_params,
        "status": status,
        "wati_status": wati_status or None,
        "wati_template_id": str(item.get("id") or item.get("watiTemplateId") or "").strip() or None,
        "wa_template_id": str(item.get("waTemplateId") or item.get("templateId") or "").strip() or None,
        "last_synced_at": _now(),
    }
    if created_by:
        payload["created_by"] = created_by
    return payload


def sync_templates_from_wati(*, created_by: int | None = None) -> dict[str, int]:
    if not whatsapp_configured() or provider_name() != "wati":
        raise WhatsAppAPIError("Wati is not configured.")

    synced = 0
    page_number = 1
    while page_number <= 20:
        response = list_message_templates(page_size=100, page_number=page_number)
        items = response.get("messageTemplates") or response.get("result") or []
        if isinstance(items, dict):
            items = items.get("messageTemplates") or []
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            payload = payload_from_wati(item, created_by=created_by)
            if not payload["element_name"]:
                continue
            upsert_whatsapp_template(payload)
            synced += 1
        if len(items) < 100:
            break
        page_number += 1
    return {"synced": synced, "pages": page_number}


def submit_template(
    *,
    element_name: str,
    category: str,
    language: str,
    body: str,
    footer: str | None = None,
    header_text: str | None = None,
    created_by: int | None = None,
    examples: dict[str, str] | None = None,
) -> int:
    name = normalize_template_name(element_name)
    if not name:
        raise ValueError("Template name is required.")
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("Template name can only use lowercase letters, numbers, and underscores.")
    body_text = (body or "").strip()
    if not body_text:
        raise ValueError("Template body is required.")
    category_value = (category or "MARKETING").strip().upper()
    if category_value not in TEMPLATE_CATEGORIES:
        raise ValueError("Choose a valid template category.")
    language_code = (language or "en").strip() or "en"
    custom_params = custom_params_from_body(body_text, examples)

    existing = get_whatsapp_template_by_name(name, language_code)
    if existing:
        raise ValueError("A template with this name and language already exists.")

    response = create_message_template(
        element_name=name,
        category=category_value,
        language=language_code,
        body=body_text,
        footer=footer,
        header_text=header_text,
        custom_params=custom_params,
    )
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    created = payload_from_wati(
        {
            "elementName": name,
            "category": category_value,
            "language": language_code,
            "header": {"text": header_text} if header_text else None,
            "body": body_text,
            "footer": footer,
            "customParams": custom_params,
            "status": (result or {}).get("status") or "PENDING",
            "id": (result or {}).get("id"),
            "waTemplateId": (result or {}).get("waTemplateId"),
            "watiTemplateId": (result or {}).get("id"),
        },
        created_by=created_by,
    )
    if created["status"] not in {"pending", "approved", "cancelled"}:
        created["status"] = "pending"
    created["wati_status"] = created.get("wati_status") or "PENDING"
    return create_whatsapp_template(created)


def cancel_template(template_id: int) -> dict:
    template = get_whatsapp_template(template_id)
    if not template:
        raise ValueError("Template not found.")
    if template["status"] == "cancelled":
        return template

    wati_error = None
    try:
        delete_message_template(template["element_name"], language=template.get("language"))
    except WhatsAppAPIError as exc:
        wati_error = str(exc)
        logger.warning("Wati template delete failed for %s: %s", template["element_name"], exc)

    update_whatsapp_template(
        template_id,
        {
            "status": "cancelled",
            "wati_status": "DELETED" if not wati_error else template.get("wati_status") or "CANCELLED",
            "last_synced_at": _now(),
        },
    )
    updated = get_whatsapp_template(template_id) or template
    updated["wati_error"] = wati_error
    return updated


def apply_template_status_event(payload: dict[str, Any]) -> dict | None:
    name = normalize_template_name(payload.get("templateName") or payload.get("elementName"))
    if not name:
        return None
    language_raw = payload.get("language") or payload.get("templateLanguage")
    language = _language_code(language_raw) if language_raw else None
    status, wati_status = map_wati_status(
        payload.get("newTemplateStatus") if "newTemplateStatus" in payload else payload.get("status")
    )
    values = {
        "status": status,
        "wati_status": wati_status or None,
        "wati_template_id": str(payload.get("watiTemplateId") or "").strip() or None,
        "wa_template_id": str(payload.get("templateId") or payload.get("waTemplateId") or "").strip() or None,
        "last_synced_at": _now(),
    }
    existing = get_whatsapp_template_by_name(name, language)
    if existing:
        cleaned = {key: value for key, value in values.items() if value is not None or key in {"wati_status"}}
        update_whatsapp_template(int(existing["id"]), cleaned)
        return get_whatsapp_template(int(existing["id"]))
    created = payload_from_wati(
        {
            "elementName": name,
            "language": language,
            "body": name,
            "status": wati_status or status,
            "id": payload.get("watiTemplateId"),
            "templateId": payload.get("templateId"),
        }
    )
    created["status"] = status
    created["wati_status"] = wati_status or created.get("wati_status")
    template_id = create_whatsapp_template(created)
    return get_whatsapp_template(template_id)
