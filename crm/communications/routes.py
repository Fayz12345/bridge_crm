from flask import Blueprint, flash, redirect, render_template, request, url_for

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
from bridge_crm.integrations.whatsapp import templates_ready, whatsapp_configured

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


@communications_bp.route("/")
@login_required
def inbox_view():
    return render_template(
        "communications/inbox.html",
        conversations=list_recent_conversations(),
        whatsapp_api_ready=whatsapp_configured(),
        whatsapp_templates_ready=templates_ready(),
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
        whatsapp_templates_ready=templates_ready(),
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
