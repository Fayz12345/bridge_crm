from sqlalchemy import func

from bridge_crm.db.schema import crm_opportunities

DEFAULT_OPPORTUNITY_CURRENCY = "CAD"

OPPORTUNITY_CURRENCY_OPTIONS = [
    ("CAD", "Canadian Dollar (CAD)"),
    ("USD", "US Dollar (USD)"),
    ("EUR", "Euro (EUR)"),
    ("GBP", "British Pound (GBP)"),
    ("AED", "UAE Dirham (AED)"),
    ("AUD", "Australian Dollar (AUD)"),
]
OPPORTUNITY_CURRENCY_CODES = tuple(code for code, _label in OPPORTUNITY_CURRENCY_OPTIONS)

OPPORTUNITY_STAGE_DEFINITIONS = [
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

OPPORTUNITY_STAGE_KEYS = tuple(stage["stage_key"] for stage in OPPORTUNITY_STAGE_DEFINITIONS)
OPEN_OPPORTUNITY_STAGES = tuple(
    stage["stage_key"]
    for stage in OPPORTUNITY_STAGE_DEFINITIONS
    if stage["stage_key"] not in {"closed_won", "closed_lost"}
)
STAGE_MIGRATION_MAP = {
    "qualification": "negotiation",
    "proposal": "negotiation",
}


def opportunity_amount_cad_expression():
    return crm_opportunities.c.amount * func.coalesce(crm_opportunities.c.conversion_rate_to_cad, 1)
