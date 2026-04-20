import csv
import io

from flask import Blueprint, Response, render_template

from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.reports.queries import (
    accounts_by_value_report,
    lead_source_breakdown,
    lead_summary_report,
    lead_summary_totals,
    opportunity_summary_report,
    opportunity_summary_totals,
    pipeline_breakdown,
    products_sold_report,
    products_sold_totals,
    sales_forecast_report,
    sales_forecast_totals,
)

reports_bp = Blueprint(
    "reports",
    __name__,
    url_prefix="/reports",
    template_folder="../../templates",
)


@reports_bp.route("/")
@login_required
def index():
    opp_rows = opportunity_summary_report()
    opp_totals = opportunity_summary_totals()
    lead_rows = lead_summary_report()
    lead_tots = lead_summary_totals()
    lead_sources = lead_source_breakdown()
    forecast_rows = sales_forecast_report()
    forecast_tots = sales_forecast_totals(forecast_rows)
    accounts = accounts_by_value_report()
    product_rows = products_sold_report()
    product_tots = products_sold_totals(product_rows)

    return render_template(
        "reports/index.html",
        opp_rows=opp_rows,
        opp_totals=opp_totals,
        lead_rows=lead_rows,
        lead_totals=lead_tots,
        lead_sources=lead_sources,
        forecast_rows=forecast_rows,
        forecast_totals=forecast_tots,
        accounts_won=accounts["closed_won"],
        accounts_open=accounts["open"],
        product_rows=product_rows,
        product_totals=product_tots,
    )


@reports_bp.route("/pipeline.csv")
@login_required
def pipeline_csv():
    rows = pipeline_breakdown()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["stage", "count", "amount"])
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=pipeline_report.csv"},
    )


@reports_bp.route("/opportunities.csv")
@login_required
def opportunities_csv():
    rows = opportunity_summary_report()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["title", "account_name", "owner_name", "stage", "amount", "currency", "probability", "expected_close_date", "close_date"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=opportunity_summary.csv"},
    )


@reports_bp.route("/leads.csv")
@login_required
def leads_csv():
    rows = lead_summary_report()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["first_name", "last_name", "company_name", "source", "status", "owner_name", "created_at"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=lead_summary.csv"},
    )


@reports_bp.route("/products.csv")
@login_required
def products_csv():
    rows = products_sold_report()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["brand", "model", "grade", "storage", "total_quantity", "total_value"],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_sold.csv"},
    )
