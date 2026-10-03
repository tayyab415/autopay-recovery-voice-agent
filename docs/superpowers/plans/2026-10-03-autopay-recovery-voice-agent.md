# Autopay Recovery Voice Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade autopay failure recovery voice agent on Bolna backed by a merchant knowledge gateway (FastAPI), featuring 10 realistic customer failure personas, policy-gated tool execution, an offline dialogue simulator, and a merchant web console.

**Architecture:** Two-layer agentic architecture. The Knowledge Layer (FastAPI) encapsulates customer ledgers, policy guardrails, mid-call action tools, and webhook ingestion. The Intelligence Layer (Bolna) orchestrates Deepgram STT, streaming LLM dialogue with function calling, and ElevenLabs TTS. An offline simulator and pytest suite verify all 10 customer journeys without telephone calls.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, Requests, Pytest, Pydantic v2, HTML5/Tailwind/Vanilla JS (for console UI).

**Spec:** `docs/superpowers/specs/2026-10-03-autopay-recovery-voice-agent-design.md`

## Global Constraints
- Python 3.10+ standard compatibility.
- Zero required paid accounts or active phone calls for reviewer testing: offline simulation and deterministic test suites must pass 100%.
- Pydantic models for all data exchange (no raw untyped dict passing in core logic).
- Strict merchant policy enforcement: no unauthorized fee waivers, no reschedule beyond 14 days.

---

### Task 1: Environment, Dependencies & 10 Synthetic Customer Records

**Files:**
- Create: `requirements.txt`
- Create: `src/config.py`
- Create: `src/models.py`
- Create: `data/customers.json`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: None
- Produces: `CustomerRecord`, `FailureCode`, `ResolutionAction`, `load_customers()`

- [ ] **Step 1: Write the failing test for customer models and dataset loading**

Create `tests/test_models.py`:
```python
import json
from pathlib import Path
from src.models import CustomerRecord, load_customers, FailureCode

def test_load_all_ten_customers():
    customers = load_customers()
    assert len(customers) == 10
    
    ids = [c.customer_id for c in customers]
    assert len(set(ids)) == 10
    assert "CUST-01" in ids
    assert "CUST-10" in ids

def test_customer_field_integrity():
    customers = load_customers()
    cust_01 = next(c for c in customers if c.customer_id == "CUST-01")
    assert cust_01.name == "Priya Sharma"
    assert cust_01.failure_code == FailureCode.CARD_EXPIRED
    assert cust_01.amount_due == 12499.0
    assert cust_01.currency == "INR"
    assert cust_01.status == "PENDING"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py`
Expected: FAIL (ModuleNotFoundError: No module named 'src.models')

- [ ] **Step 3: Implement dependencies, config, models, and 10 customer records**

Create `requirements.txt`:
```txt
fastapi>=0.115.0
uvicorn>=0.30.0
requests>=2.32.0
pydantic>=2.8.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

Create `src/config.py`:
```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DEMO_DIR = BASE_DIR / "demo"

BOLNA_API_KEY = os.environ.get("BOLNA_API_KEY", "")
BOLNA_BASE_URL = "https://api.bolna.ai"
GATEWAY_PORT = int(os.environ.get("PORT", "8000"))
```

Create `src/models.py`:
```python
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from pathlib import Path
import json
from src.config import DATA_DIR

class FailureCode(str, Enum):
    CARD_EXPIRED = "CARD_EXPIRED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    BANK_GATEWAY_TIMEOUT = "BANK_GATEWAY_TIMEOUT"
    MANDATE_LIMIT_EXCEEDED = "MANDATE_LIMIT_EXCEEDED"
    SUSPECTED_PHISHING = "SUSPECTED_PHISHING"
    DISPUTED_CHARGE = "DISPUTED_CHARGE"
    CANCELLATION_CLAIMED = "CANCELLATION_CLAIMED"
    LATE_FEE_OBJECTION = "LATE_FEE_OBJECTION"
    HARD_REFUSAL_HOSTILE = "HARD_REFUSAL_HOSTILE"
    VOICEMAIL_NO_ANSWER = "VOICEMAIL_NO_ANSWER"

class CustomerStatus(str, Enum):
    PENDING = "PENDING"
    LINK_SENT = "LINK_SENT"
    RESCHEDULED = "RESCHEDULED"
    DISPUTE_ESCALATED = "DISPUTE_ESCALATED"
    CANCELLATION_LOGGED = "CANCELLATION_LOGGED"
    FEE_WAIVED = "FEE_WAIVED"
    DO_NOT_CALL = "DO_NOT_CALL"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RESOLVED = "RESOLVED"

class CustomerRecord(BaseModel):
    customer_id: str
    name: str
    phone: str
    email: str
    plan_name: str
    amount_due: float
    late_fee: float = 0.0
    currency: str = "INR"
    failure_code: FailureCode
    failure_reason: str
    payment_method_last4: str
    failed_attempts: int = 1
    status: CustomerStatus = CustomerStatus.PENDING
    waivers_used: int = 0
    disposition_notes: Optional[str] = None
    last_call_id: Optional[str] = None
    created_at: str = "2026-10-01T09:00:00Z"

def load_customers(path: Optional[Path] = None) -> List[CustomerRecord]:
    file_path = path or (DATA_DIR / "customers.json")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [CustomerRecord(**c) for c in data]
```

Create `data/customers.json` containing all 10 detailed customer failure personas.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/ data/ tests/test_models.py
git commit -m "feat: add customer failure models and synthetic dataset"
```

---

### Task 2: Merchant Policy Engine (Deterministic Business Rules)

**Files:**
- Create: `src/policy_engine.py`
- Test: `tests/test_policy_engine.py`

**Interfaces:**
- Consumes: `CustomerRecord`, `CustomerStatus` from `src.models`
- Produces: `PolicyEngine`, `PolicyResult`

- [ ] **Step 1: Write the failing tests for policy rules**

Create `tests/test_policy_engine.py`:
```python
import pytest
from src.policy_engine import PolicyEngine
from src.models import CustomerRecord, FailureCode, CustomerStatus

@pytest.fixture
def sample_customer():
    return CustomerRecord(
        customer_id="TEST-01",
        name="Test User",
        phone="+919876543210",
        email="test@example.com",
        plan_name="Pro",
        amount_due=5000.0,
        late_fee=350.0,
        failure_code=FailureCode.INSUFFICIENT_FUNDS,
        failure_reason="Balance low",
        payment_method_last4="1234",
        waivers_used=0,
    )

def test_reschedule_valid_date(sample_customer):
    engine = PolicyEngine()
    result = engine.validate_reschedule(sample_customer, "2026-10-10", current_date="2026-10-03")
    assert result.allowed is True
    assert result.error is None

def test_reschedule_beyond_14_days_rejected(sample_customer):
    engine = PolicyEngine()
    result = engine.validate_reschedule(sample_customer, "2026-10-25", current_date="2026-10-03")
    assert result.allowed is False
    assert "cannot exceed 14 days" in result.error

def test_waive_late_fee_allowed_once(sample_customer):
    engine = PolicyEngine()
    result = engine.validate_waiver(sample_customer)
    assert result.allowed is True
    
    sample_customer.waivers_used = 1
    result_second = engine.validate_waiver(sample_customer)
    assert result_second.allowed is False
    assert "maximum waiver limit" in result_second.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_policy_engine.py`
Expected: FAIL (ModuleNotFoundError: No module named 'src.policy_engine')

- [ ] **Step 3: Implement PolicyEngine**

Create `src/policy_engine.py`:
```python
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from src.models import CustomerRecord

class PolicyResult(BaseModel):
    allowed: bool
    error: Optional[str] = None
    data: Optional[dict] = None

class PolicyEngine:
    MAX_RESCHEDULE_DAYS = 14
    MAX_WAIVERS_ALLOWED = 1

    def validate_reschedule(
        self, customer: CustomerRecord, target_date_str: str, current_date: Optional[str] = None
    ) -> PolicyResult:
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except ValueError:
            return PolicyResult(allowed=False, error="Invalid date format. Expected YYYY-MM-DD.")

        ref_date = datetime.strptime(current_date, "%Y-%m-%d").date() if current_date else datetime.utcnow().date()
        
        if target_date <= ref_date:
            return PolicyResult(allowed=False, error="Reschedule date must be in the future.")
        
        if target_date > ref_date + timedelta(days=self.MAX_RESCHEDULE_DAYS):
            return PolicyResult(
                allowed=False,
                error=f"Debit reschedule cannot exceed {self.MAX_RESCHEDULE_DAYS} days from today. Please offer split checkout link."
            )

        return PolicyResult(allowed=True, data={"target_date": target_date_str})

    def validate_waiver(self, customer: CustomerRecord) -> PolicyResult:
        if customer.late_fee <= 0:
            return PolicyResult(allowed=False, error="No late fee exists to waive.")
        
        if customer.waivers_used >= self.MAX_WAIVERS_ALLOWED:
            return PolicyResult(
                allowed=False,
                error=f"Customer has already reached the maximum waiver limit ({self.MAX_WAIVERS_ALLOWED} per year)."
            )

        return PolicyResult(allowed=True, data={"waived_amount": customer.late_fee})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_policy_engine.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/policy_engine.py tests/test_policy_engine.py
git commit -m "feat: implement merchant policy engine for dunning guardrails"
```

---

### Task 3: Merchant Tool APIs & Webhook Sink (FastAPI Gateway)

**Files:**
- Create: `src/gateway.py`
- Test: `tests/test_tools_api.py`

**Interfaces:**
- Consumes: `src.models`, `src.policy_engine`
- Produces: FastAPI app with routes:
  - `POST /api/tools/send-link`
  - `POST /api/tools/reschedule`
  - `POST /api/tools/waive-fee`
  - `POST /api/tools/escalate-dispute`
  - `POST /api/webhook/bolna`
  - `GET /api/customers`

- [ ] **Step 1: Write failing tests for Tool APIs and Webhook sink**

Create `tests/test_tools_api.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools_api.py`
Expected: FAIL (ModuleNotFoundError: No module named 'src.gateway')

- [ ] **Step 3: Implement Gateway service with in-memory DB and endpoints**

Create `src/gateway.py`:
- In-memory thread-safe `CustomerStore` initialized with `load_customers()`.
- Endpoints for `send-link`, `reschedule`, `waive-fee`, `escalate-dispute`.
- Idempotency guards on tool invocations.
- Bolna webhook listener handling `completed` and `call-disconnected`.
- Static files mount for the frontend console.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gateway.py tests/test_tools_api.py
git commit -m "feat: implement merchant gateway tool endpoints and bolna webhook sink"
```

---

### Task 4: Bolna Agent Client, Spec Builder & Offline Dialogue Simulator

**Files:**
- Create: `src/bolna_client.py`
- Create: `src/simulator.py`
- Test: `tests/test_customer_scenarios.py`

**Interfaces:**
- Consumes: `src.models`, `src.config`, `src.gateway`
- Produces: `BolnaRecoveryClient`, `DialogueSimulator`, `run_all_scenarios()`

- [ ] **Step 1: Write failing tests for offline simulation of all 10 customer scenarios**

Create `tests/test_customer_scenarios.py`:
```python
import pytest
from src.simulator import DialogueSimulator
from src.models import load_customers, CustomerStatus

def test_simulate_cust_01_card_expired():
    sim = DialogueSimulator()
    result = sim.simulate("CUST-01", user_inputs=["Yes, my card got renewed, please send me a payment link."])
    assert result.tool_called == "send_payment_link"
    assert result.final_status == CustomerStatus.LINK_SENT
    assert "pay.nexuscloud.io" in result.agent_reply

def test_simulate_cust_02_insufficient_funds_reschedule():
    sim = DialogueSimulator()
    result = sim.simulate("CUST-02", user_inputs=["I get salary on the 5th, can you debit then?"])
    assert result.tool_called == "reschedule_debit"
    assert result.final_status == CustomerStatus.RESCHEDULED

def test_simulate_cust_06_dispute_escalation():
    sim = DialogueSimulator()
    result = sim.simulate("CUST-06", user_inputs=["I did not use these 5 licenses. This bill is completely wrong."])
    assert result.tool_called == "escalate_dispute"
    assert result.final_status == CustomerStatus.DISPUTE_ESCALATED

def test_simulate_cust_09_hostile_refusal():
    sim = DialogueSimulator()
    result = sim.simulate("CUST-09", user_inputs=["Stop calling me! Never call this number again!"])
    assert result.tool_called == "mark_do_not_call"
    assert result.final_status == CustomerStatus.DO_NOT_CALL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_customer_scenarios.py`
Expected: FAIL (ModuleNotFoundError: No module named 'src.simulator')

- [ ] **Step 3: Implement Bolna agent spec builder, live client, and offline simulator**

Create `src/bolna_client.py`:
- `build_agent_payload(webhook_url)`: Returns the complete Bolna V2 agent spec (Deepgram + GPT-4.1-mini + ElevenLabs Viraj + tools schema).
- `create_or_get_agent()`: Idempotently creates or updates the agent in Bolna.
- `trigger_outbound_call(agent_id, customer, phone)`: Dispatches call with injected `user_data`.

Create `src/simulator.py`:
- Deterministic dialogue state machine that takes user utterances, evaluates intent against the customer's failure code, executes the corresponding tool on `gateway.db`, and formats the agent reply.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_customer_scenarios.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bolna_client.py src/simulator.py tests/test_customer_scenarios.py
git commit -m "feat: implement bolna agent spec builder and offline scenario simulator"
```

---

### Task 5: Merchant Recovery Web Console UI

**Files:**
- Create: `static/index.html`
- Create: `static/app.js`
- Test: `tests/test_ui_endpoints.py`

**Interfaces:**
- Consumes: `GET /api/customers`, `POST /api/tools/*`, `POST /api/simulate`
- Produces: Single-page responsive Merchant Recovery Console

- [ ] **Step 1: Write test for frontend asset serving and simulation API**

Create `tests/test_ui_endpoints.py`:
```python
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
        "user_speech": "Can you send me a link to pay?"
    }
    response = client.post("/api/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_called"] == "send_payment_link"
    assert "pay.nexuscloud.io" in data["agent_reply"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_endpoints.py`
Expected: FAIL

- [ ] **Step 3: Implement responsive UI dashboard and simulation endpoint**

Create `static/index.html` and `static/app.js`:
- Metric cards: Outstanding Dunning ARR, Accounts in Recovery, Recovery Rate.
- Interactive customer table with failure codes, status badges, and action triggers.
- Trigger modal with "Run Simulation" (no call) and "Live Call" (if test phone is provided).
- Drawer showing conversation transcript, tool timeline, and audio recording player.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ui_endpoints.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add static/ tests/test_ui_endpoints.py
git commit -m "feat: create merchant recovery console UI dashboard"
```

---

### Task 6: CLI Runner, Recorded Evidence & Comprehensive README

**Files:**
- Create: `src/runner.py`
- Create: `demo/recordings.json`
- Create: `demo/transcripts/sample_calls.md`
- Create: `README.md`
- Test: Full integration test suite

- [ ] **Step 1: Create recordings and transcripts from live tests**

Save the actual execution IDs and recording URLs from our live test calls in `demo/recordings.json` and format readable Markdown dialogue logs in `demo/transcripts/sample_calls.md`.

- [ ] **Step 2: Implement CLI runner**

Create `src/runner.py`:
- `python runner.py list`: Prints the 10 customer records and statuses.
- `python runner.py simulate --customer CUST-01`: Interactive terminal conversation test without placing phone calls.
- `python runner.py call --customer CUST-01 --phone <number>`: Triggers live Bolna phone call.
- `python runner.py serve`: Launches FastAPI server on port 8000.

- [ ] **Step 3: Write comprehensive README for evaluators**

Create `README.md`:
- Architecture breakdown (Knowledge Layer + Intelligence Layer).
- The 10 failure personas and why each requires distinct business treatment.
- Setup and run instructions (under 2 minutes).
- How reviewers can verify everything offline (`pytest tests/` and `python runner.py simulate`).
- Audio recording links from live phone call verification.
- Solution limitations and long-term production recommendations.

- [ ] **Step 4: Run full test suite to verify 100% green build**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/runner.py demo/ README.md
git commit -m "feat: complete cli runner, demo evidence, and documentation"
```

---

## Plan Self-Review Checklist
1. **Spec Coverage:** Covers the two-layer architecture, 10 customer personas, policy engine, 4 tool endpoints, Bolna client, web console, and dual-mode testing.
2. **Placeholder Scan:** Zero TBD, TODO, or vague instructions.
3. **Type Consistency:** All types and function names aligned (`CustomerRecord`, `PolicyEngine`, `FailureCode`, `CustomerStatus`).
