"""Per-failure directions the voice agent is allowed to follow.

The intelligence layer can talk. This module decides which merchant actions
that talk is allowed to trigger.
"""
from src.models import FailureCode


class PlaybookEntry:
    def __init__(self, actions: tuple[str, ...], directions: str):
        self.actions = actions
        self.directions = directions


PLAYBOOK: dict[FailureCode, PlaybookEntry] = {
    FailureCode.CARD_EXPIRED: PlaybookEntry(
        ("send_payment_link", "mark_do_not_call"),
        "The card on file is expired. Send one fresh checkout link. Do not reschedule a dead card and do not waive a fee.",
    ),
    FailureCode.INSUFFICIENT_FUNDS: PlaybookEntry(
        ("reschedule_debit", "send_payment_link", "mark_do_not_call"),
        "The customer is short until salary day. Offer a reschedule within 14 days before offering a link. Do not threaten to cut service.",
    ),
    FailureCode.BANK_GATEWAY_TIMEOUT: PlaybookEntry(
        ("retry_mandate", "send_payment_link", "mark_do_not_call"),
        "The bank timed out. The customer likely has funds. Queue a mandate re-poll first. Send a link only if they would rather pay manually.",
    ),
    FailureCode.MANDATE_LIMIT_EXCEEDED: PlaybookEntry(
        ("send_payment_link", "mark_do_not_call"),
        "The invoice is above the e-mandate cap. Send a one-time checkout link for the full amount. Do not promise another auto-debit.",
    ),
    FailureCode.SUSPECTED_PHISHING: PlaybookEntry(
        ("send_app_verification", "send_payment_link", "mark_do_not_call"),
        "The customer thinks this call is a scam. Send an in-app verification and name the official domain pay.nexuscloud.io. Never ask for a card number, OTP, or password.",
    ),
    FailureCode.DISPUTED_CHARGE: PlaybookEntry(
        ("escalate_dispute", "mark_do_not_call"),
        "The bill is disputed. Open a dispute ticket and pause dunning. Do not collect the disputed amount on this call.",
    ),
    FailureCode.CANCELLATION_CLAIMED: PlaybookEntry(
        ("log_cancellation", "mark_do_not_call"),
        "The customer says they already cancelled. Log the cancellation and pause dunning. Do not argue and do not collect.",
    ),
    FailureCode.LATE_FEE_OBJECTION: PlaybookEntry(
        ("waive_late_fee", "send_payment_link", "mark_do_not_call"),
        "They object to the late fee, not the plan. Waive the late fee if policy still allows one waiver this year, then the principal can be paid by link. Never waive the principal.",
    ),
    FailureCode.HARD_REFUSAL_HOSTILE: PlaybookEntry(
        ("mark_do_not_call",),
        "The customer is hostile or refusing contact. Apologize, mark do-not-call, and end the call. Do not pitch a link.",
    ),
    FailureCode.VOICEMAIL_NO_ANSWER: PlaybookEntry(
        ("schedule_retry", "send_payment_link", "mark_do_not_call"),
        "Nobody is on the line. Schedule a retry. A payment link is allowed only as a low-pressure follow-up, never as a demand left on a recording.",
    ),
}


def allowed_actions(code: FailureCode) -> list[str]:
    return ["get_account", *PLAYBOOK[code].actions]


def directions_for(code: FailureCode) -> str:
    return PLAYBOOK[code].directions
