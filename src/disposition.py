"""Turn a finished call, or a tool result, into a merchant disposition."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from src.models import CustomerRecord, CustomerStatus

NO_ANSWER_STATUSES = {"no-answer", "no_answer", "busy", "voicemail", "failed"}
COMPLETED_STATUSES = {
    "completed",
    "call-disconnected",
    "call_disconnected",
    "disconnected",
    *NO_ANSWER_STATUSES,
}

PROBABILITY = {
    "LINK_SENT": 0.55,
    "RESCHEDULED": 0.7,
    "FEE_WAIVED": 0.75,
    "RECOVERED": 1.0,
    "DISPUTE_ESCALATED": 0.15,
    "CANCELLATION_LOGGED": 0.05,
    "DNC_REQUESTED": 0.0,
    "RETRY_SCHEDULED": 0.35,
    "MANDATE_REQUEUED": 0.8,
    "VERIFICATION_SENT": 0.4,
    "NO_COMMITMENT": 0.2,
}

STATUS_TO_DISPOSITION = {
    CustomerStatus.LINK_SENT.value: "LINK_SENT",
    CustomerStatus.RESCHEDULED.value: "RESCHEDULED",
    CustomerStatus.FEE_WAIVED.value: "FEE_WAIVED",
    CustomerStatus.RESOLVED.value: "RECOVERED",
    CustomerStatus.DISPUTE_ESCALATED.value: "DISPUTE_ESCALATED",
    CustomerStatus.CANCELLATION_LOGGED.value: "CANCELLATION_LOGGED",
    CustomerStatus.DO_NOT_CALL.value: "DNC_REQUESTED",
    CustomerStatus.RETRY_SCHEDULED.value: "RETRY_SCHEDULED",
    CustomerStatus.VERIFICATION_SENT.value: "VERIFICATION_SENT",
    CustomerStatus.PENDING.value: "NO_COMMITMENT",
}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def add_business_days(start: date, days: int) -> date:
    current = start
    left = days
    while left > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            left -= 1
    return current


def next_touch(customer: CustomerRecord, disposition: str, today: date) -> Optional[str]:
    if disposition in {"DNC_REQUESTED", "RECOVERED"}:
        return None
    if disposition == "RESCHEDULED" and customer.scheduled_debit_date:
        return customer.scheduled_debit_date
    if disposition in {"DISPUTE_ESCALATED", "CANCELLATION_LOGGED"} and customer.dunning_paused_until:
        return customer.dunning_paused_until
    return (today + timedelta(days=1)).isoformat()


def stamp(customer: CustomerRecord, disposition: str, today: Optional[date] = None) -> None:
    day = today or utc_today()
    customer.last_disposition = disposition
    customer.recovery_probability = PROBABILITY.get(disposition, 0.2)
    customer.next_touch_at = next_touch(customer, disposition, day)


def apply_bolna_event(store, service, payload: dict, today: Optional[date] = None) -> dict:
    """Record a Bolna webhook against the ledger. Tool results already on the
    account win over the raw call status. A missed call schedules a retry
    only when nobody has committed to an outcome yet.
    """
    day = today or utc_today()
    status = str(payload.get("status", "")).lower()
    execution_id = payload.get("execution_id")
    user_data = payload.get("user_data") or {}
    customer_id = user_data.get("customer_id")
    if customer_id is None:
        user_number = payload.get("user_number")
        if user_number:
            for row in store.list_customers():
                if row.phone == user_number:
                    customer_id = row.customer_id
                    break

    if customer_id is None or status not in COMPLETED_STATUSES:
        return {"status": "ok", "disposition": None}

    customer = store.get_customer(customer_id)
    if customer is None:
        return {"status": "ok", "disposition": None}

    if execution_id:
        customer.last_call_id = execution_id
    transcript = payload.get("transcript")
    telephony = payload.get("telephony_data") or {}
    if telephony.get("recording_url"):
        customer.recording_url = telephony["recording_url"]
    store.update(customer)

    if status in NO_ANSWER_STATUSES and customer.status == CustomerStatus.PENDING:
        service.schedule_retry(customer.customer_id, reason=status or "no-answer")
        customer = store.get_customer(customer_id)

    if transcript:
        customer.disposition_notes = str(transcript)[:2000]

    name = customer.last_disposition or STATUS_TO_DISPOSITION.get(customer.status.value, "NO_COMMITMENT")
    stamp(customer, name, day)
    store.update(customer)
    return {
        "status": "ok",
        "customer_id": customer.customer_id,
        "disposition": customer.last_disposition,
        "recovery_probability": customer.recovery_probability,
        "next_touch_at": customer.next_touch_at,
    }
