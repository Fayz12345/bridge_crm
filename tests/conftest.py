import os
import sys
from pathlib import Path

import pytest

# Repo root is the `bridge_crm` package; parent must be on sys.path for imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_PARENT = _REPO_ROOT.parent
if str(_PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_PARENT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("CRM_DB_PASSWORD", "test_password")
os.environ.setdefault("CRM_DB_HOST", os.getenv("CRM_DB_HOST", "127.0.0.1"))
os.environ.setdefault("CRM_DB_PORT", os.getenv("CRM_DB_PORT", "5432"))
os.environ.setdefault("CRM_DB_NAME", os.getenv("CRM_DB_NAME", "bridge_crm_test"))
os.environ.setdefault("CRM_DB_USER", os.getenv("CRM_DB_USER", "test_user"))
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
os.environ.setdefault("SESSION_COOKIE_SAMESITE", "Lax")


@pytest.fixture(scope="session")
def app():
    from bridge_crm.app import create_app
    from bridge_crm.db.bootstrap import initialize_database

    application = create_app()
    with application.app_context():
        initialize_database()
    return application


@pytest.fixture
def client(app):
    return app.test_client()
