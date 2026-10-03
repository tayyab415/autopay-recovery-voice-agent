from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from src.models import CustomerRecord

class PolicyResult(BaseModel):
    allowed: bool
    error: Optional[str] = None
    data: Optional[dict] = None

class PolicyEngine:
    MAX_RESCHEDULE_DAYS = 14
    MAX_WAIVERS_ALLOWED = 1

    def validate_reschedule(
        self, customer: CustomerRecord, target_date_str: str, current_date: Optional[str] = None
    ) -> PolicyResult:
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except ValueError:
            return PolicyResult(allowed=False, error="Invalid date format. Expected YYYY-MM-DD.")

        ref_date = datetime.strptime(current_date, "%Y-%m-%d").date() if current_date else datetime.utcnow().date()
        
        if target_date <= ref_date:
            return PolicyResult(allowed=False, error="Reschedule date must be in the future.")
        
        if target_date > ref_date + timedelta(days=self.MAX_RESCHEDULE_DAYS):
            return PolicyResult(
                allowed=False,
                error=f"Debit reschedule cannot exceed {self.MAX_RESCHEDULE_DAYS} days from today. Please offer split checkout link."
            )

        return PolicyResult(allowed=True, data={"target_date": target_date_str})

    def validate_waiver(self, customer: CustomerRecord) -> PolicyResult:
        if customer.late_fee <= 0:
            return PolicyResult(allowed=False, error="No late fee exists to waive.")
        
        if customer.waivers_used >= self.MAX_WAIVERS_ALLOWED:
            return PolicyResult(
                allowed=False,
                error=f"Customer has already reached the maximum waiver limit ({self.MAX_WAIVERS_ALLOWED} per year)."
            )

        return PolicyResult(allowed=True, data={"waived_amount": customer.late_fee})
