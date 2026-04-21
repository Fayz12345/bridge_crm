from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_products


def list_products(filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    statement = (
        select(crm_products)
        .order_by(
            func.lower(func.coalesce(crm_products.c.brand_name, "")),
            func.lower(func.coalesce(crm_products.c.model_name, "")),
            crm_products.c.synced_at.desc(),
        )
    )

    if filters.get("brand"):
        statement = statement.where(crm_products.c.brand_name == filters["brand"])
    if filters.get("model"):
        statement = statement.where(crm_products.c.model_name.ilike(f"%{filters['model']}%"))
    if filters.get("grade"):
        statement = statement.where(crm_products.c.outward_grade == filters["grade"])
    if filters.get("status"):
        statement = statement.where(crm_products.c.item_status == filters["status"])

    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def get_product(product_id: int) -> dict | None:
    statement = select(crm_products).where(crm_products.c.id == product_id)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def update_product_custom_fields(product_id: int, custom_fields: dict) -> None:
    statement = (
        update(crm_products)
        .where(crm_products.c.id == product_id)
        .values(custom_fields=custom_fields, synced_at=datetime.now(timezone.utc))
    )
    with get_connection() as connection:
        connection.execute(statement)


def get_product_filter_options() -> dict[str, list[str]]:
    with get_connection() as connection:
        brands = connection.execute(
            select(crm_products.c.brand_name)
            .where(crm_products.c.brand_name.is_not(None))
            .distinct()
            .order_by(crm_products.c.brand_name)
        ).scalars().all()
        grades = connection.execute(
            select(crm_products.c.outward_grade)
            .where(crm_products.c.outward_grade.is_not(None))
            .distinct()
            .order_by(crm_products.c.outward_grade)
        ).scalars().all()
        statuses = connection.execute(
            select(crm_products.c.item_status)
            .where(crm_products.c.item_status.is_not(None))
            .distinct()
            .order_by(crm_products.c.item_status)
        ).scalars().all()

    return {"brands": list(brands), "grades": list(grades), "statuses": list(statuses)}


def list_product_stock_groups() -> list[dict]:
    statement = (
        select(
            crm_products.c.brand_name.label("brand"),
            crm_products.c.model_name.label("model"),
            crm_products.c.outward_grade.label("grade"),
            crm_products.c.category_name.label("category"),
            crm_products.c.rom.label("storage"),
            func.count().label("available_count"),
        )
        .group_by(
            crm_products.c.brand_name,
            crm_products.c.model_name,
            crm_products.c.outward_grade,
            crm_products.c.category_name,
            crm_products.c.rom,
        )
        .order_by(
            func.lower(func.coalesce(crm_products.c.brand_name, "")),
            func.lower(func.coalesce(crm_products.c.model_name, "")),
        )
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def delete_product(product_id: int) -> None:
    statement = delete(crm_products).where(crm_products.c.id == product_id)
    with get_connection() as connection:
        connection.execute(statement)
