"""WhatsApp business numbers (Wati channels) assigned to CRM users."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select, update

from bridge_crm.config import get_settings
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_users, crm_whatsapp_channels
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    list_phone_numbers,
    normalize_whatsapp_number,
    provider_name,
    whatsapp_configured,
)


def channel_label(channel: dict | None) -> str:
    if not channel:
        return ""
    name = (channel.get("display_name") or "").strip()
    number = (channel.get("phone_number") or "").strip()
    if name and number and name != number:
        return f"{name} ({number})"
    return name or number


def list_channels(*, active_only: bool = True) -> list[dict]:
    ensure_default_channel()
    statement = select(crm_whatsapp_channels).order_by(
        crm_whatsapp_channels.c.is_default.desc(),
        crm_whatsapp_channels.c.display_name,
        crm_whatsapp_channels.c.phone_number,
    )
    if active_only:
        statement = statement.where(crm_whatsapp_channels.c.is_active.is_(True))
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def list_user_ids_for_channel(phone_number: str | None) -> list[int]:
    """CRM users assigned to this Wati business number."""
    channel = get_channel_by_number(phone_number)
    if not channel:
        return []
    statement = select(crm_users.c.id).where(
        crm_users.c.whatsapp_channel_id == int(channel["id"]),
        crm_users.c.is_active.is_(True),
    )
    with get_connection() as connection:
        rows = connection.execute(statement).all()
    return [int(row[0]) for row in rows]


def get_channel(channel_id: int | None) -> dict | None:
    if not channel_id:
        return None
    statement = select(crm_whatsapp_channels).where(crm_whatsapp_channels.c.id == int(channel_id))
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def get_channel_by_number(phone_number: str | None) -> dict | None:
    digits = normalize_whatsapp_number(phone_number)
    if not digits:
        return None
    statement = select(crm_whatsapp_channels).where(crm_whatsapp_channels.c.phone_number == digits)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def get_default_channel() -> dict | None:
    statement = (
        select(crm_whatsapp_channels)
        .where(
            crm_whatsapp_channels.c.is_default.is_(True),
            crm_whatsapp_channels.c.is_active.is_(True),
        )
        .order_by(crm_whatsapp_channels.c.id)
        .limit(1)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    if row:
        return dict(row)
    statement = (
        select(crm_whatsapp_channels)
        .where(crm_whatsapp_channels.c.is_active.is_(True))
        .order_by(crm_whatsapp_channels.c.id)
        .limit(1)
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def resolve_channel_number(*, user: dict | None = None, explicit: str | None = None) -> str | None:
    """Pick the Wati number to send from: explicit picker, then user, then default."""
    ensure_default_channel()
    explicit_digits = normalize_whatsapp_number(explicit)
    if explicit_digits:
        return explicit_digits
    if user:
        assigned = get_channel(user.get("whatsapp_channel_id"))
        if assigned and assigned.get("is_active") is not False:
            return assigned.get("phone_number")
    default = get_default_channel()
    if default:
        return default.get("phone_number")
    return normalize_whatsapp_number(get_settings().wati_channel_number)


def ensure_default_channel() -> dict | None:
    """Keep WATI_CHANNEL_NUMBER in the catalog as the fallback/default number."""
    settings_number = normalize_whatsapp_number(get_settings().wati_channel_number)
    if not settings_number:
        return get_default_channel()
    existing = get_channel_by_number(settings_number)
    if existing:
        if not existing.get("is_default"):
            _mark_default(int(existing["id"]))
        elif existing.get("is_active") is False:
            upsert_channel(phone_number=settings_number, is_active=True, is_default=True)
        return get_channel_by_number(settings_number)
    upsert_channel(
        phone_number=settings_number,
        display_name="Default",
        is_default=True,
        is_active=True,
    )
    return get_channel_by_number(settings_number)


def upsert_channel(
    *,
    phone_number: str,
    display_name: str = "",
    is_default: bool = False,
    is_active: bool = True,
    synced_at: datetime | None = None,
) -> int:
    digits = normalize_whatsapp_number(phone_number)
    if not digits:
        raise ValueError("Invalid WhatsApp channel number.")
    now = datetime.now(timezone.utc)
    existing = get_channel_by_number(digits)
    name = (display_name or "").strip()[:120] or (existing or {}).get("display_name") or digits
    if existing:
        values: dict[str, Any] = {
            "display_name": name,
            "is_active": is_active,
            "updated_at": now,
        }
        if synced_at is not None:
            values["synced_at"] = synced_at
        statement = (
            update(crm_whatsapp_channels)
            .where(crm_whatsapp_channels.c.id == int(existing["id"]))
            .values(**values)
        )
        with get_connection() as connection:
            connection.execute(statement)
        channel_id = int(existing["id"])
    else:
        statement = (
            insert(crm_whatsapp_channels)
            .values(
                phone_number=digits,
                display_name=name,
                is_default=False,
                is_active=is_active,
                synced_at=synced_at,
                created_at=now,
                updated_at=now,
            )
            .returning(crm_whatsapp_channels.c.id)
        )
        with get_connection() as connection:
            channel_id = int(connection.execute(statement).scalar_one())
    if is_default:
        _mark_default(channel_id)
    return channel_id


def parse_wati_phone_numbers(payload: Any) -> list[dict[str, Any]]:
    items = _phone_number_items(payload)
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            digits = normalize_whatsapp_number(item)
            if digits and digits not in seen:
                seen.add(digits)
                parsed.append({"phone_number": digits, "display_name": "", "is_default": False})
            continue
        if not isinstance(item, dict):
            continue
        raw = (
            item.get("phoneNumber")
            or item.get("phone_number")
            or item.get("channelPhoneNumber")
            or item.get("channel_number")
            or item.get("number")
            or item.get("whatsappNumber")
        )
        digits = normalize_whatsapp_number(str(raw) if raw is not None else None)
        if not digits or digits in seen:
            continue
        seen.add(digits)
        name = str(
            item.get("displayName")
            or item.get("friendlyName")
            or item.get("name")
            or ""
        ).strip()
        parsed.append(
            {
                "phone_number": digits,
                "display_name": name,
                "is_default": bool(item.get("isDefault") or item.get("is_default") or item.get("default")),
            }
        )
    return parsed


def sync_channels_from_wati() -> dict[str, Any]:
    if not whatsapp_configured() or provider_name() != "wati":
        raise WhatsAppAPIError("Wati is not configured.")
    payload = list_phone_numbers()
    items = parse_wati_phone_numbers(payload)
    now = datetime.now(timezone.utc)
    synced_ids: list[int] = []
    for item in items:
        channel_id = upsert_channel(
            phone_number=item["phone_number"],
            display_name=item["display_name"],
            is_default=bool(item.get("is_default")),
            is_active=True,
            synced_at=now,
        )
        synced_ids.append(channel_id)
    if synced_ids:
        with get_connection() as connection:
            connection.execute(
                update(crm_whatsapp_channels)
                .where(crm_whatsapp_channels.c.id.notin_(synced_ids))
                .values(is_active=False, updated_at=now)
            )
    ensure_default_channel()
    return {"synced": len(synced_ids), "channels": list_channels(active_only=False)}


def _mark_default(channel_id: int) -> None:
    now = datetime.now(timezone.utc)
    with get_connection() as connection:
        connection.execute(
            update(crm_whatsapp_channels).values(is_default=False, updated_at=now)
        )
        connection.execute(
            update(crm_whatsapp_channels)
            .where(crm_whatsapp_channels.c.id == int(channel_id))
            .values(is_default=True, is_active=True, updated_at=now)
        )


def _phone_number_items(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("phoneNumbers", "phone_numbers", "items", "result", "data", "model"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _phone_number_items(value)
            if nested:
                return nested
    if any(payload.get(key) for key in ("phoneNumber", "phone_number", "number", "channelPhoneNumber")):
        return [payload]
    return []
