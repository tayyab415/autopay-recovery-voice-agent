"""Offline deterministic dialogue simulator (test path; no live Bolna calls)."""
from typing import Dict, List, Optional

from pydantic import BaseModel

from src.models import CustomerRecord, CustomerStatus


class SimulationResult(BaseModel):
    tool_called: str
    agent_reply: str
    final_status: CustomerStatus


def _contains(text: str, *phrases: str) -> bool:
    t = text.lower()
    return any(p in t for p in phrases)


def _detect_intent(text: str) -> str:
    # Priority: do-not-call and dispute first (must win over link keywords).
    if _contains(text, "stop calling", "never call", "do not call", "don't call", "do-not-call", "stop-calling"):
        return "mark_do_not_call"
    if _contains(text, "dispute", "wrong bill", "bill is", "did not use", "didnt use", "licenses", "incorrect", "wrong charge"):
        return "escalate_dispute"
    if _contains(text, "salary", "5th", "payday", "debit then", "debit on", "reschedule", "pay later", "next week"):
        return "reschedule_debit"
    if _contains(text, "payment link", "send me", "send link", "link", "card", "renewed", "checkout", "pay now"):
        return "send_payment_link"
    return "send_payment_link"


def _payment_link(customer: CustomerRecord) -> str:
    return f"https://pay.nexuscloud.io/p/{customer.customer_id.lower()}-{customer.payment_method_last4}"


class DialogueSimulator:
    def simulate(
        self,
        customer_id: str,
        user_inputs: Optional[List[str]] = None,
        user_speech: Optional[str] = None,
    ) -> SimulationResult:
        # Import here to avoid circular import at module load (gateway lazily imports simulator).
        from src.gateway import db

        utterances: List[str] = []
        if user_inputs:
            utterances.extend(user_inputs)
        if user_speech:
            utterances.append(user_speech)
        text = " ".join(utterances)

        customer = db.get_customer(customer_id)
        if customer is None:
            raise ValueError(f"Unknown customer: {customer_id}")

        intent = _detect_intent(text)

        if intent == "send_payment_link":
            customer.status = CustomerStatus.LINK_SENT
            db.update(customer)
            link = _payment_link(customer)
            reply = f"Thanks {customer.name}! I've sent a secure payment link via SMS: {link}. It covers Rs.{customer.amount_due:.0f}."
            return SimulationResult(tool_called="send_payment_link", agent_reply=reply, final_status=CustomerStatus.LINK_SENT)

        if intent == "reschedule_debit":
            customer.status = CustomerStatus.RESCHEDULED
            db.update(customer)
            reply = f"Got it {customer.name} — I've rescheduled your debit of Rs.{customer.amount_due:.0f} to your salary date (the 5th)."
            return SimulationResult(tool_called="reschedule_debit", agent_reply=reply, final_status=CustomerStatus.RESCHEDULED)

        if intent == "escalate_dispute":
            customer.status = CustomerStatus.DISPUTE_ESCALATED
            customer.disposition_notes = text[:2000]
            db.update(customer)
            reply = f"I'm sorry about the billing error, {customer.name}. I've escalated this dispute to our billing team; they'll review it within 24 hours."
            return SimulationResult(tool_called="escalate_dispute", agent_reply=reply, final_status=CustomerStatus.DISPUTE_ESCALATED)

        # mark_do_not_call
        customer.status = CustomerStatus.DO_NOT_CALL
        db.update(customer)
        reply = f"Understood {customer.name} — we won't call this number again. Sorry for the trouble."
        return SimulationResult(tool_called="mark_do_not_call", agent_reply=reply, final_status=CustomerStatus.DO_NOT_CALL)


SCENARIO_UTTERANCES: Dict[str, str] = {
    "CUST-01": "Yes, my card got renewed, please send me a payment link.",
    "CUST-02": "I get salary on the 5th, can you debit then?",
    "CUST-03": "My bank app timed out — please send me a payment link.",
    "CUST-04": "The amount exceeds my mandate limit — send me a payment link to pay the rest.",
    "CUST-05": "How do I know this is legit? Send me an official payment link.",
    "CUST-06": "I did not use these 5 licenses. This bill is completely wrong.",
    "CUST-07": "I already cancelled — log it and escalate this dispute.",
    "CUST-08": "The late fee was your bank delay — please waive it, or send a fresh payment link.",
    "CUST-09": "Stop calling me! Never call this number again!",
    "CUST-10": "I missed your call — please send me a payment link.",
}


def run_all_scenarios() -> List[SimulationResult]:
    sim = DialogueSimulator()
    results = []
    for cid, utter in SCENARIO_UTTERANCES.items():
        results.append(sim.simulate(cid, user_inputs=[utter]))
    return results
