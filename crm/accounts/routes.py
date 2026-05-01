from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from bridge_crm.crm.accounts.queries import (
    create_contact_for_account,
    create_account,
    delete_account,
    get_account,
    get_account_by_erp_client_id,
    get_accounts_by_ids,
    get_contact_for_account,
    list_accounts,
    list_contacts_for_account,
    update_contact_for_account,
    update_account,
)
from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.auth.queries import list_assignable_users
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.custom_fields.queries import (
    extract_custom_field_values,
    get_custom_field_values,
    list_custom_fields,
)
from bridge_crm.crm.emails.queries import create_email, mark_email_failed, mark_email_sent
from bridge_crm.crm.segments.queries import (
    get_account_product_interest_ids,
    get_account_tag_names,
    list_product_interest_options,
    list_tags,
    parse_tag_names,
    replace_account_product_interests,
    replace_account_tags,
)
from bridge_crm.integrations.email_sender import send_email, smtp_configured

accounts_bp = Blueprint(
    "accounts",
    __name__,
    url_prefix="/accounts",
    template_folder="../../templates",
)

ACCOUNT_FIELDS = [
    "company_name",
    "contact_name",
    "email",
    "phone",
    "phone_prefix",
    "website",
    "address_line_1",
    "address_line_2",
    "city",
    "state_province",
    "postal_code",
    "country",
    "industry",
    "erp_client_id",
    "notes",
]

CONTACT_FIELDS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "phone_prefix",
    "job_title",
    "whatsapp_number",
]


def _build_payload(form_data, user_id: int) -> dict:
    payload = {field: form_data.get(field, "").strip() or None for field in ACCOUNT_FIELDS}
    payload["company_name"] = form_data.get("company_name", "").strip()
    payload["owner_id"] = user_id
    payload["created_by"] = user_id
    return payload


def _invalid_phone_prefix(form_data) -> bool:
    phone_prefix = form_data.get("phone_prefix", "").strip()
    phone = form_data.get("phone", "").strip()
    if not phone_prefix:
        return False
    if phone and phone_prefix == phone:
        return False
    return len(phone_prefix) > 8


def _build_contact_payload(form_data, account_id: int) -> dict:
    payload = {field: form_data.get(field, "").strip() or None for field in CONTACT_FIELDS}
    payload["account_id"] = account_id
    payload["first_name"] = form_data.get("first_name", "").strip()
    payload["last_name"] = form_data.get("last_name", "").strip()
    payload["is_primary"] = form_data.get("is_primary") == "on"
    return payload


def _invalid_contact_phone_prefix(form_data) -> bool:
    phone_prefix = form_data.get("phone_prefix", "").strip()
    phone = form_data.get("phone", "").strip()
    if not phone_prefix:
        return False
    if phone and phone_prefix == phone:
        return False
    return len(phone_prefix) > 8


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
    default_url = url_for("accounts.list_view")
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


def _account_display_name(account: dict) -> str:
    return account.get("company_name") or f"Account #{account['id']}"


def _account_bulk_rows(accounts: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for account in accounts:
        rows.append(
            {
                "id": int(account["id"]),
                "display_name": _account_display_name(account),
                "subtitle": account.get("contact_name") or account.get("owner_name") or "",
                "email": account.get("email"),
                "whatsapp_number": account.get("whatsapp_number")
                or _format_phone_number(account.get("phone_prefix"), account.get("phone")),
                "product_interests": account.get("product_interests") or [],
                "tags": account.get("tags") or [],
            }
        )
    return rows


def _render_bulk_email_template(
    accounts: list[dict],
    *,
    return_to: str,
    subject: str = "",
    body_text: str = "",
    cc_address: str = "",
):
    rows = _account_bulk_rows(accounts)
    available_count = sum(1 for row in rows if row["email"])
    return render_template(
        "communications/bulk_email.html",
        records=rows,
        return_to=return_to,
        subject=subject,
        body_text=body_text,
        cc_address=cc_address,
        available_count=available_count,
        entity_label="Accounts",
        compose_endpoint="accounts.bulk_email_view",
        send_endpoint="accounts.send_bulk_email_view",
        smtp_ready=smtp_configured(),
    )


def _render_bulk_whatsapp_template(
    accounts: list[dict],
    *,
    return_to: str,
    body_text: str = "",
):
    rows = _account_bulk_rows(accounts)
    return render_template(
        "communications/bulk_whatsapp.html",
        records=rows,
        return_to=return_to,
        body_text=body_text,
        available_count=sum(1 for row in rows if row["whatsapp_number"]),
        entity_label="Accounts",
        compose_endpoint="accounts.bulk_whatsapp_view",
    )


@accounts_bp.route("/")
@login_required
def list_view():
    search_term = request.args.get("q", "").strip()
    owner_values = _parse_multi_ints([request.args.get("owner_id")])
    owner_id = owner_values[0] if owner_values else None
    product_interest_ids = _parse_multi_ints(request.args.getlist("product_interest_ids"))
    tag_ids = _parse_multi_ints(request.args.getlist("tag_ids"))
    accounts = list_accounts(
        search_term if search_term else None,
        owner_id=owner_id,
        product_interest_ids=product_interest_ids,
        tag_ids=tag_ids,
    )
    return render_template(
        "accounts/list.html",
        accounts=accounts,
        search_term=search_term,
        owners=list_assignable_users(),
        owner_id=owner_id,
        product_interest_options=list_product_interest_options(),
        selected_product_interest_ids=product_interest_ids,
        tag_options=list_tags(),
        selected_tag_ids=tag_ids,
        return_to=_current_list_url(),
    )


@accounts_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_view():
    form_data = request.form if request.method == "POST" else {}
    custom_field_definitions = list_custom_fields("account", active_only=True)
    product_interest_options = list_product_interest_options()
    selected_product_interest_ids = (
        _parse_multi_ints(request.form.getlist("product_interest_ids"))
        if request.method == "POST"
        else []
    )
    tag_input_value = request.form.get("tags", "").strip() if request.method == "POST" else ""
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        erp_client_id = request.form.get("erp_client_id", "").strip()

        if not company_name:
            flash("Company name is required.", "danger")
        elif _invalid_phone_prefix(request.form):
            flash("Phone prefix must be a short country/area prefix such as +1.", "danger")
        elif erp_client_id and get_account_by_erp_client_id(erp_client_id):
            flash("That ERP client ID is already linked to another account.", "danger")
        else:
            payload = _build_payload(request.form, g.user["id"])
            payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
            account_id = create_account(payload)
            replace_account_product_interests(account_id, selected_product_interest_ids)
            replace_account_tags(account_id, parse_tag_names(tag_input_value))
            flash("Account created.", "success")
            return redirect(url_for("accounts.detail_view", account_id=account_id))

    return render_template(
        "accounts/form.html",
        account=None,
        form_data=form_data,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if form_data else {},
        product_interest_options=product_interest_options,
        selected_product_interest_ids=selected_product_interest_ids,
        tag_input_value=tag_input_value,
        page_title="New Account",
        submit_label="Create Account",
    )


@accounts_bp.route("/<int:account_id>")
@login_required
def detail_view(account_id: int):
    account = get_account(account_id)
    if not account:
        flash("Account not found.", "danger")
        return redirect(url_for("accounts.list_view"))

    contacts = list_contacts_for_account(account_id)
    custom_field_rows = get_custom_field_values(
        account, list_custom_fields("account", active_only=True)
    )
    return render_template(
        "accounts/detail.html",
        account=account,
        contacts=contacts,
        custom_field_rows=custom_field_rows,
    )


@accounts_bp.route("/<int:account_id>/contacts/new", methods=["GET", "POST"])
@login_required
def create_contact_view(account_id: int):
    account = get_account(account_id)
    if not account:
        flash("Account not found.", "danger")
        return redirect(url_for("accounts.list_view"))

    form_data = request.form if request.method == "POST" else {}
    if request.method == "POST":
        if not request.form.get("first_name", "").strip() or not request.form.get("last_name", "").strip():
            flash("First name and last name are required.", "danger")
        elif _invalid_contact_phone_prefix(request.form):
            flash("Phone prefix must be a short country/area prefix such as +1.", "danger")
        else:
            contact_id = create_contact_for_account(_build_contact_payload(request.form, account_id))
            flash("Contact added to account.", "success")
            return redirect(url_for("accounts.detail_view", account_id=account_id, contact_id=contact_id))

    return render_template(
        "accounts/contact_form.html",
        account=account,
        contact=None,
        form_data=form_data,
        page_title="Add Contact",
        submit_label="Add Contact",
    )


@accounts_bp.route("/<int:account_id>/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contact_view(account_id: int, contact_id: int):
    account = get_account(account_id)
    if not account:
        flash("Account not found.", "danger")
        return redirect(url_for("accounts.list_view"))

    contact = get_contact_for_account(account_id, contact_id)
    if not contact:
        flash("Contact not found.", "danger")
        return redirect(url_for("accounts.detail_view", account_id=account_id))

    form_data = request.form if request.method == "POST" else contact
    if request.method == "POST":
        if not request.form.get("first_name", "").strip() or not request.form.get("last_name", "").strip():
            flash("First name and last name are required.", "danger")
        elif _invalid_contact_phone_prefix(request.form):
            flash("Phone prefix must be a short country/area prefix such as +1.", "danger")
        else:
            update_contact_for_account(account_id, contact_id, _build_contact_payload(request.form, account_id))
            flash("Contact updated.", "success")
            return redirect(url_for("accounts.detail_view", account_id=account_id, contact_id=contact_id))

    return render_template(
        "accounts/contact_form.html",
        account=account,
        contact=contact,
        form_data=form_data,
        page_title="Edit Contact",
        submit_label="Save Contact",
    )


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def edit_view(account_id: int):
    account = get_account(account_id)
    if not account:
        flash("Account not found.", "danger")
        return redirect(url_for("accounts.list_view"))

    form_data = request.form if request.method == "POST" else account
    custom_field_definitions = list_custom_fields("account", active_only=True)
    product_interest_options = list_product_interest_options()
    selected_product_interest_ids = (
        _parse_multi_ints(request.form.getlist("product_interest_ids"))
        if request.method == "POST"
        else get_account_product_interest_ids(account_id)
    )
    tag_input_value = (
        request.form.get("tags", "").strip()
        if request.method == "POST"
        else ", ".join(get_account_tag_names(account_id))
    )
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        erp_client_id = request.form.get("erp_client_id", "").strip()

        if not company_name:
            flash("Company name is required.", "danger")
        elif _invalid_phone_prefix(request.form):
            flash("Phone prefix must be a short country/area prefix such as +1.", "danger")
        elif erp_client_id and get_account_by_erp_client_id(erp_client_id, exclude_account_id=account_id):
            flash("That ERP client ID is already linked to another account.", "danger")
        else:
            payload = _build_payload(request.form, account["owner_id"] or g.user["id"])
            payload["created_by"] = account["created_by"]
            payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
            update_account(account_id, payload)
            replace_account_product_interests(account_id, selected_product_interest_ids)
            replace_account_tags(account_id, parse_tag_names(tag_input_value))
            flash("Account updated.", "success")
            return redirect(url_for("accounts.detail_view", account_id=account_id))

    return render_template(
        "accounts/form.html",
        account=account,
        form_data=form_data,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if request.method == "POST" else (account.get("custom_fields") or {}),
        product_interest_options=product_interest_options,
        selected_product_interest_ids=selected_product_interest_ids,
        tag_input_value=tag_input_value,
        page_title="Edit Account",
        submit_label="Save Changes",
    )


@accounts_bp.route("/bulk-email", methods=["POST"])
@login_required
def bulk_email_view():
    account_ids = _parse_multi_ints(request.form.getlist("selected_ids"))
    return_to = _safe_return_to(request.form.get("return_to"))
    if not account_ids:
        flash("Select at least one account for bulk email.", "warning")
        return redirect(return_to)

    accounts = get_accounts_by_ids(account_ids)
    if not accounts:
        flash("The selected accounts could not be found.", "danger")
        return redirect(return_to)
    return _render_bulk_email_template(accounts, return_to=return_to)


@accounts_bp.route("/bulk-email/send", methods=["POST"])
@login_required
def send_bulk_email_view():
    account_ids = _parse_multi_ints(request.form.getlist("selected_ids"))
    return_to = _safe_return_to(request.form.get("return_to"))
    subject = request.form.get("subject", "").strip()
    body_text = request.form.get("body_text", "").strip()
    cc_address = request.form.get("cc_address", "").strip() or None
    accounts = get_accounts_by_ids(account_ids)
    if not accounts:
        flash("The selected accounts could not be found.", "danger")
        return redirect(return_to)
    if not subject or not body_text:
        flash("Subject and message are required.", "danger")
        return _render_bulk_email_template(
            accounts,
            return_to=return_to,
            subject=subject,
            body_text=body_text,
            cc_address=cc_address or "",
        )

    sent_count = 0
    failed_count = 0
    skipped_names: list[str] = []
    for row in _account_bulk_rows(accounts):
        to_address = (row.get("email") or "").strip()
        if not to_address:
            skipped_names.append(row["display_name"])
            continue
        email_id = create_email(
            {
                "direction": "outbound",
                "related_type": "account",
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
                "account",
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
        flash(
            f"Skipped {len(skipped_names)} account(s) without an email address.",
            "warning",
        )
    if failed_count:
        flash(f"{failed_count} email(s) failed to send.", "warning")
    return redirect(return_to)


@accounts_bp.route("/bulk-whatsapp", methods=["POST"])
@login_required
def bulk_whatsapp_view():
    account_ids = _parse_multi_ints(request.form.getlist("selected_ids"))
    return_to = _safe_return_to(request.form.get("return_to"))
    if not account_ids:
        flash("Select at least one account for bulk WhatsApp.", "warning")
        return redirect(return_to)

    accounts = get_accounts_by_ids(account_ids)
    if not accounts:
        flash("The selected accounts could not be found.", "danger")
        return redirect(return_to)

    body_text = request.form.get("body_text", "").strip()
    return _render_bulk_whatsapp_template(
        accounts,
        return_to=return_to,
        body_text=body_text,
    )


@accounts_bp.route("/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_view(account_id: int):
    if g.user["role"] != "admin":
        flash("Only admins can delete accounts.", "danger")
        return redirect(url_for("accounts.detail_view", account_id=account_id))

    account = get_account(account_id)
    if not account:
        flash("Account not found.", "danger")
        return redirect(url_for("accounts.list_view"))

    name = account["company_name"]
    delete_account(account_id)
    flash(f'Account "{name}" and all associated data deleted.', "success")
    return redirect(url_for("accounts.list_view"))
