from bridge_crm.crm.whatsapp import inbound
from bridge_crm.crm.whatsapp.channels import parse_wati_phone_numbers
from bridge_crm.integrations import wati


def test_extract_channel_number_reads_wati_keys():
    assert wati.extract_channel_number({"channelPhoneNumber": "+1 (289) 217-1362"}) == "12892171362"
    assert wati.extract_channel_number({"data": {"channel_number": "971501234567"}}) == "971501234567"
    assert wati.extract_channel_number({"waId": "971509999999"}) is None


def test_parse_wati_phone_numbers_accepts_common_shapes():
    parsed = parse_wati_phone_numbers(
        {
            "result": [
                {"phoneNumber": "+1 289-217-1362", "displayName": "Bridge", "isDefault": True},
                {"number": "971501111111", "name": "Ahmed"},
            ]
        }
    )
    assert parsed[0]["phone_number"] == "12892171362"
    assert parsed[0]["is_default"] is True
    assert parsed[1]["phone_number"] == "971501111111"
    assert parsed[1]["display_name"] == "Ahmed"


def test_session_send_passes_channel_query(monkeypatch):
    captured = {}

    def fake_request(method, path, *, payload=None, query=None, form_data=None, timeout=45):
        captured.update(
            {"method": method, "path": path, "query": query, "form_data": form_data}
        )
        return {"localMessageId": "abc"}

    monkeypatch.setattr(wati, "_api_request", fake_request)
    monkeypatch.setattr(wati, "wati_credentials_configured", lambda: True)
    wati.send_session_message("971501234567", "Hello", channel_number="12892171362")
    assert captured["query"] == {"channelPhoneNumber": "12892171362"}
    assert captured["form_data"]["messageText"] == "Hello"


def test_template_send_and_broadcast_include_channel(monkeypatch):
    captured = {}

    def fake_request(method, path, *, payload=None, query=None, form_data=None, timeout=45):
        captured[path] = {"payload": payload, "query": query}
        return {"result": True, "localMessageId": "m1"}

    monkeypatch.setattr(wati, "_api_request", fake_request)
    monkeypatch.setattr(wati, "wati_credentials_configured", lambda: True)
    wati.send_template_message(
        "971501234567",
        "hello_v1",
        parameters=[{"name": "name", "value": "Ann"}],
        channel_number="12892171362",
    )
    assert captured["/api/v2/sendTemplateMessage"]["payload"]["channel_number"] == "12892171362"

    wati.send_template_broadcast(
        [{"whatsapp_number": "971501234567", "parameters": []}],
        template_name="hello_v1",
        channel_number="12892171362",
    )
    assert captured["/api/v1/sendTemplateMessages"]["payload"]["channel_number"] == "12892171362"


def test_inbound_stores_channel_as_to_number(monkeypatch):
    stored = {}

    monkeypatch.setattr(inbound, "get_whatsapp_message_by_wa_ids", lambda ids: None)
    monkeypatch.setattr(inbound, "similar_whatsapp_message_exists", lambda **kwargs: False)
    monkeypatch.setattr(
        inbound,
        "find_related_entity_by_phone",
        lambda phone: {
            "related_type": "lead",
            "related_id": 9,
            "display_name": "Ann",
            "owner_id": 3,
        },
    )
    monkeypatch.setattr(inbound, "log_activity", lambda *args, **kwargs: None)
    notified = []
    monkeypatch.setattr(inbound, "_notify_inbound", lambda entity, body, channel_number=None: notified.append((entity, body, channel_number)))

    def fake_create(**kwargs):
        stored.update(kwargs)
        return 1

    monkeypatch.setattr(inbound, "create_whatsapp_message", fake_create)
    inbound.store_wati_payload(
        {
            "eventType": "message",
            "waId": "971501111111",
            "text": "hello",
            "whatsappMessageId": "wamid.1",
            "channelPhoneNumber": "12892171362",
        }
    )
    assert stored["from_number"] == "971501111111"
    assert stored["to_number"] == "12892171362"
    assert stored["related_id"] == 9
    assert notified[0][2] == "12892171362"


def test_inbound_notify_includes_owner_and_channel_assignees(monkeypatch):
    created = []
    monkeypatch.setattr(
        "bridge_crm.crm.whatsapp.channels.list_user_ids_for_channel",
        lambda number: [7, 3] if number == "12892171362" else [],
    )
    monkeypatch.setattr(inbound, "create_notification", lambda payload: created.append(payload) or 1)
    monkeypatch.setattr(inbound, "has_request_context", lambda: False)
    inbound._notify_inbound(
        {
            "related_type": "lead",
            "related_id": 9,
            "display_name": "Ann",
            "owner_id": 3,
        },
        "hello",
        channel_number="12892171362",
    )
    assert [item["user_id"] for item in created] == [3, 7]
    assert created[0]["metadata"]["channel_number"] == "12892171362"
