from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from bridge_crm.crm.accounts.queries import create_account
from bridge_crm.crm.activities.queries import list_activities, log_activity
from bridge_crm.crm.auth.queries import list_assignable_users
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.custom_fields.queries import (
    extract_custom_field_values,
    get_custom_field_values,
    list_custom_fields,
)
from bridge_crm.crm.leads.queries import (
    VALID_LEAD_STATUSES,
    create_lead,
    get_lead,
    list_leads,
    update_lead,
)
from bridge_crm.crm.opportunities.queries import create_contact, create_opportunity

leads_bp = Blueprint(
    "leads",
    __name__,
    url_prefix="/leads",
    template_folder="../../templates",
)

LEAD_FIELDS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "phone_prefix",
    "company_name",
    "source",
    "status",
    "notes",
    "interest",
]


def _int_or_none(value: str | None):
    if not value:
        return None
    return int(value)


def _build_payload(form_data) -> dict:
    payload = {field: form_data.get(field, "").strip() or None for field in LEAD_FIELDS}
    payload["first_name"] = form_data.get("first_name", "").strip()
    payload["last_name"] = form_data.get("last_name", "").strip()
    payload["source"] = form_data.get("source", "manual").strip() or "manual"
    payload["status"] = form_data.get("status", "new").strip() or "new"
    payload["owner_id"] = _int_or_none(form_data.get("owner_id"))
    return payload


@leads_bp.route("/")
@login_required
def list_view():
    status = request.args.get("status", "new").strip().lower()
    status_filter = status if status in VALID_LEAD_STATUSES else None
    search_term = request.args.get("q", "").strip()
    leads = list_leads(status_filter, search_term if search_term else None)
    return render_template(
        "leads/list.html",
        leads=leads,
        active_status=status if status_filter else "all",
        search_term=search_term,
    )


@leads_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_view():
    form_data = request.form if request.method == "POST" else {"owner_id": g.user["id"]}
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("lead", active_only=True)
    if request.method == "POST":
        if not request.form.get("first_name", "").strip() or not request.form.get(
            "last_name", ""
        ).strip():
            flash("First and last name are required.", "danger")
        else:
            payload = _build_payload(request.form)
            payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
            lead_id = create_lead(payload)
            log_activity(
                "lead",
                lead_id,
                "created",
                f"Lead created from {payload['source']}.",
                g.user["id"],
            )
            flash("Lead created.", "success")
            return redirect(url_for("leads.detail_view", lead_id=lead_id))

    return render_template(
        "leads/form.html",
        lead=None,
        form_data=form_data,
        owners=owners,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if request.method == "POST" else {},
        page_title="New Lead",
        submit_label="Create Lead",
    )


@leads_bp.route("/<int:lead_id>")
@login_required
def detail_view(lead_id: int):
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.list_view"))

    activities = list_activities("lead", lead_id)
    custom_field_rows = get_custom_field_values(
        lead, list_custom_fields("lead", active_only=True)
    )
    return render_template(
        "leads/detail.html",
        lead=lead,
        activities=activities,
        custom_field_rows=custom_field_rows,
    )


@leads_bp.route("/<int:lead_id>/edit", methods=["GET", "POST"])
@login_required
def edit_view(lead_id: int):
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.list_view"))

    form_data = request.form if request.method == "POST" else lead
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("lead", active_only=True)
    if request.method == "POST":
        if not request.form.get("first_name", "").strip() or not request.form.get(
            "last_name", ""
        ).strip():
            flash("First and last name are required.", "danger")
        else:
            payload = _build_payload(request.form)
            payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
            previous_status = lead["status"]
            update_lead(lead_id, payload)
            if previous_status != payload["status"]:
                log_activity(
                    "lead",
                    lead_id,
                    "status_changed",
                    f"Lead status changed from {previous_status} to {payload['status']}.",
                    g.user["id"],
                    {"from": previous_status, "to": payload["status"]},
                )
            flash("Lead updated.", "success")
            return redirect(url_for("leads.detail_view", lead_id=lead_id))

    return render_template(
        "leads/form.html",
        lead=lead,
        form_data=form_data,
        owners=owners,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if request.method == "POST" else (lead.get("custom_fields") or {}),
        page_title="Edit Lead",
        submit_label="Save Changes",
    )


@leads_bp.route("/<int:lead_id>/convert", methods=["POST"])
@login_required
def convert_view(lead_id: int):
    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.list_view"))

    if lead["status"] == "converted":
        flash("Lead is already converted.", "warning")
        return redirect(url_for("leads.detail_view", lead_id=lead_id))

    account_payload = {
        "company_name": lead["company_name"] or f"{lead['first_name']} {lead['last_name']}",
        "contact_name": f"{lead['first_name']} {lead['last_name']}",
        "email": lead["email"],
        "phone": lead["phone"],
        "phone_prefix": lead["phone_prefix"],
        "website": None,
        "address_line_1": None,
        "address_line_2": None,
        "city": None,
        "state_province": None,
        "postal_code": None,
        "country": "Canada",
        "industry": None,
        "erp_client_id": None,
        "notes": lead["notes"],
        "owner_id": lead["owner_id"] or g.user["id"],
        "created_by": g.user["id"],
    }
    account_id = create_account(account_payload)

    contact_id = create_contact(
        {
            "account_id": account_id,
            "first_name": lead["first_name"],
            "last_name": lead["last_name"],
            "email": lead["email"],
            "phone": lead["phone"],
            "phone_prefix": lead["phone_prefix"],
            "job_title": None,
            "is_primary": True,
            "whatsapp_number": lead["phone"],
        }
    )

    opportunity_id = create_opportunity(
        {
            "title": request.form.get("title", "").strip()
            or f"{account_payload['company_name']} - New Opportunity",
            "account_id": account_id,
            "contact_id": contact_id,
            "stage": "prospecting",
            "amount": None,
            "currency": "CAD",
            "probability": 10,
            "expected_close_date": None,
            "close_date": None,
            "close_reason": None,
            "owner_id": lead["owner_id"] or g.user["id"],
            "lead_id": lead_id,
            "notes": lead["interest"] or lead["notes"],
            "created_by": g.user["id"],
        }
    )

    from bridge_crm.crm.leads.queries import convert_lead

    convert_lead(lead_id, account_id, opportunity_id)
    log_activity(
        "lead",
        lead_id,
        "converted",
        f"Lead converted to account #{account_id} and opportunity #{opportunity_id}.",
        g.user["id"],
        {"account_id": account_id, "opportunity_id": opportunity_id},
    )
    log_activity(
        "opportunity",
        opportunity_id,
        "created",
        "Opportunity created from converted lead.",
        g.user["id"],
        {"lead_id": lead_id},
    )
    flash("Lead converted to account and opportunity.", "success")
    return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))
