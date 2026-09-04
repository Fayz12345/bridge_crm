from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from bridge_crm.crm.auth.routes import roles_required
from bridge_crm.crm.imports.csv_parser import (
    MAX_FILE_BYTES,
    MAX_ROWS,
    ParseResult,
    decode_csv_bytes,
    error_report_csv,
    parse_contacts_csv,
)
from bridge_crm.crm.imports.queries import commit_import, plan_import
from bridge_crm.crm.imports.staging import claim_upload, load_upload, stage_upload
from bridge_crm.crm.imports.wati_sync import (
    MAX_PER_RUN,
    count_contacts_without_whatsapp,
    list_unsynced_contacts,
    sync_contacts,
    sync_status_counts,
)
from bridge_crm.integrations.whatsapp import contacts_supported

imports_bp = Blueprint(
    "imports",
    __name__,
    url_prefix="/imports",
    template_folder="../../templates",
)

PREVIEW_ROW_LIMIT = 200


def _csv_response(body: str, filename: str) -> Response:
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _render_preview(result: ParseResult, token: str, filename: str):
    plans = plan_import(result.rows)
    new_accounts = sum(1 for plan in plans if plan.creates_account)
    contacts_new = sum(1 for plan in plans if plan.contact_action == "create")
    contacts_updated = sum(1 for plan in plans if plan.contact_action == "update")
    return render_template(
        "imports/preview.html",
        result=result,
        plans=plans[:PREVIEW_ROW_LIMIT],
        plan_total=len(plans),
        preview_row_limit=PREVIEW_ROW_LIMIT,
        token=token,
        filename=filename,
        new_accounts=new_accounts,
        contacts_new=contacts_new,
        contacts_updated=contacts_updated,
    )


@imports_bp.route("/contacts", methods=["GET"])
@roles_required("admin", "manager")
def upload_view():
    return render_template("imports/upload.html", max_rows=MAX_ROWS)


@imports_bp.route("/contacts/preview", methods=["POST"])
@roles_required("admin", "manager")
def preview_view():
    upload = request.files.get("csv_file")
    if not upload or not upload.filename:
        flash("Choose a CSV file to upload.", "danger")
        return redirect(url_for("imports.upload_view"))

    # Checked before read() so an oversized upload is not pulled into memory.
    if (request.content_length or 0) > MAX_FILE_BYTES:
        flash(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.", "danger")
        return redirect(url_for("imports.upload_view"))

    text, decode_error = decode_csv_bytes(upload.read())
    if decode_error:
        flash(decode_error, "danger")
        return redirect(url_for("imports.upload_view"))

    result = parse_contacts_csv(text)
    if result.file_errors:
        for message in result.file_errors:
            flash(message, "danger")
        return redirect(url_for("imports.upload_view"))
    if result.missing_headers:
        flash(
            "The file is missing required column(s): " + ", ".join(result.missing_headers),
            "danger",
        )
        return redirect(url_for("imports.upload_view"))

    token = stage_upload(content=text, filename=upload.filename, user_id=g.user["id"])
    return _render_preview(result, token, upload.filename)


@imports_bp.route("/contacts/errors/<token>")
@roles_required("admin", "manager")
def error_report_view(token: str):
    record = load_upload(token, user_id=g.user["id"])
    if not record:
        flash("That import has expired. Upload the file again.", "warning")
        return redirect(url_for("imports.upload_view"))

    result = parse_contacts_csv(record["content"])
    return _csv_response(error_report_csv(result), "contact_import_errors.csv")


@imports_bp.route("/contacts/commit", methods=["POST"])
@roles_required("admin", "manager")
def commit_view():
    token = request.form.get("token", "").strip()
    record = load_upload(token, user_id=g.user["id"])
    if not record:
        flash("That import has expired. Upload the file again.", "warning")
        return redirect(url_for("imports.upload_view"))

    result = parse_contacts_csv(record["content"])
    if not result.is_importable:
        flash("There is nothing valid to import in that file.", "danger")
        return redirect(url_for("imports.upload_view"))

    # Claim the upload before the (potentially slow) write, so a double-submit
    # cannot start a second import of the same file against a stale view of
    # the database and duplicate every account in it.
    if not claim_upload(token, user_id=g.user["id"]):
        flash("That import is already running or has been completed.", "warning")
        return redirect(url_for("accounts.list_view"))

    outcome = commit_import(result.rows, g.user["id"])
    current_app.logger.info(
        "Contact import by user %s from %s: %s account(s), %s new / %s updated contact(s), %s failed",
        g.user["id"],
        record["filename"],
        outcome.accounts_created,
        outcome.contacts_created,
        outcome.contacts_updated,
        len(outcome.failures),
    )

    if outcome.total_written:
        flash(
            f"Imported {outcome.total_written} contact(s) across {outcome.accounts_created} new account(s).",
            "success",
        )
    if outcome.failures:
        flash(f"{len(outcome.failures)} row(s) could not be saved.", "warning")

    return render_template(
        "imports/result.html",
        outcome=outcome,
        result=result,
        filename=record["filename"],
        wati_ready=contacts_supported(),
    )


@imports_bp.route("/wati", methods=["GET"])
@roles_required("admin", "manager")
def wati_sync_view():
    return _render_wati_sync()


@imports_bp.route("/wati/sync", methods=["POST"])
@roles_required("admin", "manager")
def wati_sync_run_view():
    if not contacts_supported():
        flash(
            "Wati is not configured. Set WHATSAPP_PROVIDER=wati, WATI_API_ENDPOINT, "
            "and WATI_ACCESS_TOKEN.",
            "warning",
        )
        return redirect(url_for("imports.wati_sync_view"))

    pending = list_unsynced_contacts(limit=MAX_PER_RUN)
    if not pending:
        flash("Every contact with a WhatsApp number is already synced to Wati.", "info")
        return redirect(url_for("imports.wati_sync_view"))

    outcome = sync_contacts([int(record["id"]) for record in pending])
    current_app.logger.info(
        "Wati contact sync by user %s: %s synced, %s failed, %s skipped",
        g.user["id"],
        outcome.synced,
        outcome.failed,
        outcome.skipped,
    )

    if outcome.synced:
        flash(f"Pushed {outcome.synced} contact(s) to Wati.", "success")
    if outcome.failed:
        flash(f"{outcome.failed} contact(s) failed to sync. They can be retried.", "warning")
    if not outcome.synced and not outcome.failed:
        flash("No contacts were sent to Wati.", "warning")

    return _render_wati_sync(last_run=outcome)


def _render_wati_sync(last_run=None):
    counts = sync_status_counts()
    remaining = len(list_unsynced_contacts(limit=MAX_PER_RUN + 1))
    return render_template(
        "imports/wati_sync.html",
        counts=counts,
        remaining=remaining,
        batch_size=MAX_PER_RUN,
        more_than_one_batch=remaining > MAX_PER_RUN,
        no_whatsapp_count=count_contacts_without_whatsapp(),
        failures=[
            record
            for record in list_unsynced_contacts(limit=50)
            if record.get("wati_sync_status") == "failed"
        ],
        wati_ready=contacts_supported(),
        last_run=last_run,
    )
