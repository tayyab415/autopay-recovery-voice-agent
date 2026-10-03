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
    recording_url: Optional[str] = None
    created_at: str = "2026-10-01T09:00:00Z"

def load_customers(path: Optional[Path] = None) -> List[CustomerRecord]:
    file_path = path or (DATA_DIR / "customers.json")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [CustomerRecord(**c) for c in data]
