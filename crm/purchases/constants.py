from sqlalchemy import func

from bridge_crm.db.schema import crm_purchases

DEFAULT_PURCHASE_CURRENCY = "CAD"

PURCHASE_CURRENCY_OPTIONS = [
    ("CAD", "Canadian Dollar (CAD)"),
    ("USD", "US Dollar (USD)"),
    ("EUR", "Euro (EUR)"),
    ("GBP", "British Pound (GBP)"),
    ("AED", "UAE Dirham (AED)"),
    ("AUD", "Australian Dollar (AUD)"),
]
PURCHASE_CURRENCY_CODES = tuple(code for code, _label in PURCHASE_CURRENCY_OPTIONS)

PURCHASE_STAGE_DEFINITIONS = [
    {
        "stage_key": "prospecting",
        "display_name": "Prospecting",
        "display_order": 1,
        "default_probability": 10,
    },
    {
        "stage_key": "negotiation",
        "display_name": "Negotiation",
        "display_order": 2,
        "default_probability": 70,
    },
    {
        "stage_key": "closed_won",
        "display_name": "Closed Won",
        "display_order": 3,
        "default_probability": 100,
    },
    {
        "stage_key": "closed_lost",
        "display_name": "Closed Lost",
        "display_order": 4,
        "default_probability": 0,
    },
]

PURCHASE_STAGE_KEYS = tuple(stage["stage_key"] for stage in PURCHASE_STAGE_DEFINITIONS)
OPEN_PURCHASE_STAGES = tuple(
    stage["stage_key"]
    for stage in PURCHASE_STAGE_DEFINITIONS
    if stage["stage_key"] not in {"closed_won", "closed_lost"}
)


def purchase_total_cad_expression():
    return crm_purchases.c.estimated_total * func.coalesce(crm_purchases.c.conversion_rate_to_cad, 1)
