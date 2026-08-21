from bridge_crm.crm.whatsapp.templates import (
    custom_params_from_body,
    extract_body_params,
    map_wati_status,
    normalize_template_name,
    payload_from_wati,
)


def test_normalize_template_name_uses_underscores():
    assert normalize_template_name(" Restock Update! ") == "restock_update"


def test_extract_body_params_keeps_order_and_uniques():
    body = "Hi {{name}}, {{rep_name}} here. {{name}} {{message}}"
    assert extract_body_params(body) == ["name", "rep_name", "message"]


def test_custom_params_from_body_adds_sample_values():
    params = custom_params_from_body("Hello {{name}}", {"name": "Alex"})
    assert params == [{"paramName": "name", "paramValue": "Alex"}]


def test_map_wati_status_codes():
    assert map_wati_status(1) == ("pending", "PENDING")
    assert map_wati_status(2) == ("approved", "APPROVED")
    assert map_wati_status(3) == ("cancelled", "REJECTED")
    assert map_wati_status(4) == ("cancelled", "DELETED")
    assert map_wati_status("APPROVED") == ("approved", "APPROVED")
    assert map_wati_status({"newStatus": 2}) == ("approved", "APPROVED")


def test_payload_from_wati_normalizes_language_object():
    payload = payload_from_wati(
        {
            "id": "abc123",
            "elementName": "about_wati",
            "category": "MARKETING",
            "status": "APPROVED",
            "language": {"value": "en_US", "text": "English (US)"},
            "bodyOriginal": "Hello {{name}}",
            "footer": "Bridge Wireless",
        }
    )
    assert payload["element_name"] == "about_wati"
    assert payload["status"] == "approved"
    assert payload["language"] == "en_US"
    assert payload["custom_params"][0]["paramName"] == "name"
