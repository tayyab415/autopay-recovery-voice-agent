import pytest
from fastapi.testclient import TestClient
from src.gateway import app, db

client = TestClient(app)


def test_get_customers():
    response = client.get("/api/customers")
    assert response.status_code == 200
    assert len(response.json()) == 10


def test_send_payment_link_tool():
    payload = {"customer_id": "CUST-01", "channel": "sms"}
    response = client.post("/api/tools/send-link", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "pay.nexuscloud.io" in data["short_url"]

    # Verify customer status updated in db
    assert db.get_customer("CUST-01").status == "LINK_SENT"


def test_reschedule_tool():
    payload = {"customer_id": "CUST-02", "target_date": "2026-10-06"}
    response = client.post("/api/tools/reschedule", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert db.get_customer("CUST-02").status == "RESCHEDULED"


def test_reschedule_invalid_date_rejected():
    payload = {"customer_id": "CUST-02", "target_date": "2026-11-20"}
    response = client.post("/api/tools/reschedule", json=payload)
    assert response.status_code == 422
    assert "cannot exceed 14 days" in response.json()["detail"]


def test_webhook_completed_event():
    webhook_payload = {
        "status": "completed",
        "agent_id": "agent-123",
        "execution_id": "exec-abc-1",
        "user_number": "+919876543210",
        "conversation_duration": 45,
        "transcript": "assistant: Hello Priya... user: please send me link... assistant: sent!",
        "telephony_data": {
            "recording_url": "https://api.bolna.ai/recordings/call/exec-abc-1"
        },
        "user_data": {"customer_id": "CUST-01"}
    }
    response = client.post("/api/webhook/bolna", json=webhook_payload)
    assert response.status_code == 200
    cust = db.get_customer("CUST-01")
    assert cust.last_call_id == "exec-abc-1"


def test_simulate_endpoint():
    # Pre-flight ruling: POST /api/simulate required by Task 5 tests.
    payload = {"customer_id": "CUST-01", "user_speech": "please send me a payment link"}
    response = client.post("/api/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "tool_called" in data
    assert "agent_reply" in data
    assert "final_status" in data
