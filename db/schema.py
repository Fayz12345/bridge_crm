from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=naming_convention)

crm_users = Table(
    "crm_users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("full_name", String(255), nullable=False),
    Column("role", String(20), nullable=False, server_default="rep"),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("role IN ('admin', 'manager', 'rep')", name="user_role"),
)

crm_accounts = Table(
    "crm_accounts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("company_name", String(255), nullable=False),
    Column("contact_name", String(255)),
    Column("email", String(255)),
    Column("phone", String(30)),
    Column("phone_prefix", String(8)),
    Column("website", String(255)),
    Column("address_line_1", String(255)),
    Column("address_line_2", String(255)),
    Column("city", String(120)),
    Column("state_province", String(120)),
    Column("postal_code", String(30)),
    Column("country", String(120)),
    Column("industry", String(120)),
    Column("erp_client_id", String(11), nullable=True),
    Column("notes", Text),
    Column("custom_fields", JSONB().with_variant(JSON(), "sqlite")),
    Column("owner_id", ForeignKey("crm_users.id")),
    Column("created_by", ForeignKey("crm_users.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("erp_client_id", name="uq_crm_accounts_erp_client_id"),
)

crm_contacts = Table(
    "crm_contacts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("account_id", ForeignKey("crm_accounts.id"), nullable=False),
    Column("first_name", String(120), nullable=False),
    Column("last_name", String(120), nullable=False),
    Column("email", String(255)),
    Column("phone", String(30)),
    Column("phone_prefix", String(8)),
    Column("job_title", String(120)),
    Column("is_primary", Boolean, nullable=False, server_default="false"),
    Column("whatsapp_number", String(30)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

crm_leads = Table(
    "crm_leads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("first_name", String(120), nullable=False),
    Column("last_name", String(120), nullable=False),
    Column("email", String(255)),
    Column("phone", String(30)),
    Column("phone_prefix", String(8)),
    Column("company_name", String(255)),
    Column("source", String(30), nullable=False, server_default="manual"),
    Column("status", String(30), nullable=False, server_default="new"),
    Column("notes", Text),
    Column("interest", Text),
    Column("custom_fields", JSONB().with_variant(JSON(), "sqlite")),
    Column("owner_id", ForeignKey("crm_users.id")),
    Column("converted_account_id", ForeignKey("crm_accounts.id")),
    Column("converted_opportunity_id", ForeignKey("crm_opportunities.id")),
    Column("converted_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "source IN ('web_form', 'manual', 'import', 'referral', 'whatsapp')",
        name="lead_source",
    ),
    CheckConstraint(
        "status IN ('new', 'contacted', 'qualified', 'unqualified', 'converted')",
        name="lead_status",
    ),
)

crm_pipeline_stages = Table(
    "crm_pipeline_stages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("stage_key", String(30), nullable=False, unique=True),
    Column("display_name", String(60), nullable=False),
    Column("display_order", Integer, nullable=False),
    Column("default_probability", Integer, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
)

crm_opportunities = Table(
    "crm_opportunities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", String(255), nullable=False),
    Column("account_id", ForeignKey("crm_accounts.id"), nullable=False),
    Column("contact_id", ForeignKey("crm_contacts.id")),
    Column("stage", String(30), nullable=False, server_default="prospecting"),
    Column("amount", Numeric(14, 2)),
    Column("currency", String(3), nullable=False, server_default="CAD"),
    Column("probability", Integer, nullable=False, server_default="10"),
    Column("expected_close_date", Date),
    Column("close_date", Date),
    Column("close_reason", Text),
    Column("owner_id", ForeignKey("crm_users.id")),
    Column("lead_id", ForeignKey("crm_leads.id")),
    Column("notes", Text),
    Column("custom_fields", JSONB().with_variant(JSON(), "sqlite")),
    Column("created_by", ForeignKey("crm_users.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "stage IN ('prospecting', 'qualification', 'proposal', 'negotiation', 'closed_won', 'closed_lost')",
        name="opportunity_stage",
    ),
)

crm_products = Table(
    "crm_products",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("erp_inventory_id", Integer, nullable=False, unique=True),
    Column("serial_number", String(25), unique=True),
    Column("imei_1", String(32)),
    Column("model_name", String(255)),
    Column("brand_name", String(120)),
    Column("category_name", String(120)),
    Column("color", String(120)),
    Column("ram", String(60)),
    Column("rom", String(60)),
    Column("outward_grade", String(10)),
    Column("inward_grade", String(10)),
    Column("outward_sales_price", Numeric(11, 2)),
    Column("item_status", String(60)),
    Column("bin_location", String(60)),
    Column("inward_item_cost", Numeric(11, 2)),
    Column("lot_num", String(60)),
    Column("custom_fields", JSONB().with_variant(JSON(), "sqlite")),
    Column("erp_last_modified", DateTime(timezone=True)),
    Column("synced_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

crm_custom_fields = Table(
    "crm_custom_fields",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("object_type", String(30), nullable=False),
    Column("field_key", String(64), nullable=False),
    Column("field_label", String(120), nullable=False),
    Column("field_type", String(20), nullable=False, server_default="text"),
    Column("help_text", String(255)),
    Column("placeholder", String(120)),
    Column("options_json", JSONB().with_variant(JSON(), "sqlite")),
    Column("is_required", Boolean, nullable=False, server_default="false"),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("display_order", Integer, nullable=False, server_default="0"),
    Column("created_by", ForeignKey("crm_users.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("object_type", "field_key", name="uq_crm_custom_fields_object_type_field_key"),
    CheckConstraint(
        "object_type IN ('account', 'lead', 'opportunity', 'product')",
        name="custom_field_object_type",
    ),
    CheckConstraint(
        "field_type IN ('text', 'textarea', 'number', 'date', 'select', 'checkbox')",
        name="custom_field_type",
    ),
)

crm_notifications = Table(
    "crm_notifications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", ForeignKey("crm_users.id"), nullable=False),
    Column("notification_type", String(30), nullable=False, server_default="mention"),
    Column("title", String(255), nullable=False),
    Column("message", Text, nullable=False),
    Column("link_url", String(255)),
    Column("related_type", String(20)),
    Column("related_id", Integer),
    Column("metadata", JSONB().with_variant(JSON(), "sqlite")),
    Column("is_read", Boolean, nullable=False, server_default="false"),
    Column("read_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "notification_type IN ('mention', 'assignment', 'system')",
        name="notification_type",
    ),
)

crm_product_sync_log = Table(
    "crm_product_sync_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sync_started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sync_completed_at", DateTime(timezone=True)),
    Column("records_processed", Integer, nullable=False, server_default="0"),
    Column("records_inserted", Integer, nullable=False, server_default="0"),
    Column("records_updated", Integer, nullable=False, server_default="0"),
    Column("status", String(20), nullable=False, server_default="running"),
    Column("error_message", Text),
    CheckConstraint("status IN ('running', 'completed', 'failed')", name="sync_status"),
)

crm_opportunity_lines = Table(
    "crm_opportunity_lines",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "opportunity_id",
        ForeignKey("crm_opportunities.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("brand", String(50), nullable=False),
    Column("model", String(50), nullable=False),
    Column("grade", String(4)),
    Column("category", String(50)),
    Column("storage", String(10)),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(11, 2), nullable=False),
    Column(
        "line_total",
        Numeric(14, 2),
        Computed("quantity * unit_price", persisted=True),
    ),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

crm_emails = Table(
    "crm_emails",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("direction", String(20), nullable=False),
    Column("related_type", String(20), nullable=False),
    Column("related_id", Integer, nullable=False),
    Column("from_address", String(255), nullable=False),
    Column("to_address", String(255), nullable=False),
    Column("cc_address", String(255)),
    Column("subject", String(255)),
    Column("body_html", Text),
    Column("body_text", Text),
    Column("status", String(20), nullable=False, server_default="draft"),
    Column("sent_at", DateTime(timezone=True)),
    Column("sent_by", ForeignKey("crm_users.id")),
    Column("error_message", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("direction IN ('outbound', 'inbound')", name="email_direction"),
    CheckConstraint(
        "related_type IN ('lead', 'opportunity', 'account')",
        name="email_related_type",
    ),
    CheckConstraint("status IN ('draft', 'sent', 'failed')", name="email_status"),
)

crm_whatsapp_messages = Table(
    "crm_whatsapp_messages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("direction", String(20), nullable=False),
    Column("related_type", String(20), nullable=False),
    Column("related_id", Integer, nullable=False),
    Column("wa_message_id", String(255)),
    Column("from_number", String(30)),
    Column("to_number", String(30)),
    Column("message_type", String(20), nullable=False, server_default="text"),
    Column("body", Text),
    Column("template_name", String(255)),
    Column("status", String(20), nullable=False, server_default="sent"),
    Column("sent_at", DateTime(timezone=True)),
    Column("sent_by", ForeignKey("crm_users.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "direction IN ('outbound', 'inbound')", name="whatsapp_direction"
    ),
    CheckConstraint(
        "related_type IN ('lead', 'opportunity', 'account')",
        name="whatsapp_related_type",
    ),
    CheckConstraint(
        "message_type IN ('text', 'template', 'media')", name="whatsapp_type"
    ),
    CheckConstraint(
        "status IN ('sent', 'delivered', 'read', 'failed')",
        name="whatsapp_status",
    ),
)

crm_activities = Table(
    "crm_activities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("related_type", String(20), nullable=False),
    Column("related_id", Integer, nullable=False),
    Column("activity_type", String(30), nullable=False),
    Column("description", Text, nullable=False),
    Column("metadata", JSONB().with_variant(JSON(), "sqlite")),
    Column("created_by", ForeignKey("crm_users.id")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "activity_type IN ('note', 'call', 'meeting', 'email_sent', 'whatsapp_sent', 'stage_changed', 'status_changed', 'product_added', 'created', 'converted')",
        name="activity_type",
    ),
)

crm_login_attempts = Table(
    "crm_login_attempts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(255)),
    Column("ip_address", String(64), nullable=False),
    Column("successful", Boolean, nullable=False, server_default="false"),
    Column("attempted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

crm_rate_limits = Table(
    "crm_rate_limits",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("ip_address", String(64), nullable=False),
    Column("endpoint", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

Index("ix_crm_accounts_company_name", crm_accounts.c.company_name)
Index("ix_crm_accounts_owner_id", crm_accounts.c.owner_id)
Index("ix_crm_contacts_account_id", crm_contacts.c.account_id)
Index("ix_crm_leads_status", crm_leads.c.status)
Index("ix_crm_leads_owner_id", crm_leads.c.owner_id)
Index("ix_crm_opportunities_stage", crm_opportunities.c.stage)
Index("ix_crm_opportunities_owner_id", crm_opportunities.c.owner_id)
Index("ix_crm_products_model_name", crm_products.c.model_name)
Index("ix_crm_products_brand_name", crm_products.c.brand_name)
Index("ix_crm_custom_fields_object_type", crm_custom_fields.c.object_type)
Index("ix_crm_activities_related", crm_activities.c.related_type, crm_activities.c.related_id)
Index("ix_crm_notifications_user_read", crm_notifications.c.user_id, crm_notifications.c.is_read)
Index("ix_crm_login_attempts_ip_address", crm_login_attempts.c.ip_address)
Index("ix_crm_rate_limits_lookup", crm_rate_limits.c.endpoint, crm_rate_limits.c.ip_address)
