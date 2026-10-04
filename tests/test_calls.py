"""Outbound call guardrails (no live calls; Bolna client is stubbed)."""
from fastapi.testclient import TestClient

import src.config as config
from src.gateway import app

client = TestClient(app)


def test_outbound_unknown_customer_404(monkeypatch):
    monkeypatch.setattr(config, "CALL_ALLOWLIST", [])
    res = client.post("/api/calls/outbound", json={"customer_id": "NOPE", "phone": "+917007623382"})
    assert res.status_code == 404


def test_outbound_bad_phone_422(monkeypatch):
    monkeypatch.setattr(config, "CALL_ALLOWLIST", [])
    res = client.post("/api/calls/outbound", json={"customer_id": "CUST-01", "phone": "7007623382"})
    assert res.status_code == 422


def test_outbound_not_allowlisted_403(monkeypatch):
    monkeypatch.setattr(config, "CALL_ALLOWLIST", ["+911234567890"])
    res = client.post("/api/calls/outbound", json={"customer_id": "CUST-01", "phone": "+917007623382"})
    assert res.status_code == 403


def test_outbound_unconfigured_503(monkeypatch):
    monkeypatch.setattr(config, "CALL_ALLOWLIST", ["+917007623382"])
    monkeypatch.setattr(config, "BOLNA_API_KEY", "")
    monkeypatch.setattr(config, "BOLNA_AGENT_ID", "")
    res = client.post("/api/calls/outbound", json={"customer_id": "CUST-01", "phone": "+917007623382"})
    assert res.status_code == 503


def test_outbound_queued_and_status_proxied(monkeypatch):
    from src import bolna_client

    monkeypatch.setattr(config, "CALL_ALLOWLIST", ["+917007623382"])
    monkeypatch.setattr(config, "BOLNA_API_KEY", "test-key")
    monkeypatch.setattr(config, "BOLNA_AGENT_ID", "agent-1")
    monkeypatch.setattr(
        bolna_client.BolnaRecoveryClient,
        "trigger_outbound_call",
        lambda self, agent_id, customer, phone=None: {"status": "queued", "execution_id": "exec-1"},
    )
    monkeypatch.setattr(
        bolna_client.BolnaRecoveryClient,
        "get_execution",
        lambda self, eid: {
            "status": "completed",
            "conversation_duration": 42.0,
            "total_cost": 5.0,
            "transcript": "assistant: hi",
            "telephony_data": {"recording_url": "https://example/r.mp3"},
        },
    )
    res = client.post("/api/calls/outbound", json={"customer_id": "CUST-01", "phone": "+917007623382"})
    assert res.status_code == 200
    assert res.json()["execution_id"] == "exec-1"
    res2 = client.get("/api/calls/exec-1")
    assert res2.status_code == 200
    assert res2.json()["recording_url"] == "https://example/r.mp3"


def test_web_session_unconfigured_503(monkeypatch):
    monkeypatch.setattr(config, "BOLNA_API_KEY", "")
    monkeypatch.setattr(config, "BOLNA_AGENT_ID", "")
    res = client.post("/api/calls/web-session", json={"user_data": {"customer_id": "CUST-01"}})
    assert res.status_code == 503


def test_messages_unknown_customer_404():
    res = client.get("/api/customers/NOPE/messages")
    assert res.status_code == 404


def test_web_session_unknown_customer_404():
    res = client.post("/api/calls/web-session", json={"user_data": {"customer_id": "NOPE"}})
    assert res.status_code == 404


def test_web_session_uses_ledger_not_browser_amounts(monkeypatch):
    from src import bolna_client

    captured = {}

    def fake_mint(self, agent_id, user_data):
        captured["agent_id"] = agent_id
        captured["user_data"] = user_data
        return 200, {"run_id": "run-web-1", "agent_id": agent_id, "expires_in": 120, "ice_servers": []}

    monkeypatch.setattr(config, "BOLNA_API_KEY", "bn-secret")
    monkeypatch.setattr(config, "BOLNA_AGENT_ID", "agent-web")
    monkeypatch.setattr(bolna_client.BolnaRecoveryClient, "mint_web_session", fake_mint)
    res = client.post("/api/calls/web-session", json={"user_data": {"customer_id": "CUST-02", "amount_due": 1, "customer_name": "Not Rahul"}})
    assert res.status_code == 200
    assert res.json()["run_id"] == "run-web-1"
    assert "bn-secret" not in res.text
    assert captured["agent_id"] == "agent-web"
    assert captured["user_data"]["customer_name"] == "Rahul Verma"
    assert captured["user_data"]["amount_due"] == 4999.0
    assert captured["user_data"]["failure_code"] == "INSUFFICIENT_FUNDS"


def test_cli_call_refuses_without_public_base_url(monkeypatch, capsys):
    from src.runner import cmd_call

    monkeypatch.setattr(config, "BOLNA_API_KEY", "test-key")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
    assert cmd_call("CUST-03", "+917007623382") == 2
    assert "PUBLIC_BASE_URL" in capsys.readouterr().err
