import pytest

from bridge_crm.crm.imports import queries as import_queries
from bridge_crm.crm.imports.csv_parser import (
    decode_csv_bytes,
    error_report_csv,
    normalize_header,
    parse_contacts_csv,
)

HEADER = "company_name,first_name,last_name,email,phone_prefix,phone,whatsapp_number,is_primary"


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def test_normalize_header_accepts_spaced_and_cased_names():
    assert normalize_header(" Company Name ") == "company_name"
    assert normalize_header("WhatsApp-Number") == "whatsapp_number"


def test_header_aliases_map_to_canonical_fields():
    result = parse_contacts_csv("Company,Given Name,Surname,Mobile\nAcme,Ann,Lee,971501234567")
    assert not result.missing_headers
    row = result.rows[0]
    assert row.account["company_name"] == "Acme"
    assert row.contact["first_name"] == "Ann"
    assert row.contact["last_name"] == "Lee"


def test_missing_required_headers_are_reported():
    result = parse_contacts_csv("first_name,last_name\nAnn,Lee")
    assert result.missing_headers == ["company_name"]
    assert not result.is_importable


def test_unknown_headers_are_collected_not_fatal():
    result = parse_contacts_csv(
        "company_name,first_name,last_name,email,loyalty_points\nAcme,Ann,Lee,ann@acme.test,50"
    )
    assert result.unknown_headers == ["loyalty_points"]
    assert result.valid_rows


def test_row_requires_a_contact_method():
    result = parse_contacts_csv(_csv("Acme,Ann,Lee,,,,,yes"))
    row = result.rows[0]
    assert not row.is_valid
    assert "at least one of email" in row.errors[0]


def test_invalid_email_is_rejected():
    result = parse_contacts_csv(_csv("Acme,Ann,Lee,not-an-email,,,971501234567,yes"))
    row = result.rows[0]
    assert not row.is_valid
    assert "not a valid email" in row.errors[0]


def test_email_is_lowercased_and_whatsapp_normalized():
    result = parse_contacts_csv(_csv("Acme,Ann,Lee,Ann@Acme.TEST,+971,50 123 4567,+971 50 123 4567,yes"))
    row = result.rows[0]
    assert row.is_valid
    assert row.contact["email"] == "ann@acme.test"
    assert row.contact["whatsapp_number"] == "971501234567"


def test_whatsapp_derived_from_phone_when_column_missing():
    result = parse_contacts_csv(_csv("Acme,Ann,Lee,ann@acme.test,+971,501234567,,yes"))
    row = result.rows[0]
    assert row.contact["whatsapp_number"] == "971501234567"
    assert any("derived from the phone" in warning for warning in row.warnings)


def test_is_primary_parsing_and_unknown_value_warns():
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Bob,Ray,bob@acme.test,,,971501234568,no",
            "Acme,Cid,Fox,cid@acme.test,,,971501234569,maybe",
        )
    )
    assert [row.contact["is_primary"] for row in result.rows] == [True, False, False]
    assert result.rows[2].warnings


def test_erp_client_id_longer_than_column_is_an_error():
    result = parse_contacts_csv(
        "company_name,erp_client_id,first_name,last_name,email\n"
        "Acme,THIS-ID-IS-FAR-TOO-LONG,Ann,Lee,ann@acme.test"
    )
    row = result.rows[0]
    assert not row.is_valid
    assert "Erp client id is longer than 11" in row.errors[0]


def test_long_job_title_is_truncated_with_a_warning():
    result = parse_contacts_csv(
        "company_name,first_name,last_name,email,job_title\n"
        f"Acme,Ann,Lee,ann@acme.test,{'x' * 200}"
    )
    row = result.rows[0]
    assert row.is_valid
    assert len(row.contact["job_title"]) == 120
    assert row.warnings


def test_duplicate_rows_in_the_same_file_are_rejected_once():
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,no",
        )
    )
    assert result.rows[0].is_valid
    assert not result.rows[1].is_valid
    assert "Duplicate of row 2" in result.rows[1].errors[0]


def test_same_person_at_a_different_company_is_not_a_duplicate():
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Globex,Ann,Lee,ann@acme.test,,,971501234567,yes",
        )
    )
    assert all(row.is_valid for row in result.rows)


def test_company_count_groups_rows_case_insensitively():
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "ACME,Bob,Ray,bob@acme.test,,,971501234568,no",
        )
    )
    assert result.company_count == 1


def test_blank_lines_are_skipped_and_row_numbers_track_the_file():
    result = parse_contacts_csv(_csv("", "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes"))
    assert len(result.rows) == 1
    assert result.rows[0].row_number == 3


def test_tags_split_on_semicolons_and_pipes():
    result = parse_contacts_csv(
        "company_name,first_name,last_name,email,tags\n"
        "Acme,Ann,Lee,ann@acme.test,vip; reseller|vip"
    )
    assert result.rows[0].tags == ["vip", "reseller"]


def test_empty_file_reports_a_file_error():
    assert parse_contacts_csv("").file_errors
    assert parse_contacts_csv(HEADER).file_errors


def test_decode_handles_excel_bom():
    text, error = decode_csv_bytes("company_name,first_name\n".encode("utf-8-sig"))
    assert error is None
    assert text.startswith("company_name")


def test_decode_rejects_oversized_files():
    _, error = decode_csv_bytes(b"x" * (6 * 1024 * 1024))
    assert error and "larger than" in error


def test_error_report_lists_rejected_rows_only():
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Bob,Ray,,,,,no",
        )
    )
    report = error_report_csv(result)
    assert "Bob" in report
    assert "Ann" not in report


@pytest.fixture
def stub_lookups(monkeypatch):
    """Run plan_import against a fake database.

    `accounts` maps a company key ("acme") or ERP key ("erp:erp-1") to an account
    id; `contacts` maps (account_id, email) to a contact id.
    """

    def _install(accounts: dict, contacts: dict | None = None):
        index: dict[int, dict[str, int]] = {}
        for (account_id, email), contact_id in (contacts or {}).items():
            index.setdefault(account_id, {})[f"email:{email}"] = contact_id
        monkeypatch.setattr(import_queries, "_lookup_accounts", lambda rows: dict(accounts))
        monkeypatch.setattr(import_queries, "_lookup_contacts", lambda account_ids: index)

    return _install


def test_plan_creates_one_account_for_repeated_company_rows(stub_lookups):
    stub_lookups({})
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Bob,Ray,bob@acme.test,,,971501234568,no",
            "Globex,Cid,Fox,cid@globex.test,,,971501234569,yes",
        )
    )
    plans = import_queries.plan_import(result.rows)
    assert [plan.creates_account for plan in plans] == [True, False, True]
    assert all(plan.contact_action == "create" for plan in plans)


def test_plan_reuses_an_existing_account_matched_by_name(stub_lookups):
    stub_lookups({"acme": 7})
    result = parse_contacts_csv(_csv("Acme,Ann,Lee,ann@acme.test,,,971501234567,yes"))
    plan = import_queries.plan_import(result.rows)[0]
    assert plan.account_action == "reuse"
    assert plan.account_id == 7


def test_plan_prefers_erp_id_over_company_name(stub_lookups):
    stub_lookups({"acme": 7, "erp:erp-1": 9})
    result = parse_contacts_csv(
        "company_name,erp_client_id,first_name,last_name,email\nAcme,ERP-1,Ann,Lee,ann@acme.test"
    )
    plan = import_queries.plan_import(result.rows)[0]
    assert plan.account_id == 9


def test_plan_marks_a_known_contact_as_an_update(stub_lookups):
    stub_lookups({"acme": 7}, {(7, "ann@acme.test"): 42})
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Bob,Ray,bob@acme.test,,,971501234568,no",
        )
    )
    plans = import_queries.plan_import(result.rows)
    assert plans[0].contact_action == "update"
    assert plans[0].contact_id == 42
    assert plans[1].contact_action == "create"


def test_plan_skips_invalid_rows(stub_lookups):
    stub_lookups({})
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Bob,Ray,,,,,no",
        )
    )
    assert len(import_queries.plan_import(result.rows)) == 1


@pytest.fixture
def stub_writes(monkeypatch):
    """Capture what commit_import would write instead of touching the database."""
    written = {"accounts": [], "created": [], "updated": []}
    counter = {"account_id": 100, "contact_id": 500}

    def fake_create_account(payload):
        counter["account_id"] += 1
        written["accounts"].append(payload)
        return counter["account_id"]

    def fake_create_contact(payload):
        if payload.get("first_name") == "Boom":
            raise RuntimeError("insert exploded")
        counter["contact_id"] += 1
        written["created"].append(payload)
        return counter["contact_id"]

    def fake_update_contact(account_id, contact_id, payload):
        written["updated"].append((account_id, contact_id, payload))

    monkeypatch.setattr(import_queries, "create_account", fake_create_account)
    monkeypatch.setattr(import_queries, "create_contact_for_account", fake_create_contact)
    monkeypatch.setattr(import_queries, "update_contact_for_account", fake_update_contact)
    monkeypatch.setattr(import_queries, "replace_account_tags", lambda account_id, tags: None)
    monkeypatch.setattr(import_queries, "log_activity", lambda *args, **kwargs: None)
    return written


def test_commit_creates_one_account_for_rows_sharing_a_company(stub_lookups, stub_writes):
    stub_lookups({})
    result = parse_contacts_csv(
        _csv(
            "Acme,Ann,Lee,ann@acme.test,,,971501234567,yes",
            "Acme,Bob,Ray,bob@acme.test,,,971501234568,no",
            "Globex,Cid,Fox,cid@globex.test,,,971501234569,yes",
        )
    )
    outcome = import_queries.commit_import(result.rows, user_id=1)
    assert outcome.accounts_created == 2
    assert outcome.contacts_created == 3
    assert len(stub_writes["accounts"]) == 2
    # Both Acme contacts land on the same account id.
    acme_account_ids = {payload["account_id"] for payload in stub_writes["created"][:2]}
    assert len(acme_account_ids) == 1


def test_commit_updates_a_matched_contact_instead_of_creating(stub_lookups, stub_writes):
    stub_lookups({"acme": 7}, {(7, "ann@acme.test"): 42})
    result = parse_contacts_csv(_csv("Acme,Ann,Lee,ann@acme.test,,,971501234567,yes"))
    outcome = import_queries.commit_import(result.rows, user_id=1)
    assert outcome.contacts_updated == 1
    assert outcome.contacts_created == 0
    assert outcome.accounts_created == 0
    assert stub_writes["updated"][0][:2] == (7, 42)


def test_commit_records_a_failed_row_and_keeps_going(stub_lookups, stub_writes):
    stub_lookups({})
    result = parse_contacts_csv(
        _csv(
            "Acme,Boom,Bad,boom@acme.test,,,971501234500,yes",
            "Globex,Cid,Fox,cid@globex.test,,,971501234569,yes",
        )
    )
    outcome = import_queries.commit_import(result.rows, user_id=1)
    assert outcome.contacts_created == 1
    assert len(outcome.failures) == 1
    assert outcome.failures[0]["display_name"] == "Boom Bad"
    assert "insert exploded" in outcome.failures[0]["error"]


def test_commit_passes_account_columns_through_to_create(stub_lookups, stub_writes):
    stub_lookups({})
    result = parse_contacts_csv(
        "company_name,erp_client_id,first_name,last_name,email,industry,city\n"
        "Acme,ERP-1,Ann,Lee,ann@acme.test,Retail,Dubai"
    )
    import_queries.commit_import(result.rows, user_id=9)
    payload = stub_writes["accounts"][0]
    assert payload["company_name"] == "Acme"
    assert payload["erp_client_id"] == "ERP-1"
    assert payload["industry"] == "Retail"
    assert payload["city"] == "Dubai"
    assert payload["owner_id"] == 9 and payload["created_by"] == 9
