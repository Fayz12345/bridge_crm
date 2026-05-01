from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, func, insert, select

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_account_product_interests,
    crm_account_tags,
    crm_lead_product_interests,
    crm_lead_tags,
    crm_product_interest_options,
    crm_tags,
)


def _normalize_tag_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def parse_tag_names(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for chunk in str(raw_value).replace("\n", ",").split(","):
        name = _normalize_tag_name(chunk)
        if not name:
            continue
        tag_key = name.casefold()
        if tag_key in seen:
            continue
        seen.add(tag_key)
        names.append(name)
    return names


def list_product_interest_options(active_only: bool = True) -> list[dict]:
    statement = select(crm_product_interest_options).order_by(
        crm_product_interest_options.c.display_order,
        func.lower(crm_product_interest_options.c.display_name),
    )
    if active_only:
        statement = statement.where(crm_product_interest_options.c.is_active.is_(True))
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def list_tags() -> list[dict]:
    statement = select(crm_tags).order_by(func.lower(crm_tags.c.tag_name), crm_tags.c.id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_account_product_interest_ids(account_id: int) -> list[int]:
    statement = (
        select(crm_account_product_interests.c.interest_option_id)
        .where(crm_account_product_interests.c.account_id == account_id)
        .order_by(crm_account_product_interests.c.interest_option_id)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).all()
    return [int(row[0]) for row in rows]


def get_lead_product_interest_ids(lead_id: int) -> list[int]:
    statement = (
        select(crm_lead_product_interests.c.interest_option_id)
        .where(crm_lead_product_interests.c.lead_id == lead_id)
        .order_by(crm_lead_product_interests.c.interest_option_id)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).all()
    return [int(row[0]) for row in rows]


def list_account_product_interests_map(account_ids: list[int]) -> dict[int, list[dict]]:
    if not account_ids:
        return {}
    statement = (
        select(
            crm_account_product_interests.c.account_id,
            crm_product_interest_options.c.id,
            crm_product_interest_options.c.option_key,
            crm_product_interest_options.c.display_name,
            crm_product_interest_options.c.display_order,
        )
        .select_from(
            crm_account_product_interests.join(
                crm_product_interest_options,
                crm_account_product_interests.c.interest_option_id
                == crm_product_interest_options.c.id,
            )
        )
        .where(crm_account_product_interests.c.account_id.in_(account_ids))
        .order_by(
            crm_account_product_interests.c.account_id,
            crm_product_interest_options.c.display_order,
            func.lower(crm_product_interest_options.c.display_name),
        )
    )
    result: dict[int, list[dict]] = defaultdict(list)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    for row in rows:
        result[int(row["account_id"])].append(
            {
                "id": int(row["id"]),
                "option_key": row["option_key"],
                "display_name": row["display_name"],
                "display_order": int(row["display_order"]),
            }
        )
    return dict(result)


def list_lead_product_interests_map(lead_ids: list[int]) -> dict[int, list[dict]]:
    if not lead_ids:
        return {}
    statement = (
        select(
            crm_lead_product_interests.c.lead_id,
            crm_product_interest_options.c.id,
            crm_product_interest_options.c.option_key,
            crm_product_interest_options.c.display_name,
            crm_product_interest_options.c.display_order,
        )
        .select_from(
            crm_lead_product_interests.join(
                crm_product_interest_options,
                crm_lead_product_interests.c.interest_option_id
                == crm_product_interest_options.c.id,
            )
        )
        .where(crm_lead_product_interests.c.lead_id.in_(lead_ids))
        .order_by(
            crm_lead_product_interests.c.lead_id,
            crm_product_interest_options.c.display_order,
            func.lower(crm_product_interest_options.c.display_name),
        )
    )
    result: dict[int, list[dict]] = defaultdict(list)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    for row in rows:
        result[int(row["lead_id"])].append(
            {
                "id": int(row["id"]),
                "option_key": row["option_key"],
                "display_name": row["display_name"],
                "display_order": int(row["display_order"]),
            }
        )
    return dict(result)


def list_account_tags_map(account_ids: list[int]) -> dict[int, list[dict]]:
    if not account_ids:
        return {}
    statement = (
        select(
            crm_account_tags.c.account_id,
            crm_tags.c.id,
            crm_tags.c.tag_key,
            crm_tags.c.tag_name,
        )
        .select_from(crm_account_tags.join(crm_tags, crm_account_tags.c.tag_id == crm_tags.c.id))
        .where(crm_account_tags.c.account_id.in_(account_ids))
        .order_by(
            crm_account_tags.c.account_id,
            func.lower(crm_tags.c.tag_name),
            crm_tags.c.id,
        )
    )
    result: dict[int, list[dict]] = defaultdict(list)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    for row in rows:
        result[int(row["account_id"])].append(
            {
                "id": int(row["id"]),
                "tag_key": row["tag_key"],
                "tag_name": row["tag_name"],
            }
        )
    return dict(result)


def list_lead_tags_map(lead_ids: list[int]) -> dict[int, list[dict]]:
    if not lead_ids:
        return {}
    statement = (
        select(
            crm_lead_tags.c.lead_id,
            crm_tags.c.id,
            crm_tags.c.tag_key,
            crm_tags.c.tag_name,
        )
        .select_from(crm_lead_tags.join(crm_tags, crm_lead_tags.c.tag_id == crm_tags.c.id))
        .where(crm_lead_tags.c.lead_id.in_(lead_ids))
        .order_by(
            crm_lead_tags.c.lead_id,
            func.lower(crm_tags.c.tag_name),
            crm_tags.c.id,
        )
    )
    result: dict[int, list[dict]] = defaultdict(list)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    for row in rows:
        result[int(row["lead_id"])].append(
            {
                "id": int(row["id"]),
                "tag_key": row["tag_key"],
                "tag_name": row["tag_name"],
            }
        )
    return dict(result)


def get_account_tag_names(account_id: int) -> list[str]:
    tags_map = list_account_tags_map([account_id])
    return [tag["tag_name"] for tag in tags_map.get(account_id, [])]


def get_lead_tag_names(lead_id: int) -> list[str]:
    tags_map = list_lead_tags_map([lead_id])
    return [tag["tag_name"] for tag in tags_map.get(lead_id, [])]


def replace_account_product_interests(account_id: int, interest_option_ids: list[int]) -> None:
    unique_ids = sorted({int(value) for value in interest_option_ids})
    with get_connection() as connection:
        connection.execute(
            delete(crm_account_product_interests).where(
                crm_account_product_interests.c.account_id == account_id
            )
        )
        if unique_ids:
            connection.execute(
                insert(crm_account_product_interests),
                [
                    {
                        "account_id": account_id,
                        "interest_option_id": interest_option_id,
                    }
                    for interest_option_id in unique_ids
                ],
            )


def replace_lead_product_interests(lead_id: int, interest_option_ids: list[int]) -> None:
    unique_ids = sorted({int(value) for value in interest_option_ids})
    with get_connection() as connection:
        connection.execute(
            delete(crm_lead_product_interests).where(
                crm_lead_product_interests.c.lead_id == lead_id
            )
        )
        if unique_ids:
            connection.execute(
                insert(crm_lead_product_interests),
                [
                    {
                        "lead_id": lead_id,
                        "interest_option_id": interest_option_id,
                    }
                    for interest_option_id in unique_ids
                ],
            )


def _ensure_tag_ids(connection, tag_names: list[str]) -> list[int]:
    tag_ids: list[int] = []
    for tag_name in tag_names:
        tag_key = tag_name.casefold()
        row = connection.execute(
            select(crm_tags.c.id).where(crm_tags.c.tag_key == tag_key)
        ).first()
        if row:
            tag_ids.append(int(row[0]))
            continue
        tag_id = connection.execute(
            insert(crm_tags)
            .values(tag_key=tag_key, tag_name=tag_name)
            .returning(crm_tags.c.id)
        ).scalar_one()
        tag_ids.append(int(tag_id))
    return tag_ids


def replace_account_tags(account_id: int, tag_names: list[str]) -> None:
    normalized = parse_tag_names(",".join(tag_names))
    with get_connection() as connection:
        tag_ids = _ensure_tag_ids(connection, normalized)
        connection.execute(
            delete(crm_account_tags).where(crm_account_tags.c.account_id == account_id)
        )
        if tag_ids:
            connection.execute(
                insert(crm_account_tags),
                [{"account_id": account_id, "tag_id": tag_id} for tag_id in tag_ids],
            )


def replace_lead_tags(lead_id: int, tag_names: list[str]) -> None:
    normalized = parse_tag_names(",".join(tag_names))
    with get_connection() as connection:
        tag_ids = _ensure_tag_ids(connection, normalized)
        connection.execute(delete(crm_lead_tags).where(crm_lead_tags.c.lead_id == lead_id))
        if tag_ids:
            connection.execute(
                insert(crm_lead_tags),
                [{"lead_id": lead_id, "tag_id": tag_id} for tag_id in tag_ids],
            )
