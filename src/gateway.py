"""FastAPI merchant gateway: knowledge-layer tools, Bolna webhook, console."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import config as app_config
from src.config import NTFY_BASE_URL, NTFY_TOPIC, STATIC_DIR
from src.disposition import apply_bolna_event, stamp
from src.ledger import db
from src.models import CustomerStatus
from src.policy_engine import PolicyEngine
from src.tools import ToolResult, ToolService, checkout_ref

engine = PolicyEngine()
app = FastAPI(title="Autopay Recovery Voice Agent Gateway")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class SendLinkRequest(BaseModel):
    customer_id: str
    channel: str = "sms"
    resend: bool = False


class RescheduleRequest(BaseModel):
    customer_id: str
    target_date: Optional[str] = None


class WaiveFeeRequest(BaseModel):
    customer_id: str
    reason: Optional[str] = None
    waive_principal: bool = False


class EscalateDisputeRequest(BaseModel):
    customer_id: str
    reason: Optional[str] = None
    summary: Optional[str] = None
    dispute_type: str = "billing_error"


class CancellationRequest(BaseModel):
    customer_id: str
    reason: Optional[str] = None


class DoNotCallRequest(BaseModel):
    customer_id: str
    reason: Optional[str] = None


class CustomerToolRequest(BaseModel):
    customer_id: str
    reason: Optional[str] = None


class SimulateRequest(BaseModel):
    customer_id: str
    user_speech: str = ""


class OutboundCallRequest(BaseModel):
    customer_id: str
    phone: str


class WebSessionRequest(BaseModel):
    user_data: Optional[dict] = None


def _norm_phone(raw: str) -> str:
    return "".join(raw.split())


def publish_push(title: str, message: str, topic: Optional[str] = None) -> bool:
    """Best-effort push via ntfy (free, no account). Returns True on 200.

    Demo stand-in for SMS. Production swaps the provider. Call sites stay.
    """
    import requests

    try:
        resp = requests.post(
            f"{NTFY_BASE_URL}/{topic or NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title[:60], "Tags": "moneybag"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


tool_service = ToolService(db, engine, publish_push)


def _finish(result: ToolResult):
    if result.http_status >= 400:
        body = dict(result.body)
        body["detail"] = result.message
        return JSONResponse(status_code=result.http_status, content=body)
    return result.body


@app.get("/api/customers")
def get_customers():
    return [c.model_dump() for c in db.list_customers()]


@app.get("/api/customers/{customer_id}/audit")
def get_audit(customer_id: str):
    if db.get_customer(customer_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown customer: {customer_id}")
    return db.audit_for(customer_id)


@app.get("/api/customers/{customer_id}/messages")
def get_messages(customer_id: str):
    if db.get_customer(customer_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown customer: {customer_id}")
    return db.messages_for(customer_id)


@app.get("/api/scenarios")
def get_scenarios():
    from src.simulator import SCENARIO_UTTERANCES
    return SCENARIO_UTTERANCES


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Console UI not built")
    return FileResponse(str(index_path), media_type="text/html")


@app.post("/api/tools/get-account")
def get_account(payload: CustomerToolRequest):
    return _finish(tool_service.get_account(payload.customer_id))


@app.post("/api/tools/send-link")
def send_link(payload: SendLinkRequest):
    return _finish(tool_service.send_link(payload.customer_id, payload.channel, payload.resend))


@app.post("/api/tools/reschedule")
def reschedule(payload: RescheduleRequest):
    return _finish(tool_service.reschedule(payload.customer_id, payload.target_date))


@app.post("/api/tools/waive-fee")
def waive_fee(payload: WaiveFeeRequest):
    return _finish(tool_service.waive_fee(payload.customer_id, payload.reason, payload.waive_principal))


@app.post("/api/tools/escalate-dispute")
def escalate_dispute(payload: EscalateDisputeRequest):
    summary = payload.summary or payload.reason
    return _finish(tool_service.escalate_dispute(payload.customer_id, summary, payload.dispute_type))


@app.post("/api/tools/log-cancellation")
def log_cancellation(payload: CancellationRequest):
    return _finish(tool_service.log_cancellation(payload.customer_id, payload.reason))


@app.post("/api/tools/donotcall")
def mark_do_not_call(payload: DoNotCallRequest):
    return _finish(tool_service.mark_do_not_call(payload.customer_id, payload.reason))


@app.post("/api/tools/retry-mandate")
def retry_mandate(payload: CustomerToolRequest):
    return _finish(tool_service.retry_mandate(payload.customer_id))


@app.post("/api/tools/verify-caller")
def verify_caller(payload: CustomerToolRequest):
    return _finish(tool_service.send_app_verification(payload.customer_id))


@app.post("/api/tools/schedule-retry")
def schedule_retry(payload: CustomerToolRequest):
    return _finish(tool_service.schedule_retry(payload.customer_id, payload.reason))


@app.get("/pay/{ref}", response_class=HTMLResponse)
def checkout_page(ref: str):
    """Mock merchant checkout. Fictional demo only: no real money moves."""
    cust = _find_by_ref(ref)
    if cust is None:
        raise HTTPException(status_code=404, detail="Unknown payment reference")
    total = cust.amount_due + cust.late_fee
    return f"""<!doctype html><html><head><title>NexusCloud checkout</title></head><body>
<h1>NexusCloud secure checkout (demo)</h1>
<p>Customer: {cust.name} ({cust.customer_id})</p>
<p>Plan: {cust.plan_name}</p>
<p>Amount due: Rs.{cust.amount_due:.0f} + late fee Rs.{cust.late_fee:.0f} = Rs.{total:.0f}</p>
<p>Failure: {cust.failure_code.value}</p>
<form method="post" action="/api/pay/{ref.lower()}/complete"><button type="submit">Pay Rs.{total:.0f}</button></form>
<p><small>Demo checkout. No real payment is processed.</small></p>
</body></html>"""


@app.post("/api/pay/{ref}/complete")
def complete_payment(ref: str):
    cust = _find_by_ref(ref)
    if cust is None:
        raise HTTPException(status_code=404, detail="Unknown payment reference")
    cust.status = CustomerStatus.RESOLVED
    stamp(cust, "RECOVERED")
    db.update(cust)
    db.add_audit({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "customer_id": cust.customer_id,
        "tool": "checkout_complete",
        "arguments": {"ref": ref},
        "http_status": 200,
        "result_status": "success",
        "message": "Checkout completed. Invoice marked recovered.",
    })
    return {"status": "success", "customer_id": cust.customer_id, "final_status": "RESOLVED"}


def _find_by_ref(ref: str):
    for cust in db.list_customers():
        if checkout_ref(cust) == ref.lower():
            return cust
    return None


@app.post("/api/webhook/bolna")
def bolna_webhook(payload: dict):
    return apply_bolna_event(db, tool_service, payload)


@app.post("/api/calls/outbound")
def outbound_call(payload: OutboundCallRequest):
    """Place a real Bolna call. Guarded: key + agent required, phone allowlisted.

    The key stays server-side; the browser only sees execution IDs.
    """
    cust = db.get_customer(payload.customer_id)
    if cust is None:
        raise HTTPException(status_code=404, detail=f"Unknown customer: {payload.customer_id}")
    phone = _norm_phone(payload.phone)
    if not phone.startswith("+"):
        raise HTTPException(status_code=422, detail="Phone must be E.164, e.g. +917007623382")
    if app_config.CALL_ALLOWLIST and phone not in app_config.CALL_ALLOWLIST:
        raise HTTPException(status_code=403, detail="Number not in call allowlist")
    if not app_config.BOLNA_API_KEY or not app_config.BOLNA_AGENT_ID:
        raise HTTPException(status_code=503, detail="Live calling not configured on this server")
    from src.bolna_client import BolnaRecoveryClient

    try:
        res = BolnaRecoveryClient().trigger_outbound_call(
            agent_id=app_config.BOLNA_AGENT_ID, customer=cust, phone=phone
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bolna call failed: {exc}")
    eid = res.get("execution_id") or res.get("run_id") or ""
    return {"status": "queued", "execution_id": eid, "customer_id": cust.customer_id}


def _call_user_data(cust) -> dict:
    return {
        "customer_id": cust.customer_id,
        "customer_name": cust.name,
        "amount_due": cust.amount_due,
        "failure_code": cust.failure_code.value,
    }


@app.post("/api/calls/web-session")
def web_session(payload: WebSessionRequest):
    """Mint a Bolna browser-call session. No phone number. The key never leaves the server.

    user_data from the browser is not trusted. The ledger supplies the name,
    amount, and failure code for the chosen customer id.
    """
    requested = (payload.user_data or {}).get("customer_id")
    cust = db.get_customer(requested) if requested else None
    if cust is None:
        raise HTTPException(status_code=404, detail="Pick a customer from the table")
    if not app_config.BOLNA_API_KEY or not app_config.BOLNA_AGENT_ID:
        raise HTTPException(status_code=503, detail="Browser calling is not configured on this server")
    from src.bolna_client import BolnaRecoveryClient

    try:
        code, body = BolnaRecoveryClient().mint_web_session(app_config.BOLNA_AGENT_ID, _call_user_data(cust))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bolna session failed: {exc}")
    if code >= 400:
        detail = body.get("message") or body.get("detail") or "Bolna refused the browser session"
        if isinstance(detail, (dict, list)):
            detail = str(detail)
        raise HTTPException(status_code=502, detail=str(detail))
    return body


@app.get("/api/calls/{execution_id}")
def call_status(execution_id: str):
    """Trimmed live status for polling. Key stays server-side."""
    if not app_config.BOLNA_API_KEY:
        raise HTTPException(status_code=503, detail="Live calling not configured on this server")
    from src.bolna_client import BolnaRecoveryClient

    try:
        d = BolnaRecoveryClient().get_execution(execution_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bolna lookup failed: {exc}")
    tele = d.get("telephony_data") or {}
    return {
        "execution_id": execution_id,
        "status": d.get("status"),
        "conversation_duration": d.get("conversation_duration"),
        "total_cost": d.get("total_cost"),
        "transcript": d.get("transcript"),
        "recording_url": tele.get("recording_url"),
    }


@app.post("/api/simulate")
def simulate_endpoint(payload: SimulateRequest):
    from src.simulator import SCENARIO_UTTERANCES, DialogueSimulator

    speech = (payload.user_speech or "").strip()
    if not speech:
        speech = SCENARIO_UTTERANCES.get(payload.customer_id, "")
    sim = DialogueSimulator(tool_service)
    result = sim.simulate(payload.customer_id, user_speech=speech)
    return {
        "tool_called": result.tool_called,
        "agent_reply": result.agent_reply,
        "final_status": result.final_status.value if isinstance(result.final_status, CustomerStatus) else result.final_status,
    }
