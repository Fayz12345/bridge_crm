from sqlalchemy import insert, select

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_documents


def create_document(payload: dict) -> int:
    statement = insert(crm_documents).values(**payload).returning(crm_documents.c.id)
    with get_connection() as connection:
        document_id = connection.execute(statement).scalar_one()
    return int(document_id)


def get_document_for_opportunity(opportunity_id: int, document_id: int) -> dict | None:
    statement = (
        select(crm_documents)
        .where(
            crm_documents.c.id == document_id,
            crm_documents.c.opportunity_id == opportunity_id,
        )
    )
    with get_connection() as connection:
        row = connection.execute(statement).mappings().first()
    return dict(row) if row else None


def list_documents_for_opportunity(opportunity_id: int) -> list[dict]:
    statement = (
        select(crm_documents)
        .where(crm_documents.c.opportunity_id == opportunity_id)
        .order_by(crm_documents.c.created_at.desc(), crm_documents.c.id.desc())
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]
