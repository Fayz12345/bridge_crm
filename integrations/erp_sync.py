"""Sync product inventory from the remote ERP MySQL database into crm_products."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pymysql
from pymysql.cursors import DictCursor

from bridge_crm.config import get_settings
from bridge_crm.crm.products.sync_queries import (
    complete_sync_log,
    fail_sync_log,
    get_last_completed_sync_watermark,
    start_sync_log,
    upsert_products,
)

logger = logging.getLogger(__name__)

ERP_PRODUCT_QUERY = """
SELECT
  inv.id AS erp_inventory_id,
  inv.serial_number,
  inv.imei_1,
  m.model_name,
  b.brand_name,
  c.category_name,
  color_attr.attribute_value AS color,
  ram_attr.attribute_value AS ram,
  rom_attr.attribute_value AS rom,
  inv.outward_grade,
  inv.inward_grade,
  inv.outward_sales_price,
  inv.item_status,
  inv.bin_location,
  inv.inward_item_cost,
  inv.lot_num,
  COALESCE(inv.mod_dateTime, inv.cr_dateTime) AS erp_last_modified
FROM wh_inv_master inv
LEFT JOIN web_model_master m ON inv.model_id = m.id
LEFT JOIN web_brand_master b ON inv.brand_id = b.id
LEFT JOIN web_category_master c ON inv.prod_cat_id = c.id
LEFT JOIN web_attribute_master color_attr ON inv.color_id = color_attr.id
LEFT JOIN web_attribute_master ram_attr ON inv.ram_id = ram_attr.id
LEFT JOIN web_attribute_master rom_attr ON inv.rom_id = rom_attr.id
{where_clause}
ORDER BY inv.id
"""


def erp_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.erp_db_host.strip()
        and settings.erp_db_user.strip()
        and settings.erp_db_password.strip()
    )


def _normalize_row(row: dict) -> dict:
    erp_last_modified = row.get("erp_last_modified")
    if isinstance(erp_last_modified, datetime) and erp_last_modified.tzinfo is None:
        erp_last_modified = erp_last_modified.replace(tzinfo=timezone.utc)

    outward_price = row.get("outward_sales_price")
    inward_cost = row.get("inward_item_cost")

    return {
        "erp_inventory_id": int(row["erp_inventory_id"]),
        "serial_number": row.get("serial_number"),
        "imei_1": row.get("imei_1"),
        "model_name": row.get("model_name"),
        "brand_name": row.get("brand_name"),
        "category_name": row.get("category_name"),
        "color": row.get("color"),
        "ram": row.get("ram"),
        "rom": row.get("rom"),
        "outward_grade": row.get("outward_grade"),
        "inward_grade": row.get("inward_grade"),
        "outward_sales_price": Decimal(str(outward_price)) if outward_price is not None else None,
        "item_status": row.get("item_status"),
        "bin_location": row.get("bin_location"),
        "inward_item_cost": Decimal(str(inward_cost)) if inward_cost is not None else None,
        "lot_num": row.get("lot_num"),
        "erp_last_modified": erp_last_modified,
    }


def fetch_erp_rows(*, full: bool) -> list[dict]:
    settings = get_settings()
    where_clause = ""
    params: tuple = ()

    if not full:
        watermark = get_last_completed_sync_watermark()
        if watermark:
            where_clause = "WHERE COALESCE(inv.mod_dateTime, inv.cr_dateTime) >= %s"
            params = (watermark.replace(tzinfo=None) if watermark.tzinfo else watermark,)

    query = ERP_PRODUCT_QUERY.format(where_clause=where_clause)

    connection = pymysql.connect(
        host=settings.erp_db_host,
        port=settings.erp_db_port,
        user=settings.erp_db_user,
        password=settings.erp_db_password,
        database=settings.erp_db_name,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=30,
        read_timeout=300,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
    finally:
        connection.close()

    return [_normalize_row(row) for row in rows]


def run_sync(*, full: bool = False) -> dict:
    if not erp_configured():
        raise RuntimeError(
            "ERP sync is not configured. Set ERP_DB_HOST, ERP_DB_USER, and ERP_DB_PASSWORD in .env."
        )

    mode = "full" if full else "incremental"
    logger.info("Starting ERP product sync (%s)", mode)
    log_id = start_sync_log()

    try:
        rows = fetch_erp_rows(full=full)
        processed, inserted, updated = upsert_products(rows)
        complete_sync_log(
            log_id,
            records_processed=processed,
            records_inserted=inserted,
            records_updated=updated,
        )
        result = {
            "mode": mode,
            "processed": processed,
            "inserted": inserted,
            "updated": updated,
            "status": "completed",
        }
        logger.info("ERP sync completed: %s", result)
        return result
    except Exception as exc:
        logger.exception("ERP sync failed")
        fail_sync_log(log_id, str(exc))
        raise


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Bridge CRM ERP product sync")
    parser.add_argument("--full", action="store_true", help="Full reconciliation sync")
    args = parser.parse_args()

    if not erp_configured():
        print(
            "ERP sync skipped: ERP_DB_HOST, ERP_DB_USER, and ERP_DB_PASSWORD are not configured.",
            file=sys.stderr,
        )
        sys.exit(0)

    try:
        result = run_sync(full=args.full)
    except Exception:
        sys.exit(1)

    print(
        f"ERP sync {result['mode']}: "
        f"{result['processed']} processed, "
        f"{result['inserted']} inserted, "
        f"{result['updated']} updated."
    )


if __name__ == "__main__":
    main()
