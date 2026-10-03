"""Checkout loop + webhook recording URL (mock money, real state changes)."""
from fastapi.testclient import TestClient

from src.gateway import app, db

client = TestClient(app)


def test_send_link_includes_checkout_url():
    res = client.post("/api/tools/send-link", json={"customer_id": "CUST-03"})
    assert res.status_code == 200
    data = res.json()
    assert "pay.nexuscloud.io" in data["short_url"]
    assert data["checkout_url"].endswith("/pay/cust-03-2190")
    assert isinstance(data["push_sent"], bool)


def test_checkout_page_renders_amount():
    res = client.get("/pay/cust-01-4521")
    assert res.status_code == 200
    assert "Priya Sharma" in res.text
    assert "12499" in res.text
    assert "Demo checkout" in res.text


def test_checkout_complete_marks_resolved():
    client.post("/api/tools/send-link", json={"customer_id": "CUST-04"})
    res = client.post("/api/pay/cust-04-9042/complete")
    assert res.status_code == 200
    assert res.json()["final_status"] == "RESOLVED"
    assert db.get_customer("CUST-04").status.value == "RESOLVED"


def test_checkout_unknown_ref_404():
    assert client.get("/pay/nope-0000").status_code == 404
    assert client.post("/api/pay/nope-0000/complete").status_code == 404


def test_webhook_stores_recording_url():
    payload = {
        "status": "completed",
        "execution_id": "exec-live-1",
        "transcript": "assistant: hi user: ok",
        "telephony_data": {"recording_url": "https://api.bolna.ai/recordings/call/exec-live-1"},
        "user_data": {"customer_id": "CUST-05"},
    }
    res = client.post("/api/webhook/bolna", json=payload)
    assert res.status_code == 200
    cust = db.get_customer("CUST-05")
    assert cust.last_call_id == "exec-live-1"
    assert cust.recording_url == "https://api.bolna.ai/recordings/call/exec-live-1"
    assert "assistant: hi" in (cust.disposition_notes or "")
