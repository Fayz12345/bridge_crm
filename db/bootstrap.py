from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import insert

from bridge_crm.db.engine import get_engine
from bridge_crm.db.schema import (
    crm_pipeline_stages,
    crm_product_interest_options,
    crm_purchase_stages,
    metadata,
)
from bridge_crm.crm.opportunities.constants import (
    OPPORTUNITY_STAGE_DEFINITIONS,
    OPPORTUNITY_STAGE_KEYS,
    STAGE_MIGRATION_MAP,
)
from bridge_crm.crm.purchases.constants import (
    PURCHASE_STAGE_DEFINITIONS,
    PURCHASE_STAGE_KEYS,
)
from bridge_crm.crm.segments.constants import DEFAULT_PRODUCT_INTEREST_OPTIONS

DEFAULT_PIPELINE_STAGES = OPPORTUNITY_STAGE_DEFINITIONS
DEFAULT_PURCHASE_STAGES = PURCHASE_STAGE_DEFINITIONS


def initialize_database() -> None:
    engine = get_engine()
    metadata.create_all(engine)

    with engine.begin() as connection:
        _ensure_incremental_schema(connection)
        _sync_stage_table(connection, crm_pipeline_stages, DEFAULT_PIPELINE_STAGES)
        _sync_stage_table(connection, crm_purchase_stages, DEFAULT_PURCHASE_STAGES)
        _sync_product_interest_options(connection)


def _ensure_incremental_schema(connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    email_columns = (
        {column["name"] for column in inspector.get_columns("crm_emails")}
        if "crm_emails" in tables
        else set()
    )
    if "crm_emails" in tables and "attachments_json" not in email_columns:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE crm_emails "
                    "ADD COLUMN attachments_json JSONB DEFAULT '[]'::jsonb"
                )
            )
        else:
            connection.execute(
                text(
                    "ALTER TABLE crm_emails "
                    "ADD COLUMN attachments_json JSON DEFAULT '[]'"
                )
            )

    purchase_columns = (
        {column["name"] for column in inspector.get_columns("crm_purchases")}
        if "crm_purchases" in tables
        else set()
    )

    opportunity_columns = (
        {column["name"] for column in inspector.get_columns("crm_opportunities")}
        if "crm_opportunities" in tables
        else set()
    )
    if "crm_opportunities" in tables and "conversion_rate_to_cad" not in opportunity_columns:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE crm_opportunities "
                    "ADD COLUMN conversion_rate_to_cad NUMERIC(12, 6) NOT NULL DEFAULT 1"
                )
            )
        else:
            connection.execute(
                text(
                    "ALTER TABLE crm_opportunities "
                    "ADD COLUMN conversion_rate_to_cad NUMERIC DEFAULT 1"
                )
            )

    if "crm_purchases" in tables and "conversion_rate_to_cad" not in purchase_columns:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE crm_purchases "
                    "ADD COLUMN conversion_rate_to_cad NUMERIC(12, 6) NOT NULL DEFAULT 1"
                )
            )
        else:
            connection.execute(
                text(
                    "ALTER TABLE crm_purchases "
                    "ADD COLUMN conversion_rate_to_cad NUMERIC DEFAULT 1"
                )
            )

    if "crm_opportunities" in tables:
        connection.execute(
            text(
                "UPDATE crm_opportunities "
                "SET currency = 'CAD' "
                "WHERE currency IS NULL OR TRIM(currency) = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE crm_opportunities "
                "SET conversion_rate_to_cad = 1 "
                "WHERE conversion_rate_to_cad IS NULL OR conversion_rate_to_cad <= 0"
            )
        )
        for old_stage, new_stage in STAGE_MIGRATION_MAP.items():
            connection.execute(
                text(
                    "UPDATE crm_opportunities "
                    "SET stage = :new_stage, "
                    "probability = CASE WHEN probability IS NULL OR probability < 70 THEN 70 ELSE probability END "
                    "WHERE stage = :old_stage"
                ),
                {"old_stage": old_stage, "new_stage": new_stage},
            )

        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE crm_opportunities "
                    "DROP CONSTRAINT IF EXISTS ck_crm_opportunities_opportunity_stage"
                )
            )
            allowed_stages = "', '".join(OPPORTUNITY_STAGE_KEYS)
            connection.execute(
                text(
                    "ALTER TABLE crm_opportunities "
                    f"ADD CONSTRAINT ck_crm_opportunities_opportunity_stage CHECK (stage IN ('{allowed_stages}'))"
                )
            )

    if "crm_purchases" in tables:
        connection.execute(
            text(
                "UPDATE crm_purchases "
                "SET currency = 'CAD' "
                "WHERE currency IS NULL OR TRIM(currency) = ''"
            )
        )
        connection.execute(
            text(
                "UPDATE crm_purchases "
                "SET conversion_rate_to_cad = 1 "
                "WHERE conversion_rate_to_cad IS NULL OR conversion_rate_to_cad <= 0"
            )
        )
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE crm_purchases "
                    "DROP CONSTRAINT IF EXISTS ck_crm_purchases_purchase_stage"
                )
            )
            allowed_purchase_stages = "', '".join(PURCHASE_STAGE_KEYS)
            connection.execute(
                text(
                    "ALTER TABLE crm_purchases "
                    f"ADD CONSTRAINT ck_crm_purchases_purchase_stage CHECK (stage IN ('{allowed_purchase_stages}'))"
                )
            )

    if connection.dialect.name == "postgresql":
        _replace_postgres_check_constraint(
            connection,
            table_name="crm_custom_fields",
            constraint_name="ck_crm_custom_fields_custom_field_object_type",
            expression="object_type IN ('account', 'lead', 'opportunity', 'purchase', 'product')",
        )
        _replace_postgres_check_constraint(
            connection,
            table_name="crm_emails",
            constraint_name="ck_crm_emails_email_related_type",
            expression="related_type IN ('lead', 'opportunity', 'purchase', 'account')",
        )
        _replace_postgres_check_constraint(
            connection,
            table_name="crm_whatsapp_messages",
            constraint_name="ck_crm_whatsapp_messages_whatsapp_related_type",
            expression="related_type IN ('lead', 'opportunity', 'purchase', 'account')",
        )


def _sync_stage_table(connection, table, stage_definitions: list[dict]) -> None:
    for stage in stage_definitions:
        statement = insert(table).values(**stage)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.stage_key],
            set_={
                "display_name": stage["display_name"],
                "display_order": stage["display_order"],
                "default_probability": stage["default_probability"],
                "is_active": True,
            },
        )
        connection.execute(statement)

    active_stage_keys = "', '".join(stage["stage_key"] for stage in stage_definitions)
    connection.execute(
        text(
            f"UPDATE {table.name} "
            "SET is_active = false "
            f"WHERE stage_key NOT IN ('{active_stage_keys}')"
        )
    )


def _sync_product_interest_options(connection) -> None:
    for option in DEFAULT_PRODUCT_INTEREST_OPTIONS:
        statement = insert(crm_product_interest_options).values(**option)
        statement = statement.on_conflict_do_update(
            index_elements=[crm_product_interest_options.c.option_key],
            set_={
                "display_name": option["display_name"],
                "display_order": option["display_order"],
                "is_active": option["is_active"],
            },
        )
        connection.execute(statement)


def _replace_postgres_check_constraint(
    connection,
    *,
    table_name: str,
    constraint_name: str,
    expression: str,
) -> None:
    connection.execute(
        text(
            f"ALTER TABLE {table_name} "
            f"DROP CONSTRAINT IF EXISTS {constraint_name}"
        )
    )
    connection.execute(
        text(
            f"ALTER TABLE {table_name} "
            f"ADD CONSTRAINT {constraint_name} CHECK ({expression})"
        )
    )


def get_pipeline_stages() -> list[dict]:
    with get_engine().connect() as connection:
        rows = connection.execute(
            select(crm_pipeline_stages).order_by(crm_pipeline_stages.c.display_order)
        )
        return [dict(row._mapping) for row in rows]
