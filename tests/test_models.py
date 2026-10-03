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
