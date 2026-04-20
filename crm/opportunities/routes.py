import re
from pathlib import Path

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

from bridge_crm.crm.activities.queries import list_activities, log_activity
from bridge_crm.crm.auth.queries import (
    get_users_by_emails,
    get_users_by_ids,
    list_assignable_users,
)
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.custom_fields.queries import (
    extract_custom_field_values,
    get_custom_field_values,
    list_custom_fields,
)
from bridge_crm.crm.documents.queries import (
    get_document_for_opportunity,
    list_documents_for_opportunity,
)
from bridge_crm.crm.emails.queries import create_email, list_emails, mark_email_failed, mark_email_sent
from bridge_crm.crm.notifications.queries import create_notification
from bridge_crm.crm.opportunities.queries import (
    create_opportunity_line,
    create_opportunity,
    get_opportunity,
    get_opportunity_line_items,
    get_pipeline_stage,
    get_pipeline_stages,
    list_accounts_for_select,
    list_contacts_for_account_select,
    list_opportunities,
    opportunities_by_stage,
    update_opportunity_stage,
    update_opportunity,
    upsert_pipeline_stage,
)
from bridge_crm.crm.products.queries import list_product_stock_groups
from bridge_crm.integrations.email_sender import send_email, smtp_configured
from bridge_crm.integrations.pdf_generator import generate_invoice_pdf, generate_quote_pdf

opportunities_bp = Blueprint(
    "opportunities",
    __name__,
    url_prefix="/opportunities",
    template_folder="../../templates",
)


def _int_or_none(value: str | None):
    if not value:
        return None
    return int(value)


def _int_list(values: list[str]) -> list[int]:
    items = []
    for value in values:
        if not value:
            continue
        try:
            items.append(int(value))
        except ValueError:
            continue
    return items


def _detail_url(opportunity_id: int, attachment_id: int | None = None) -> str:
    if attachment_id:
        return url_for(
            "opportunities.detail_view",
            opportunity_id=opportunity_id,
            attachment=attachment_id,
        )
    return url_for("opportunities.detail_view", opportunity_id=opportunity_id)


def _format_file_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 B"
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{int(size_bytes)} B"


def _serialize_document(document: dict | None, opportunity_id: int) -> dict | None:
    if not document:
        return None
    item = dict(document)
    item["size_display"] = _format_file_size(item.get("file_size_bytes"))
    item["download_url"] = url_for(
        "opportunities.download_document_view",
        opportunity_id=opportunity_id,
        doc_id=item["id"],
    )
    return item


def _serialize_email(email: dict, opportunity_id: int) -> dict:
    item = dict(email)
    attachments = []
    for attachment in item.get("attachments_json") or []:
        payload = dict(attachment)
        payload["size_display"] = _format_file_size(payload.get("size_bytes"))
        document_id = payload.get("document_id")
        payload["download_url"] = (
            url_for(
                "opportunities.download_document_view",
                opportunity_id=opportunity_id,
                doc_id=document_id,
            )
            if document_id
            else None
        )
        attachments.append(payload)
    item["attachments"] = attachments
    return item


def _extract_mentions(note: str, selected_user_ids: list[int]) -> list[dict]:
    mention_map: dict[int, dict] = {}

    for user in get_users_by_ids(selected_user_ids):
        mention_map[int(user["id"])] = {
            "id": int(user["id"]),
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user["role"],
        }

    email_mentions = re.findall(r"@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", note or "")
    for user in get_users_by_emails(email_mentions):
        mention_map[int(user["id"])] = {
            "id": int(user["id"]),
            "full_name": user["full_name"],
            "email": user["email"],
            "role": user["role"],
        }

    return list(mention_map.values())


def _create_mention_notifications(opportunity: dict, mentions: list[dict], note: str) -> None:
    link_url = url_for("opportunities.detail_view", opportunity_id=opportunity["id"])
    for mention in mentions:
        if mention["id"] == g.user["id"]:
            continue

        create_notification(
            {
                "user_id": mention["id"],
                "notification_type": "mention",
                "title": f"You were tagged on opportunity: {opportunity['title']}",
                "message": f"{g.user['full_name']} mentioned you in a note on {opportunity['title']}.",
                "link_url": link_url,
                "related_type": "opportunity",
                "related_id": opportunity["id"],
                "metadata": {"note": note, "mentioned_by": g.user["id"]},
            }
        )

        if smtp_configured() and mention.get("email"):
            try:
                send_email(
                    to_address=mention["email"],
                    subject=f"Bridge CRM mention: {opportunity['title']}",
                    body_text=(
                        f"{g.user['full_name']} mentioned you on opportunity '{opportunity['title']}'.\n\n"
                        f"Note:\n{note}\n\n"
                        f"Open the CRM record: {link_url}"
                    ),
                )
            except Exception:
                pass


def _build_payload(form_data, user_id: int, existing: dict | None = None) -> dict:
    stage = form_data.get("stage", (existing or {}).get("stage", "prospecting")).strip()
    probability = form_data.get(
        "probability", str((existing or {}).get("probability", 10))
    ).strip()
    return {
        "title": form_data.get("title", "").strip(),
        "account_id": _int_or_none(form_data.get("account_id")),
        "contact_id": _int_or_none(form_data.get("contact_id")),
        "stage": stage,
        "amount": form_data.get("amount", "").strip() or None,
        "currency": form_data.get("currency", "CAD").strip() or "CAD",
        "probability": int(probability or "10"),
        "expected_close_date": form_data.get("expected_close_date", "").strip() or None,
        "close_date": form_data.get("close_date", "").strip() or None,
        "close_reason": form_data.get("close_reason", "").strip() or None,
        "owner_id": _int_or_none(form_data.get("owner_id")),
        "lead_id": _int_or_none(form_data.get("lead_id")),
        "notes": form_data.get("notes", "").strip() or None,
        "created_by": (existing or {}).get("created_by", user_id),
    }


@opportunities_bp.route("/")
@login_required
def list_view():
    stage = request.args.get("stage", "").strip() or None
    opportunities = list_opportunities(stage)
    stages = get_pipeline_stages()
    return render_template(
        "opportunities/list.html",
        opportunities=opportunities,
        stages=stages,
        active_stage=stage,
    )


@opportunities_bp.route("/pipeline")
@login_required
def pipeline_view():
    stages = get_pipeline_stages()
    opportunities = opportunities_by_stage()
    grouped = {stage["stage_key"]: [] for stage in stages}
    for opportunity in opportunities:
        grouped.setdefault(opportunity["stage"], []).append(opportunity)
    return render_template(
        "opportunities/pipeline.html",
        stages=stages,
        grouped=grouped,
    )


@opportunities_bp.route("/new", methods=["GET", "POST"])
@login_required
def create_view():
    form_data = request.form if request.method == "POST" else {"owner_id": g.user["id"]}
    accounts = list_accounts_for_select()
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("opportunity", active_only=True)
    selected_account_id = _int_or_none(request.values.get("account_id"))
    contacts = list_contacts_for_account_select(selected_account_id)
    stages = get_pipeline_stages()

    if request.method == "POST":
        payload = _build_payload(request.form, g.user["id"])
        payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
        if not payload["title"] or not payload["account_id"]:
            flash("Title and account are required.", "danger")
        else:
            opportunity_id = create_opportunity(payload)
            log_activity(
                "opportunity",
                opportunity_id,
                "created",
                "Opportunity created.",
                g.user["id"],
            )
            flash("Opportunity created.", "success")
            return redirect(
                url_for("opportunities.detail_view", opportunity_id=opportunity_id)
            )

    return render_template(
        "opportunities/form.html",
        opportunity=None,
        form_data=form_data,
        accounts=accounts,
        owners=owners,
        contacts=contacts,
        stages=stages,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if request.method == "POST" else {},
        page_title="New Opportunity",
        submit_label="Create Opportunity",
    )


@opportunities_bp.route("/<int:opportunity_id>")
@login_required
def detail_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    activities = list_activities("opportunity", opportunity_id)
    line_items = get_opportunity_line_items(opportunity_id)
    stock_groups = list_product_stock_groups()
    emails = [
        _serialize_email(email, opportunity_id)
        for email in list_emails("opportunity", opportunity_id)
    ]
    documents = [
        _serialize_document(document, opportunity_id)
        for document in list_documents_for_opportunity(opportunity_id)
    ]
    mentionable_users = list_assignable_users()
    attachment = None
    attachment_id = _int_or_none(request.args.get("attachment"))
    if attachment_id:
        attachment = _serialize_document(
            get_document_for_opportunity(opportunity_id, attachment_id),
            opportunity_id,
        )
    custom_field_rows = get_custom_field_values(
        opportunity, list_custom_fields("opportunity", active_only=True)
    )
    return render_template(
        "opportunities/detail.html",
        opportunity=opportunity,
        activities=activities,
        line_items=line_items,
        stock_groups=stock_groups,
        emails=emails,
        documents=documents,
        attachment=attachment,
        mentionable_users=mentionable_users,
        custom_field_rows=custom_field_rows,
        smtp_ready=smtp_configured(),
    )


@opportunities_bp.route("/<int:opportunity_id>/edit", methods=["GET", "POST"])
@login_required
def edit_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    form_data = request.form if request.method == "POST" else opportunity
    selected_account_id = _int_or_none(
        request.values.get("account_id") or str(opportunity["account_id"])
    )
    accounts = list_accounts_for_select()
    owners = list_assignable_users()
    custom_field_definitions = list_custom_fields("opportunity", active_only=True)
    contacts = list_contacts_for_account_select(selected_account_id)
    stages = get_pipeline_stages()

    if request.method == "POST":
        payload = _build_payload(request.form, opportunity["owner_id"] or g.user["id"], existing=opportunity)
        payload["custom_fields"] = extract_custom_field_values(request.form, custom_field_definitions)
        if not payload["title"] or not payload["account_id"]:
            flash("Title and account are required.", "danger")
        else:
            previous_stage = opportunity["stage"]
            update_opportunity(opportunity_id, payload)
            if previous_stage != payload["stage"]:
                log_activity(
                    "opportunity",
                    opportunity_id,
                    "stage_changed",
                    f"Opportunity stage changed from {previous_stage} to {payload['stage']}.",
                    g.user["id"],
                    {"from": previous_stage, "to": payload["stage"]},
                )
            flash("Opportunity updated.", "success")
            return redirect(
                url_for("opportunities.detail_view", opportunity_id=opportunity_id)
            )

    return render_template(
        "opportunities/form.html",
        opportunity=opportunity,
        form_data=form_data,
        accounts=accounts,
        owners=owners,
        contacts=contacts,
        stages=stages,
        custom_field_definitions=custom_field_definitions,
        custom_field_values=extract_custom_field_values(form_data, custom_field_definitions) if request.method == "POST" else (opportunity.get("custom_fields") or {}),
        page_title="Edit Opportunity",
        submit_label="Save Changes",
    )


@opportunities_bp.route("/<int:opportunity_id>/stage", methods=["POST"])
@login_required
def update_stage_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    target_stage = request.form.get("stage", "").strip()
    stage = get_pipeline_stage(target_stage)
    if not stage:
        flash("Invalid stage.", "danger")
        return redirect(url_for("opportunities.pipeline_view"))

    update_opportunity_stage(opportunity_id, stage["stage_key"], stage["default_probability"])
    log_activity(
        "opportunity",
        opportunity_id,
        "stage_changed",
        f"Opportunity stage changed from {opportunity['stage']} to {stage['stage_key']}.",
        g.user["id"],
        {"from": opportunity["stage"], "to": stage["stage_key"]},
    )
    flash("Opportunity stage updated.", "success")
    return redirect(url_for("opportunities.pipeline_view"))


@opportunities_bp.route("/<int:opportunity_id>/notes", methods=["POST"])
@login_required
def add_note_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    note = request.form.get("note", "").strip()
    if note:
        mentions = _extract_mentions(note, _int_list(request.form.getlist("tag_user_ids")))
        metadata = {"mentions": mentions} if mentions else None
        log_activity("opportunity", opportunity_id, "note", note, g.user["id"], metadata)
        if mentions:
            _create_mention_notifications(opportunity, mentions, note)
        flash("Note added.", "success")
    else:
        flash("Note cannot be empty.", "danger")
    return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))


@opportunities_bp.route("/<int:opportunity_id>/lines", methods=["POST"])
@login_required
def add_line_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    try:
        line_id = create_opportunity_line(
            {
                "opportunity_id": opportunity_id,
                "brand": request.form.get("brand", "").strip(),
                "model": request.form.get("model", "").strip(),
                "grade": request.form.get("grade", "").strip() or None,
                "category": request.form.get("category", "").strip() or None,
                "storage": request.form.get("storage", "").strip() or None,
                "quantity": request.form.get("quantity", "").strip() or "0",
                "unit_price": request.form.get("unit_price", "").strip(),
                "notes": request.form.get("notes", "").strip() or None,
            }
        )
    except Exception as exc:
        flash(f"Could not add quote line: {exc}", "danger")
        return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))

    log_activity(
        "opportunity",
        opportunity_id,
        "product_added",
        f"Quote line added for {request.form.get('brand', '').strip()} {request.form.get('model', '').strip()}.",
        g.user["id"],
        {"line_id": line_id},
    )
    flash("Quote line added.", "success")
    return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))


@opportunities_bp.route("/<int:opportunity_id>/generate-quote", methods=["POST"])
@login_required
def generate_quote_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    try:
        document = generate_quote_pdf(opportunity_id, g.user["id"])
        flash("Quote PDF generated and attached to the email form.", "success")
        return redirect(_detail_url(opportunity_id, document["id"]))
    except Exception as exc:
        flash(f"Quote PDF could not be generated: {exc}", "warning")
        return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))


@opportunities_bp.route("/<int:opportunity_id>/generate-invoice", methods=["POST"])
@login_required
def generate_invoice_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))
    if opportunity["stage"] != "closed_won":
        flash("Invoices can only be generated for closed won opportunities.", "danger")
        return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))

    try:
        document = generate_invoice_pdf(opportunity_id, g.user["id"])
        flash("Invoice PDF generated and attached to the email form.", "success")
        return redirect(_detail_url(opportunity_id, document["id"]))
    except Exception as exc:
        flash(f"Invoice PDF could not be generated: {exc}", "warning")
        return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))


@opportunities_bp.route("/<int:opportunity_id>/documents/<int:doc_id>/download")
@login_required
def download_document_view(opportunity_id: int, doc_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        abort(404)
    if g.user["role"] == "rep" and opportunity["owner_id"] != g.user["id"]:
        abort(403)

    document = get_document_for_opportunity(opportunity_id, doc_id)
    if not document:
        abort(404)

    file_path = Path(document["file_path"])
    if not file_path.is_file():
        abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=document["file_name"],
        mimetype="application/pdf",
    )


@opportunities_bp.route("/<int:opportunity_id>/emails", methods=["POST"])
@login_required
def send_email_view(opportunity_id: int):
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        flash("Opportunity not found.", "danger")
        return redirect(url_for("opportunities.list_view"))

    to_address = request.form.get("to_address", "").strip()
    subject = request.form.get("subject", "").strip()
    body_text = request.form.get("body_text", "").strip()
    cc_address = request.form.get("cc_address", "").strip() or None
    attachment_id = _int_or_none(request.form.get("attachment_id"))
    if not to_address or not subject or not body_text:
        flash("To, subject, and body are required.", "danger")
        return redirect(_detail_url(opportunity_id, attachment_id))

    attachments = []
    attachment_metadata = []
    if attachment_id:
        attachment = get_document_for_opportunity(opportunity_id, attachment_id)
        if not attachment:
            flash("The selected attachment is no longer available.", "danger")
            return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))
        file_path = Path(attachment["file_path"])
        if not file_path.is_file():
            flash("The selected attachment file could not be found.", "danger")
            return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))
        attachments.append(
            {
                "filename": attachment["file_name"],
                "filepath": str(file_path),
            }
        )
        attachment_metadata.append(
            {
                "document_id": attachment["id"],
                "document_number": attachment["document_number"],
                "document_type": attachment["document_type"],
                "filename": attachment["file_name"],
                "size_bytes": attachment["file_size_bytes"],
            }
        )

    email_id = create_email(
        {
            "direction": "outbound",
            "related_type": "opportunity",
            "related_id": opportunity_id,
            "from_address": g.user["email"],
            "to_address": to_address,
            "cc_address": cc_address,
            "subject": subject,
            "body_html": None,
            "body_text": body_text,
            "status": "draft",
            "sent_by": g.user["id"],
            "attachments_json": attachment_metadata,
        }
    )

    try:
        send_email(to_address, subject, body_text, cc_address, attachments=attachments)
        mark_email_sent(email_id)
        log_activity(
            "opportunity",
            opportunity_id,
            "email_sent",
            f"Outbound email sent to {to_address}.",
            g.user["id"],
            {"email_id": email_id, "attachments": attachment_metadata},
        )
        flash("Email sent.", "success")
    except Exception as exc:
        mark_email_failed(email_id, str(exc))
        flash(f"Email could not be sent: {exc}", "warning")

    return redirect(url_for("opportunities.detail_view", opportunity_id=opportunity_id))


@opportunities_bp.route("/stages", methods=["GET", "POST"])
@login_required
def stages_view():
    if request.method == "POST":
        stage_key = request.form.get("stage_key", "").strip()
        display_name = request.form.get("display_name", "").strip()
        if stage_key and display_name:
            upsert_pipeline_stage(
                {
                    "stage_key": stage_key,
                    "display_name": display_name,
                    "display_order": int(request.form.get("display_order", "0") or "0"),
                    "default_probability": int(request.form.get("default_probability", "0") or "0"),
                    "is_active": request.form.get("is_active") == "on",
                }
            )
            flash("Pipeline stage saved.", "success")
        else:
            flash("Stage key and display name are required.", "danger")
        return redirect(url_for("opportunities.stages_view"))

    return render_template("opportunities/stages.html", stages=get_pipeline_stages())
