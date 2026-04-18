from sqlalchemy import func, select

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_leads, crm_opportunities


def pipeline_breakdown() -> list[dict]:
    statement = (
        select(
            crm_opportunities.c.stage,
            func.count().label("count"),
            func.coalesce(func.sum(crm_opportunities.c.amount), 0).label("amount"),
        )
        .group_by(crm_opportunities.c.stage)
        .order_by(crm_opportunities.c.stage)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def lead_source_breakdown() -> list[dict]:
    statement = (
        select(crm_leads.c.source, func.count().label("count"))
        .group_by(crm_leads.c.source)
        .order_by(crm_leads.c.source)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def sales_forecast() -> list[dict]:
    month_bucket = func.to_char(crm_opportunities.c.expected_close_date, "YYYY-MM")
    statement = (
        select(
            month_bucket.label("forecast_month"),
            func.coalesce(
                func.sum(crm_opportunities.c.amount * crm_opportunities.c.probability / 100.0),
                0,
            ).label("weighted_amount"),
        )
        .where(
            crm_opportunities.c.expected_close_date.is_not(None),
            crm_opportunities.c.amount.is_not(None),
        )
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]
