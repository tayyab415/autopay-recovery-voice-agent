from datetime import date

from fastapi.testclient import TestClient

from src.bolna_client import build_agent_payload
from src.disposition import apply_bolna_event
from src.gateway import app
from src.ledger import CustomerStore
from src.models import CustomerStatus, load_customers
from src.policy_engine import PolicyEngine
from src.tools import ToolService

client = TestClient(app)
FIXED = date(2026, 10, 3)


def _service():
    store = CustomerStore(load_customers())
    service = ToolService(store, PolicyEngine(), push=lambda *args, **kwargs: False, today=FIXED)
    return store, service


def test_reschedule_without_a_date_tells_the_model_what_to_send():
    _, service = _service()
    result = service.reschedule("CUST-02", None)
    assert result.http_status == 422
    assert "target_date" in result.message
    assert "14 days" in result.message


def test_reschedule_past_the_window_is_rejected():
    _, service = _service()
    result = service.reschedule("CUST-02", "2026-10-25")
    assert result.http_status == 422
    assert "cannot exceed 14 days" in result.message


def test_second_waiver_does_not_stack():
    store, service = _service()
    first = service.waive_fee("CUST-08", reason="bank delay")
    second = service.waive_fee("CUST-08", reason="please again")
    assert first.http_status == 200
    assert second.http_status == 422
    assert "maximum waiver limit" in second.message
    assert store.get_customer("CUST-08").waivers_used == 1


def test_principal_cannot_be_waived():
    _, service = _service()
    result = service.waive_fee("CUST-08", reason="goodwill", waive_principal=True)
    assert result.http_status == 422
    assert "Principal" in result.message
    assert service.store.get_customer("CUST-08").waivers_used == 0


def test_payment_link_shows_up_as_one_sms():
    store, service = _service()
    service.send_link("CUST-01", "sms")
    service.send_link("CUST-01", "sms")
    notes = store.messages_for("CUST-01")
    assert len(notes) == 1
    assert notes[0]["channel"] == "sms"
    assert notes[0]["sender"] == "NexusCloud"
    assert "Pay securely" in notes[0]["body"]
    assert notes[0]["checkout_url"].endswith("/pay/cust-01-4521")


def test_duplicate_link_does_not_push_again():
    store, service = _service()
    pushes = {"n": 0}

    def push(*args, **kwargs):
        pushes["n"] += 1
        return True

    service.push = push
    first = service.send_link("CUST-01", "sms")
    second = service.send_link("CUST-01", "sms")
    assert first.body["push_sent"] is True
    assert second.body["duplicate"] is True
    assert second.body["push_sent"] is False
    assert second.body["short_url"] == first.body["short_url"]
    assert pushes["n"] == 1
    assert len([row for row in store.audit_for("CUST-01") if row["tool"] == "send_payment_link"]) == 2


def test_do_not_call_blocks_a_later_link():
    _, service = _service()
    service.mark_do_not_call("CUST-09", reason="stop calling")
    result = service.send_link("CUST-09", "sms")
    assert result.http_status == 422
    assert "do-not-call" in result.message


def test_completed_call_keeps_the_tool_disposition():
    store, service = _service()
    service.send_link("CUST-01", "sms")
    out = apply_bolna_event(store, service, {
        "status": "completed",
        "execution_id": "exec-1",
        "transcript": "assistant: link sent",
        "telephony_data": {"recording_url": "https://example.com/a.wav"},
        "user_data": {"customer_id": "CUST-01"},
    }, today=FIXED)
    customer = store.get_customer("CUST-01")
    assert out["disposition"] == "LINK_SENT"
    assert customer.recovery_probability == 0.55
    assert customer.next_touch_at == "2026-10-04"
    assert customer.recording_url == "https://example.com/a.wav"
    assert "link sent" in customer.disposition_notes


def test_no_answer_schedules_a_retry_without_clobbering_a_link():
    store, service = _service()
    service.send_link("CUST-01", "sms")
    apply_bolna_event(store, service, {
        "status": "no-answer",
        "execution_id": "exec-missed-paid",
        "user_data": {"customer_id": "CUST-01"},
    }, today=FIXED)
    assert store.get_customer("CUST-01").status == CustomerStatus.LINK_SENT

    apply_bolna_event(store, service, {
        "status": "no-answer",
        "execution_id": "exec-missed",
        "transcript": "voicemail tone",
        "user_data": {"customer_id": "CUST-10"},
    }, today=FIXED)
    missed = store.get_customer("CUST-10")
    assert missed.status == CustomerStatus.RETRY_SCHEDULED
    assert missed.last_disposition == "RETRY_SCHEDULED"
    assert missed.next_touch_at == "2026-10-04"
    assert "voicemail tone" in missed.disposition_notes


def test_bolna_reschedule_tool_sends_the_date():
    payload = build_agent_payload("https://example.com/hook", "https://example.com")
    tools = {tool["name"]: tool for tool in payload["agent_config"]["tasks"][0]["tools_config"]["api_tools"]}
    reschedule = tools["reschedule_debit"]
    assert "target_date" in reschedule["parameters"]["properties"]
    assert "target_date" in reschedule["parameters"]["required"]
    assert reschedule["value"]["param"]["target_date"] == "%(target_date)s"
    assert reschedule["value"]["url"] == "https://example.com/api/tools/reschedule"
    assert tools["mark_do_not_call"]["value"]["url"].endswith("/api/tools/donotcall")
    assert "get_account" in tools
    prompt = payload["agent_prompts"]["task_1"]["system_prompt"]
    assert payload["agent_config"]["agent_welcome_message"] == ""
    assert "Do not speak until the person says hello" in prompt
    assert "get_account" in prompt
    assert "14 days" in prompt


def test_http_get_account_and_refusal_and_duplicate_link():
    account = client.post("/api/tools/get-account", json={"customer_id": "CUST-02"})
    assert account.status_code == 200
    assert "reschedule_debit" in account.json()["allowed_actions"]

    refused = client.post("/api/tools/send-link", json={"customer_id": "CUST-06", "channel": "sms"})
    assert refused.status_code == 422
    assert "not allowed" in refused.json()["detail"]

    missing = client.post("/api/tools/reschedule", json={"customer_id": "CUST-02"})
    assert missing.status_code == 422
    assert "target_date" in missing.json()["detail"]

    first = client.post("/api/tools/send-link", json={"customer_id": "CUST-10", "channel": "sms"})
    second = client.post("/api/tools/send-link", json={"customer_id": "CUST-10", "channel": "sms"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["push_sent"] is False

    audit = client.get("/api/customers/CUST-10/audit")
    assert audit.status_code == 200
    assert any(row["tool"] == "send_payment_link" and row["result_status"] == "duplicate" for row in audit.json())
