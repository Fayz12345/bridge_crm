from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from bridge_crm.crm.accounts.queries import (
    create_contact_for_account,
    create_account,
    get_account,
    get_account_by_erp_client_id,
    get_contact_for_account,
    list_accounts,
    list_contacts_for_account,
    update_contact_for_account,
    update_account,
)
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.custom_fields.queries import (
    extract_custom_field_values,
    get_custom_field_values,
    list_custom_fields,
)

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


@accounts_bp.route("/")
@login_required
def list_view():
    search_term = request.args.get("q", "").strip()
    accounts = list_accounts(search_term if search_term else None)
    return render_template("accounts/list.html", accounts=accounts, search_term=search_term)


@accounts_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_view():
    form_data = request.form if request.method == "POST" else {}
    custom_field_definitions = list_custom_fields("account", active_only=True)
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
            flash("Account created.", "success")
            return redirect(url_for("accounts.detail_view", account_id=account_id))

    return render_template(
        "accounts/form.html",
        account=None,
        form_data=form_data,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if form_data else {},
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
            flash("Account updated.", "success")
            return redirect(url_for("accounts.detail_view", account_id=account_id))

    return render_template(
        "accounts/form.html",
        account=account,
        form_data=form_data,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if request.method == "POST" else (account.get("custom_fields") or {}),
        page_title="Edit Account",
        submit_label="Save Changes",
    )
