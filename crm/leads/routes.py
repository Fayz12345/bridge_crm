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
from bridge_crm.crm.emails.queries import create_email, mark_email_failed, mark_email_sent
from bridge_crm.crm.leads.queries import (
    VALID_LEAD_STATUSES,
    create_lead,
    delete_lead,
    get_lead,
    get_leads_by_ids,
    list_leads,
    update_lead,
)
from bridge_crm.crm.opportunities.constants import DEFAULT_OPPORTUNITY_CURRENCY
from bridge_crm.crm.opportunities.queries import create_contact, create_opportunity
from bridge_crm.crm.segments.queries import (
    get_lead_product_interest_ids,
    get_lead_tag_names,
    list_product_interest_options,
    list_tags,
    parse_tag_names,
    replace_account_product_interests,
    replace_account_tags,
    replace_lead_product_interests,
    replace_lead_tags,
)
from bridge_crm.integrations.email_sender import send_email, smtp_configured

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


def _parse_multi_ints(values) -> list[int]:
    parsed: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            continue
        if parsed_value in seen:
            continue
        seen.add(parsed_value)
        parsed.append(parsed_value)
    return parsed


def _safe_return_to(value: str | None) -> str:
    default_url = url_for("leads.list_view")
    candidate = (value or "").strip()
    if candidate.startswith(default_url):
        return candidate
    return default_url


def _current_list_url() -> str:
    full_path = request.full_path.rstrip("?")
    return full_path or request.path


def _format_phone_number(phone_prefix: str | None, phone: str | None) -> str | None:
    raw = f"{phone_prefix or ''}{phone or ''}".strip()
    if not raw:
        return None
    normalized = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if not normalized:
        return None
    if normalized.startswith("+"):
        return normalized
    if phone_prefix and str(phone_prefix).strip().startswith("+"):
        return f"+{normalized}"
    return normalized


def _lead_display_name(lead: dict) -> str:
    return f"{lead.get('first_name', '').strip()} {lead.get('last_name', '').strip()}".strip() or f"Lead #{lead['id']}"


def _lead_bulk_rows(leads: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for lead in leads:
        rows.append(
            {
                "id": int(lead["id"]),
                "display_name": _lead_display_name(lead),
                "subtitle": lead.get("company_name") or lead.get("owner_name") or "",
                "email": lead.get("email"),
                "whatsapp_number": _format_phone_number(
                    lead.get("phone_prefix"), lead.get("phone")
                ),
                "product_interests": lead.get("product_interests") or [],
                "tags": lead.get("tags") or [],
            }
        )
    return rows


def _render_bulk_email_template(
    leads: list[dict],
    *,
    return_to: str,
    subject: str = "",
    body_text: str = "",
    cc_address: str = "",
):
    rows = _lead_bulk_rows(leads)
    available_count = sum(1 for row in rows if row["email"])
    return render_template(
        "communications/bulk_email.html",
        records=rows,
        return_to=return_to,
        subject=subject,
        body_text=body_text,
        cc_address=cc_address,
        available_count=available_count,
        entity_label="Leads",
        compose_endpoint="leads.bulk_email_view",
        send_endpoint="leads.send_bulk_email_view",
        smtp_ready=smtp_configured(),
    )


def _render_bulk_whatsapp_template(
    leads: list[dict],
    *,
    return_to: str,
    body_text: str = "",
):
    rows = _lead_bulk_rows(leads)
    return render_template(
        "communications/bulk_whatsapp.html",
        records=rows,
        return_to=return_to,
        body_text=body_text,
        available_count=sum(1 for row in rows if row["whatsapp_number"]),
        entity_label="Leads",
        compose_endpoint="leads.bulk_whatsapp_view",
    )


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
    owner_values = _parse_multi_ints([request.args.get("owner_id")])
    owner_id = owner_values[0] if owner_values else None
    product_interest_ids = _parse_multi_ints(request.args.getlist("product_interest_ids"))
    tag_ids = _parse_multi_ints(request.args.getlist("tag_ids"))
    leads = list_leads(
        status_filter,
        search_term if search_term else None,
        owner_id=owner_id,
        product_interest_ids=product_interest_ids,
        tag_ids=tag_ids,
    )
    return render_template(
        "leads/list.html",
        leads=leads,
        active_status=status if status_filter else "all",
        search_term=search_term,
        owners=list_assignable_users(),
        owner_id=owner_id,
        product_interest_options=list_product_interest_options(),
        selected_product_interest_ids=product_interest_ids,
        tag_options=list_tags(),
        selected_tag_ids=tag_ids,
        return_to=_current_list_url(),
    )


@leads_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_view():
    form_data = request.form if request.method == "POST" else {"owner_id": g.user["id"]}
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("lead", active_only=True)
    product_interest_options = list_product_interest_options()
    selected_product_interest_ids = (
        _parse_multi_ints(request.form.getlist("product_interest_ids"))
        if request.method == "POST"
        else []
    )
    tag_input_value = request.form.get("tags", "").strip() if request.method == "POST" else ""
    if request.method == "POST":
        if not request.form.get("first_name", "").strip() or not request.form.get(
            "last_name", ""
        ).strip():
            flash("First and last name are required.", "danger")
        else:
            payload = _build_payload(request.form)
            payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
            lead_id = create_lead(payload)
            replace_lead_product_interests(lead_id, selected_product_interest_ids)
            replace_lead_tags(lead_id, parse_tag_names(tag_input_value))
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
        product_interest_options=product_interest_options,
        selected_product_interest_ids=selected_product_interest_ids,
        tag_input_value=tag_input_value,
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
    product_interest_options = list_product_interest_options()
    selected_product_interest_ids = (
        _parse_multi_ints(request.form.getlist("product_interest_ids"))
        if request.method == "POST"
        else get_lead_product_interest_ids(lead_id)
    )
    tag_input_value = (
        request.form.get("tags", "").strip()
        if request.method == "POST"
        else ", ".join(get_lead_tag_names(lead_id))
    )
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
            replace_lead_product_interests(lead_id, selected_product_interest_ids)
            replace_lead_tags(lead_id, parse_tag_names(tag_input_value))
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
        product_interest_options=product_interest_options,
        selected_product_interest_ids=selected_product_interest_ids,
        tag_input_value=tag_input_value,
        page_title="Edit Lead",
        submit_label="Save Changes",
    )


@leads_bp.route("/bulk-email", methods=["POST"])
@login_required
def bulk_email_view():
    lead_ids = _parse_multi_ints(request.form.getlist("selected_ids"))
    return_to = _safe_return_to(request.form.get("return_to"))
    if not lead_ids:
        flash("Select at least one lead for bulk email.", "warning")
        return redirect(return_to)

    leads = get_leads_by_ids(lead_ids)
    if not leads:
        flash("The selected leads could not be found.", "danger")
        return redirect(return_to)
    return _render_bulk_email_template(leads, return_to=return_to)


@leads_bp.route("/bulk-email/send", methods=["POST"])
@login_required
def send_bulk_email_view():
    lead_ids = _parse_multi_ints(request.form.getlist("selected_ids"))
    return_to = _safe_return_to(request.form.get("return_to"))
    subject = request.form.get("subject", "").strip()
    body_text = request.form.get("body_text", "").strip()
    cc_address = request.form.get("cc_address", "").strip() or None
    leads = get_leads_by_ids(lead_ids)
    if not leads:
        flash("The selected leads could not be found.", "danger")
        return redirect(return_to)
    if not subject or not body_text:
        flash("Subject and message are required.", "danger")
        return _render_bulk_email_template(
            leads,
            return_to=return_to,
            subject=subject,
            body_text=body_text,
            cc_address=cc_address or "",
        )

    sent_count = 0
    failed_count = 0
    skipped_names: list[str] = []
    for row in _lead_bulk_rows(leads):
        to_address = (row.get("email") or "").strip()
        if not to_address:
            skipped_names.append(row["display_name"])
            continue
        email_id = create_email(
            {
                "direction": "outbound",
                "related_type": "lead",
                "related_id": row["id"],
                "from_address": g.user["email"],
                "to_address": to_address,
                "cc_address": cc_address,
                "subject": subject,
                "body_html": None,
                "body_text": body_text,
                "status": "draft",
                "sent_by": g.user["id"],
                "attachments_json": [],
            }
        )
        try:
            send_email(to_address, subject, body_text, cc_address, attachments=None)
            mark_email_sent(email_id)
            log_activity(
                "lead",
                row["id"],
                "email_sent",
                f"Bulk email sent to {to_address}.",
                g.user["id"],
                {"email_id": email_id, "bulk": True},
            )
            sent_count += 1
        except Exception as exc:
            mark_email_failed(email_id, str(exc))
            failed_count += 1

    if sent_count:
        flash(f"Sent {sent_count} bulk email(s).", "success")
    if skipped_names:
        flash(f"Skipped {len(skipped_names)} lead(s) without an email address.", "warning")
    if failed_count:
        flash(f"{failed_count} email(s) failed to send.", "warning")
    return redirect(return_to)


@leads_bp.route("/bulk-whatsapp", methods=["POST"])
@login_required
def bulk_whatsapp_view():
    lead_ids = _parse_multi_ints(request.form.getlist("selected_ids"))
    return_to = _safe_return_to(request.form.get("return_to"))
    if not lead_ids:
        flash("Select at least one lead for bulk WhatsApp.", "warning")
        return redirect(return_to)

    leads = get_leads_by_ids(lead_ids)
    if not leads:
        flash("The selected leads could not be found.", "danger")
        return redirect(return_to)

    body_text = request.form.get("body_text", "").strip()
    return _render_bulk_whatsapp_template(
        leads,
        return_to=return_to,
        body_text=body_text,
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
    replace_account_product_interests(
        account_id,
        [item["id"] for item in lead.get("product_interests") or []],
    )
    replace_account_tags(
        account_id,
        [tag["tag_name"] for tag in lead.get("tags") or []],
    )

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
            "currency": DEFAULT_OPPORTUNITY_CURRENCY,
            "conversion_rate_to_cad": "1",
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


@leads_bp.route("/<int:lead_id>/delete", methods=["POST"])
@login_required
def delete_view(lead_id: int):
    if g.user["role"] != "admin":
        flash("Only admins can delete leads.", "danger")
        return redirect(url_for("leads.detail_view", lead_id=lead_id))

    lead = get_lead(lead_id)
    if not lead:
        flash("Lead not found.", "danger")
        return redirect(url_for("leads.list_view"))

    name = f"{lead['first_name']} {lead['last_name']}"
    delete_lead(lead_id)
    flash(f'Lead "{name}" deleted.', "success")
    return redirect(url_for("leads.list_view"))
