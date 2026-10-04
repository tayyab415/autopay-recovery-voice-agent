from datetime import date

from src.disposition import add_business_days
from src.ledger import CustomerStore
from src.models import CustomerStatus, load_customers
from src.policy_engine import PolicyEngine
from src.simulator import DialogueSimulator, SCENARIO_UTTERANCES
from src.tools import ToolService

FIXED = date(2026, 10, 3)

EXPECTED = {
    "CUST-01": ("send_payment_link", CustomerStatus.LINK_SENT),
    "CUST-02": ("reschedule_debit", CustomerStatus.RESCHEDULED),
    "CUST-03": ("retry_mandate", CustomerStatus.RETRY_SCHEDULED),
    "CUST-04": ("send_payment_link", CustomerStatus.LINK_SENT),
    "CUST-05": ("send_app_verification", CustomerStatus.VERIFICATION_SENT),
    "CUST-06": ("escalate_dispute", CustomerStatus.DISPUTE_ESCALATED),
    "CUST-07": ("log_cancellation", CustomerStatus.CANCELLATION_LOGGED),
    "CUST-08": ("waive_late_fee", CustomerStatus.FEE_WAIVED),
    "CUST-09": ("mark_do_not_call", CustomerStatus.DO_NOT_CALL),
    "CUST-10": ("schedule_retry", CustomerStatus.RETRY_SCHEDULED),
}


def _simulator():
    store = CustomerStore(load_customers())
    service = ToolService(store, PolicyEngine(), push=lambda *args, **kwargs: False, today=FIXED)
    return store, DialogueSimulator(service)


def test_each_persona_hits_its_own_tool():
    store, sim = _simulator()
    for customer_id, utterance in SCENARIO_UTTERANCES.items():
        result = sim.simulate(customer_id, user_inputs=[utterance])
        tool, status = EXPECTED[customer_id]
        assert result.tool_called == tool, customer_id
        assert result.final_status == status, customer_id
        assert store.get_customer(customer_id).status == status


def test_salary_reschedule_uses_the_fifth():
    store, sim = _simulator()
    sim.simulate("CUST-02", user_inputs=[SCENARIO_UTTERANCES["CUST-02"]])
    assert store.get_customer("CUST-02").scheduled_debit_date == "2026-10-05"


def test_dispute_opens_one_ticket_and_pauses_dunning():
    store, sim = _simulator()
    sim.simulate("CUST-06", user_inputs=[SCENARIO_UTTERANCES["CUST-06"]])
    customer = store.get_customer("CUST-06")
    assert customer.support_ticket_id == "NC-CUST-06-1"
    assert customer.dunning_paused_until == add_business_days(FIXED, 10).isoformat()
    assert "Do not ask for payment" in sim.simulate("CUST-06", user_inputs=["the bill is still wrong"]).agent_reply


def test_disputed_customer_cannot_be_sent_a_link():
    store, sim = _simulator()
    result = sim.simulate("CUST-06", user_inputs=["please send me a payment link"])
    assert result.tool_called == "send_payment_link"
    assert "not allowed" in result.agent_reply
    assert "escalate_dispute" in result.agent_reply
    assert store.get_customer("CUST-06").status == CustomerStatus.PENDING


def test_card_expired_link_names_the_official_domain():
    _, sim = _simulator()
    result = sim.simulate("CUST-01", user_inputs=[SCENARIO_UTTERANCES["CUST-01"]])
    assert "pay.nexuscloud.io" in result.agent_reply


def test_late_fee_is_waived_once_and_principal_remains():
    store, sim = _simulator()
    sim.simulate("CUST-08", user_inputs=[SCENARIO_UTTERANCES["CUST-08"]])
    customer = store.get_customer("CUST-08")
    assert customer.waivers_used == 1
    assert customer.late_fee == 0
    assert customer.amount_due == 6200.0
