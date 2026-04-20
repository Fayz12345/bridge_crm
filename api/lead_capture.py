from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, render_template, request
from markupsafe import escape
from sqlalchemy import func, insert, select

from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.leads.queries import create_lead
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_rate_limits

lead_capture_bp = Blueprint(
    "lead_capture",
    __name__,
    template_folder="../templates",
)


def _origin_allowed(origin: str | None) -> bool:
    allowed = current_app.config.get("CORS_ALLOWED_ORIGINS", [])
    if not origin:
        return True
    return origin in allowed


def _corsify(response):
    origin = request.headers.get("Origin")
    if origin and _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


def _too_many_requests(ip_address: str, endpoint: str, window_seconds: int, limit: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    statement = select(func.count()).select_from(crm_rate_limits).where(
        crm_rate_limits.c.ip_address == ip_address,
        crm_rate_limits.c.endpoint == endpoint,
        crm_rate_limits.c.created_at >= cutoff,
    )
    with get_connection() as connection:
        count = connection.execute(statement).scalar_one()
    return int(count) >= limit


def _record_request(ip_address: str, endpoint: str) -> None:
    statement = insert(crm_rate_limits).values(ip_address=ip_address, endpoint=endpoint)
    with get_connection() as connection:
        connection.execute(statement)


@lead_capture_bp.route("/api/leads", methods=["OPTIONS"])
def lead_capture_options():
    response = jsonify({"ok": True})
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return _corsify(response)


@lead_capture_bp.route("/api/leads", methods=["POST"])
def capture_lead():
    origin = request.headers.get("Origin")
    if origin and not _origin_allowed(origin):
        return jsonify({"ok": False, "errors": {"origin": "Origin not allowed"}}), 403

    if request.content_type is None or "application/json" not in request.content_type:
        return jsonify({"ok": False, "errors": {"content_type": "Expected application/json"}}), 415

    ip_address = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    ip_address = ip_address.split(",")[0].strip()
    if _too_many_requests(ip_address, "/api/leads", 3600, 5):
        return jsonify({"ok": False, "errors": {"rate_limit": "Too many requests"}}), 429

    data = request.get_json(silent=True) or {}
    first_name = escape((data.get("first_name") or "").strip())
    last_name = escape((data.get("last_name") or "").strip())
    email = escape((data.get("email") or "").strip())
    phone = escape((data.get("phone") or "").strip())
    company_name = escape((data.get("company_name") or "").strip())
    interest = escape((data.get("interest") or "").strip())

    errors = {}
    if not first_name:
        errors["first_name"] = "First name is required."
    if not last_name:
        errors["last_name"] = "Last name is required."
    if not email:
        errors["email"] = "Email is required."

    if errors:
        response = jsonify({"ok": False, "errors": errors})
        return _corsify(response), 400

    lead_id = create_lead(
        {
            "first_name": str(first_name)[:120],
            "last_name": str(last_name)[:120],
            "email": str(email)[:255],
            "phone": str(phone)[:30],
            "phone_prefix": "+1",
            "company_name": str(company_name)[:255],
            "source": "web_form",
            "status": "new",
            "notes": None,
            "interest": str(interest)[:5000],
            "owner_id": None,
        }
    )
    _record_request(ip_address, "/api/leads")
    log_activity(
        "lead",
        lead_id,
        "created",
        "Lead captured from public web form.",
        None,
        {"source": "web_form"},
    )
    response = jsonify({"ok": True, "message": "Lead received."})
    return _corsify(response), 201


@lead_capture_bp.route("/lead-form")
def lead_form():
    return render_template("lead_form/index.html")
