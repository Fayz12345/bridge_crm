"""Parsing and validation for the contact CSV import.

Kept free of database access so the row rules can be unit tested directly.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from bridge_crm.integrations.wati import normalize_whatsapp_number

MAX_ROWS = 5000
MAX_FILE_BYTES = 5 * 1024 * 1024

ACCOUNT_FIELDS = (
    "company_name",
    "erp_client_id",
    "website",
    "address_line_1",
    "address_line_2",
    "city",
    "state_province",
    "postal_code",
    "country",
    "industry",
    "notes",
)

CONTACT_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "phone_prefix",
    "whatsapp_number",
    "job_title",
    "is_primary",
)

REQUIRED_HEADERS = ("company_name", "first_name", "last_name")

# Column widths from db.schema; a value longer than this cannot be stored.
MAX_LENGTHS = {
    "company_name": 255,
    "erp_client_id": 11,
    "website": 255,
    "address_line_1": 255,
    "address_line_2": 255,
    "city": 120,
    "state_province": 120,
    "postal_code": 30,
    "country": 120,
    "industry": 120,
    "first_name": 120,
    "last_name": 120,
    "email": 255,
    "phone": 30,
    "phone_prefix": 8,
    "whatsapp_number": 30,
    "job_title": 120,
}

# Fields where an over-long value is a hard error rather than a silent truncation,
# because the value identifies the record.
STRICT_LENGTH_FIELDS = frozenset({"erp_client_id", "company_name", "first_name", "last_name", "email"})

_HEADER_ALIASES = {
    "company": "company_name",
    "company_name": "company_name",
    "account": "company_name",
    "account_name": "company_name",
    "organisation": "company_name",
    "organization": "company_name",
    "erp_client_id": "erp_client_id",
    "erp_id": "erp_client_id",
    "client_id": "erp_client_id",
    "first_name": "first_name",
    "firstname": "first_name",
    "given_name": "first_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "family_name": "last_name",
    "email": "email",
    "email_address": "email",
    "phone": "phone",
    "phone_number": "phone",
    "telephone": "phone",
    "mobile": "phone",
    "phone_prefix": "phone_prefix",
    "country_code": "phone_prefix",
    "dial_code": "phone_prefix",
    "whatsapp_number": "whatsapp_number",
    "whatsapp": "whatsapp_number",
    "wa_number": "whatsapp_number",
    "job_title": "job_title",
    "title": "job_title",
    "position": "job_title",
    "role": "job_title",
    "is_primary": "is_primary",
    "primary": "is_primary",
    "primary_contact": "is_primary",
    "industry": "industry",
    "sector": "industry",
    "website": "website",
    "web": "website",
    "url": "website",
    "address_line_1": "address_line_1",
    "address": "address_line_1",
    "address_1": "address_line_1",
    "street": "address_line_1",
    "address_line_2": "address_line_2",
    "address_2": "address_line_2",
    "city": "city",
    "town": "city",
    "state_province": "state_province",
    "state": "state_province",
    "province": "state_province",
    "region": "state_province",
    "postal_code": "postal_code",
    "postcode": "postal_code",
    "zip": "postal_code",
    "zip_code": "postal_code",
    "country": "country",
    "notes": "notes",
    "note": "notes",
    "comments": "notes",
    "tags": "tags",
    "tag": "tags",
}

_TRUE_VALUES = frozenset({"yes", "y", "true", "t", "1", "primary"})
_FALSE_VALUES = frozenset({"no", "n", "false", "f", "0", ""})

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ParsedRow:
    row_number: int
    account: dict = field(default_factory=dict)
    contact: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def company_key(self) -> str:
        return (self.account.get("company_name") or "").casefold()

    @property
    def contact_key(self) -> str:
        """Identity of the person within their company, for in-file duplicate checks."""
        email = (self.contact.get("email") or "").casefold()
        if email:
            return f"email:{email}"
        number = self.contact.get("whatsapp_number") or self.contact.get("phone") or ""
        if number:
            return f"phone:{number}"
        first = (self.contact.get("first_name") or "").casefold()
        last = (self.contact.get("last_name") or "").casefold()
        return f"name:{first} {last}"

    @property
    def display_name(self) -> str:
        name = f"{self.contact.get('first_name') or ''} {self.contact.get('last_name') or ''}".strip()
        return name or "(no name)"


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    recognized_headers: list[str] = field(default_factory=list)
    unknown_headers: list[str] = field(default_factory=list)
    missing_headers: list[str] = field(default_factory=list)
    file_errors: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def valid_rows(self) -> list[ParsedRow]:
        return [row for row in self.rows if row.is_valid]

    @property
    def error_rows(self) -> list[ParsedRow]:
        return [row for row in self.rows if not row.is_valid]

    @property
    def is_importable(self) -> bool:
        return not self.file_errors and not self.missing_headers and bool(self.valid_rows)

    @property
    def company_count(self) -> int:
        return len({row.company_key for row in self.valid_rows})


def normalize_header(value: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().casefold())
    return cleaned.strip("_")


def decode_csv_bytes(raw: bytes) -> tuple[str, str | None]:
    """Decode uploaded bytes, tolerating the BOM Excel writes. Returns (text, error)."""
    if len(raw) > MAX_FILE_BYTES:
        return "", f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return "", "Could not decode the file. Save it as UTF-8 CSV and try again."


def parse_contacts_csv(text: str) -> ParseResult:
    result = ParseResult()
    if not (text or "").strip():
        result.file_errors.append("The file is empty.")
        return result

    reader = csv.reader(io.StringIO(text))
    try:
        raw_headers = next(reader)
    except StopIteration:
        result.file_errors.append("The file is empty.")
        return result

    header_map: dict[int, str] = {}
    for index, raw_header in enumerate(raw_headers):
        normalized = normalize_header(raw_header)
        if not normalized:
            continue
        canonical = _HEADER_ALIASES.get(normalized)
        if canonical:
            # First column wins if a header is repeated.
            if canonical not in header_map.values():
                header_map[index] = canonical
        else:
            result.unknown_headers.append(raw_header.strip())

    result.recognized_headers = sorted(set(header_map.values()))
    result.missing_headers = [name for name in REQUIRED_HEADERS if name not in header_map.values()]
    if result.missing_headers:
        return result

    seen_keys: dict[tuple[str, str], int] = {}
    for offset, raw_row in enumerate(reader):
        if len(result.rows) >= MAX_ROWS:
            result.truncated = True
            break
        if not any((cell or "").strip() for cell in raw_row):
            continue

        row_number = offset + 2  # header is row 1
        values = {
            canonical: (raw_row[index] if index < len(raw_row) else "")
            for index, canonical in header_map.items()
        }
        parsed = _build_row(row_number, values)

        if parsed.is_valid:
            key = (parsed.company_key, parsed.contact_key)
            first_seen = seen_keys.get(key)
            if first_seen:
                parsed.errors.append(
                    f"Duplicate of row {first_seen} in this file (same company and contact)."
                )
            else:
                seen_keys[key] = row_number

        result.rows.append(parsed)

    if not result.rows:
        result.file_errors.append("The file has a header row but no data rows.")
    return result


def _build_row(row_number: int, values: dict[str, str]) -> ParsedRow:
    row = ParsedRow(row_number=row_number)

    for name in ACCOUNT_FIELDS:
        row.account[name] = _clean_field(name, values.get(name), row)
    for name in CONTACT_FIELDS:
        if name == "is_primary":
            continue
        row.contact[name] = _clean_field(name, values.get(name), row)

    row.contact["is_primary"] = _parse_bool(values.get("is_primary"), row)
    row.tags = _parse_tags(values.get("tags"))

    if not row.account["company_name"]:
        row.errors.append("Company name is required.")
    if not row.contact["first_name"]:
        row.errors.append("First name is required.")
    if not row.contact["last_name"]:
        row.errors.append("Last name is required.")

    email = row.contact["email"]
    if email:
        if _EMAIL_PATTERN.match(email):
            row.contact["email"] = email.casefold()
        else:
            row.errors.append(f'"{email}" is not a valid email address.')
            row.contact["email"] = None

    whatsapp_raw = row.contact["whatsapp_number"]
    phone_raw = row.contact["phone"]
    whatsapp = normalize_whatsapp_number(whatsapp_raw)
    if whatsapp_raw and not whatsapp:
        row.warnings.append(
            f'WhatsApp number "{whatsapp_raw}" is too short to be valid and was dropped.'
        )
    if not whatsapp and phone_raw:
        derived = normalize_whatsapp_number(f"{row.contact['phone_prefix'] or ''}{phone_raw}")
        if derived:
            whatsapp = derived
            row.warnings.append("WhatsApp number derived from the phone column.")
    row.contact["whatsapp_number"] = whatsapp

    prefix = row.contact["phone_prefix"]
    if prefix and prefix == phone_raw:
        row.contact["phone_prefix"] = None
    elif not prefix and phone_raw:
        # crm.accounts.queries falls back to "+1" when no prefix is stored.
        row.warnings.append('No phone prefix given; the contact will be saved with "+1".')

    if not row.contact["email"] and not whatsapp and not phone_raw:
        row.errors.append("Needs at least one of email, phone, or WhatsApp number.")

    return row


def _clean_field(name: str, value: str | None, row: ParsedRow) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None

    limit = MAX_LENGTHS.get(name)
    if limit and len(cleaned) > limit:
        if name in STRICT_LENGTH_FIELDS:
            row.errors.append(f"{_label(name)} is longer than {limit} characters.")
            return None
        row.warnings.append(f"{_label(name)} was shortened to {limit} characters.")
        return cleaned[:limit]
    return cleaned


def _parse_bool(value: str | None, row: ParsedRow) -> bool:
    cleaned = (value or "").strip().casefold()
    if cleaned in _TRUE_VALUES:
        return True
    if cleaned in _FALSE_VALUES:
        return False
    row.warnings.append(f'Could not read "{value}" as yes/no for primary contact; treated as no.')
    return False


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[;,\n|]", str(value)):
        name = " ".join(chunk.strip().split())
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append(name[:80])
    return names


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def sample_csv_header() -> str:
    return ",".join(
        [
            "company_name",
            "erp_client_id",
            "first_name",
            "last_name",
            "email",
            "phone_prefix",
            "phone",
            "whatsapp_number",
            "job_title",
            "is_primary",
            "industry",
            "city",
            "country",
            "notes",
        ]
    )


def error_report_csv(result: ParseResult) -> str:
    """Render the rejected rows as a CSV the user can fix and re-upload."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_number", "company_name", "first_name", "last_name", "email", "problems"])
    for row in result.error_rows:
        writer.writerow(
            [
                row.row_number,
                row.account.get("company_name") or "",
                row.contact.get("first_name") or "",
                row.contact.get("last_name") or "",
                row.contact.get("email") or "",
                "; ".join(row.errors),
            ]
        )
    return buffer.getvalue()
