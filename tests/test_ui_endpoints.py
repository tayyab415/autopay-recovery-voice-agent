from fastapi.testclient import TestClient
from src.gateway import app

client = TestClient(app)


def test_index_html_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Nexus Cloud" in response.text
    assert "Autopay Recovery Console" in response.text


def test_simulation_endpoint():
    payload = {
        "customer_id": "CUST-01",
        "user_speech": "Can you send me a link to pay?",
    }
    response = client.post("/api/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_called"] == "send_payment_link"
    assert "pay.nexuscloud.io" in data["agent_reply"]
