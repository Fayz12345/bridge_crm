from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from bridge_crm.db.engine import get_engine
from bridge_crm.db.schema import crm_pipeline_stages, metadata

DEFAULT_PIPELINE_STAGES = [
    {
        "stage_key": "prospecting",
        "display_name": "Prospecting",
        "display_order": 1,
        "default_probability": 10,
    },
    {
        "stage_key": "qualification",
        "display_name": "Qualification",
        "display_order": 2,
        "default_probability": 30,
    },
    {
        "stage_key": "proposal",
        "display_name": "Proposal",
        "display_order": 3,
        "default_probability": 50,
    },
    {
        "stage_key": "negotiation",
        "display_name": "Negotiation",
        "display_order": 4,
        "default_probability": 70,
    },
    {
        "stage_key": "closed_won",
        "display_name": "Closed Won",
        "display_order": 5,
        "default_probability": 100,
    },
    {
        "stage_key": "closed_lost",
        "display_name": "Closed Lost",
        "display_order": 6,
        "default_probability": 0,
    },
]


def initialize_database() -> None:
    engine = get_engine()
    metadata.create_all(engine)

    with engine.begin() as connection:
        for stage in DEFAULT_PIPELINE_STAGES:
            statement = insert(crm_pipeline_stages).values(**stage)
            statement = statement.on_conflict_do_nothing(
                index_elements=[crm_pipeline_stages.c.stage_key]
            )
            connection.execute(statement)


def get_pipeline_stages() -> list[dict]:
    with get_engine().connect() as connection:
        rows = connection.execute(
            select(crm_pipeline_stages).order_by(crm_pipeline_stages.c.display_order)
        )
        return [dict(row._mapping) for row in rows]
