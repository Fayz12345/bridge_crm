"""Store inbound WhatsApp replies and sync conversation history from Wati."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from flask import has_request_context, url_for

from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.leads.queries import create_lead
from bridge_crm.crm.notifications.queries import create_notification
from bridge_crm.crm.whatsapp.queries import (
    create_whatsapp_message,
    find_related_entity_by_phone,
    get_whatsapp_message_by_wa_ids,
    link_unlinked_outbound_message,
    similar_whatsapp_message_exists,
)
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    get_conversation_messages,
    normalize_whatsapp_number,
    provider_name,
    whatsapp_configured,
)

logger = logging.getLogger(__name__)

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
    "newMessageReceived",
    "chatMessage",
    "replied",
}

MEDIA_LABELS = {
    "image": "[Image]",
    "video": "[Video]",
    "audio": "[Audio]",
    "voice": "[Voice message]",
    "ptt": "[Voice message]",
    "document": "[Document]",
    "sticker": "[Sticker]",
    "location": "[Location]",
    "contacts": "[Contact]",
    "contact": "[Contact]",
}

_last_sync_at: dict[tuple[str, int], float] = {}


SKIP_EVENT_TYPE_VALUES = {
    "text",
    "image",
    "video",
    "audio",
    "voice",
    "ptt",
    "document",
    "sticker",
    "location",
    "contacts",
    "contact",
    "button",
    "list",
    "interactive",
    "media",
}


def event_type(payload: dict[str, Any]) -> str:
    for key in ("eventType", "event", "event_type", "type"):
        value = payload.get(key)
        if not value:
            continue
        text = str(value)
        if text.lower() in SKIP_EVENT_TYPE_VALUES:
            continue
        return text
    nested = payload.get("data")
    if isinstance(nested, dict):
        return event_type(nested)
    return ""


def is_operator_message(payload: dict[str, Any]) -> bool:
    for key in ("owner", "isOwner", "isFromMe"):
        value = payload.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
            return True
        if value == 1:
            return True
    nested = payload.get("data")
    if isinstance(nested, dict) and nested is not payload:
        return is_operator_message(nested)
    return False


def looks_like_inbound(payload: dict[str, Any]) -> bool:
    if is_operator_message(payload):
        return False
    body, _message_type = extract_body_and_type(payload)
    return bool(body and extract_wa_id(payload))


def extract_wa_id(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("waId"),
        payload.get("whatsappNumber"),
        payload.get("whatsapp_number"),
        payload.get("phone"),
        payload.get("from"),
        payload.get("wa_id"),
    ]
    sender = payload.get("sender")
    if isinstance(sender, dict):
        candidates.extend([sender.get("phone"), sender.get("waId"), sender.get("whatsappNumber")])
    contact = payload.get("contact") or payload.get("messageContact")
    if isinstance(contact, dict):
        candidates.extend([contact.get("waId"), contact.get("phone"), contact.get("whatsappNumber")])
    for value in candidates:
        digits = normalize_whatsapp_number(str(value) if value is not None else None)
        if digits:
            return digits
    nested = payload.get("data")
    if isinstance(nested, dict):
        return extract_wa_id(nested)
    return None


def extract_message_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    keys = (
        "whatsappMessageId",
        "whatsapp_message_id",
        "localMessageId",
        "local_message_id",
        "messageId",
        "message_id",
        "id",
    )
    for key in keys:
        value = payload.get(key)
        if value is None or value == "":
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    nested = payload.get("data")
    if isinstance(nested, dict):
        for item in extract_message_ids(nested):
            if item not in seen:
                seen.add(item)
                ids.append(item)
    return ids


def extract_sender_name(payload: dict[str, Any]) -> str:
    for key in ("senderName", "sender_name", "name", "fullName"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for nested_key in ("sender", "contact", "messageContact"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            for key in ("name", "fullName", "senderName"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            first = str(nested.get("firstName") or nested.get("first_name") or "").strip()
            last = str(nested.get("lastName") or nested.get("last_name") or "").strip()
            combined = f"{first} {last}".strip()
            if combined:
                return combined
    data = payload.get("data")
    if isinstance(data, dict):
        return extract_sender_name(data)
    return ""


def extract_body_and_type(payload: dict[str, Any]) -> tuple[str, str]:
    text = _extract_text(payload)
    raw_type = str(payload.get("type") or payload.get("messageType") or payload.get("dataType") or "text").lower()
    if _looks_like_media_type(raw_type) and not text:
        text = MEDIA_LABELS.get(raw_type, f"[{raw_type}]")
    stored_type = "media" if _looks_like_media_type(raw_type) else "text"
    return text, stored_type


def extract_created_at(payload: dict[str, Any]) -> datetime | None:
    for key in ("created", "time", "timestamp", "createdAt"):
        parsed = _parse_datetime(payload.get(key))
        if parsed:
            return parsed
    nested = payload.get("data")
    if isinstance(nested, dict):
        return extract_created_at(nested)
    return None


def conversation_items_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    messages = response.get("messages")
    if isinstance(messages, dict):
        items = messages.get("items") or messages.get("Items") or []
        return [item for item in items if isinstance(item, dict)]
    if isinstance(messages, list):
        return [item for item in messages if isinstance(item, dict)]
    result = response.get("result")
    if isinstance(result, dict):
        return conversation_items_from_response(result)
    return []


def record_inbound_message(
    *,
    from_number: str,
    body: str,
    wa_message_id: str | None,
    wa_message_ids: list[str] | None = None,
    sender_name: str | None = None,
    message_type: str = "text",
    created_at: datetime | None = None,
    notify: bool = True,
    log: bool = True,
    related_type: str | None = None,
    related_id: int | None = None,
) -> dict | None:
    digits = normalize_whatsapp_number(from_number)
    text = (body or "").strip()
    if not digits or not text:
        return None

    ids = [item for item in (wa_message_ids or []) if item]
    if wa_message_id and wa_message_id not in ids:
        ids.insert(0, wa_message_id)
    stored_id = ids[0] if ids else None

    if get_whatsapp_message_by_wa_ids(ids):
        return None

    entity: dict | None = None
    if related_type and related_id:
        entity = {
            "related_type": related_type,
            "related_id": related_id,
            "display_name": sender_name or digits,
            "owner_id": None,
        }
        matched = find_related_entity_by_phone(digits)
        if matched and matched["related_type"] == related_type and matched["related_id"] == related_id:
            entity = matched
    else:
        entity = find_related_entity_by_phone(digits)
        if not entity:
            entity = _create_lead_for_unknown_number(digits, sender_name)

    if similar_whatsapp_message_exists(
        related_type=entity["related_type"],
        related_id=entity["related_id"],
        direction="inbound",
        body=text,
        created_at=created_at,
        window_seconds=120,
    ):
        return None

    create_whatsapp_message(
        direction="inbound",
        related_type=entity["related_type"],
        related_id=entity["related_id"],
        to_number=None,
        from_number=digits,
        message_type=message_type if message_type in {"text", "template", "media"} else "text",
        body=text,
        template_name=None,
        status="delivered",
        wa_message_id=stored_id,
        sent_by=None,
        created_at=created_at,
    )
    if log:
        sender_label = (sender_name or "").strip() or digits
        log_activity(
            entity["related_type"],
            entity["related_id"],
            "note",
            f"Inbound WhatsApp from {sender_label}: {text[:200]}",
            None,
            {"channel": "whatsapp", "wa_message_id": stored_id},
        )
    if notify:
        _notify_owner(entity, text)
    return entity


def store_wati_payload(
    payload: dict[str, Any],
    *,
    related_type: str | None = None,
    related_id: int | None = None,
    fallback_number: str | None = None,
    notify: bool = True,
    log: bool = True,
) -> dict | None:
    body, message_type = extract_body_and_type(payload)
    from_number = extract_wa_id(payload) or normalize_whatsapp_number(fallback_number)
    ids = extract_message_ids(payload)
    if not body or not from_number:
        return None

    if is_operator_message(payload):
        if not related_type or not related_id:
            return None
        stored_id = ids[0] if ids else None
        if get_whatsapp_message_by_wa_ids(ids):
            return None
        if stored_id and link_unlinked_outbound_message(
            related_type=related_type,
            related_id=related_id,
            body=body,
            wa_message_id=stored_id,
        ):
            return None
        if similar_whatsapp_message_exists(
            related_type=related_type,
            related_id=related_id,
            direction="outbound",
            body=body,
            created_at=extract_created_at(payload),
            window_seconds=86400,
        ):
            return None
        create_whatsapp_message(
            direction="outbound",
            related_type=related_type,
            related_id=related_id,
            to_number=from_number,
            from_number=None,
            message_type=message_type if message_type in {"text", "template", "media"} else "text",
            body=body,
            template_name=None,
            status="sent",
            wa_message_id=stored_id,
            sent_by=None,
            created_at=extract_created_at(payload),
        )
        return {"related_type": related_type, "related_id": related_id, "direction": "outbound"}

    return record_inbound_message(
        from_number=from_number,
        body=body,
        wa_message_id=ids[0] if ids else None,
        wa_message_ids=ids,
        sender_name=extract_sender_name(payload),
        message_type=message_type,
        created_at=extract_created_at(payload),
        notify=notify,
        log=log,
        related_type=related_type,
        related_id=related_id,
    )


def sync_conversation_from_provider(
    related_type: str,
    related_id: int,
    phone: str | None,
    *,
    min_interval_seconds: int = 20,
) -> int:
    if provider_name() != "wati" or not whatsapp_configured():
        return 0
    digits = normalize_whatsapp_number(phone)
    if not digits:
        return 0

    cache_key = (related_type, related_id)
    now = time.monotonic()
    last = _last_sync_at.get(cache_key, 0.0)
    if min_interval_seconds and now - last < min_interval_seconds:
        return 0
    _last_sync_at[cache_key] = now

    try:
        response = get_conversation_messages(digits)
    except WhatsAppAPIError:
        logger.warning("Wati message history sync failed for %s/%s", related_type, related_id)
        return 0
    except Exception:
        logger.exception("Wati message history sync failed for %s/%s", related_type, related_id)
        return 0

    stored = 0
    for item in conversation_items_from_response(response):
        result = store_wati_payload(
            item,
            related_type=related_type,
            related_id=related_id,
            fallback_number=digits,
            notify=False,
            log=False,
        )
        if result:
            stored += 1
    if stored:
        logger.info("Synced %s WhatsApp message(s) for %s/%s", stored, related_type, related_id)
    return stored


def _extract_text(payload: dict[str, Any]) -> str:
    for key in ("text", "message", "body", "messageText", "reply", "caption"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("body") or value.get("text") or value.get("message") or value.get("caption")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    for key in ("buttonReply", "button_reply", "listReply", "list_reply"):
        value = payload.get(key)
        if isinstance(value, dict):
            title = value.get("title") or value.get("description") or value.get("payload") or value.get("text")
            if isinstance(title, str) and title.strip():
                return title.strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    interactive = payload.get("interactive")
    if isinstance(interactive, dict):
        nested_text = _extract_text(interactive)
        if nested_text:
            return nested_text
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_text(data)
    if isinstance(data, str) and data.strip() and not data.strip().startswith("{"):
        return data.strip()
    return ""


def _looks_like_media_type(value: str) -> bool:
    return value.lower() in MEDIA_LABELS


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e12:
            timestamp /= 1000.0
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_datetime(int(text))
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _split_sender_name(sender_name: str | None, fallback_digits: str) -> tuple[str, str]:
    parts = [part for part in (sender_name or "").replace("_", " ").split() if part]
    if not parts:
        return "WhatsApp", fallback_digits[-4:]
    if len(parts) == 1:
        return parts[0][:120], fallback_digits[-4:]
    return parts[0][:120], " ".join(parts[1:])[:120]


def _create_lead_for_unknown_number(digits: str, sender_name: str | None) -> dict:
    first_name, last_name = _split_sender_name(sender_name, digits)
    lead_id = create_lead(
        {
            "first_name": first_name,
            "last_name": last_name,
            "phone": digits,
            "phone_prefix": None,
            "source": "whatsapp",
            "status": "new",
            "notes": f"Created from inbound WhatsApp reply ({digits}).",
        }
    )
    logger.info("Created WhatsApp lead %s for unknown number %s", lead_id, digits)
    return {
        "related_type": "lead",
        "related_id": lead_id,
        "display_name": f"{first_name} {last_name}".strip(),
        "owner_id": None,
    }


def _notify_owner(entity: dict, body: str) -> None:
    owner_id = entity.get("owner_id")
    if not owner_id:
        return
    related_type = entity["related_type"]
    related_id = entity["related_id"]
    display_name = entity.get("display_name") or f"{related_type.title()} #{related_id}"
    link_url = ""
    if has_request_context():
        if related_type == "lead":
            link_url = url_for("leads.detail_view", lead_id=related_id)
        elif related_type == "account":
            link_url = url_for("accounts.detail_view", account_id=related_id)
    create_notification(
        {
            "user_id": int(owner_id),
            "notification_type": "system",
            "title": f"WhatsApp reply from {display_name}",
            "message": (body or "")[:400],
            "link_url": link_url or None,
            "related_type": related_type,
            "related_id": related_id,
            "metadata": {"channel": "whatsapp"},
        }
    )
