"""Matching and write logic for the contact CSV import."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select

from bridge_crm.crm.accounts.queries import (
    create_account,
    create_contact_for_account,
    update_contact_for_account,
)
from bridge_crm.crm.activities.queries import log_activity
from bridge_crm.crm.imports.csv_parser import ACCOUNT_FIELDS, ParsedRow
from bridge_crm.crm.segments.queries import replace_account_tags
from bridge_crm.db.engine import get_connection
from bridge_crm.db.schema import crm_accounts, crm_contacts

logger = logging.getLogger(__name__)


@dataclass
class RowPlan:
    """What the import will do with one parsed row."""

    row: ParsedRow
    account_action: str = "create"  # create | reuse
    account_id: int | None = None
    account_name: str = ""
    contact_action: str = "create"  # create | update
    contact_id: int | None = None

    @property
    def creates_account(self) -> bool:
        return self.account_action == "create"


@dataclass
class ImportOutcome:
    accounts_created: int = 0
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
        self._accounts = _lookup_accounts(rows)
        self._contacts = _lookup_contacts(set(self._accounts.values()))

    def find_account(self, row: ParsedRow) -> int | None:
        for key in (_erp_key(row.account.get("erp_client_id")), row.company_key):
            if key and key in self._accounts:
                return self._accounts[key]
        return None

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

        number = row.contact.get("whatsapp_number") or row.contact.get("phone")
        if number and f"num:{number}" in index:
            return index[f"num:{number}"]
        return None


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

            contact_id = resolver.find_contact(account_id, row)
            payload = {**row.contact, "account_id": account_id}
            if contact_id is None:
                contact_id = create_contact_for_account(payload)
                outcome.contacts_created += 1
            else:
                update_contact_for_account(account_id, contact_id, payload)
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


def _lookup_accounts(rows: list[ParsedRow]) -> dict[str, int]:
    """Map company-name keys and ERP keys to existing account ids in one query."""
    names = {row.account["company_name"] for row in rows if row.account.get("company_name")}
    erp_ids = {
        row.account["erp_client_id"].strip()
        for row in rows
        if (row.account.get("erp_client_id") or "").strip()
    }
    if not names and not erp_ids:
        return {}

    conditions = []
    if names:
        conditions.append(
            func.lower(crm_accounts.c.company_name).in_([name.casefold() for name in names])
        )
    if erp_ids:
        conditions.append(crm_accounts.c.erp_client_id.in_(list(erp_ids)))

    statement = (
        select(crm_accounts.c.id, crm_accounts.c.company_name, crm_accounts.c.erp_client_id)
        .where(or_(*conditions))
        .order_by(crm_accounts.c.id)
    )
    with get_connection() as connection:
        found = connection.execute(statement).mappings().all()

    lookup: dict[str, int] = {}
    for record in found:
        account_id = int(record["id"])
        # setdefault keeps the lowest id when two accounts share a name.
        lookup.setdefault((record["company_name"] or "").casefold(), account_id)
        erp_key = _erp_key(record["erp_client_id"])
        if erp_key:
            lookup.setdefault(erp_key, account_id)
    return lookup


def _lookup_contacts(account_ids: set[int]) -> dict[int, dict[str, int]]:
    """Index the existing contacts of the given accounts by email and number."""
    ids = {account_id for account_id in account_ids if account_id is not None}
    if not ids:
        return {}

    statement = select(
        crm_contacts.c.id,
        crm_contacts.c.account_id,
        crm_contacts.c.email,
        crm_contacts.c.whatsapp_number,
        crm_contacts.c.phone,
    ).where(crm_contacts.c.account_id.in_(list(ids))).order_by(crm_contacts.c.id)

    with get_connection() as connection:
        found = connection.execute(statement).mappings().all()

    index: dict[int, dict[str, int]] = {}
    for record in found:
        contact_id = int(record["id"])
        bucket = index.setdefault(int(record["account_id"]), {})
        if record["email"]:
            bucket.setdefault(f"email:{record['email'].casefold()}", contact_id)
        for number in (record["whatsapp_number"], record["phone"]):
            if number:
                bucket.setdefault(f"num:{number}", contact_id)
    return index
