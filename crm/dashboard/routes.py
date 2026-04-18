from decimal import Decimal

from flask import Blueprint, render_template
from sqlalchemy import func, select

from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.leads.queries import lead_status_counts
from bridge_crm.crm.opportunities.queries import list_opportunities
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_accounts, crm_leads, crm_opportunities

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@login_required
def index():
    with get_connection() as connection:
        account_count = connection.execute(
            select(func.count()).select_from(crm_accounts)
        ).scalar_one()
        lead_count = connection.execute(
            select(func.count()).select_from(crm_leads)
        ).scalar_one()
        opportunity_count = connection.execute(
            select(func.count()).select_from(crm_opportunities)
        ).scalar_one()
        pipeline_value = connection.execute(
            select(func.coalesce(func.sum(crm_opportunities.c.amount), 0))
        ).scalar_one()

    opportunities = list_opportunities()[:5]
    return render_template(
        "dashboard/index.html",
        metrics={
            "accounts": int(account_count),
            "leads": int(lead_count),
            "opportunities": int(opportunity_count),
            "pipeline_value": Decimal(pipeline_value or 0),
        },
        lead_counts=lead_status_counts(),
        opportunities=opportunities,
    )
