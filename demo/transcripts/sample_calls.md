# Sample Calls — OFFLINE SIMULATED TRANSCRIPTS

> **Notice:** These dialogues were generated **offline** by `src/simulator.py`
> (`DialogueSimulator`) without placing any live phone calls.
> `simulated_offline: true` — see `demo/recordings.json`.
> No live Bolna execution IDs or recording URLs exist for this batch.

## CUST-01 — Priya Sharma (CARD_EXPIRED → send_payment_link)

- **Customer:** Yes, my card got renewed, please send me a payment link.
- **Agent [send_payment_link]:** Thanks Priya Sharma! I've sent a secure payment link via SMS: https://pay.nexuscloud.io/p/cust-01-4521. It covers Rs.12499.
- **Final status:** LINK_SENT

## CUST-02 — Rahul Verma (INSUFFICIENT_FUNDS → reschedule_debit)

- **Customer:** I get salary on the 5th, can you debit then?
- **Agent [reschedule_debit]:** Rescheduled the Rs.4999 debit to the salary date (the 5th, within the 14-day policy window).
- **Final status:** RESCHEDULED

## CUST-03 — Ananya Iyer (BANK_GATEWAY_TIMEOUT → send_payment_link)

- **Customer:** My bank app timed out — please send me a payment link.
- **Agent [send_payment_link]:** Fresh checkout link issued; bank-side timeout needs no dispute.
- **Final status:** LINK_SENT

## CUST-04 — Vikram Patel (MANDATE_LIMIT_EXCEEDED → send_payment_link)

- **Customer:** The amount exceeds my mandate limit — send me a payment link to pay the rest.
- **Agent [send_payment_link]:** Split checkout link for the over-cap Rs.24999 invoice.
- **Final status:** LINK_SENT

## CUST-05 — Sneha Kulkarni (SUSPECTED_PHISHING → send_payment_link)

- **Customer:** How do I know this is legit? Send me an official payment link.
- **Agent [send_payment_link]:** Trust anchored on the official `pay.nexuscloud.io` domain link.
- **Final status:** LINK_SENT

## CUST-06 — Arjun Mehta (DISPUTED_CHARGE → escalate_dispute)

- **Customer:** I did not use these 5 licenses. This bill is completely wrong.
- **Agent [escalate_dispute]:** Dispute escalated to the billing team for 24h review; no payment pushed.
- **Final status:** DISPUTE_ESCALATED

## CUST-07 — Rohit Roy (CANCELLATION_CLAIMED → escalate_dispute)

- **Customer:** I already cancelled — log it and escalate this dispute.
- **Agent [escalate_dispute]:** Cancellation claim logged and escalated; no retry scheduled.
- **Final status:** DISPUTE_ESCALATED

## CUST-08 — Pooja Nair (LATE_FEE_OBJECTION → send_payment_link / waive_late_fee eligible)

- **Customer:** The late fee was your bank delay — please waive it, or send a fresh payment link.
- **Agent:** Rs.350 fee is waivable once per year (`POST /api/tools/waive-fee`); fresh link as fallback.
- **Final status:** LINK_SENT (simulated default; waiver path verified in `test_policy_engine.py`)

## CUST-09 — Harish Reddy (HARD_REFUSAL_HOSTILE → mark_do_not_call)

- **Customer:** Stop calling me! Never call this number again!
- **Agent [mark_do_not_call]:** Do-not-call honored immediately; no further retries.
- **Final status:** DO_NOT_CALL

## CUST-10 — Neha Joshi (VOICEMAIL_NO_ANSWER → send_payment_link)

- **Customer:** I missed your call — please send me a payment link.
- **Agent [send_payment_link]:** Retry link issued for the missed-contact recovery path.
- **Final status:** LINK_SENT

---

To replay any of these offline: `python3 -m src.runner simulate --customer CUST-01`
