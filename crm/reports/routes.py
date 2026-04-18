import csv
import io

from flask import Blueprint, Response, render_template

from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.reports.queries import (
    lead_source_breakdown,
    pipeline_breakdown,
    sales_forecast,
)

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


@reports_bp.route("/")
@login_required
def index():
    pipeline = pipeline_breakdown()
    lead_sources = lead_source_breakdown()
    forecast = sales_forecast()
    return render_template(
        "reports/index.html",
        pipeline=pipeline,
        lead_sources=lead_sources,
        forecast=forecast,
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
