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
    company_name: str
    company_address: str
    company_phone: str
    company_email: str
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
    email_provider: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    m365_tenant_id: str
    m365_client_id: str
    m365_client_secret: str
    m365_sender: str
    cors_allowed_origins: list[str]
    lead_form_allowed_parents: list[str]
    session_cookie_secure: bool
    session_cookie_samesite: str
    session_cookie_name: str
    login_rate_limit_count: int
    login_rate_limit_window_seconds: int
    document_storage_dir: str
    quote_valid_days: int
    sales_order_payment_terms_days: int
    sales_order_payment_terms_text: str
    document_terms_text: str
    document_footer_text: str
    document_tax_rate: float
    log_level: str
    whatsapp_provider: str
    whatsapp_access_token: str
    whatsapp_phone_number_id: str
    whatsapp_business_account_id: str
    whatsapp_api_version: str
    whatsapp_default_template: str
    whatsapp_default_template_language: str
    whatsapp_webhook_verify_token: str
    wati_api_endpoint: str
    wati_access_token: str
    wati_channel_number: str
    wati_template_param_names: str
    wati_webhook_secret: str

    def to_flask_config(self) -> dict[str, object]:
        return {
            "APP_NAME": self.app_name,
            "COMPANY_NAME": self.company_name,
            "COMPANY_ADDRESS": self.company_address,
            "COMPANY_PHONE": self.company_phone,
            "COMPANY_EMAIL": self.company_email,
            "SECRET_KEY": self.secret_key,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_NAME": self.session_cookie_name,
            "SESSION_COOKIE_SECURE": self.session_cookie_secure,
            "SESSION_COOKIE_SAMESITE": self.session_cookie_samesite,
            "WTF_CSRF_TIME_LIMIT": 1800,
            "CORS_ALLOWED_ORIGINS": self.cors_allowed_origins,
            "LEAD_FORM_ALLOWED_PARENTS": self.lead_form_allowed_parents,
            "LOGIN_RATE_LIMIT_COUNT": self.login_rate_limit_count,
            "LOGIN_RATE_LIMIT_WINDOW_SECONDS": self.login_rate_limit_window_seconds,
            "DOCUMENT_STORAGE_DIR": self.document_storage_dir,
            "QUOTE_VALID_DAYS": self.quote_valid_days,
            "SALES_ORDER_PAYMENT_TERMS_DAYS": self.sales_order_payment_terms_days,
            "SALES_ORDER_PAYMENT_TERMS_TEXT": self.sales_order_payment_terms_text,
            "DOCUMENT_TERMS_TEXT": self.document_terms_text,
            "DOCUMENT_FOOTER_TEXT": self.document_footer_text,
            "DOCUMENT_TAX_RATE": self.document_tax_rate,
            "LOG_LEVEL": self.log_level,
            "WHATSAPP_PROVIDER": self.whatsapp_provider,
            "WHATSAPP_ACCESS_TOKEN": self.whatsapp_access_token,
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
            "WHATSAPP_BUSINESS_ACCOUNT_ID": self.whatsapp_business_account_id,
            "WHATSAPP_API_VERSION": self.whatsapp_api_version,
            "WHATSAPP_DEFAULT_TEMPLATE": self.whatsapp_default_template,
            "WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE": self.whatsapp_default_template_language,
            "WHATSAPP_WEBHOOK_VERIFY_TOKEN": self.whatsapp_webhook_verify_token,
            "WATI_API_ENDPOINT": self.wati_api_endpoint,
            "WATI_ACCESS_TOKEN": self.wati_access_token,
            "WATI_CHANNEL_NUMBER": self.wati_channel_number,
            "WATI_TEMPLATE_PARAM_NAMES": self.wati_template_param_names,
            "WATI_WEBHOOK_SECRET": self.wati_webhook_secret,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("CRM_APP_NAME", "Bridge CRM"),
        secret_key=os.environ["SECRET_KEY"],
        company_name=os.getenv("COMPANY_NAME", "Bridge Wireless"),
        company_address=os.getenv(
            "COMPANY_ADDRESS",
            "Bridge Wireless, Toronto, ON, Canada",
        ),
        company_phone=os.getenv("COMPANY_PHONE", ""),
        company_email=os.getenv("COMPANY_EMAIL", ""),
        crm_db_host=os.getenv("CRM_DB_HOST", "127.0.0.1"),
        crm_db_port=int(os.getenv("CRM_DB_PORT", "5432")),
        crm_db_name=os.getenv("CRM_DB_NAME", "bridge_crm"),
        crm_db_user=os.getenv("CRM_DB_USER", "bridge_crm"),
        crm_db_password=os.environ["CRM_DB_PASSWORD"],
        erp_db_host=os.getenv("ERP_DB_HOST", ""),
        erp_db_port=int(os.getenv("ERP_DB_PORT", "3306")),
        erp_db_name=os.getenv("ERP_DB_NAME", "gadgetkg_bwqa_main"),
        erp_db_user=os.getenv("ERP_DB_USER", ""),
        erp_db_password=os.getenv("ERP_DB_PASSWORD", ""),
        email_provider=os.getenv("EMAIL_PROVIDER", "smtp").strip().lower(),
        smtp_host=os.getenv("SMTP_HOST", "smtp.office365.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        m365_tenant_id=os.getenv("M365_TENANT_ID", ""),
        m365_client_id=os.getenv("M365_CLIENT_ID", ""),
        m365_client_secret=os.getenv("M365_CLIENT_SECRET", ""),
        m365_sender=os.getenv("M365_SENDER", ""),
        cors_allowed_origins=_list_env("CORS_ALLOWED_ORIGINS"),
        lead_form_allowed_parents=_list_env("LEAD_FORM_ALLOWED_PARENTS")
        or ["https://bridge-wireless.com", "https://www.bridge-wireless.com"],
        session_cookie_secure=_bool_env("SESSION_COOKIE_SECURE", True),
        session_cookie_samesite=os.getenv("SESSION_COOKIE_SAMESITE", "Strict"),
        session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "bridge_crm_session"),
        login_rate_limit_count=int(os.getenv("LOGIN_RATE_LIMIT_COUNT", "5")),
        login_rate_limit_window_seconds=int(
            os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")
        ),
        document_storage_dir=os.getenv(
            "DOCUMENT_STORAGE_DIR", str(BASE_DIR / "data" / "documents")
        ),
        quote_valid_days=int(os.getenv("QUOTE_VALID_DAYS", "30")),
        sales_order_payment_terms_days=int(
            os.getenv("SALES_ORDER_PAYMENT_TERMS_DAYS")
            or os.getenv("INVOICE_PAYMENT_TERMS_DAYS", "30")
        ),
        sales_order_payment_terms_text=(
            os.getenv("SALES_ORDER_PAYMENT_TERMS_TEXT")
            or os.getenv("INVOICE_PAYMENT_TERMS_TEXT", "Net 30")
        ),
        document_terms_text=os.getenv(
            "DOCUMENT_TERMS_TEXT",
            "Prices are valid for the stated period and subject to product availability.",
        ),
        document_footer_text=os.getenv(
            "DOCUMENT_FOOTER_TEXT", "Thank you for your business."
        ),
        document_tax_rate=float(os.getenv("DOCUMENT_TAX_RATE", "0")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        whatsapp_provider=os.getenv("WHATSAPP_PROVIDER", "wati").strip().lower(),
        whatsapp_access_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
        whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
        whatsapp_business_account_id=os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
        whatsapp_api_version=os.getenv("WHATSAPP_API_VERSION", "v21.0"),
        whatsapp_default_template=os.getenv("WHATSAPP_DEFAULT_TEMPLATE", ""),
        whatsapp_default_template_language=os.getenv(
            "WHATSAPP_DEFAULT_TEMPLATE_LANGUAGE", "en_US"
        ),
        whatsapp_webhook_verify_token=os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", ""),
        wati_api_endpoint=os.getenv("WATI_API_ENDPOINT", ""),
        wati_access_token=os.getenv("WATI_ACCESS_TOKEN", ""),
        wati_channel_number=os.getenv("WATI_CHANNEL_NUMBER", ""),
        wati_template_param_names=os.getenv(
            "WATI_TEMPLATE_PARAM_NAMES", "name,rep_name,message"
        ),
        wati_webhook_secret=os.getenv("WATI_WEBHOOK_SECRET", ""),
    )
