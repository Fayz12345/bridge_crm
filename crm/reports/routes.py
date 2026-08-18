import csv
import io

from flask import Blueprint, Response, render_template, request

from bridge_crm.crm.auth.queries import list_assignable_users
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.reports.queries import (
    CHART_DATASETS,
    CHART_TYPES,
    RANGE_OPTIONS,
    TABLE_PREVIEW_LIMIT,
    accounts_by_value_report,
    custom_chart_data,
    lead_source_breakdown,
    lead_status_breakdown,
    lead_summary_report,
    lead_summary_totals,
    opportunities_by_owner,
    opportunity_summary_report,
    opportunity_summary_totals,
    pipeline_breakdown,
    products_sold_report,
    products_sold_totals,
    resolve_since,
    sales_forecast_report,
    sales_forecast_totals,
    won_revenue_by_month,
)

reports_bp = Blueprint(
    "reports",
    __name__,
    url_prefix="/reports",
    template_folder="../../templates",
)


def _filter_args() -> dict:
    range_key = (request.args.get("range") or "90").strip().lower()
    if range_key not in {key for key, _label in RANGE_OPTIONS}:
        range_key = "90"
    owner_raw = (request.args.get("owner_id") or "").strip()
    try:
        owner_id = int(owner_raw) if owner_raw else None
    except ValueError:
        owner_id = None
    return {"range": range_key, "owner_id": owner_id}


def _chart_args() -> dict:
    dataset = (request.args.get("chart_dataset") or "opportunities").strip()
    if dataset not in CHART_DATASETS:
        dataset = "opportunities"
    allowed_groups = {key for key, _label in CHART_DATASETS[dataset]["groups"]}
    allowed_metrics = {key for key, _label in CHART_DATASETS[dataset]["metrics"]}
    group_by = (request.args.get("chart_group") or CHART_DATASETS[dataset]["groups"][0][0]).strip()
    metric = (request.args.get("chart_metric") or CHART_DATASETS[dataset]["metrics"][0][0]).strip()
    chart_type = (request.args.get("chart_type") or "bar").strip()
    if group_by not in allowed_groups:
        group_by = CHART_DATASETS[dataset]["groups"][0][0]
    if metric not in allowed_metrics:
        metric = CHART_DATASETS[dataset]["metrics"][0][0]
    if chart_type not in {key for key, _label in CHART_TYPES}:
        chart_type = "bar"
    return {
        "dataset": dataset,
        "group_by": group_by,
        "metric": metric,
        "chart_type": chart_type,
    }


def _query_params(extra: dict | None = None) -> dict:
    filters = _filter_args()
    params = {"range": filters["range"]}
    if filters["owner_id"]:
        params["owner_id"] = filters["owner_id"]
    if extra:
        params.update({key: value for key, value in extra.items() if value})
    return params


@reports_bp.route("/")
@login_required
def index():
    filters = _filter_args()
    chart = _chart_args()
    since = resolve_since(filters["range"])
    owner_id = filters["owner_id"]

    opp_rows = opportunity_summary_report(since=since, owner_id=owner_id, limit=TABLE_PREVIEW_LIMIT)
    opp_totals = opportunity_summary_totals(since=since, owner_id=owner_id)
    lead_rows = lead_summary_report(since=since, owner_id=owner_id, limit=TABLE_PREVIEW_LIMIT)
    lead_tots = lead_summary_totals(since=since, owner_id=owner_id)
    lead_sources = lead_source_breakdown(since=since, owner_id=owner_id)
    lead_statuses = lead_status_breakdown(since=since, owner_id=owner_id)
    forecast_rows = sales_forecast_report(owner_id=owner_id)
    forecast_tots = sales_forecast_totals(forecast_rows)
    accounts = accounts_by_value_report(since=since, owner_id=owner_id, limit=TABLE_PREVIEW_LIMIT)
    product_rows = products_sold_report(since=since, owner_id=owner_id, limit=TABLE_PREVIEW_LIMIT)
    product_tots = products_sold_totals(product_rows)
    pipeline_rows = pipeline_breakdown(since=since, owner_id=owner_id)
    owner_rows = opportunities_by_owner(since=since, owner_id=owner_id)
    won_months = won_revenue_by_month(since=since, owner_id=owner_id)
    built_chart = custom_chart_data(
        chart["dataset"],
        chart["group_by"],
        chart["metric"],
        since=since,
        owner_id=owner_id,
    )

    return render_template(
        "reports/index.html",
        range_key=filters["range"],
        owner_id=owner_id,
        owners=list_assignable_users(),
        range_options=RANGE_OPTIONS,
        chart_datasets=CHART_DATASETS,
        chart_types=CHART_TYPES,
        chart=chart,
        built_chart=built_chart,
        filter_params=_query_params(),
        table_limit=TABLE_PREVIEW_LIMIT,
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
        pipeline_rows=pipeline_rows,
        chart_pipeline_labels=[row.get("display_name") or row["stage"].replace("_", " ").title() for row in pipeline_rows],
        chart_pipeline_counts=[int(row["count"]) for row in pipeline_rows],
        chart_pipeline_values=[float(row["amount_cad"] or 0) for row in pipeline_rows],
        chart_lead_labels=[src["source"].replace("_", " ").title() for src in lead_sources],
        chart_lead_counts=[int(src["count"]) for src in lead_sources],
        chart_lead_status_labels=[row["status"].replace("_", " ").title() for row in lead_statuses],
        chart_lead_status_counts=[int(row["count"]) for row in lead_statuses],
        chart_owner_labels=[row["owner_name"] for row in owner_rows],
        chart_owner_values=[float(row["amount_cad"] or 0) for row in owner_rows],
        chart_won_labels=[row["month"] for row in won_months],
        chart_won_values=[float(row["amount_cad"] or 0) for row in won_months],
        chart_product_labels=[f"{row['brand']} {row['model']}".strip() for row in product_rows[:8]],
        chart_product_values=[float(row["total_value"] or 0) for row in product_rows[:8]],
        chart_forecast_labels=[row["forecast_month"] for row in forecast_rows],
        chart_forecast_total=[float(row["total_amount"] or 0) for row in forecast_rows],
        chart_forecast_weighted=[float(row["weighted_amount"] or 0) for row in forecast_rows],
    )


def _csv_response(filename: str, fieldnames: list[str], rows: list[dict]) -> Response:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@reports_bp.route("/pipeline.csv")
@login_required
def pipeline_csv():
    filters = _filter_args()
    rows = pipeline_breakdown(since=resolve_since(filters["range"]), owner_id=filters["owner_id"])
    return _csv_response("pipeline_report.csv", ["stage", "display_name", "count", "amount_cad"], rows)


@reports_bp.route("/opportunities.csv")
@login_required
def opportunities_csv():
    filters = _filter_args()
    rows = opportunity_summary_report(since=resolve_since(filters["range"]), owner_id=filters["owner_id"])
    return _csv_response(
        "opportunity_summary.csv",
        [
            "title",
            "account_name",
            "salesperson_name",
            "stage",
            "amount",
            "currency",
            "conversion_rate_to_cad",
            "amount_cad",
            "probability",
            "expected_close_date",
            "close_date",
        ],
        rows,
    )


@reports_bp.route("/leads.csv")
@login_required
def leads_csv():
    filters = _filter_args()
    rows = lead_summary_report(since=resolve_since(filters["range"]), owner_id=filters["owner_id"])
    return _csv_response(
        "lead_summary.csv",
        ["first_name", "last_name", "company_name", "source", "status", "owner_name", "created_at"],
        rows,
    )


@reports_bp.route("/products.csv")
@login_required
def products_csv():
    filters = _filter_args()
    rows = products_sold_report(since=resolve_since(filters["range"]), owner_id=filters["owner_id"])
    return _csv_response(
        "products_sold.csv",
        ["brand", "model", "grade", "storage", "total_quantity", "total_value"],
        rows,
    )
