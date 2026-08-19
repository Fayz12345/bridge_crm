#!/usr/bin/env python3
"""Start Bridge CRM locally with an embedded PostgreSQL server (no Docker/sudo)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PGDATA_DIR = PROJECT_ROOT / "data" / "pgdata"
DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_NAME = "Local Admin"
DEFAULT_ADMIN_PASSWORD = "local-admin-pass"


def _configure_environment(pg_host: str) -> None:
    os.environ.setdefault(
        "SECRET_KEY",
        "local-dev-secret-change-before-production-use-only",
    )
    os.environ.setdefault("CRM_DB_PASSWORD", "local-dev-password")
    os.environ.setdefault("CRM_DB_USER", "bridge_crm")
    os.environ.setdefault("CRM_DB_NAME", "bridge_crm")
    os.environ.setdefault("CRM_DB_PORT", "5432")
    os.environ["CRM_DB_HOST"] = pg_host
    os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
    os.environ.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    os.environ.setdefault(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000",
    )
    os.environ.setdefault(
        "LEAD_FORM_ALLOWED_PARENTS",
        "http://127.0.0.1:5000,http://localhost:5000",
    )


def _ensure_pgserver() -> str:
    try:
        import pgserver
    except ImportError as exc:
        raise SystemExit(
            "pgserver is required for local runs. Install with:\n"
            "  .venv/bin/pip install pgserver"
        ) from exc

    PGDATA_DIR.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(PGDATA_DIR))
    pg_host = str(PGDATA_DIR)

    try:
        server.psql(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bridge_crm') THEN "
            "CREATE ROLE bridge_crm LOGIN PASSWORD 'local-dev-password'; "
            "END IF; END $$;"
        )
        exists = server.psql(
            "SELECT 1 FROM pg_database WHERE datname = 'bridge_crm';"
        )
        if "1 row" not in exists:
            server.psql("CREATE DATABASE bridge_crm OWNER bridge_crm;")
    except Exception:  # noqa: BLE001,S110
        # Role/database may already exist from a prior run.
        pass

    return pg_host


def _bootstrap_schema() -> None:
    from bridge_crm.config import get_settings

    get_settings.cache_clear()
    from bridge_crm.db.bootstrap import initialize_database

    initialize_database()


def _seed_admin_if_needed(email: str, full_name: str, password: str) -> None:
    from sqlalchemy import func, select

    from bridge_crm.crm.auth.queries import create_user
    from bridge_crm.db.engine import get_connection
    from bridge_crm.db.schema import crm_users

    with get_connection() as connection:
        count = connection.execute(select(func.count()).select_from(crm_users)).scalar_one()

    if count:
        return

    create_user(email=email, password=password, full_name=full_name, role="admin")
    print(f"Seeded admin user: {email.lower()} / {password}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bridge CRM locally")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-debug", action="store_true")
    parser.add_argument("--admin-email", default=DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--admin-name", default=DEFAULT_ADMIN_NAME)
    parser.add_argument("--admin-password", default=DEFAULT_ADMIN_PASSWORD)
    args = parser.parse_args()

    if len(args.admin_password) < 12:
        raise SystemExit("Admin password must be at least 12 characters.")

    parent = PROJECT_ROOT.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))

    pg_host = _ensure_pgserver()
    _configure_environment(pg_host)
    _bootstrap_schema()
    _seed_admin_if_needed(args.admin_email, args.admin_name, args.admin_password)

    from bridge_crm.app import create_app

    app = create_app()
    print()
    print("Bridge CRM is running locally")
    print(f"  URL:   http://{args.host}:{args.port}/")
    print(f"  Login: {args.admin_email.lower()} / {args.admin_password}")
    print(f"  DB:    PostgreSQL socket at {pg_host}")
    print("Press Ctrl+C to stop.")
    print()
    app.run(host=args.host, port=args.port, debug=not args.no_debug, use_reloader=False)


if __name__ == "__main__":
    main()
