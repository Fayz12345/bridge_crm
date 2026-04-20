import base64
import json
import mimetypes
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path
from urllib import error, parse, request

from bridge_crm.config import get_settings

_GRAPH_TOKEN_CACHE: dict[str, float | str] = {"access_token": "", "expires_at": 0.0}


def smtp_configured() -> bool:
    settings = get_settings()
    if settings.email_provider == "graph":
        return bool(
            settings.m365_tenant_id
            and settings.m365_client_id
            and settings.m365_client_secret
            and settings.m365_sender
        )
    return bool(settings.smtp_user and settings.smtp_password)


def _smtp_send(
    to_address: str,
    subject: str,
    body_text: str,
    cc_address: str | None = None,
    attachments: list[dict] | None = None,
) -> None:
    settings = get_settings()
    if not (settings.smtp_user and settings.smtp_password):
        raise RuntimeError("SMTP credentials are not configured.")

    message = EmailMessage()
    message["From"] = settings.smtp_user
    message["To"] = to_address
    if cc_address:
        message["Cc"] = cc_address
    message["Subject"] = subject
    message.set_content(body_text)
    for attachment in attachments or []:
        file_path = Path(attachment["filepath"])
        data = file_path.read_bytes()
        message.add_attachment(
            data,
            maintype="application",
            subtype="pdf",
            filename=attachment["filename"],
        )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def _graph_access_token() -> str:
    settings = get_settings()
    now = time.time()
    cached_token = str(_GRAPH_TOKEN_CACHE["access_token"])
    expires_at = float(_GRAPH_TOKEN_CACHE["expires_at"])
    if cached_token and expires_at - 60 > now:
        return cached_token

    token_url = (
        f"https://login.microsoftonline.com/{settings.m365_tenant_id}/oauth2/v2.0/token"
    )
    payload = parse.urlencode(
        {
            "client_id": settings.m365_client_id,
            "client_secret": settings.m365_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    token_request = request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with request.urlopen(token_request, timeout=30) as response:
            token_data = json.load(response)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph token request failed: {body}") from exc

    access_token = token_data.get("access_token")
    expires_in = int(token_data.get("expires_in", 0) or 0)
    if not access_token:
        raise RuntimeError("Graph token response did not include an access token.")

    _GRAPH_TOKEN_CACHE["access_token"] = access_token
    _GRAPH_TOKEN_CACHE["expires_at"] = now + max(expires_in, 300)
    return str(access_token)


def _attachment_payload(attachment: dict) -> dict[str, str]:
    file_path = Path(attachment["filepath"])
    data = file_path.read_bytes()
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment["filename"],
        "contentType": content_type,
        "contentBytes": base64.b64encode(data).decode("ascii"),
    }


def _graph_send(
    to_address: str,
    subject: str,
    body_text: str,
    cc_address: str | None = None,
    attachments: list[dict] | None = None,
) -> None:
    settings = get_settings()
    if not smtp_configured():
        raise RuntimeError("Microsoft 365 Graph credentials are not configured.")

    message = {
        "subject": subject,
        "body": {
            "contentType": "Text",
            "content": body_text,
        },
        "toRecipients": [{"emailAddress": {"address": to_address}}],
    }
    if cc_address:
        message["ccRecipients"] = [{"emailAddress": {"address": cc_address}}]
    if attachments:
        message["attachments"] = [_attachment_payload(attachment) for attachment in attachments]

    graph_request = request.Request(
        (
            "https://graph.microsoft.com/v1.0/users/"
            f"{parse.quote(settings.m365_sender)}/sendMail"
        ),
        data=json.dumps({"message": message, "saveToSentItems": True}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_graph_access_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(graph_request, timeout=30):
            return
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph sendMail failed: {body}") from exc


def send_email(
    to_address: str,
    subject: str,
    body_text: str,
    cc_address: str | None = None,
    attachments: list[dict] | None = None,
) -> None:
    settings = get_settings()
    if not smtp_configured():
        raise RuntimeError(f"{settings.email_provider} email credentials are not configured.")

    if settings.email_provider == "graph":
        _graph_send(to_address, subject, body_text, cc_address, attachments)
        return

    _smtp_send(to_address, subject, body_text, cc_address, attachments)
