from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from bridge_crm.crm.accounts.queries import get_accounts_by_ids, list_accounts
from bridge_crm.crm.auth.routes import login_required
from bridge_crm.crm.communications.whatsapp_bulk import (
    render_bulk_whatsapp_page,
    send_bulk_whatsapp,
)
from bridge_crm.crm.communications.whatsapp_thread import (
    conversation_context,
    require_thread_entity,
)
from bridge_crm.crm.leads.queries import get_leads_by_ids, list_leads
from bridge_crm.crm.whatsapp.queries import list_recent_conversations
from bridge_crm.crm.whatsapp.template_queries import (
    count_templates_by_status,
    get_whatsapp_template,
    has_approved_template,
    list_whatsapp_templates,
)
from bridge_crm.crm.whatsapp.templates import (
    TEMPLATE_CATEGORIES,
    TEMPLATE_LANGUAGES,
    cancel_template,
    submit_template,
    sync_templates_from_wati,
)
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    templates_ready,
    whatsapp_configured,
)

communications_bp = Blueprint(
    "communications",
    __name__,
    url_prefix="/communications",
    template_folder="../../templates",
)


def _parse_ids(values) -> list[int]:
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


def _format_phone(phone_prefix: str | None, phone: str | None) -> str | None:
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


def _lead_rows(leads: list[dict]) -> list[dict]:
    rows = []
    for lead in leads:
        rows.append(
            {
                "id": int(lead["id"]),
                "display_name": (
                    f"{lead.get('first_name', '').strip()} {lead.get('last_name', '').strip()}".strip()
                    or f"Lead #{lead['id']}"
                ),
                "subtitle": lead.get("company_name") or lead.get("owner_name") or "",
                "whatsapp_number": _format_phone(lead.get("phone_prefix"), lead.get("phone")),
                "product_interests": lead.get("product_interests") or [],
                "tags": lead.get("tags") or [],
            }
        )
    return rows


def _account_rows(accounts: list[dict]) -> list[dict]:
    rows = []
    for account in accounts:
        rows.append(
            {
                "id": int(account["id"]),
                "display_name": account.get("company_name") or f"Account #{account['id']}",
                "subtitle": account.get("contact_name") or account.get("owner_name") or "",
                "whatsapp_number": account.get("whatsapp_number")
                or _format_phone(account.get("phone_prefix"), account.get("phone")),
                "product_interests": account.get("product_interests") or [],
                "tags": account.get("tags") or [],
            }
        )
    return rows


def _whatsapp_templates_ready() -> bool:
    return templates_ready() or has_approved_template()


@communications_bp.route("/")
@login_required
def inbox_view():
    return render_template(
        "communications/inbox.html",
        conversations=list_recent_conversations(),
        template_counts=count_templates_by_status(),
        whatsapp_api_ready=whatsapp_configured(),
        whatsapp_templates_ready=_whatsapp_templates_ready(),
    )


@communications_bp.route("/thread/<related_type>/<int:related_id>/messages")
@login_required
def thread_messages_view(related_type: str, related_id: int):
    related_type = (related_type or "").strip().lower()
    if related_type not in {"lead", "account"}:
        return ("Not found", 404)
    phone = require_thread_entity(related_type, related_id)
    context = conversation_context(
        related_type,
        related_id,
        phone,
        sync=True,
        min_interval_seconds=20,
    )
    return render_template("components/whatsapp_messages.html", **context)


@communications_bp.route("/broadcast", methods=["GET", "POST"])
@login_required
def broadcast_view():
    entity = (request.values.get("entity") or "leads").strip().lower()
    if entity not in {"leads", "accounts"}:
        entity = "leads"

    if request.method == "POST" and request.form.get("action") != "preview":
        selected_ids = _parse_ids(request.form.getlist("selected_ids"))
        if not selected_ids:
            flash("Select at least one recipient for the broadcast.", "warning")
            return redirect(url_for("communications.broadcast_view", entity=entity))
        records = _records_for_ids(entity, selected_ids)
        return render_bulk_whatsapp_page(
            records=records,
            return_to=url_for("communications.broadcast_view", entity=entity),
            body_text=request.form.get("body_text", "").strip(),
            entity_label="Leads" if entity == "leads" else "Accounts",
            compose_endpoint="communications.broadcast_preview_view",
            send_endpoint="communications.send_broadcast_view",
            broadcast_name=request.form.get("broadcast_name", "").strip(),
            template_name=request.form.get("template_name", "").strip(),
            entity=entity,
        )

    search_term = request.args.get("q", "").strip()
    if entity == "accounts":
        source = list_accounts(search_term if search_term else None)
        records = _account_rows(source)
    else:
        source = list_leads(None, search_term if search_term else None)
        records = _lead_rows(source)

    return render_template(
        "communications/broadcast.html",
        entity=entity,
        records=records,
        search_term=search_term,
        available_count=sum(1 for row in records if row.get("whatsapp_number")),
        whatsapp_api_ready=whatsapp_configured(),
        whatsapp_templates_ready=_whatsapp_templates_ready(),
    )


@communications_bp.route("/broadcast/preview", methods=["POST"])
@login_required
def broadcast_preview_view():
    entity = (request.form.get("entity") or "leads").strip().lower()
    if entity not in {"leads", "accounts"}:
        entity = "leads"
    selected_ids = _parse_ids(request.form.getlist("selected_ids"))
    if not selected_ids:
        flash("Select at least one recipient for the broadcast.", "warning")
        return redirect(url_for("communications.broadcast_view", entity=entity))
    records = _records_for_ids(entity, selected_ids)
    return render_bulk_whatsapp_page(
        records=records,
        return_to=url_for("communications.broadcast_view", entity=entity),
        body_text=request.form.get("body_text", "").strip(),
        entity_label="Leads" if entity == "leads" else "Accounts",
        compose_endpoint="communications.broadcast_preview_view",
        send_endpoint="communications.send_broadcast_view",
        broadcast_name=request.form.get("broadcast_name", "").strip(),
        template_name=request.form.get("template_name", "").strip(),
        entity=entity,
    )


@communications_bp.route("/broadcast/send", methods=["POST"])
@login_required
def send_broadcast_view():
    entity = (request.form.get("entity") or "leads").strip().lower()
    if entity not in {"leads", "accounts"}:
        entity = "leads"
    selected_ids = _parse_ids(request.form.getlist("selected_ids"))
    return_to = url_for("communications.inbox_view")
    if not selected_ids:
        flash("Select at least one recipient for the broadcast.", "warning")
        return redirect(url_for("communications.broadcast_view", entity=entity))

    records = _records_for_ids(entity, selected_ids)
    send_bulk_whatsapp(
        records=records,
        body_text=request.form.get("body_text", "").strip(),
        related_type="lead" if entity == "leads" else "account",
        return_to=return_to,
        broadcast_name=request.form.get("broadcast_name", "").strip(),
        template_name=request.form.get("template_name", "").strip(),
    )
    return redirect(return_to)


def _records_for_ids(entity: str, selected_ids: list[int]) -> list[dict]:
    if entity == "accounts":
        return _account_rows(get_accounts_by_ids(selected_ids))
    return _lead_rows(get_leads_by_ids(selected_ids))


@communications_bp.route("/templates")
@login_required
def templates_view():
    status = (request.args.get("status") or "").strip().lower()
    if status not in {"pending", "approved", "cancelled"}:
        status = ""
    return render_template(
        "communications/templates.html",
        templates=list_whatsapp_templates(status or None),
        status=status or "all",
        template_counts=count_templates_by_status(),
        whatsapp_api_ready=whatsapp_configured(),
    )


@communications_bp.route("/templates/sync", methods=["POST"])
@login_required
def sync_templates_view():
    if not whatsapp_configured():
        flash("Connect Wati before syncing templates.", "danger")
        return redirect(url_for("communications.templates_view"))
    try:
        result = sync_templates_from_wati(created_by=g.user["id"])
    except WhatsAppAPIError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("communications.templates_view"))
    flash(f"Synced {result['synced']} template(s) from Wati.", "success")
    return redirect(url_for("communications.templates_view"))


@communications_bp.route("/templates/new", methods=["GET", "POST"])
@login_required
def create_template_view():
    form_data = request.form if request.method == "POST" else {
        "category": "MARKETING",
        "language": "en",
        "body": "Hi {{name}}, this is {{rep_name}} from Bridge Wireless. {{message}}",
    }
    if request.method == "POST":
        if not whatsapp_configured():
            flash("Connect Wati before creating a template.", "danger")
        else:
            try:
                template_id = submit_template(
                    element_name=request.form.get("element_name", ""),
                    category=request.form.get("category", "MARKETING"),
                    language=request.form.get("language", "en"),
                    body=request.form.get("body", ""),
                    footer=request.form.get("footer", "").strip() or None,
                    header_text=request.form.get("header_text", "").strip() or None,
                    created_by=g.user["id"],
                )
                flash("Template submitted to Wati. Status starts as pending until Meta approves it.", "success")
                return redirect(url_for("communications.template_detail_view", template_id=template_id))
            except ValueError as exc:
                flash(str(exc), "danger")
            except WhatsAppAPIError as exc:
                flash(str(exc), "danger")
    return render_template(
        "communications/template_form.html",
        form_data=form_data,
        categories=TEMPLATE_CATEGORIES,
        languages=TEMPLATE_LANGUAGES,
        whatsapp_api_ready=whatsapp_configured(),
    )


@communications_bp.route("/templates/<int:template_id>")
@login_required
def template_detail_view(template_id: int):
    template = get_whatsapp_template(template_id)
    if not template:
        flash("Template not found.", "danger")
        return redirect(url_for("communications.templates_view"))
    return render_template("communications/template_detail.html", template=template)


@communications_bp.route("/templates/<int:template_id>/cancel", methods=["POST"])
@login_required
def cancel_template_view(template_id: int):
    try:
        updated = cancel_template(template_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("communications.templates_view"))
    if updated.get("wati_error"):
        flash(
            "Marked cancelled in CRM. Wati cancel failed: " + updated["wati_error"],
            "warning",
        )
    else:
        flash("Template cancelled.", "success")
    return redirect(url_for("communications.template_detail_view", template_id=template_id))

