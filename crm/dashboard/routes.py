from flask import Blueprint, g, render_template

from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.dashboard.queries import (
    all_recent_opportunities,
    my_leads,
    my_lead_count,
    my_opportunities,
    my_pipeline_value,
    recently_closed_opportunities,
    top_accounts_by_value,
    top_selling_products,
    total_open_opportunities,
)
from bridge_crm.crm.leads.queries import lead_status_counts

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard",
    template_folder="../../templates",
)


@dashboard_bp.route("/")
@login_required
def index():
    role = g.user["role"]
    user_id = g.user["id"]

    if role == "rep":
        pipeline = my_pipeline_value(user_id)
        return render_template(
            "dashboard/index.html",
            role=role,
            my_opportunities=my_opportunities(user_id),
            my_pipeline=pipeline,
            my_leads=my_leads(user_id),
            my_lead_count=my_lead_count(user_id),
        )

    open_opps = total_open_opportunities()
    return render_template(
        "dashboard/index.html",
        role=role,
        top_accounts=top_accounts_by_value(),
        recent_opportunities=all_recent_opportunities(),
        top_products=top_selling_products(),
        open_opportunities=open_opps,
        closed_opportunities=recently_closed_opportunities(),
        lead_counts=lead_status_counts(),
    )
