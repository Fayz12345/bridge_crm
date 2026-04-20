from decimal import Decimal

from sqlalchemy import case, func, literal_column, select, union_all

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_leads,
    crm_opportunities,
    crm_opportunity_lines,
    crm_users,
)


# ---------------------------------------------------------------------------
# Rep dashboard queries (scoped to owner_id)
# ---------------------------------------------------------------------------

def my_opportunities(user_id: int, limit: int = 10) -> list[dict]:
    account = crm_accounts.alias("account")
    statement = (
        select(
            crm_opportunities.c.id,
            crm_opportunities.c.title,
            crm_opportunities.c.stage,
            crm_opportunities.c.amount,
            crm_opportunities.c.currency,
            crm_opportunities.c.expected_close_date,
            account.c.company_name.label("account_name"),
        )
        .select_from(
            crm_opportunities.join(account, crm_opportunities.c.account_id == account.c.id)
        )
        .where(crm_opportunities.c.owner_id == user_id)
        .order_by(crm_opportunities.c.created_at.desc())
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def my_pipeline_value(user_id: int) -> dict:
    open_stages = ("prospecting", "qualification", "proposal", "negotiation")
    statement = select(
        func.count().label("count"),
        func.coalesce(func.sum(crm_opportunities.c.amount), 0).label("value"),
    ).where(
        crm_opportunities.c.owner_id == user_id,
        crm_opportunities.c.stage.in_(open_stages),
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return {"count": int(row["count"]), "value": Decimal(row["value"] or 0)}


def my_leads(user_id: int, limit: int = 10) -> list[dict]:
    statement = (
        select(
            crm_leads.c.id,
            crm_leads.c.first_name,
            crm_leads.c.last_name,
            crm_leads.c.company_name,
            crm_leads.c.status,
            crm_leads.c.source,
            crm_leads.c.created_at,
        )
        .where(crm_leads.c.owner_id == user_id)
        .order_by(crm_leads.c.created_at.desc())
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def my_lead_count(user_id: int) -> int:
    statement = select(func.count()).select_from(crm_leads).where(
        crm_leads.c.owner_id == user_id,
    )
    with get_connection() as connection:
        return int(connection.execute(statement).scalar_one())


# ---------------------------------------------------------------------------
# Manager / admin dashboard queries (org-wide)
# ---------------------------------------------------------------------------

def top_accounts_by_value(limit: int = 10) -> list[dict]:
    statement = (
        select(
            crm_accounts.c.id,
            crm_accounts.c.company_name,
            func.count(crm_opportunities.c.id).label("opportunity_count"),
            func.coalesce(func.sum(crm_opportunities.c.amount), 0).label("total_value"),
        )
        .select_from(
            crm_accounts.join(crm_opportunities, crm_accounts.c.id == crm_opportunities.c.account_id)
        )
        .group_by(crm_accounts.c.id, crm_accounts.c.company_name)
        .order_by(func.coalesce(func.sum(crm_opportunities.c.amount), 0).desc())
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def all_recent_opportunities(limit: int = 10) -> list[dict]:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_opportunities.c.id,
            crm_opportunities.c.title,
            crm_opportunities.c.stage,
            crm_opportunities.c.amount,
            crm_opportunities.c.currency,
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
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def top_selling_products(limit: int = 10) -> list[dict]:
    statement = (
        select(
            crm_opportunity_lines.c.brand,
            crm_opportunity_lines.c.model,
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
        .group_by(crm_opportunity_lines.c.brand, crm_opportunity_lines.c.model)
        .order_by(func.sum(crm_opportunity_lines.c.line_total).desc())
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def total_open_opportunities() -> dict:
    open_stages = ("prospecting", "qualification", "proposal", "negotiation")
    statement = select(
        func.count().label("count"),
        func.coalesce(func.sum(crm_opportunities.c.amount), 0).label("value"),
    ).where(crm_opportunities.c.stage.in_(open_stages))
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return {"count": int(row["count"]), "value": Decimal(row["value"] or 0)}


def recently_closed_opportunities(limit: int = 10) -> list[dict]:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_opportunities.c.id,
            crm_opportunities.c.title,
            crm_opportunities.c.stage,
            crm_opportunities.c.amount,
            crm_opportunities.c.currency,
            crm_opportunities.c.close_date,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("owner_name"),
        )
        .select_from(
            crm_opportunities
            .join(account, crm_opportunities.c.account_id == account.c.id)
            .outerjoin(owner, crm_opportunities.c.owner_id == owner.c.id)
        )
        .where(crm_opportunities.c.stage.in_(("closed_won", "closed_lost")))
        .order_by(crm_opportunities.c.updated_at.desc())
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]
