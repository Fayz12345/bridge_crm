import pytest

from bridge_crm.crm.imports import wati_sync
from bridge_crm.integrations.wati import contact_params
from bridge_crm.integrations.whatsapp import WhatsAppAPIError

CONTACT = {
    "id": 5,
    "account_id": 2,
    "first_name": "Ann",
    "last_name": "Lee",
    "email": "ann@acme.test",
    "job_title": "Buyer",
    "whatsapp_number": "971501234567",
    "company_name": "Acme",
    "erp_client_id": "ERP-1",
}


def test_contact_params_drops_blanks_and_shapes_pairs():
    params = contact_params({"a": "1", "b": "", "c": None, "d": "  x  "})
    assert params == [{"name": "a", "value": "1"}, {"name": "d", "value": "x"}]


def test_attributes_carry_crm_ids_back_to_wati():
    params = {item["name"]: item["value"] for item in wati_sync._attributes_for(CONTACT)}
    assert params["crm_contact_id"] == "5"
    assert params["crm_account_id"] == "2"
    assert params["company_name"] == "Acme"
    assert params["erp_client_id"] == "ERP-1"


def test_display_name_falls_back_to_company():
    assert wati_sync._display_name(CONTACT) == "Ann Lee"
    assert wati_sync._display_name({"company_name": "Acme"}) == "Acme"
    assert wati_sync._display_name({}) == "Contact"


@pytest.fixture
def stub_sync(monkeypatch):
    """Drive sync_contacts without a database or a live Wati account."""
    state = {"sent": [], "marked": []}

    def _install(records, *, supported=True, fail_numbers=()):
        def fake_add_contact(number, *, name, custom_params=None):
            if number in fail_numbers:
                raise WhatsAppAPIError("Wati rejected this number")
            state["sent"].append({"number": number, "name": name, "params": custom_params})
            return {"result": True}

        monkeypatch.setattr(wati_sync, "contacts_supported", lambda: supported)
        monkeypatch.setattr(wati_sync, "_load_contacts", lambda ids: list(records))
        monkeypatch.setattr(wati_sync, "add_contact", fake_add_contact)
        monkeypatch.setattr(
            wati_sync,
            "_mark",
            lambda contact_id, status, error: state["marked"].append((contact_id, status, error)),
        )

    return _install, state


def test_sync_pushes_each_contact_and_marks_it_synced(stub_sync):
    install, state = stub_sync
    install([CONTACT])
    outcome = wati_sync.sync_contacts([5], throttle=0)
    assert outcome.synced == 1 and outcome.failed == 0
    assert state["sent"][0]["number"] == "971501234567"
    assert state["sent"][0]["name"] == "Ann Lee"
    assert state["marked"] == [(5, "synced", None)]


def test_sync_records_a_failure_without_stopping(stub_sync):
    install, state = stub_sync
    second = {**CONTACT, "id": 6, "whatsapp_number": "971509999999"}
    install([CONTACT, second], fail_numbers={"971501234567"})
    outcome = wati_sync.sync_contacts([5, 6], throttle=0)
    assert outcome.failed == 1 and outcome.synced == 1
    assert outcome.failures[0]["contact_id"] == 5
    assert "rejected" in outcome.failures[0]["error"]
    assert (6, "synced", None) in state["marked"]


def test_sync_skips_a_contact_with_an_unusable_number(stub_sync):
    install, state = stub_sync
    install([{**CONTACT, "whatsapp_number": "123"}])
    outcome = wati_sync.sync_contacts([5], throttle=0)
    assert outcome.skipped == 1 and outcome.synced == 0
    assert state["sent"] == []
    assert state["marked"][0][1] == "skipped"


def test_sync_normalizes_a_formatted_number_before_sending(stub_sync):
    install, state = stub_sync
    install([{**CONTACT, "whatsapp_number": "+971 50 123 4567"}])
    wati_sync.sync_contacts([5], throttle=0)
    assert state["sent"][0]["number"] == "971501234567"


def test_sync_is_a_no_op_when_wati_is_not_configured(stub_sync):
    install, state = stub_sync
    install([CONTACT], supported=False)
    outcome = wati_sync.sync_contacts([5], throttle=0)
    assert outcome.skipped == 1 and outcome.synced == 0
    assert state["sent"] == [] and state["marked"] == []


def test_sync_of_an_empty_list_touches_nothing(stub_sync):
    install, state = stub_sync
    install([])
    outcome = wati_sync.sync_contacts([], throttle=0)
    assert (outcome.synced, outcome.failed, outcome.skipped) == (0, 0, 0)
    assert state["sent"] == []


def test_sync_one_contact_reports_failure_without_raising(stub_sync, monkeypatch):
    install, _ = stub_sync
    install([CONTACT])
    monkeypatch.setattr(
        wati_sync,
        "sync_contacts",
        lambda ids, throttle=0: (_ for _ in ()).throw(RuntimeError("connection reset")),
    )
    outcome = wati_sync.sync_one_contact(5)
    assert outcome.failed == 1
    assert "connection reset" in outcome.failures[0]["error"]


def test_sync_one_contact_is_quiet_when_wati_is_unconfigured(stub_sync):
    install, _ = stub_sync
    install([CONTACT], supported=False)
    outcome = wati_sync.sync_one_contact(5)
    # `failed` is what makes the calling save warn the user; a missing
    # integration must not look like a failure.
    assert outcome.failed == 0
    assert outcome.skipped == 1
