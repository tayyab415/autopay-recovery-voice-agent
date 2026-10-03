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
