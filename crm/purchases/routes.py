from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from bridge_crm.crm.activities.queries import list_activities, log_activity
from bridge_crm.crm.auth.queries import list_assignable_users
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.custom_fields.queries import (
    extract_custom_field_values,
    get_custom_field_values,
    list_custom_fields,
)
from bridge_crm.crm.emails.queries import create_email, list_emails, mark_email_failed, mark_email_sent
from bridge_crm.crm.products.queries import list_product_stock_groups
from bridge_crm.crm.purchases.constants import (
    DEFAULT_PURCHASE_CURRENCY,
    PURCHASE_CURRENCY_CODES,
    PURCHASE_CURRENCY_OPTIONS,
    PURCHASE_STAGE_KEYS,
)
from bridge_crm.crm.purchases.queries import (
    create_purchase,
    create_purchase_line,
    delete_purchase,
    delete_purchase_line,
    get_purchase,
    get_purchase_line,
    get_purchase_line_items,
    get_purchase_stage,
    get_purchase_stages,
    list_accounts_for_select,
    list_contacts_for_account_select,
    list_purchases,
    purchases_by_stage,
    update_purchase,
    update_purchase_line,
    update_purchase_stage,
    upsert_purchase_stage,
)
from bridge_crm.integrations.email_sender import send_email, smtp_configured

purchases_bp = Blueprint(
    "purchases",
    __name__,
    url_prefix="/purchases",
    template_folder="../../templates",
)


def _int_or_none(value: str | None):
    if not value:
        return None
    return int(value)


def _serialize_email(email: dict) -> dict:
    item = dict(email)
    item["attachments"] = item.get("attachments_json") or []
    return item


def _build_payload(form_data, user_id: int, existing: dict | None = None) -> dict:
    stage = form_data.get("stage", (existing or {}).get("stage", "prospecting")).strip()
    if stage not in PURCHASE_STAGE_KEYS:
        raise ValueError("Please select a valid purchase stage.")

    currency = (
        form_data.get(
            "currency",
            (existing or {}).get("currency", DEFAULT_PURCHASE_CURRENCY),
        )
        .strip()
        .upper()
        or DEFAULT_PURCHASE_CURRENCY
    )
    if currency not in PURCHASE_CURRENCY_CODES:
        raise ValueError("Please select a supported currency.")

    raw_conversion_rate = form_data.get(
        "conversion_rate_to_cad",
        str((existing or {}).get("conversion_rate_to_cad", "1")),
    ).strip()
    try:
        conversion_rate_to_cad = Decimal(raw_conversion_rate or "1")
    except InvalidOperation as exc:
        raise ValueError("Conversion rate to CAD must be a valid number.") from exc
    if conversion_rate_to_cad <= 0:
        raise ValueError("Conversion rate to CAD must be greater than 0.")

    return {
        "title": form_data.get("title", "").strip(),
        "account_id": _int_or_none(form_data.get("account_id")),
        "contact_id": _int_or_none(form_data.get("contact_id")),
        "stage": stage,
        "estimated_total": form_data.get("estimated_total", "").strip() or None,
        "currency": currency,
        "conversion_rate_to_cad": str(conversion_rate_to_cad),
        "expected_delivery_date": form_data.get("expected_delivery_date", "").strip() or None,
        "close_date": form_data.get("close_date", "").strip() or None,
        "close_reason": form_data.get("close_reason", "").strip() or None,
        "supplier_quote_number": form_data.get("supplier_quote_number", "").strip() or None,
        "owner_id": _int_or_none(form_data.get("owner_id")),
        "notes": form_data.get("notes", "").strip() or None,
        "created_by": (existing or {}).get("created_by", user_id),
    }


@purchases_bp.route("/")
@login_required
def list_view():
    stage = request.args.get("stage", "").strip() or None
    purchases = list_purchases(stage)
    stages = get_purchase_stages()
    return render_template(
        "purchases/list.html",
        purchases=purchases,
        stages=stages,
        active_stage=stage,
    )


@purchases_bp.route("/pipeline")
@login_required
def pipeline_view():
    stages = get_purchase_stages()
    purchases = purchases_by_stage()
    grouped = {stage["stage_key"]: [] for stage in stages}
    for purchase in purchases:
        grouped.setdefault(purchase["stage"], []).append(purchase)
    return render_template("purchases/pipeline.html", stages=stages, grouped=grouped)


@purchases_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_view():
    form_data = request.form if request.method == "POST" else {
        "owner_id": g.user["id"],
        "currency": DEFAULT_PURCHASE_CURRENCY,
        "conversion_rate_to_cad": "1",
    }
    accounts = list_accounts_for_select()
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("purchase", active_only=True)
    selected_account_id = _int_or_none(request.values.get("account_id"))
    contacts = list_contacts_for_account_select(selected_account_id)
    stages = get_purchase_stages()

    if request.method == "POST":
        try:
            payload = _build_payload(request.form, g.user["id"])
        except ValueError as exc:
            flash(str(exc), "danger")
            payload = None

        if payload is not None:
            payload["custom_fields"] = extract_custom_field_values(
                request.form, custom_field_definitions
            )
            if not payload["title"] or not payload["account_id"]:
                flash("Title and account are required.", "danger")
            else:
                purchase_id = create_purchase(payload)
                log_activity(
                    "purchase",
                    purchase_id,
                    "created",
                    "Purchase created.",
                    g.user["id"],
                )
                flash("Purchase created.", "success")
                return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    return render_template(
        "purchases/form.html",
        purchase=None,
        form_data=form_data,
        accounts=accounts,
        owners=owners,
        contacts=contacts,
        stages=stages,
        currency_options=PURCHASE_CURRENCY_OPTIONS,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions)
        if request.method == "POST"
        else {},
        page_title="New Purchase",
        submit_label="Create Purchase",
    )


@purchases_bp.route("/<int:purchase_id>")
@login_required
def detail_view(purchase_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    activities = list_activities("purchase", purchase_id)
    line_items = get_purchase_line_items(purchase_id)
    stock_groups = list_product_stock_groups()
    emails = [_serialize_email(email) for email in list_emails("purchase", purchase_id)]
    custom_field_rows = get_custom_field_values(
        purchase, list_custom_fields("purchase", active_only=True)
    )
    return render_template(
        "purchases/detail.html",
        purchase=purchase,
        activities=activities,
        line_items=line_items,
        stock_groups=stock_groups,
        emails=emails,
        custom_field_rows=custom_field_rows,
        smtp_ready=smtp_configured(),
    )


@purchases_bp.route("/<int:purchase_id>/edit", methods=["GET", "POST"])
@login_required
def edit_view(purchase_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    form_data = request.form if request.method == "POST" else purchase
    selected_account_id = _int_or_none(
        request.values.get("account_id") or str(purchase["account_id"])
    )
    accounts = list_accounts_for_select()
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("purchase", active_only=True)
    contacts = list_contacts_for_account_select(selected_account_id)
    stages = get_purchase_stages()

    if request.method == "POST":
        try:
            payload = _build_payload(
                request.form,
                purchase["owner_id"] or g.user["id"],
                existing=purchase,
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            payload = None

        if payload is not None:
            payload["custom_fields"] = extract_custom_field_values(
                request.form, custom_field_definitions
            )
            if not payload["title"] or not payload["account_id"]:
                flash("Title and account are required.", "danger")
            else:
                previous_stage = purchase["stage"]
                update_purchase(purchase_id, payload)
                if previous_stage != payload["stage"]:
                    log_activity(
                        "purchase",
                        purchase_id,
                        "stage_changed",
                        f"Purchase stage changed from {previous_stage} to {payload['stage']}.",
                        g.user["id"],
                        {"from": previous_stage, "to": payload["stage"]},
                    )
                flash("Purchase updated.", "success")
                return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    return render_template(
        "purchases/form.html",
        purchase=purchase,
        form_data=form_data,
        accounts=accounts,
        owners=owners,
        contacts=contacts,
        stages=stages,
        currency_options=PURCHASE_CURRENCY_OPTIONS,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions)
        if request.method == "POST"
        else (purchase.get("custom_fields") or {}),
        page_title="Edit Purchase",
        submit_label="Save Changes",
    )


def _wants_json() -> bool:
    requested = (request.headers.get("X-Requested-With") or "").lower()
    if requested == "xmlhttprequest":
        return True
    return request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json"


@purchases_bp.route("/<int:purchase_id>/stage", methods=["POST"])
@login_required
def update_stage_view(purchase_id: int):
    purchase = get_purchase(purchase_id)
    wants_json = _wants_json()
    if not purchase:
        if wants_json:
            return jsonify({"ok": False, "error": "Purchase not found."}), 404
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    target_stage = request.form.get("stage", "").strip()
    stage = get_purchase_stage(target_stage)
    if not stage:
        if wants_json:
            return jsonify({"ok": False, "error": "Invalid stage."}), 400
        flash("Invalid stage.", "danger")
        return redirect(url_for("purchases.pipeline_view"))

    if purchase["stage"] != stage["stage_key"]:
        update_purchase_stage(purchase_id, stage["stage_key"])
        log_activity(
            "purchase",
            purchase_id,
            "stage_changed",
            f"Purchase stage changed from {purchase['stage']} to {stage['stage_key']}.",
            g.user["id"],
            {"from": purchase["stage"], "to": stage["stage_key"]},
        )

    if wants_json:
        return jsonify({"ok": True, "stage": stage["stage_key"]})
    flash("Purchase stage updated.", "success")
    return redirect(url_for("purchases.pipeline_view"))


@purchases_bp.route("/<int:purchase_id>/notes", methods=["POST"])
@login_required
def add_note_view(purchase_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    note = request.form.get("note", "").strip()
    if note:
        log_activity("purchase", purchase_id, "note", note, g.user["id"])
        flash("Note added.", "success")
    else:
        flash("Note cannot be empty.", "danger")
    return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))


@purchases_bp.route("/<int:purchase_id>/lines", methods=["POST"])
@login_required
def add_line_view(purchase_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    try:
        line_id = create_purchase_line(
            {
                "purchase_id": purchase_id,
                "brand": request.form.get("brand", "").strip(),
                "model": request.form.get("model", "").strip(),
                "grade": request.form.get("grade", "").strip() or None,
                "category": request.form.get("category", "").strip() or None,
                "storage": request.form.get("storage", "").strip() or None,
                "quantity": request.form.get("quantity", "").strip() or "0",
                "unit_cost": request.form.get("unit_cost", "").strip(),
                "notes": request.form.get("notes", "").strip() or None,
            }
        )
    except Exception as exc:
        flash(f"Could not add quote line: {exc}", "danger")
        return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    log_activity(
        "purchase",
        purchase_id,
        "product_added",
        f"Quote line added for {request.form.get('brand', '').strip()} {request.form.get('model', '').strip()}.",
        g.user["id"],
        {"line_id": line_id},
    )
    flash("Quote line added.", "success")
    return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))


@purchases_bp.route("/<int:purchase_id>/lines/<int:line_id>/edit", methods=["POST"])
@login_required
def edit_line_view(purchase_id: int, line_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    line = get_purchase_line(purchase_id, line_id)
    if not line:
        flash("Quote line not found.", "danger")
        return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    try:
        update_purchase_line(
            purchase_id,
            line_id,
            {
                "brand": request.form.get("brand", "").strip(),
                "model": request.form.get("model", "").strip(),
                "grade": request.form.get("grade", "").strip() or None,
                "category": request.form.get("category", "").strip() or None,
                "storage": request.form.get("storage", "").strip() or None,
                "quantity": request.form.get("quantity", "").strip() or "0",
                "unit_cost": request.form.get("unit_cost", "").strip(),
                "notes": request.form.get("notes", "").strip() or None,
            },
        )
    except Exception as exc:
        flash(f"Could not update quote line: {exc}", "danger")
        return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    flash("Quote line updated.", "success")
    return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))


@purchases_bp.route("/<int:purchase_id>/lines/<int:line_id>/delete", methods=["POST"])
@login_required
def delete_line_view(purchase_id: int, line_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    line = get_purchase_line(purchase_id, line_id)
    if not line:
        flash("Quote line not found.", "danger")
        return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    delete_purchase_line(purchase_id, line_id)
    log_activity(
        "purchase",
        purchase_id,
        "product_added",
        f"Quote line removed for {line['brand']} {line['model']}.",
        g.user["id"],
        {"line_id": line_id},
    )
    flash("Quote line removed.", "success")
    return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))


@purchases_bp.route("/<int:purchase_id>/delete", methods=["POST"])
@login_required
def delete_view(purchase_id: int):
    if g.user["role"] != "admin":
        flash("Only admins can delete purchases.", "danger")
        return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    title = purchase["title"]
    delete_purchase(purchase_id)
    flash(f'Purchase "{title}" deleted.', "success")
    return redirect(url_for("purchases.list_view"))


@purchases_bp.route("/<int:purchase_id>/emails", methods=["POST"])
@login_required
def send_email_view(purchase_id: int):
    purchase = get_purchase(purchase_id)
    if not purchase:
        flash("Purchase not found.", "danger")
        return redirect(url_for("purchases.list_view"))

    to_address = request.form.get("to_address", "").strip()
    subject = request.form.get("subject", "").strip()
    body_text = request.form.get("body_text", "").strip()
    cc_address = request.form.get("cc_address", "").strip() or None
    if not to_address or not subject or not body_text:
        flash("To, subject, and body are required.", "danger")
        return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))

    email_id = create_email(
        {
            "direction": "outbound",
            "related_type": "purchase",
            "related_id": purchase_id,
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
            "purchase",
            purchase_id,
            "email_sent",
            f"Outbound email sent to {to_address}.",
            g.user["id"],
            {"email_id": email_id},
        )
        flash("Email sent.", "success")
    except Exception as exc:
        mark_email_failed(email_id, str(exc))
        flash(f"Email could not be sent: {exc}", "warning")

    return redirect(url_for("purchases.detail_view", purchase_id=purchase_id))


@purchases_bp.route("/stages", methods=["GET", "POST"])
@login_required
def stages_view():
    if request.method == "POST":
        stage_key = request.form.get("stage_key", "").strip()
        display_name = request.form.get("display_name", "").strip()
        if stage_key and display_name:
            if stage_key not in PURCHASE_STAGE_KEYS:
                flash("Only the standard purchase stages can be configured here.", "danger")
                return redirect(url_for("purchases.stages_view"))
            upsert_purchase_stage(
                {
                    "stage_key": stage_key,
                    "display_name": display_name,
                    "display_order": int(request.form.get("display_order", "0") or "0"),
                    "default_probability": int(
                        request.form.get("default_probability", "0") or "0"
                    ),
                    "is_active": request.form.get("is_active") == "on",
                }
            )
            flash("Purchase stage saved.", "success")
        else:
            flash("Stage key and display name are required.", "danger")
        return redirect(url_for("purchases.stages_view"))

    return render_template("purchases/stages.html", stages=get_purchase_stages())
