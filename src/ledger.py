"""In-memory merchant ledger plus an audit log of every tool call."""
from typing import Dict, List, Optional
import threading

from src.models import CustomerRecord, load_customers


class CustomerStore:
    def __init__(self, customers: Optional[List[CustomerRecord]] = None):
        self._lock = threading.Lock()
        seed = customers if customers is not None else load_customers()
        self._customers: Dict[str, CustomerRecord] = {c.customer_id: c for c in seed}
        self._audit: List[dict] = []
        self._messages: List[dict] = []

    def list_customers(self) -> List[CustomerRecord]:
        with self._lock:
            return list(self._customers.values())

    def get_customer(self, customer_id: str) -> Optional[CustomerRecord]:
        with self._lock:
            return self._customers.get(customer_id)

    def update(self, customer: CustomerRecord) -> None:
        with self._lock:
            self._customers[customer.customer_id] = customer

    def add_audit(self, entry: dict) -> None:
        with self._lock:
            self._audit.append(entry)

    def audit_for(self, customer_id: str) -> List[dict]:
        with self._lock:
            return [row for row in self._audit if row.get("customer_id") == customer_id]

    def add_message(self, entry: dict) -> None:
        with self._lock:
            self._messages.append(entry)

    def messages_for(self, customer_id: str) -> List[dict]:
        with self._lock:
            return [row for row in self._messages if row.get("customer_id") == customer_id]


db = CustomerStore()
