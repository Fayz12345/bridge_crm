from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

from bridge_crm.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    url = URL.create(
        "postgresql+psycopg2",
        username=settings.crm_db_user,
        password=settings.crm_db_password,
        host=settings.crm_db_host,
        port=settings.crm_db_port,
        database=settings.crm_db_name,
    )
    return create_engine(url, future=True, pool_pre_ping=True)


@contextmanager
def get_connection():
    with get_engine().begin() as connection:
        yield connection
