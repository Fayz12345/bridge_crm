"""Matching and write logic for the contact CSV import."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update

from bridge_crm.crm.accounts.queries import (
    create_account,
    create_contact_for_account,
    update_contact_for_account,
)
from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.imports.csv_parser import ACCOUNT_FIELDS, ParsedRow
from bridge_crm.crm.segments.queries import get_account_tag_names, replace_account_tags
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_accounts, crm_contacts
from bridge_crm.integrations.wati import normalize_whatsapp_number

logger = logging.getLogger(__name__)

# Contact columns the import is allowed to write.
CONTACT_WRITE_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "phone_prefix",
    "whatsapp_number",
    "job_title",
)

# Account columns the import may fill in on an account that already exists.
# Only ever written when the stored value is blank, never over existing data.
ACCOUNT_BACKFILL_FIELDS = tuple(name for name in ACCOUNT_FIELDS if name != "company_name")


@dataclass
class RowPlan:
    """What the import will do with one parsed row."""

    row: ParsedRow
    account_action: str = "create"  # create | reuse
    account_id: int | None = None
    account_name: str = ""
    contact_action: str = "create"  # create | update
    contact_id: int | None = None
    backfill_fields: list[str] = field(default_factory=list)

    @property
    def creates_account(self) -> bool:
        return self.account_action == "create"


@dataclass
class ImportOutcome:
    accounts_created: int = 0
    accounts_backfilled: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    failures: list[dict] = field(default_factory=list)
    contact_ids: list[int] = field(default_factory=list)

    @property
    def total_written(self) -> int:
        return self.contacts_created + self.contacts_updated


class Resolver:
    """Resolves rows against existing records using two upfront queries.

    A per-row lookup would mean thousands of round trips on a real migration,
    so every candidate account and its contacts are loaded once and matched in
    memory. Accounts created during a run are registered as they are made.
    """

    def __init__(self, rows: list[ParsedRow]):
        self._accounts, self._account_rows = _lookup_accounts(rows)
        self._contacts, self._contact_rows = _lookup_contacts(set(self._accounts.values()))

    def find_account(self, row: ParsedRow) -> int | None:
        for key in (_erp_key(row.account.get("erp_client_id")), row.company_key):
            if key and key in self._accounts:
                return self._accounts[key]
        return None

    def account_record(self, account_id: int | None) -> dict | None:
        return self._account_rows.get(account_id) if account_id else None

    def remember_account(self, row: ParsedRow, account_id: int | None) -> None:
        """Record that this run has handled the row's company.

        `account_id` is None during preview, where nothing is written but later
        rows for the same company must still resolve to "reuse".
        """
        for key in (_erp_key(row.account.get("erp_client_id")), row.company_key):
            if key:
                self._accounts[key] = account_id

    def knows_account(self, row: ParsedRow) -> bool:
        return any(
            key in self._accounts
            for key in (_erp_key(row.account.get("erp_client_id")), row.company_key)
            if key
        )

    def find_contact(self, account_id: int | None, row: ParsedRow) -> int | None:
        """Find this person inside the account: email first, then WhatsApp/phone."""
        if account_id is None:
            return None
        index = self._contacts.get(account_id)
        if not index:
            return None

        email = row.contact.get("email")
        if email and f"email:{email.casefold()}" in index:
            return index[f"email:{email.casefold()}"]

        for raw_number in (row.contact.get("whatsapp_number"), row.contact.get("phone")):
            key = _number_key(raw_number)
            if key and key in index:
                return index[key]
        return None

    def contact_record(self, contact_id: int) -> dict:
        return self._contact_rows.get(contact_id, {})


def plan_import(rows: list[ParsedRow]) -> list[RowPlan]:
    """Resolve each valid row against existing records without writing anything.

    Rows are processed in file order so the first row for a new company is the
    one shown as creating it, and later rows for that company reuse it.
    """
    valid_rows = [row for row in rows if row.is_valid]
    if not valid_rows:
        return []

    resolver = Resolver(valid_rows)
    plans: list[RowPlan] = []

    for row in valid_rows:
        plan = RowPlan(row=row, account_name=row.account["company_name"])
        if resolver.knows_account(row):
            plan.account_action = "reuse"
            plan.account_id = resolver.find_account(row)
            plan.backfill_fields = sorted(
                _blank_account_fields(resolver.account_record(plan.account_id), row)
            )
            contact_id = resolver.find_contact(plan.account_id, row)
            if contact_id is not None:
                plan.contact_action = "update"
                plan.contact_id = contact_id
        else:
            resolver.remember_account(row, None)
        plans.append(plan)

    return plans


def commit_import(rows: list[ParsedRow], user_id: int) -> ImportOutcome:
    """Write the valid rows.

    Each row commits on its own so one bad row cannot roll back the rest of a
    large migration; failures are collected and reported per row.
    """
    outcome = ImportOutcome()
    valid_rows = [row for row in rows if row.is_valid]
    if not valid_rows:
        return outcome

    resolver = Resolver(valid_rows)

    for row in valid_rows:
        try:
            account_id = resolver.find_account(row)
            if account_id is None:
                account_id = _create_account_for_row(row, user_id)
                resolver.remember_account(row, account_id)
                outcome.accounts_created += 1
            elif _backfill_account(account_id, resolver.account_record(account_id), row):
                outcome.accounts_backfilled += 1

            contact_id = resolver.find_contact(account_id, row)
            if contact_id is None:
                contact_id = create_contact_for_account(
                    {**_contact_values(row), "account_id": account_id}
                )
                outcome.contacts_created += 1
            else:
                update_contact_for_account(
                    account_id,
                    contact_id,
                    _merged_contact_values(row, resolver.contact_record(contact_id), account_id),
                )
                outcome.contacts_updated += 1
            outcome.contact_ids.append(int(contact_id))
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the import
            logger.exception("Contact import failed on row %s", row.row_number)
            outcome.failures.append(
                {
                    "row_number": row.row_number,
                    "company_name": row.account.get("company_name") or "",
                    "display_name": row.display_name,
                    "error": str(exc)[:300],
                }
            )

    return outcome


def _contact_values(row: ParsedRow) -> dict:
    values = {name: row.contact.get(name) for name in CONTACT_WRITE_FIELDS}
    values["is_primary"] = bool(row.contact.get("is_primary"))
    return values


def _merged_contact_values(row: ParsedRow, existing: dict, account_id: int) -> dict:
    """Build the payload for updating a contact that already exists.

    `update_contact_for_account` writes every column it is given, so the stored
    values are the base and the file only overrides what it actually carries. A
    blank cell means "no data supplied", never "erase what the CRM has".
    """
    values = {name: existing.get(name) for name in CONTACT_WRITE_FIELDS}
    for name in CONTACT_WRITE_FIELDS:
        incoming = row.contact.get(name)
        if incoming not in (None, ""):
            values[name] = incoming

    # A bool cannot say "absent", so only honour it when the column exists.
    values["is_primary"] = (
        bool(row.contact.get("is_primary"))
        if "is_primary" in row.provided
        else bool(existing.get("is_primary"))
    )
    values["account_id"] = account_id
    return values


def _blank_account_fields(existing: dict | None, row: ParsedRow) -> set[str]:
    """Account columns the file can fill in because the CRM has nothing there."""
    if not existing:
        return set()
    return {
        name
        for name in ACCOUNT_BACKFILL_FIELDS
        if row.account.get(name) and not (existing.get(name) or "")
    }


def _backfill_account(account_id: int, existing: dict | None, row: ParsedRow) -> bool:
    """Fill blank columns on an account that already exists, and merge its tags.

    Existing values are never overwritten -- an import backfills gaps only.
    """
    changed = False
    fields = _blank_account_fields(existing, row)
    if fields:
        values = {name: row.account[name] for name in fields}
        values["updated_at"] = datetime.now(timezone.utc)
        with get_connection() as connection:
            connection.execute(
                update(crm_accounts).where(crm_accounts.c.id == account_id).values(**values)
            )
        if existing is not None:
            existing.update({name: row.account[name] for name in fields})
        changed = True

    if row.tags:
        current = get_account_tag_names(account_id)
        merged = list(current)
        seen = {name.casefold() for name in current}
        for name in row.tags:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                merged.append(name)
        if len(merged) != len(current):
            replace_account_tags(account_id, merged)
            changed = True

    return changed


def _create_account_for_row(row: ParsedRow, user_id: int) -> int:
    payload = {name: row.account.get(name) for name in ACCOUNT_FIELDS}
    payload["company_name"] = row.account["company_name"]
    payload["owner_id"] = user_id
    payload["created_by"] = user_id
    payload["custom_fields"] = {}
    account_id = create_account(payload)

    if row.tags:
        replace_account_tags(account_id, row.tags)

    log_activity(
        "account",
        account_id,
        "created",
        f"Account created from contact CSV import (row {row.row_number}).",
        user_id,
        {"source": "csv_import", "row_number": row.row_number},
    )
    return account_id


def _erp_key(erp_client_id: str | None) -> str | None:
    cleaned = (erp_client_id or "").strip()
    return f"erp:{cleaned.casefold()}" if cleaned else None


def _number_key(number: str | None) -> str | None:
    """Key a phone number by its digits so "+971 50 123 4567" and
    "971501234567" match: the CRM stores whatever was typed in, the CSV parser
    stores digits only."""
    normalized = normalize_whatsapp_number(number)
    return f"num:{normalized}" if normalized else None


def _lookup_accounts(rows: list[ParsedRow]) -> tuple[dict[str, int], dict[int, dict]]:
    """Map company-name keys and ERP keys to existing account ids in one query."""
    names = {row.account["company_name"] for row in rows if row.account.get("company_name")}
    erp_ids = {
        row.account["erp_client_id"].strip().casefold()
        for row in rows
        if (row.account.get("erp_client_id") or "").strip()
    }
    if not names and not erp_ids:
        return {}, {}

    conditions = []
    if names:
        conditions.append(
            func.lower(crm_accounts.c.company_name).in_([name.casefold() for name in names])
        )
    if erp_ids:
        # Matched case-insensitively to agree with the in-memory ERP key.
        conditions.append(func.lower(crm_accounts.c.erp_client_id).in_(list(erp_ids)))

    statement = select(crm_accounts).where(or_(*conditions)).order_by(crm_accounts.c.id)
    with get_connection() as connection:
        found = connection.execute(statement).mappings().all()

    lookup: dict[str, int] = {}
    records: dict[int, dict] = {}
    for record in found:
        account_id = int(record["id"])
        records[account_id] = dict(record)
        # setdefault keeps the lowest id when two accounts share a name.
        lookup.setdefault((record["company_name"] or "").casefold(), account_id)
        erp_key = _erp_key(record["erp_client_id"])
        if erp_key:
            lookup.setdefault(erp_key, account_id)
    return lookup, records


def _lookup_contacts(
    account_ids: set[int],
) -> tuple[dict[int, dict[str, int]], dict[int, dict]]:
    """Index the existing contacts of the given accounts by email and number."""
    ids = {account_id for account_id in account_ids if account_id is not None}
    if not ids:
        return {}, {}

    statement = (
        select(crm_contacts)
        .where(crm_contacts.c.account_id.in_(list(ids)))
        .order_by(crm_contacts.c.id)
    )
    with get_connection() as connection:
        found = connection.execute(statement).mappings().all()

    index: dict[int, dict[str, int]] = {}
    records: dict[int, dict] = {}
    for record in found:
        contact_id = int(record["id"])
        records[contact_id] = dict(record)
        bucket = index.setdefault(int(record["account_id"]), {})
        if record["email"]:
            bucket.setdefault(f"email:{record['email'].casefold()}", contact_id)
        for number in (record["whatsapp_number"], record["phone"]):
            key = _number_key(number)
            if key:
                bucket.setdefault(key, contact_id)
    return index, records
