"""Merchant tools. Bolna, the console, and the offline simulator all call this.

Every method returns a speakable message. Policy rejections are the
directions the voice model has to say next. They are not silent 500s.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from src.config import PUBLIC_BASE_URL
from src.disposition import add_business_days, stamp, utc_today
from src.ledger import CustomerStore
from src.models import CustomerRecord, CustomerStatus, FailureCode
from src.playbook import allowed_actions, directions_for
from src.policy_engine import PolicyEngine

PAY_LINK_DOMAIN = "pay.nexuscloud.io"
PushFn = Callable[..., bool]


class ToolResult:
    def __init__(self, http_status: int, body: dict):
        self.http_status = http_status
        self.body = body

    @property
    def message(self) -> str:
        return str(self.body.get("message", ""))


def checkout_ref(customer: CustomerRecord) -> str:
    return f"{customer.customer_id.lower()}-{customer.payment_method_last4}"


def payment_link(customer: CustomerRecord) -> str:
    return f"https://{PAY_LINK_DOMAIN}/p/{checkout_ref(customer)}"


def checkout_url(customer: CustomerRecord) -> str:
    ref = checkout_ref(customer)
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/pay/{ref}"
    return f"/pay/{ref}"


class ToolService:
    def __init__(
        self,
        store: CustomerStore,
        engine: Optional[PolicyEngine] = None,
        push: Optional[PushFn] = None,
        today: Optional[date] = None,
    ):
        self.store = store
        self.engine = engine or PolicyEngine()
        self.push = push or (lambda *args, **kwargs: False)
        self.today = today

    def _today(self) -> date:
        return self.today or utc_today()

    def _require(self, customer_id: str) -> Optional[CustomerRecord]:
        return self.store.get_customer(customer_id)

    def _missing(self, customer_id: str, tool: str) -> ToolResult:
        return ToolResult(404, {
            "status": "rejected",
            "tool": tool,
            "customer_id": customer_id,
            "duplicate": False,
            "message": f"Unknown customer: {customer_id}",
        })

    def _audit(self, customer_id: str, tool: str, arguments: dict, result: ToolResult) -> ToolResult:
        result_status = "duplicate" if result.body.get("duplicate") else result.body.get("status", "rejected")
        self.store.add_audit({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "customer_id": customer_id,
            "tool": tool,
            "arguments": arguments,
            "http_status": result.http_status,
            "result_status": result_status,
            "message": result.message,
        })
        return result

    def _ok(self, customer: CustomerRecord, tool: str, message: str, extra: Optional[dict] = None, duplicate: bool = False) -> ToolResult:
        body = {
            "status": "success",
            "tool": tool,
            "customer_id": customer.customer_id,
            "duplicate": duplicate,
            "message": message,
        }
        if extra:
            body.update(extra)
        return ToolResult(200, body)

    def _reject(self, customer: CustomerRecord, tool: str, message: str, extra: Optional[dict] = None, http_status: int = 422) -> ToolResult:
        body = {
            "status": "rejected",
            "tool": tool,
            "customer_id": customer.customer_id,
            "duplicate": False,
            "message": message,
            "allowed_actions": allowed_actions(customer.failure_code),
        }
        if extra:
            body.update(extra)
        return ToolResult(http_status, body)

    def _hold_outcome(self, customer: CustomerRecord, tool: str) -> Optional[ToolResult]:
        protected = {
            CustomerStatus.LINK_SENT,
            CustomerStatus.RESCHEDULED,
            CustomerStatus.FEE_WAIVED,
            CustomerStatus.DISPUTE_ESCALATED,
            CustomerStatus.CANCELLATION_LOGGED,
            CustomerStatus.VERIFICATION_SENT,
        }
        if customer.status in protected:
            return self._reject(
                customer, tool,
                f"This account is already {customer.status.value}. Do not replace that outcome with {tool}.",
            )
        return None

    def _guard(self, customer: CustomerRecord, tool: str) -> Optional[ToolResult]:
        if customer.status == CustomerStatus.DO_NOT_CALL and tool != "get_account":
            return self._reject(
                customer, tool,
                "This account is marked do-not-call. Do not attempt collection. End the call.",
            )
        if customer.status == CustomerStatus.RESOLVED and tool != "get_account":
            return self._reject(
                customer, tool,
                "This invoice is already paid. Do not send another link or change the debit.",
            )
        if tool in {"get_account", "schedule_retry"}:
            return None
        if tool not in allowed_actions(customer.failure_code):
            actions = ", ".join(allowed_actions(customer.failure_code))
            return self._reject(
                customer, tool,
                f"That action is not allowed for {customer.failure_code.value}. "
                f"Allowed actions: {actions}. {directions_for(customer.failure_code)}",
            )
        return None

    def get_account(self, customer_id: str) -> ToolResult:
        customer = self._require(customer_id)
        if customer is None:
            return self._audit(customer_id, "get_account", {}, self._missing(customer_id, "get_account"))
        actions = allowed_actions(customer.failure_code)
        directions = directions_for(customer.failure_code)
        waivers_remaining = max(0, self.engine.MAX_WAIVERS_ALLOWED - customer.waivers_used)
        body_extra = {
            "name": customer.name,
            "failure_code": customer.failure_code.value,
            "failure_reason": customer.failure_reason,
            "amount_due": customer.amount_due,
            "late_fee": customer.late_fee,
            "currency": customer.currency,
            "account_status": customer.status.value,
            "allowed_actions": actions,
            "directions": directions,
            "waivers_remaining": waivers_remaining,
            "reschedule_limit_days": self.engine.MAX_RESCHEDULE_DAYS,
            "scheduled_debit_date": customer.scheduled_debit_date,
            "support_ticket_id": customer.support_ticket_id,
            "dunning_paused_until": customer.dunning_paused_until,
            "last_disposition": customer.last_disposition,
        }
        result = self._ok(customer, "get_account", directions, body_extra)
        return self._audit(customer_id, "get_account", {}, result)

    def send_link(self, customer_id: str, channel: str = "sms", resend: bool = False) -> ToolResult:
        tool = "send_payment_link"
        customer = self._require(customer_id)
        if customer is None:
            return self._audit(customer_id, tool, {"channel": channel}, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, {"channel": channel, "resend": resend}, blocked)

        channel = (channel or "sms").lower()
        if channel not in {"sms", "whatsapp", "push"}:
            result = self._reject(customer, tool, "Channel must be sms, whatsapp, or push.")
            return self._audit(customer_id, tool, {"channel": channel}, result)

        short_url = payment_link(customer)
        checkout = checkout_url(customer)
        same_channel = customer.last_link_channel == channel and customer.status == CustomerStatus.LINK_SENT
        if same_channel and not _as_bool(resend):
            result = self._ok(customer, tool, (
                f"A payment link was already sent via {channel}. Do not send another. "
                f"The existing link is {short_url}."
            ), {
                "short_url": short_url,
                "checkout_url": checkout,
                "push_sent": False,
                "expires_at": customer.link_expires_at,
                "channel": channel,
            }, duplicate=True)
            return self._audit(customer_id, tool, {"channel": channel, "resend": False}, result)

        total = customer.amount_due + customer.late_fee
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        note = ""
        if customer.failure_code == FailureCode.MANDATE_LIMIT_EXCEEDED:
            note = " This is a one-time checkout because the invoice is above the e-mandate cap."
        sms_body = (
            f"Hi {customer.name}, your autopay of Rs.{total:.0f} failed ({customer.failure_code.value}). "
            f"Pay securely: {checkout}"
        )
        pushed = bool(self.push(f"NexusCloud autopay Rs.{total:.0f}", sms_body))
        self.store.add_message({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "customer_id": customer.customer_id,
            "channel": "whatsapp" if channel == "whatsapp" else "sms",
            "sender": "NexusCloud",
            "body": sms_body,
            "checkout_url": checkout,
        })
        customer.status = CustomerStatus.LINK_SENT
        customer.last_link_channel = channel
        customer.link_expires_at = expires
        stamp(customer, "LINK_SENT", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, (
            f"Payment link sent via {channel}. The customer can pay Rs.{total:.0f} at {short_url}. "
            f"It expires in 24 hours.{note}"
        ), {
            "short_url": short_url,
            "checkout_url": checkout,
            "push_sent": pushed,
            "expires_at": expires,
            "channel": channel,
        })
        return self._audit(customer_id, tool, {"channel": channel, "resend": _as_bool(resend)}, result)

    def reschedule(self, customer_id: str, target_date: Optional[str]) -> ToolResult:
        tool = "reschedule_debit"
        customer = self._require(customer_id)
        args = {"target_date": target_date}
        if customer is None:
            return self._audit(customer_id, tool, args, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, args, blocked)
        if not target_date:
            result = self._reject(
                customer, tool,
                "Ask which date they want, then call reschedule_debit with target_date as YYYY-MM-DD. "
                "The date must be within 14 days. Do not invent a date.",
            )
            return self._audit(customer_id, tool, args, result)
        if customer.status == CustomerStatus.RESCHEDULED and customer.scheduled_debit_date == target_date:
            result = self._ok(customer, tool, (
                f"The auto-debit is already rescheduled to {target_date}. Confirm that date and do not book it again."
            ), {"target_date": target_date}, duplicate=True)
            return self._audit(customer_id, tool, args, result)

        decision = self.engine.validate_reschedule(customer, target_date, current_date=self._today().isoformat())
        if not decision.allowed:
            result = self._reject(customer, tool, decision.error or "Reschedule rejected.")
            return self._audit(customer_id, tool, args, result)

        customer.status = CustomerStatus.RESCHEDULED
        customer.scheduled_debit_date = target_date
        stamp(customer, "RESCHEDULED", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, (
            f"Auto-debit of Rs.{customer.amount_due:.0f} is rescheduled to {target_date}. Confirm that date and nothing else."
        ), {"target_date": target_date})
        return self._audit(customer_id, tool, args, result)

    def waive_fee(self, customer_id: str, reason: Optional[str] = None, waive_principal: bool = False) -> ToolResult:
        tool = "waive_late_fee"
        customer = self._require(customer_id)
        args = {"reason": reason, "waive_principal": waive_principal}
        if customer is None:
            return self._audit(customer_id, tool, args, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, args, blocked)
        if _as_bool(waive_principal):
            result = self._reject(customer, tool, "Principal subscription amount cannot be waived. Only the late fee is eligible, and only once a year.")
            return self._audit(customer_id, tool, args, result)
        if customer.status == CustomerStatus.FEE_WAIVED or customer.waivers_used >= self.engine.MAX_WAIVERS_ALLOWED:
            result = self._reject(
                customer, tool,
                "Late fee was already waived. Customer has already reached the maximum waiver limit (1 per year). Do not grant another.",
            )
            return self._audit(customer_id, tool, args, result)

        decision = self.engine.validate_waiver(customer)
        if not decision.allowed:
            result = self._reject(customer, tool, decision.error or "Waiver rejected.")
            return self._audit(customer_id, tool, args, result)

        waived = customer.late_fee
        customer.waivers_used += 1
        customer.late_fee = 0
        customer.status = CustomerStatus.FEE_WAIVED
        stamp(customer, "FEE_WAIVED", self._today())
        self.store.update(customer)
        why = f" Reason recorded: {reason}." if reason else ""
        result = self._ok(customer, tool, (
            f"Late fee of Rs.{waived:.0f} is waived.{why} One waiver per year has been used. "
            f"The remaining balance is Rs.{customer.amount_due:.0f}."
        ), {"waived_amount": waived})
        return self._audit(customer_id, tool, args, result)

    def escalate_dispute(self, customer_id: str, summary: Optional[str] = None, dispute_type: str = "billing_error") -> ToolResult:
        tool = "escalate_dispute"
        customer = self._require(customer_id)
        args = {"summary": summary, "dispute_type": dispute_type}
        if customer is None:
            return self._audit(customer_id, tool, args, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, args, blocked)
        if customer.status == CustomerStatus.DISPUTE_ESCALATED and customer.support_ticket_id:
            result = self._ok(customer, tool, (
                f"Dispute ticket {customer.support_ticket_id} is already open. Dunning stays paused until {customer.dunning_paused_until}. Do not ask for payment."
            ), {"support_ticket_id": customer.support_ticket_id, "dunning_paused_until": customer.dunning_paused_until}, duplicate=True)
            return self._audit(customer_id, tool, args, result)
        if not (summary or "").strip():
            result = self._reject(customer, tool, "Ask what is wrong with the bill, then call escalate_dispute with that summary. Do not collect meanwhile.")
            return self._audit(customer_id, tool, args, result)

        ticket = customer.support_ticket_id or f"NC-{customer.customer_id}-1"
        paused = add_business_days(self._today(), 10).isoformat()
        customer.support_ticket_id = ticket
        customer.dunning_paused_until = paused
        customer.disposition_notes = summary.strip()[:2000]
        customer.status = CustomerStatus.DISPUTE_ESCALATED
        stamp(customer, "DISPUTE_ESCALATED", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, (
            f"Dispute ticket {ticket} is open ({dispute_type}). Dunning is paused until {paused}. Do not ask for payment on this call."
        ), {"support_ticket_id": ticket, "dunning_paused_until": paused, "dispute_type": dispute_type})
        return self._audit(customer_id, tool, args, result)

    def log_cancellation(self, customer_id: str, reason: Optional[str] = None) -> ToolResult:
        tool = "log_cancellation"
        customer = self._require(customer_id)
        args = {"reason": reason}
        if customer is None:
            return self._audit(customer_id, tool, args, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, args, blocked)
        if customer.status == CustomerStatus.CANCELLATION_LOGGED and customer.support_ticket_id:
            result = self._ok(customer, tool, (
                f"Cancellation ticket {customer.support_ticket_id} is already logged. Dunning stays paused until {customer.dunning_paused_until}. Do not collect."
            ), {"support_ticket_id": customer.support_ticket_id, "dunning_paused_until": customer.dunning_paused_until}, duplicate=True)
            return self._audit(customer_id, tool, args, result)

        ticket = customer.support_ticket_id or f"NC-{customer.customer_id}-CANCEL"
        paused = add_business_days(self._today(), 10).isoformat()
        customer.support_ticket_id = ticket
        customer.dunning_paused_until = paused
        if reason:
            customer.disposition_notes = reason.strip()[:2000]
        customer.status = CustomerStatus.CANCELLATION_LOGGED
        stamp(customer, "CANCELLATION_LOGGED", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, (
            f"Cancellation ticket {ticket} is logged. Dunning is paused until {paused}. Do not argue and do not collect."
        ), {"support_ticket_id": ticket, "dunning_paused_until": paused})
        return self._audit(customer_id, tool, args, result)

    def mark_do_not_call(self, customer_id: str, reason: Optional[str] = None) -> ToolResult:
        tool = "mark_do_not_call"
        customer = self._require(customer_id)
        args = {"reason": reason}
        if customer is None:
            return self._audit(customer_id, tool, args, self._missing(customer_id, tool))
        if customer.status == CustomerStatus.RESOLVED:
            blocked = self._guard(customer, tool)
            return self._audit(customer_id, tool, args, blocked)
        if customer.status == CustomerStatus.DO_NOT_CALL:
            result = self._ok(customer, tool, "Account is already marked do-not-call. Apologize if needed and end the call.", duplicate=True)
            return self._audit(customer_id, tool, args, result)
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, args, blocked)
        customer.status = CustomerStatus.DO_NOT_CALL
        if reason:
            customer.disposition_notes = reason.strip()[:2000]
        stamp(customer, "DNC_REQUESTED", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, "Account marked do-not-call. Apologize and end the call now. Do not offer a payment link.")
        return self._audit(customer_id, tool, args, result)

    def retry_mandate(self, customer_id: str) -> ToolResult:
        tool = "retry_mandate"
        customer = self._require(customer_id)
        if customer is None:
            return self._audit(customer_id, tool, {}, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, {}, blocked)
        held = self._hold_outcome(customer, tool)
        if held:
            return self._audit(customer_id, tool, {}, held)
        if customer.last_disposition == "MANDATE_REQUEUED":
            result = self._ok(
                customer, tool,
                "A mandate re-poll is already queued. Tell the customer they do not need to do anything.",
                duplicate=True,
            )
            return self._audit(customer_id, tool, {}, result)
        customer.status = CustomerStatus.RETRY_SCHEDULED
        stamp(customer, "MANDATE_REQUEUED", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, "Queued an immediate re-poll of the bank mandate. The customer does not need to do anything.")
        return self._audit(customer_id, tool, {}, result)

    def send_app_verification(self, customer_id: str) -> ToolResult:
        tool = "send_app_verification"
        customer = self._require(customer_id)
        if customer is None:
            return self._audit(customer_id, tool, {}, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, {}, blocked)
        if customer.status == CustomerStatus.VERIFICATION_SENT:
            result = self._ok(
                customer, tool,
                "An in-app verification was already sent. The only official domain is pay.nexuscloud.io. Do not ask for card numbers, OTPs, or passwords.",
                duplicate=True,
            )
            return self._audit(customer_id, tool, {}, result)
        verify_body = (
            f"Hi {customer.name}, NexusCloud is on a call about your autopay. "
            f"Confirm it in the app. Official domain: {PAY_LINK_DOMAIN}."
        )
        self.push("NexusCloud call verification", verify_body)
        self.store.add_message({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "customer_id": customer.customer_id,
            "channel": "sms",
            "sender": "NexusCloud",
            "body": verify_body,
            "checkout_url": None,
        })
        customer.status = CustomerStatus.VERIFICATION_SENT
        stamp(customer, "VERIFICATION_SENT", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, (
            "Sent an in-app verification. Tell them the only official domain is pay.nexuscloud.io. "
            "Do not ask for card numbers, OTPs, or passwords."
        ))
        return self._audit(customer_id, tool, {}, result)

    def schedule_retry(self, customer_id: str, reason: Optional[str] = None) -> ToolResult:
        tool = "schedule_retry"
        customer = self._require(customer_id)
        args = {"reason": reason}
        if customer is None:
            return self._audit(customer_id, tool, args, self._missing(customer_id, tool))
        blocked = self._guard(customer, tool)
        if blocked:
            return self._audit(customer_id, tool, args, blocked)
        held = self._hold_outcome(customer, tool)
        if held:
            return self._audit(customer_id, tool, args, held)
        when = (self._today() + timedelta(days=1)).isoformat()
        if customer.status == CustomerStatus.RETRY_SCHEDULED and customer.next_touch_at == when and customer.last_disposition == "RETRY_SCHEDULED":
            result = self._ok(customer, tool, f"A retry is already scheduled for {when}.", {"next_touch_at": when}, duplicate=True)
            return self._audit(customer_id, tool, args, result)
        customer.status = CustomerStatus.RETRY_SCHEDULED
        if reason:
            customer.disposition_notes = reason.strip()[:2000]
        stamp(customer, "RETRY_SCHEDULED", self._today())
        self.store.update(customer)
        result = self._ok(customer, tool, (
            f"No conversation happened. A retry is scheduled for {customer.next_touch_at}. Do not leave a payment demand."
        ), {"next_touch_at": customer.next_touch_at})
        return self._audit(customer_id, tool, args, result)


def _as_bool(value) -> bool:
    return str(value).lower() in {"1", "true", "yes"}
