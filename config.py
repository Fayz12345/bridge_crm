import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _list_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    secret_key: str
    crm_db_host: str
    crm_db_port: int
    crm_db_name: str
    crm_db_user: str
    crm_db_password: str
    erp_db_host: str
    erp_db_port: int
    erp_db_name: str
    erp_db_user: str
    erp_db_password: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    cors_allowed_origins: list[str]
    session_cookie_secure: bool
    session_cookie_samesite: str
    session_cookie_name: str
    login_rate_limit_count: int
    login_rate_limit_window_seconds: int
    log_level: str

    def to_flask_config(self) -> dict[str, object]:
        return {
            "APP_NAME": self.app_name,
            "SECRET_KEY": self.secret_key,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_NAME": self.session_cookie_name,
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
            "WTF_CSRF_TIME_LIMIT": 3600,
            "CORS_ALLOWED_ORIGINS": self.cors_allowed_origins,
            "LOGIN_RATE_LIMIT_COUNT": self.login_rate_limit_count,
            "LOGIN_RATE_LIMIT_WINDOW_SECONDS": self.login_rate_limit_window_seconds,
            "LOG_LEVEL": self.log_level,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("CRM_APP_NAME", "Bridge CRM"),
        secret_key=os.getenv("SECRET_KEY", "change-me-in-production"),
        crm_db_host=os.getenv("CRM_DB_HOST", "127.0.0.1"),
        crm_db_port=int(os.getenv("CRM_DB_PORT", "5432")),
        crm_db_name=os.getenv("CRM_DB_NAME", "bridge_crm"),
        crm_db_user=os.getenv("CRM_DB_USER", "bridge_crm"),
        crm_db_password=os.getenv("CRM_DB_PASSWORD", "bridge_crm"),
        erp_db_host=os.getenv("ERP_DB_HOST", ""),
        erp_db_port=int(os.getenv("ERP_DB_PORT", "3306")),
        erp_db_name=os.getenv("ERP_DB_NAME", "gadgetkg_bwqa_main"),
        erp_db_user=os.getenv("ERP_DB_USER", ""),
        erp_db_password=os.getenv("ERP_DB_PASSWORD", ""),
        smtp_host=os.getenv("SMTP_HOST", "smtp.office365.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        cors_allowed_origins=_list_env("CORS_ALLOWED_ORIGINS"),
        session_cookie_secure=_bool_env("SESSION_COOKIE_SECURE", False),
        session_cookie_samesite=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "bridge_crm_session"),
        login_rate_limit_count=int(os.getenv("LOGIN_RATE_LIMIT_COUNT", "5")),
        login_rate_limit_window_seconds=int(
            os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
