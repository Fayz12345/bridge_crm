from sqlalchemy import case, func, literal_column, select

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_leads,
    crm_opportunities,
    crm_opportunity_lines,
    crm_users,
)


# ---------------------------------------------------------------------------
# 1. Opportunity Summary Report
# ---------------------------------------------------------------------------

def opportunity_summary_report() -> list[dict]:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_opportunities.c.id,
            crm_opportunities.c.title,
            crm_opportunities.c.stage,
            crm_opportunities.c.amount,
            crm_opportunities.c.currency,
            crm_opportunities.c.probability,
            crm_opportunities.c.expected_close_date,
            crm_opportunities.c.close_date,
            crm_opportunities.c.created_at,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("owner_name"),
        )
        .select_from(
            crm_opportunities
            .join(account, crm_opportunities.c.account_id == account.c.id)
            .outerjoin(owner, crm_opportunities.c.owner_id == owner.c.id)
        )
        .order_by(crm_opportunities.c.created_at.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def opportunity_summary_totals() -> dict:
    open_stages = ("prospecting", "qualification", "proposal", "negotiation")
    statement = select(
        func.count().label("total"),
        func.count().filter(crm_opportunities.c.stage.in_(open_stages)).label("open_count"),
        func.coalesce(
            func.sum(crm_opportunities.c.amount).filter(crm_opportunities.c.stage.in_(open_stages)), 0
        ).label("open_value"),
        func.count().filter(crm_opportunities.c.stage == "closed_won").label("won_count"),
        func.coalesce(
            func.sum(crm_opportunities.c.amount).filter(crm_opportunities.c.stage == "closed_won"), 0
        ).label("won_value"),
        func.count().filter(crm_opportunities.c.stage == "closed_lost").label("lost_count"),
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row)


# ---------------------------------------------------------------------------
# 2. Lead Summary Report
# ---------------------------------------------------------------------------

def lead_summary_report() -> list[dict]:
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_leads.c.id,
            crm_leads.c.first_name,
            crm_leads.c.last_name,
            crm_leads.c.company_name,
            crm_leads.c.source,
            crm_leads.c.status,
            crm_leads.c.created_at,
            owner.c.full_name.label("owner_name"),
        )
        .select_from(
            crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id)
        )
        .order_by(crm_leads.c.created_at.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def lead_summary_totals() -> dict:
    statement = select(
        func.count().label("total"),
        func.count().filter(crm_leads.c.status == "new").label("new"),
        func.count().filter(crm_leads.c.status == "contacted").label("contacted"),
        func.count().filter(crm_leads.c.status == "qualified").label("qualified"),
        func.count().filter(crm_leads.c.status == "unqualified").label("unqualified"),
        func.count().filter(crm_leads.c.status == "converted").label("converted"),
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row)


def lead_source_breakdown() -> list[dict]:
    statement = (
        select(crm_leads.c.source, func.count().label("count"))
        .group_by(crm_leads.c.source)
        .order_by(func.count().desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 3. Sales Forecast Report (detailed)
# ---------------------------------------------------------------------------

def sales_forecast_report() -> list[dict]:
    month_bucket = func.to_char(crm_opportunities.c.expected_close_date, "YYYY-MM")
    open_stages = ("prospecting", "qualification", "proposal", "negotiation")
    statement = (
        select(
            month_bucket.label("forecast_month"),
            func.count().label("deal_count"),
            func.coalesce(func.sum(crm_opportunities.c.amount), 0).label("total_amount"),
            func.coalesce(
                func.sum(crm_opportunities.c.amount * crm_opportunities.c.probability / 100.0), 0
            ).label("weighted_amount"),
            func.round(func.avg(crm_opportunities.c.probability), 0).label("avg_probability"),
        )
        .where(
            crm_opportunities.c.expected_close_date.is_not(None),
            crm_opportunities.c.amount.is_not(None),
            crm_opportunities.c.stage.in_(open_stages),
        )
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def sales_forecast_totals(forecast_rows: list[dict]) -> dict:
    total_amount = sum(r["total_amount"] for r in forecast_rows)
    weighted = sum(r["weighted_amount"] for r in forecast_rows)
    deals = sum(r["deal_count"] for r in forecast_rows)
    return {"total_amount": total_amount, "weighted_amount": weighted, "deal_count": deals}


# ---------------------------------------------------------------------------
# 4. Accounts by Value Report (closed-won + open sections)
# ---------------------------------------------------------------------------

def accounts_by_value_report() -> dict:
    open_stages = ("prospecting", "qualification", "proposal", "negotiation")

    def _query(stage_filter):
        statement = (
            select(
                crm_accounts.c.id,
                crm_accounts.c.company_name,
                func.count(crm_opportunities.c.id).label("deal_count"),
                func.coalesce(func.sum(crm_opportunities.c.amount), 0).label("total_value"),
            )
            .select_from(
                crm_accounts.join(crm_opportunities, crm_accounts.c.id == crm_opportunities.c.account_id)
            )
            .where(stage_filter)
            .group_by(crm_accounts.c.id, crm_accounts.c.company_name)
            .order_by(func.coalesce(func.sum(crm_opportunities.c.amount), 0).desc())
        )
        with get_connection() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    return {
        "closed_won": _query(crm_opportunities.c.stage == "closed_won"),
        "open": _query(crm_opportunities.c.stage.in_(open_stages)),
    }


# ---------------------------------------------------------------------------
# 5. Products Sold Report
# ---------------------------------------------------------------------------

def products_sold_report() -> list[dict]:
    statement = (
        select(
            crm_opportunity_lines.c.brand,
            crm_opportunity_lines.c.model,
            crm_opportunity_lines.c.grade,
            crm_opportunity_lines.c.storage,
            func.sum(crm_opportunity_lines.c.quantity).label("total_quantity"),
            func.sum(crm_opportunity_lines.c.line_total).label("total_value"),
        )
        .select_from(
            crm_opportunity_lines.join(
                crm_opportunities,
                crm_opportunity_lines.c.opportunity_id == crm_opportunities.c.id,
            )
        )
        .where(crm_opportunities.c.stage == "closed_won")
        .group_by(
            crm_opportunity_lines.c.brand,
            crm_opportunity_lines.c.model,
            crm_opportunity_lines.c.grade,
            crm_opportunity_lines.c.storage,
        )
        .order_by(func.sum(crm_opportunity_lines.c.line_total).desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def products_sold_totals(rows: list[dict]) -> dict:
    total_qty = sum(r["total_quantity"] for r in rows)
    total_val = sum(r["total_value"] for r in rows)
    return {"total_quantity": total_qty, "total_value": total_val}


# ---------------------------------------------------------------------------
# Legacy (kept for pipeline CSV export)
# ---------------------------------------------------------------------------

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
