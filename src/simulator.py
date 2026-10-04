"""Scripted caller for offline tests. It picks a tool. The tool service decides if that tool is allowed."""
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from pydantic import BaseModel

from src.models import CustomerStatus
from src.tools import ToolService


class SimulationResult(BaseModel):
    tool_called: str
    agent_reply: str
    final_status: CustomerStatus


def _contains(text: str, *phrases: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def _detect_intent(text: str) -> str:
    if _contains(text, "stop calling", "never call", "do not call", "don't call", "do-not-call", "stop-calling"):
        return "mark_do_not_call"
    if _contains(text, "cancelled", "cancellation", "already cancel"):
        return "log_cancellation"
    if _contains(text, "dispute", "wrong bill", "bill is", "did not use", "didnt use", "licenses", "incorrect", "wrong charge"):
        return "escalate_dispute"
    if _contains(text, "waive", "late fee"):
        return "waive_late_fee"
    if _contains(text, "scam", "legit", "phishing", "official"):
        return "send_app_verification"
    if _contains(text, "retry the mandate", "retry the debit", "timed out", "re-poll", "bank timeout"):
        return "retry_mandate"
    if _contains(text, "voicemail", "no one is available", "answering machine", "leave a message"):
        return "schedule_retry"
    if _contains(text, "salary", "5th", "payday", "debit then", "debit on", "reschedule", "pay later", "next week"):
        return "reschedule_debit"
    if _contains(text, "payment link", "send me", "send link", "link", "card", "renewed", "checkout", "pay now"):
        return "send_payment_link"
    return "get_account"


def _next_day_of_month(today: date, day: int) -> str:
    candidate = today.replace(day=day)
    if candidate <= today:
        month = today.month + 1
        year = today.year
        if month == 13:
            month = 1
            year += 1
        candidate = date(year, month, day)
    return candidate.isoformat()


def _target_date(text: str, today: date) -> Optional[str]:
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    if _contains(text, "5th", "fifth", "salary"):
        return _next_day_of_month(today, 5)
    if _contains(text, "next week"):
        return (today + timedelta(days=7)).isoformat()
    return None


class DialogueSimulator:
    def __init__(self, service: Optional[ToolService] = None):
        self.service = service

    def _service(self) -> ToolService:
        if self.service is not None:
            return self.service
        from src.gateway import tool_service
        return tool_service

    def simulate(
        self,
        customer_id: str,
        user_inputs: Optional[List[str]] = None,
        user_speech: Optional[str] = None,
    ) -> SimulationResult:
        service = self._service()
        utterances: List[str] = []
        if user_inputs:
            utterances.extend(user_inputs)
        if user_speech:
            utterances.append(user_speech)
        text = " ".join(utterances)
        intent = _detect_intent(text)
        today = service._today()

        if intent == "send_payment_link":
            channel = "whatsapp" if "whatsapp" in text.lower() else "sms"
            result = service.send_link(customer_id, channel)
        elif intent == "reschedule_debit":
            result = service.reschedule(customer_id, _target_date(text, today))
        elif intent == "escalate_dispute":
            result = service.escalate_dispute(customer_id, summary=text[:500] or "Customer disputed the charge.")
        elif intent == "waive_late_fee":
            result = service.waive_fee(customer_id, reason="bank_processing_delay")
        elif intent == "log_cancellation":
            result = service.log_cancellation(customer_id, reason=text[:500])
        elif intent == "mark_do_not_call":
            result = service.mark_do_not_call(customer_id, reason=text[:500])
        elif intent == "retry_mandate":
            result = service.retry_mandate(customer_id)
        elif intent == "send_app_verification":
            result = service.send_app_verification(customer_id)
        elif intent == "schedule_retry":
            result = service.schedule_retry(customer_id, reason="voicemail")
        else:
            result = service.get_account(customer_id)

        customer = service.store.get_customer(customer_id)
        if customer is None:
            raise ValueError(f"Unknown customer: {customer_id}")
        return SimulationResult(
            tool_called=intent,
            agent_reply=result.message,
            final_status=customer.status,
        )


SCENARIO_UTTERANCES: Dict[str, str] = {
    "CUST-01": "Yes, my card got renewed, please send me a payment link.",
    "CUST-02": "I get salary on the 5th, can you debit then?",
    "CUST-03": "The bank timed out on their side. Please retry the mandate.",
    "CUST-04": "The amount exceeds my mandate limit. Send me a payment link to pay the rest.",
    "CUST-05": "Is this a scam? How do I know this call is legit?",
    "CUST-06": "I did not use these 5 licenses. This bill is completely wrong.",
    "CUST-07": "I already cancelled last week. Please log the cancellation.",
    "CUST-08": "The late fee was your bank delay. Please waive it.",
    "CUST-09": "Stop calling me! Never call this number again!",
    "CUST-10": "This is the voicemail box. No one is available.",
}


def run_all_scenarios() -> List[SimulationResult]:
    sim = DialogueSimulator()
    results = []
    for cid, utter in SCENARIO_UTTERANCES.items():
        results.append(sim.simulate(cid, user_inputs=[utter]))
    return results
