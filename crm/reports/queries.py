from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from bridge_crm.crm.opportunities.constants import (
    OPEN_OPPORTUNITY_STAGES,
    opportunity_amount_cad_expression,
)
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import (
    crm_accounts,
    crm_leads,
    crm_opportunities,
    crm_opportunity_lines,
    crm_pipeline_stages,
    crm_users,
)

RANGE_OPTIONS = [
    ("30", "Last 30 days"),
    ("90", "Last 90 days"),
    ("365", "Last 12 months"),
    ("ytd", "Year to date"),
    ("all", "All time"),
]
TABLE_PREVIEW_LIMIT = 12
CHART_DATASETS = {
    "opportunities": {
        "label": "Opportunities",
        "groups": [("stage", "Stage"), ("owner", "Salesperson"), ("month", "Month created")],
        "metrics": [("count", "Count"), ("amount_cad", "CAD value"), ("weighted", "Weighted CAD")],
    },
    "leads": {
        "label": "Leads",
        "groups": [("status", "Status"), ("source", "Source"), ("owner", "Owner"), ("month", "Month created")],
        "metrics": [("count", "Count")],
    },
    "products": {
        "label": "Products sold",
        "groups": [("product", "Product")],
        "metrics": [("quantity", "Units"), ("value", "CAD value")],
    },
    "accounts": {
        "label": "Accounts",
        "groups": [("account", "Account")],
        "metrics": [("won_value", "Won CAD"), ("open_value", "Open CAD")],
    },
}
CHART_TYPES = [
    ("bar", "Column"),
    ("horizontalBar", "Bar"),
    ("line", "Line"),
    ("doughnut", "Doughnut"),
    ("pie", "Pie"),
]


def resolve_since(range_key: str | None) -> datetime | None:
    key = (range_key or "90").strip().lower()
    now = datetime.now(timezone.utc)
    if key == "30":
        return now - timedelta(days=30)
    if key == "90":
        return now - timedelta(days=90)
    if key == "365":
        return now - timedelta(days=365)
    if key == "ytd":
        return datetime(now.year, 1, 1, tzinfo=timezone.utc)
    return None


def _scoped(statement, table, since: datetime | None = None, owner_id: int | None = None):
    if since is not None:
        statement = statement.where(table.c.created_at >= since)
    if owner_id:
        statement = statement.where(table.c.owner_id == int(owner_id))
    return statement


def _pretty(value: str | None) -> str:
    raw = (value or "Unknown").strip() or "Unknown"
    return raw.replace("_", " ").title()


def _float(value) -> float:
    return float(value or 0)


# ---------------------------------------------------------------------------
# 1. Opportunity Summary Report
# ---------------------------------------------------------------------------

def opportunity_summary_report(
    since: datetime | None = None,
    owner_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    account = crm_accounts.alias("account")
    owner = crm_users.alias("owner")
    statement = (
        select(
            crm_opportunities.c.id,
            crm_opportunities.c.title,
            crm_opportunities.c.stage,
            crm_opportunities.c.amount,
            crm_opportunities.c.currency,
            crm_opportunities.c.conversion_rate_to_cad,
            opportunity_amount_cad_expression().label("amount_cad"),
            crm_opportunities.c.probability,
            crm_opportunities.c.expected_close_date,
            crm_opportunities.c.close_date,
            crm_opportunities.c.created_at,
            account.c.company_name.label("account_name"),
            owner.c.full_name.label("salesperson_name"),
        )
        .select_from(
            crm_opportunities
            .join(account, crm_opportunities.c.account_id == account.c.id)
            .outerjoin(owner, crm_opportunities.c.owner_id == owner.c.id)
        )
        .order_by(crm_opportunities.c.created_at.desc())
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    if limit:
        statement = statement.limit(limit)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def opportunity_summary_totals(since: datetime | None = None, owner_id: int | None = None) -> dict:
    statement = select(
        func.count().label("total"),
        func.count().filter(crm_opportunities.c.stage.in_(OPEN_OPPORTUNITY_STAGES)).label("open_count"),
        func.coalesce(
            func.sum(opportunity_amount_cad_expression()).filter(
                crm_opportunities.c.stage.in_(OPEN_OPPORTUNITY_STAGES)
            ),
            0,
        ).label("open_value"),
        func.count().filter(crm_opportunities.c.stage == "closed_won").label("won_count"),
        func.coalesce(
            func.sum(opportunity_amount_cad_expression()).filter(
                crm_opportunities.c.stage == "closed_won"
            ),
            0,
        ).label("won_value"),
        func.count().filter(crm_opportunities.c.stage == "closed_lost").label("lost_count"),
        func.coalesce(
            func.sum(opportunity_amount_cad_expression()).filter(
                crm_opportunities.c.stage == "closed_lost"
            ),
            0,
        ).label("lost_value"),
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    totals = dict(row or {})
    won = int(totals.get("won_count") or 0)
    lost = int(totals.get("lost_count") or 0)
    closed = won + lost
    totals["win_rate"] = round((won / closed) * 100, 1) if closed else 0
    return totals


# ---------------------------------------------------------------------------
# 2. Lead Summary Report
# ---------------------------------------------------------------------------

def lead_summary_report(
    since: datetime | None = None,
    owner_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
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
    statement = _scoped(statement, crm_leads, since=since, owner_id=owner_id)
    if limit:
        statement = statement.limit(limit)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def lead_summary_totals(since: datetime | None = None, owner_id: int | None = None) -> dict:
    statement = select(
        func.count().label("total"),
        func.count().filter(crm_leads.c.status == "new").label("new"),
        func.count().filter(crm_leads.c.status == "contacted").label("contacted"),
        func.count().filter(crm_leads.c.status == "qualified").label("qualified"),
        func.count().filter(crm_leads.c.status == "unqualified").label("unqualified"),
        func.count().filter(crm_leads.c.status == "converted").label("converted"),
    )
    statement = _scoped(statement, crm_leads, since=since, owner_id=owner_id)
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    totals = dict(row or {})
    total = int(totals.get("total") or 0)
    converted = int(totals.get("converted") or 0)
    totals["conversion_rate"] = round((converted / total) * 100, 1) if total else 0
    return totals


def lead_source_breakdown(since: datetime | None = None, owner_id: int | None = None) -> list[dict]:
    statement = (
        select(crm_leads.c.source, func.count().label("count"))
        .group_by(crm_leads.c.source)
        .order_by(func.count().desc())
    )
    statement = _scoped(statement, crm_leads, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def lead_status_breakdown(since: datetime | None = None, owner_id: int | None = None) -> list[dict]:
    statement = (
        select(crm_leads.c.status, func.count().label("count"))
        .group_by(crm_leads.c.status)
        .order_by(func.count().desc())
    )
    statement = _scoped(statement, crm_leads, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# 3. Sales Forecast Report (detailed)
# ---------------------------------------------------------------------------

def sales_forecast_report(owner_id: int | None = None) -> list[dict]:
    month_bucket = func.to_char(crm_opportunities.c.expected_close_date, "YYYY-MM")
    statement = (
        select(
            month_bucket.label("forecast_month"),
            func.count().label("deal_count"),
            func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).label("total_amount"),
            func.coalesce(
                func.sum(opportunity_amount_cad_expression() * crm_opportunities.c.probability / 100.0),
                0,
            ).label("weighted_amount"),
            func.round(func.avg(crm_opportunities.c.probability), 0).label("avg_probability"),
        )
        .where(
            crm_opportunities.c.expected_close_date.is_not(None),
            crm_opportunities.c.amount.is_not(None),
            crm_opportunities.c.stage.in_(OPEN_OPPORTUNITY_STAGES),
        )
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    if owner_id:
        statement = statement.where(crm_opportunities.c.owner_id == int(owner_id))
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

def accounts_by_value_report(
    since: datetime | None = None,
    owner_id: int | None = None,
    limit: int | None = None,
) -> dict:
    def _query(stage_filter):
        statement = (
            select(
                crm_accounts.c.id,
                crm_accounts.c.company_name,
                func.count(crm_opportunities.c.id).label("deal_count"),
                func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).label("total_value"),
            )
            .select_from(
                crm_accounts.join(crm_opportunities, crm_accounts.c.id == crm_opportunities.c.account_id)
            )
            .where(stage_filter)
            .group_by(crm_accounts.c.id, crm_accounts.c.company_name)
            .order_by(func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).desc())
        )
        statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
        if limit:
            statement = statement.limit(limit)
        with get_connection() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    return {
        "closed_won": _query(crm_opportunities.c.stage == "closed_won"),
        "open": _query(crm_opportunities.c.stage.in_(OPEN_OPPORTUNITY_STAGES)),
    }


# ---------------------------------------------------------------------------
# 5. Products Sold Report
# ---------------------------------------------------------------------------

def products_sold_report(
    since: datetime | None = None,
    owner_id: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    statement = (
        select(
            crm_opportunity_lines.c.brand,
            crm_opportunity_lines.c.model,
            crm_opportunity_lines.c.grade,
            crm_opportunity_lines.c.storage,
            func.sum(crm_opportunity_lines.c.quantity).label("total_quantity"),
            func.sum(
                crm_opportunity_lines.c.line_total
                * func.coalesce(crm_opportunities.c.conversion_rate_to_cad, 1)
            ).label("total_value"),
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
        .order_by(
            func.sum(
                crm_opportunity_lines.c.line_total
                * func.coalesce(crm_opportunities.c.conversion_rate_to_cad, 1)
            ).desc()
        )
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    if limit:
        statement = statement.limit(limit)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def products_sold_totals(rows: list[dict]) -> dict:
    total_qty = sum(r["total_quantity"] for r in rows)
    total_val = sum(r["total_value"] for r in rows)
    return {"total_quantity": total_qty or 0, "total_value": total_val or 0}


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def pipeline_breakdown(since: datetime | None = None, owner_id: int | None = None) -> list[dict]:
    statement = (
        select(
            crm_opportunities.c.stage,
            func.coalesce(crm_pipeline_stages.c.display_name, crm_opportunities.c.stage).label("display_name"),
            func.count().label("count"),
            func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).label("amount_cad"),
        )
        .select_from(
            crm_opportunities.outerjoin(
                crm_pipeline_stages,
                crm_pipeline_stages.c.stage_key == crm_opportunities.c.stage,
            )
        )
        .group_by(
            crm_opportunities.c.stage,
            crm_pipeline_stages.c.display_name,
            crm_pipeline_stages.c.display_order,
        )
        .order_by(func.coalesce(crm_pipeline_stages.c.display_order, 99), crm_opportunities.c.stage)
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def opportunities_by_owner(since: datetime | None = None, owner_id: int | None = None) -> list[dict]:
    owner = crm_users.alias("owner")
    statement = (
        select(
            func.coalesce(owner.c.full_name, "Unassigned").label("owner_name"),
            func.count().label("count"),
            func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).label("amount_cad"),
        )
        .select_from(crm_opportunities.outerjoin(owner, crm_opportunities.c.owner_id == owner.c.id))
        .group_by(owner.c.full_name)
        .order_by(func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).desc())
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def won_revenue_by_month(since: datetime | None = None, owner_id: int | None = None) -> list[dict]:
    month_bucket = func.to_char(
        func.coalesce(crm_opportunities.c.close_date, func.date(crm_opportunities.c.created_at)),
        "YYYY-MM",
    )
    statement = (
        select(
            month_bucket.label("month"),
            func.count().label("count"),
            func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).label("amount_cad"),
        )
        .where(crm_opportunities.c.stage == "closed_won")
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def custom_chart_data(
    dataset: str,
    group_by: str,
    metric: str,
    since: datetime | None = None,
    owner_id: int | None = None,
    limit: int = 12,
) -> dict:
    dataset_conf = CHART_DATASETS.get(dataset) or CHART_DATASETS["opportunities"]
    allowed_groups = {key for key, _label in dataset_conf["groups"]}
    allowed_metrics = {key for key, _label in dataset_conf["metrics"]}
    if group_by not in allowed_groups:
        group_by = dataset_conf["groups"][0][0]
    if metric not in allowed_metrics:
        metric = dataset_conf["metrics"][0][0]

    rows: list[dict] = []
    unit = "count"
    if dataset == "leads":
        rows, unit = _lead_chart_rows(group_by, since, owner_id)
    elif dataset == "products":
        rows, unit = _product_chart_rows(metric, since, owner_id)
    elif dataset == "accounts":
        rows, unit = _account_chart_rows(metric, since, owner_id)
    else:
        rows, unit = _opportunity_chart_rows(group_by, metric, since, owner_id)

    rows = rows[:limit]
    group_label = dict(dataset_conf["groups"]).get(group_by, group_by)
    metric_label = dict(dataset_conf["metrics"]).get(metric, metric)
    return {
        "labels": [row["label"] for row in rows],
        "values": [row["value"] for row in rows],
        "unit": unit,
        "title": f"{dataset_conf['label']}: {metric_label.lower()} by {group_label.lower()}",
    }


def _opportunity_chart_rows(group_by: str, metric: str, since, owner_id) -> tuple[list[dict], str]:
    owner = crm_users.alias("owner")
    if group_by == "owner":
        label_expr = func.coalesce(owner.c.full_name, "Unassigned")
    elif group_by == "month":
        label_expr = func.to_char(crm_opportunities.c.created_at, "YYYY-MM")
    else:
        label_expr = func.coalesce(crm_pipeline_stages.c.display_name, crm_opportunities.c.stage)

    if metric == "weighted":
        value_expr = func.coalesce(
            func.sum(opportunity_amount_cad_expression() * crm_opportunities.c.probability / 100.0),
            0,
        )
        unit = "cad"
    elif metric == "amount_cad":
        value_expr = func.coalesce(func.sum(opportunity_amount_cad_expression()), 0)
        unit = "cad"
    else:
        value_expr = func.count()
        unit = "count"

    statement = select(label_expr.label("label"), value_expr.label("value"))
    if group_by == "owner":
        statement = statement.select_from(
            crm_opportunities.outerjoin(owner, crm_opportunities.c.owner_id == owner.c.id)
        )
    elif group_by == "stage":
        statement = statement.select_from(
            crm_opportunities.outerjoin(
                crm_pipeline_stages,
                crm_pipeline_stages.c.stage_key == crm_opportunities.c.stage,
            )
        )
    statement = statement.group_by(label_expr).order_by(value_expr.desc())
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [{"label": _pretty(row["label"]) if group_by != "month" else str(row["label"]), "value": _float(row["value"])} for row in rows], unit


def _lead_chart_rows(group_by: str, since, owner_id) -> tuple[list[dict], str]:
    owner = crm_users.alias("owner")
    if group_by == "owner":
        label_expr = func.coalesce(owner.c.full_name, "Unassigned")
    elif group_by == "month":
        label_expr = func.to_char(crm_leads.c.created_at, "YYYY-MM")
    elif group_by == "source":
        label_expr = func.coalesce(crm_leads.c.source, "Unknown")
    else:
        label_expr = func.coalesce(crm_leads.c.status, "Unknown")

    statement = select(label_expr.label("label"), func.count().label("value"))
    if group_by == "owner":
        statement = statement.select_from(
            crm_leads.outerjoin(owner, crm_leads.c.owner_id == owner.c.id)
        )
    statement = statement.group_by(label_expr).order_by(func.count().desc())
    statement = _scoped(statement, crm_leads, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    pretty = group_by != "month"
    return [
        {"label": _pretty(row["label"]) if pretty else str(row["label"]), "value": _float(row["value"])}
        for row in rows
    ], "count"


def _product_chart_rows(metric: str, since, owner_id) -> tuple[list[dict], str]:
    label_expr = func.concat(
        func.coalesce(crm_opportunity_lines.c.brand, ""),
        " ",
        func.coalesce(crm_opportunity_lines.c.model, ""),
    )
    if metric == "quantity":
        value_expr = func.coalesce(func.sum(crm_opportunity_lines.c.quantity), 0)
        unit = "count"
    else:
        value_expr = func.coalesce(
            func.sum(
                crm_opportunity_lines.c.line_total
                * func.coalesce(crm_opportunities.c.conversion_rate_to_cad, 1)
            ),
            0,
        )
        unit = "cad"
    statement = (
        select(label_expr.label("label"), value_expr.label("value"))
        .select_from(
            crm_opportunity_lines.join(
                crm_opportunities,
                crm_opportunity_lines.c.opportunity_id == crm_opportunities.c.id,
            )
        )
        .where(crm_opportunities.c.stage == "closed_won")
        .group_by(label_expr)
        .order_by(value_expr.desc())
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [{"label": (row["label"] or "Unknown").strip() or "Unknown", "value": _float(row["value"])} for row in rows], unit


def _account_chart_rows(metric: str, since, owner_id) -> tuple[list[dict], str]:
    stage_filter = (
        crm_opportunities.c.stage.in_(OPEN_OPPORTUNITY_STAGES)
        if metric == "open_value"
        else crm_opportunities.c.stage == "closed_won"
    )
    statement = (
        select(
            crm_accounts.c.company_name.label("label"),
            func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).label("value"),
        )
        .select_from(crm_accounts.join(crm_opportunities, crm_accounts.c.id == crm_opportunities.c.account_id))
        .where(stage_filter)
        .group_by(crm_accounts.c.company_name)
        .order_by(func.coalesce(func.sum(opportunity_amount_cad_expression()), 0).desc())
    )
    statement = _scoped(statement, crm_opportunities, since=since, owner_id=owner_id)
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [{"label": row["label"] or "Unknown", "value": _float(row["value"])} for row in rows], "cad"
