import re
from datetime import datetime, timezone

from sqlalchemy import func, insert, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_custom_fields,
    crm_leads,
    crm_opportunities,
    crm_products,
)

VALID_OBJECT_TYPES = ("account", "lead", "opportunity", "product")
VALID_FIELD_TYPES = ("text", "textarea", "number", "date", "select", "checkbox")

OBJECT_TABLES = {
    "account": crm_accounts,
    "lead": crm_leads,
    "opportunity": crm_opportunities,
    "product": crm_products,
}


def _clean(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_field_key(value: str | None) -> str:
    raw = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def parse_options(raw_value: str | None) -> list[str]:
    raw = (raw_value or "").strip()
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def list_custom_fields(object_type: str | None = None, active_only: bool = False) -> list[dict]:
    statement = select(crm_custom_fields).order_by(
        crm_custom_fields.c.object_type,
        crm_custom_fields.c.display_order,
        func.lower(crm_custom_fields.c.field_label),
    )
    if object_type:
        statement = statement.where(crm_custom_fields.c.object_type == object_type)
    if active_only:
        statement = statement.where(crm_custom_fields.c.is_active.is_(True))

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_custom_field(field_id: int) -> dict | None:
    statement = select(crm_custom_fields).where(crm_custom_fields.c.id == field_id)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def get_custom_field_by_key(object_type: str, field_key: str) -> dict | None:
    statement = select(crm_custom_fields).where(
        crm_custom_fields.c.object_type == object_type,
        crm_custom_fields.c.field_key == field_key,
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def create_custom_field(payload: dict) -> int:
    statement = insert(crm_custom_fields).values(**payload).returning(crm_custom_fields.c.id)
    with get_connection() as connection:
        field_id = connection.execute(statement).scalar_one()
    return int(field_id)


def update_custom_field(field_id: int, payload: dict) -> None:
    statement = (
        update(crm_custom_fields)
        .where(crm_custom_fields.c.id == field_id)
        .values(**payload, updated_at=datetime.now(timezone.utc))
    )
    with get_connection() as connection:
        connection.execute(statement)


def build_custom_field_payload(form_data, user_id: int, existing: dict | None = None) -> dict:
    object_type = (form_data.get("object_type") or "").strip().lower()
    field_type = (form_data.get("field_type") or "text").strip().lower()
    return {
        "object_type": object_type,
        "field_key": normalize_field_key(form_data.get("field_key") or form_data.get("field_label")),
        "field_label": form_data.get("field_label", "").strip(),
        "field_type": field_type if field_type in VALID_FIELD_TYPES else "text",
        "help_text": _clean(form_data.get("help_text")),
        "placeholder": _clean(form_data.get("placeholder")),
        "options_json": parse_options(form_data.get("options_raw")),
        "is_required": form_data.get("is_required") == "on",
        "is_active": form_data.get("is_active") == "on",
        "display_order": int((form_data.get("display_order") or "0").strip() or "0"),
        "created_by": (existing or {}).get("created_by", user_id),
    }


def extract_custom_field_values(form_data, definitions: list[dict]) -> dict:
    values = {}
    for definition in definitions:
        field_name = f"cf__{definition['field_key']}"
        field_type = definition["field_type"]
        if field_type == "checkbox":
            value = form_data.get(field_name) == "on"
        else:
            raw_value = form_data.get(field_name, "")
            value = raw_value.strip() if isinstance(raw_value, str) else raw_value
            if value == "":
                value = None
        values[definition["field_key"]] = value
    return values


def get_custom_field_values(record: dict | None, definitions: list[dict]) -> list[dict]:
    stored = (record or {}).get("custom_fields") or {}
    rows = []
    for definition in definitions:
        value = stored.get(definition["field_key"])
        rows.append(
            {
                **definition,
                "value": value,
                "display_value": format_custom_field_value(definition, value),
            }
        )
    return rows


def format_custom_field_value(definition: dict, value):
    if value is None or value == "":
        return "—"
    if definition["field_type"] == "checkbox":
        return "Yes" if value else "No"
    return value


def update_record_custom_fields(object_type: str, record_id: int, custom_fields: dict) -> None:
    table = OBJECT_TABLES[object_type]
    values = {"custom_fields": custom_fields}
    if "updated_at" in table.c:
        values["updated_at"] = datetime.now(timezone.utc)
    statement = update(table).where(table.c.id == record_id).values(**values)
    with get_connection() as connection:
        connection.execute(statement)
