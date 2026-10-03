"""FastAPI merchant gateway: tool endpoints + Bolna webhook sink + simulate wrapper."""
from typing import Dict, List, Optional
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import STATIC_DIR
from src.models import CustomerRecord, CustomerStatus, load_customers
from src.policy_engine import PolicyEngine

PAY_LINK_DOMAIN = "pay.nexuscloud.io"


class CustomerStore:
    """Thread-safe in-memory store seeded from load_customers()."""

    def __init__(self, customers: Optional[List[CustomerRecord]] = None):
        self._lock = threading.Lock()
        seed = customers if customers is not None else load_customers()
        self._customers: Dict[str, CustomerRecord] = {c.customer_id: c for c in seed}

    def list_customers(self) -> List[CustomerRecord]:
        with self._lock:
            return list(self._customers.values())

    def get_customer(self, customer_id: str) -> Optional[CustomerRecord]:
        with self._lock:
            return self._customers.get(customer_id)

    def update(self, customer: CustomerRecord) -> None:
        with self._lock:
            self._customers[customer.customer_id] = customer


db = CustomerStore()
engine = PolicyEngine()
app = FastAPI(title="Autopay Recovery Voice Agent Gateway")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---- Request models (Pydantic v2) ----
class SendLinkRequest(BaseModel):
    customer_id: str
    channel: str = "sms"


class RescheduleRequest(BaseModel):
    customer_id: str
    target_date: str


class WaiveFeeRequest(BaseModel):
    customer_id: str


class EscalateDisputeRequest(BaseModel):
    customer_id: str
    reason: Optional[str] = None


class SimulateRequest(BaseModel):
    customer_id: str
    user_speech: str = ""


def _require_customer(customer_id: str) -> CustomerRecord:
    cust = db.get_customer(customer_id)
    if cust is None:
        raise HTTPException(status_code=404, detail=f"Unknown customer: {customer_id}")
    return cust


def _payment_link(customer: CustomerRecord) -> str:
    return f"https://{PAY_LINK_DOMAIN}/p/{customer.customer_id.lower()}-{customer.payment_method_last4}"


@app.get("/api/customers")
def get_customers():
    return [c.model_dump() for c in db.list_customers()]


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Console UI not built")
    return FileResponse(str(index_path), media_type="text/html")


@app.post("/api/tools/send-link")
def send_link(payload: SendLinkRequest):
    cust = _require_customer(payload.customer_id)
    short_url = _payment_link(cust)
    cust.status = CustomerStatus.LINK_SENT
    db.update(cust)
    return {"status": "success", "short_url": short_url, "customer_id": cust.customer_id}


@app.post("/api/tools/reschedule")
def reschedule(payload: RescheduleRequest):
    cust = _require_customer(payload.customer_id)
    result = engine.validate_reschedule(cust, payload.target_date)
    if not result.allowed:
        raise HTTPException(status_code=422, detail=result.error)
    cust.status = CustomerStatus.RESCHEDULED
    db.update(cust)
    return {"status": "success", "customer_id": cust.customer_id, "target_date": payload.target_date}


@app.post("/api/tools/waive-fee")
def waive_fee(payload: WaiveFeeRequest):
    cust = _require_customer(payload.customer_id)
    result = engine.validate_waiver(cust)
    if not result.allowed:
        raise HTTPException(status_code=422, detail=result.error)
    cust.status = CustomerStatus.FEE_WAIVED
    cust.waivers_used += 1
    db.update(cust)
    return {"status": "success", "customer_id": cust.customer_id, "waived_amount": cust.late_fee}


@app.post("/api/tools/escalate-dispute")
def escalate_dispute(payload: EscalateDisputeRequest):
    cust = _require_customer(payload.customer_id)
    cust.status = CustomerStatus.DISPUTE_ESCALATED
    if payload.reason:
        cust.disposition_notes = payload.reason
    db.update(cust)
    return {"status": "success", "customer_id": cust.customer_id}


@app.post("/api/webhook/bolna")
def bolna_webhook(payload: dict):
    status = str(payload.get("status", "")).lower()
    execution_id = payload.get("execution_id")
    user_data = payload.get("user_data") or {}
    customer_id = user_data.get("customer_id")
    if customer_id is None:
        # Fallback: match by phone number
        user_number = payload.get("user_number")
        if user_number:
            for c in db.list_customers():
                if c.phone == user_number:
                    customer_id = c.customer_id
                    break
    if customer_id is not None and execution_id is not None and status in ("completed", "call-disconnected", "call_disconnected", "disconnected"):
        cust = db.get_customer(customer_id)
        if cust is not None:
            cust.last_call_id = execution_id
            transcript = payload.get("transcript")
            if transcript:
                cust.disposition_notes = str(transcript)[:2000]
            db.update(cust)
    return {"status": "ok"}


@app.post("/api/simulate")
def simulate_endpoint(payload: SimulateRequest):
    # Lazy import avoids circular dependency (simulator imports gateway.db).
    from src.simulator import DialogueSimulator

    sim = DialogueSimulator()
    result = sim.simulate(payload.customer_id, user_speech=payload.user_speech)
    return {
        "tool_called": result.tool_called,
        "agent_reply": result.agent_reply,
        "final_status": result.final_status.value if isinstance(result.final_status, CustomerStatus) else result.final_status,
    }
