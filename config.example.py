# Flask
CRM_APP_NAME = "Bridge CRM"
SECRET_KEY = "replace-with-a-random-64-char-secret"
SESSION_COOKIE_NAME = "bridge_crm_session"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
LOG_LEVEL = "INFO"

# PostgreSQL
CRM_DB_HOST = "127.0.0.1"
CRM_DB_PORT = 5432
CRM_DB_NAME = "bridge_crm"
CRM_DB_USER = "bridge_crm"
CRM_DB_PASSWORD = "replace-me"

# Remote ERP MySQL (read-only)
ERP_DB_HOST = "your-erp-ec2-ip"
ERP_DB_PORT = 3306
ERP_DB_NAME = "gadgetkg_bwqa_main"
ERP_DB_USER = "crm_reader"
ERP_DB_PASSWORD = "replace-me"

# Outlook SMTP
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = "crm@yourdomain.com"
SMTP_PASSWORD = "replace-me"

# Public lead-form allowlist
CORS_ALLOWED_ORIGINS = "https://www.yourdomain.com,https://forms.yourdomain.com"

# Auth controls
LOGIN_RATE_LIMIT_COUNT = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 900
