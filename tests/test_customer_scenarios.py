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
