"""Pushes CRM contacts into the Wati address book.

Wati's addContact upserts on the WhatsApp number, so one call covers both
creating a contact there and refreshing one that already exists. Every contact
carries its CRM ids back as custom attributes, which is what lets an inbound
Wati webhook be matched to the right record later.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_accounts, crm_contacts
from bridge_crm.integrations.wati import contact_params
from bridge_crm.integrations.whatsapp import (
    WhatsAppAPIError,
    add_contact,
    contacts_supported,
    normalize_whatsapp_number,
)

logger = logging.getLogger(__name__)

# Wati rate-limits writes; a short pause keeps a large migration under the cap.
THROTTLE_SECONDS = 0.15
# Sized so one run finishes inside a normal request timeout. A larger list is
# synced by running the batch again; the page reports what is left.
MAX_PER_RUN = 200

STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class SyncOutcome:
    synced: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[dict] = field(default_factory=list)
    stopped_early: bool = False

    @property
    def attempted(self) -> int:
        return self.synced + self.failed


def sync_contacts(contact_ids: list[int], *, throttle: float = THROTTLE_SECONDS) -> SyncOutcome:
    """Push the given contacts to Wati, one at a time, recording each result."""
    outcome = SyncOutcome()
    if not contact_ids:
        return outcome
    if not contacts_supported():
        logger.info("Wati contact sync skipped: provider not configured")
        outcome.skipped = len(contact_ids)
        return outcome

    records = _load_contacts(contact_ids)
    for index, record in enumerate(records):
        number = normalize_whatsapp_number(record["whatsapp_number"])
        if not number:
            _mark(record["id"], STATUS_SKIPPED, "No WhatsApp number.")
            outcome.skipped += 1
            continue

        try:
            add_contact(
                number,
                name=_display_name(record),
                custom_params=_attributes_for(record),
            )
            _mark(record["id"], STATUS_SYNCED, None)
            outcome.synced += 1
        except WhatsAppAPIError as exc:
            message = str(exc)[:300]
            _mark(record["id"], STATUS_FAILED, message)
            outcome.failed += 1
            outcome.failures.append(
                {
                    "contact_id": int(record["id"]),
                    "display_name": _display_name(record),
                    "whatsapp_number": number,
                    "error": message,
                }
            )
            logger.warning("Wati contact sync failed for contact %s: %s", record["id"], message)

        if throttle and index + 1 < len(records):
            time.sleep(throttle)

    return outcome


def sync_one_contact(contact_id: int) -> SyncOutcome:
    """Best-effort push for a single contact after a manual save.

    Never raises: a Wati outage must not fail the user's save. The caller reads
    the outcome to tell a real failure apart from Wati simply not being set up.
    """
    try:
        return sync_contacts([contact_id], throttle=0)
    except Exception as exc:
        logger.exception("Wati contact sync raised for contact %s", contact_id)
        return SyncOutcome(failed=1, failures=[{"contact_id": contact_id, "error": str(exc)[:300]}])


def list_unsynced_contacts(limit: int = MAX_PER_RUN) -> list[dict]:
    """Contacts that have a WhatsApp number but are not currently synced."""
    statement = (
        _contact_select()
        .where(
            crm_contacts.c.whatsapp_number.is_not(None),
            crm_contacts.c.whatsapp_number != "",
            func.coalesce(crm_contacts.c.wati_sync_status, "") != STATUS_SYNCED,
        )
        .order_by(crm_contacts.c.id)
        .limit(limit)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def sync_status_counts() -> dict[str, int]:
    """Counts for the sync dashboard, over contacts that have a WhatsApp number."""
    statement = (
        select(
            func.coalesce(crm_contacts.c.wati_sync_status, "pending").label("status"),
            func.count().label("total"),
        )
        .where(
            crm_contacts.c.whatsapp_number.is_not(None),
            crm_contacts.c.whatsapp_number != "",
        )
        .group_by(func.coalesce(crm_contacts.c.wati_sync_status, "pending"))
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()

    counts = {"pending": 0, STATUS_SYNCED: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 0}
    for row in rows:
        counts[row["status"]] = int(row["total"])
    counts["total"] = sum(
        counts[key] for key in ("pending", STATUS_SYNCED, STATUS_FAILED, STATUS_SKIPPED)
    )
    return counts


def count_contacts_without_whatsapp() -> int:
    statement = select(func.count()).select_from(crm_contacts).where(
        (crm_contacts.c.whatsapp_number.is_(None)) | (crm_contacts.c.whatsapp_number == "")
    )
    with get_connection() as connection:
        return int(connection.execute(statement).scalar_one())


def _contact_select():
    return select(
        crm_contacts.c.id,
        crm_contacts.c.first_name,
        crm_contacts.c.last_name,
        crm_contacts.c.email,
        crm_contacts.c.job_title,
        crm_contacts.c.whatsapp_number,
        crm_contacts.c.wati_sync_status,
        crm_contacts.c.wati_synced_at,
        crm_contacts.c.wati_sync_error,
        crm_contacts.c.account_id,
        crm_accounts.c.company_name,
        crm_accounts.c.erp_client_id,
    ).select_from(crm_contacts.join(crm_accounts, crm_contacts.c.account_id == crm_accounts.c.id))


def _load_contacts(contact_ids: list[int]) -> list[dict]:
    statement = (
        _contact_select()
        .where(crm_contacts.c.id.in_(list(contact_ids)))
        .order_by(crm_contacts.c.id)
    )
    with get_connection() as connection:
        rows = connection.execute(statement).mappings().all()
    return [dict(row) for row in rows]


def _display_name(record: dict) -> str:
    name = f"{record.get('first_name') or ''} {record.get('last_name') or ''}".strip()
    return name or record.get("company_name") or "Contact"


def _attributes_for(record: dict) -> list[dict[str, str]]:
    return contact_params(
        {
            "crm_contact_id": str(record["id"]),
            "crm_account_id": str(record["account_id"]),
            "company_name": record.get("company_name"),
            "erp_client_id": record.get("erp_client_id"),
            "email": record.get("email"),
            "job_title": record.get("job_title"),
        }
    )


def _mark(contact_id: int, status: str, error: str | None) -> None:
    statement = (
        update(crm_contacts)
        .where(crm_contacts.c.id == contact_id)
        .values(
            wati_sync_status=status,
            wati_synced_at=datetime.now(timezone.utc) if status == STATUS_SYNCED else None,
            wati_sync_error=error,
        )
    )
    with get_connection() as connection:
        connection.execute(statement)
