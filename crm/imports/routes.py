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
from bridge_crm.crm.imports.staging import discard_upload, load_upload, stage_upload

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

    outcome = commit_import(result.rows, g.user["id"])
    discard_upload(token)
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
    )
