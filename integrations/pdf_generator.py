from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from flask import current_app, render_template

from bridge_crm.config import get_settings
from bridge_crm.crm.documents.queries import create_document
from bridge_crm.crm.opportunities.queries import get_opportunity, get_opportunity_line_items


def generate_quote_pdf(opportunity_id: int, generated_by: int) -> dict:
    settings = get_settings()
    generated_at = datetime.now(timezone.utc)
    valid_until = (generated_at + timedelta(days=settings.quote_valid_days)).date()
    document_number = f"Q-{opportunity_id}-{generated_at.strftime('%Y%m%d%H%M%S%f')}"
    return _generate_document(
        opportunity_id=opportunity_id,
        generated_by=generated_by,
        document_type="quote",
        document_number=document_number,
        generated_at=generated_at,
        extra_context={
            "heading": "Quote",
            "document_label": "Quote Number",
            "document_date_label": "Generated Date",
            "secondary_date_label": "Valid Until",
            "secondary_date": valid_until,
            "payment_terms_text": None,
        },
        template_name="documents/quote.html",
    )


def generate_sales_order_pdf(opportunity_id: int, generated_by: int) -> dict:
    settings = get_settings()
    generated_at = datetime.now(timezone.utc)
    due_date = (generated_at + timedelta(days=settings.sales_order_payment_terms_days)).date()
    document_number = f"SO-{opportunity_id}-{generated_at.strftime('%Y%m%d%H%M%S%f')}"
    return _generate_document(
        opportunity_id=opportunity_id,
        generated_by=generated_by,
        document_type="sales_order",
        document_number=document_number,
        generated_at=generated_at,
        extra_context={
            "heading": "Sales Order",
            "document_label": "Sales Order Number",
            "document_date_label": "Order Date",
            "secondary_date_label": "Due Date",
            "secondary_date": due_date,
            "payment_terms_text": settings.sales_order_payment_terms_text,
        },
        template_name="documents/invoice.html",
    )


def _generate_document(
    *,
    opportunity_id: int,
    generated_by: int,
    document_type: str,
    document_number: str,
    generated_at: datetime,
    extra_context: dict,
    template_name: str,
) -> dict:
    opportunity = get_opportunity(opportunity_id)
    if not opportunity:
        raise RuntimeError("Opportunity not found.")

    line_items = get_opportunity_line_items(opportunity_id)
    context = _build_context(
        opportunity=opportunity,
        line_items=line_items,
        document_number=document_number,
        generated_at=generated_at,
        extra_context=extra_context,
    )

    html = render_template(template_name, **context)
    pdf_bytes = _render_pdf(html)

    storage_dir = Path(get_settings().document_storage_dir).expanduser()
    storage_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{document_number}.pdf"
    file_path = storage_dir / filename
    file_path.write_bytes(pdf_bytes)

    document_id = create_document(
        {
            "opportunity_id": opportunity_id,
            "document_type": document_type,
            "document_number": document_number,
            "file_name": filename,
            "file_path": str(file_path),
            "file_size_bytes": len(pdf_bytes),
            "generated_by": generated_by,
        }
    )
    return {
        "id": document_id,
        "document_number": document_number,
        "file_name": filename,
        "file_path": str(file_path),
        "file_size_bytes": len(pdf_bytes),
        "document_type": document_type,
        "created_at": generated_at,
    }


def _build_context(
    *,
    opportunity: dict,
    line_items: list[dict],
    document_number: str,
    generated_at: datetime,
    extra_context: dict,
) -> dict:
    settings = get_settings()
    subtotal = sum((Decimal(line["line_total"] or 0) for line in line_items), Decimal("0"))
    tax_rate = Decimal(str(settings.document_tax_rate or 0))
    tax_amount = (subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    grand_total = subtotal + tax_amount

    return {
        "company": {
            "name": settings.company_name,
            "address": settings.company_address,
            "phone": settings.company_phone,
            "email": settings.company_email,
        },
        "opportunity": opportunity,
        "line_items": line_items,
        "document_number": document_number,
        "generated_at": generated_at,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "terms_text": settings.document_terms_text,
        "footer_text": settings.document_footer_text,
        **extra_context,
    }


def _render_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - dependency driven
        raise RuntimeError(
            "WeasyPrint is not installed. Install the Python package and required system libraries."
        ) from exc

    return HTML(string=html, base_url=current_app.root_path).write_pdf()
