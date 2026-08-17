from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_product_sync_log, crm_products


def get_last_completed_sync_watermark() -> datetime | None:
    statement = (
        select(func.max(crm_product_sync_log.c.sync_completed_at))
        .where(crm_product_sync_log.c.status == "completed")
    )
    with get_connection() as connection:
        return connection.execute(statement).scalar_one_or_none()


def start_sync_log() -> int:
    with get_connection() as connection:
        row = connection.execute(
            crm_product_sync_log.insert()
            .values(status="running")
            .returning(crm_product_sync_log.c.id)
        ).first()
    return int(row[0])


def complete_sync_log(
    log_id: int,
    *,
    records_processed: int,
    records_inserted: int,
    records_updated: int,
    watermark: datetime | None = None,
) -> None:
    values = {
        "sync_completed_at": datetime.now(timezone.utc),
        "records_processed": records_processed,
        "records_inserted": records_inserted,
        "records_updated": records_updated,
        "status": "completed",
        "error_message": None,
    }
    statement = (
        update(crm_product_sync_log)
        .where(crm_product_sync_log.c.id == log_id)
        .values(**values)
    )
    with get_connection() as connection:
        connection.execute(statement)


def fail_sync_log(log_id: int, error_message: str) -> None:
    statement = (
        update(crm_product_sync_log)
        .where(crm_product_sync_log.c.id == log_id)
        .values(
            sync_completed_at=datetime.now(timezone.utc),
            status="failed",
            error_message=error_message[:4000],
        )
    )
    with get_connection() as connection:
        connection.execute(statement)


def upsert_products(rows: list[dict]) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0

    now = datetime.now(timezone.utc)
    erp_ids = [row["erp_inventory_id"] for row in rows]

    with get_connection() as connection:
        existing_ids = {
            row[0]
            for row in connection.execute(
                select(crm_products.c.erp_inventory_id).where(
                    crm_products.c.erp_inventory_id.in_(erp_ids)
                )
            ).all()
        }

        inserted = 0
        updated = 0
        for row in rows:
            values = {**row, "synced_at": now}
            statement = insert(crm_products).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[crm_products.c.erp_inventory_id],
                set_={
                    key: values[key]
                    for key in values
                    if key not in {"erp_inventory_id", "id"}
                },
            )
            connection.execute(statement)
            if row["erp_inventory_id"] in existing_ids:
                updated += 1
            else:
                inserted += 1

    return len(rows), inserted, updated
