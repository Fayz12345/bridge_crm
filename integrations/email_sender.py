import smtplib
from email.message import EmailMessage

from bridge_crm.config import get_settings


def smtp_configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_user and settings.smtp_password)


def send_email(to_address: str, subject: str, body_text: str, cc_address: str | None = None) -> None:
    settings = get_settings()
    if not smtp_configured():
        raise RuntimeError("SMTP credentials are not configured.")

    message = EmailMessage()
    message["From"] = settings.smtp_user
    message["To"] = to_address
    if cc_address:
        message["Cc"] = cc_address
    message["Subject"] = subject
    message.set_content(body_text)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
