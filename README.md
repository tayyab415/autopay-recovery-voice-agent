# Autopay Recovery Voice Agent (Nexus Cloud)

Offline-first autopay dunning system: a merchant gateway with policy guardrails,
an offline dialogue simulator, a Bolna voice client, a recovery console UI,
and a CLI runner — with 10 synthetic failure personas covering every dunning path.

## Architecture

Two layers, per the design spec:

- **Knowledge Layer** (`src/playbook.py`, `src/tools.py`, `src/ledger.py`, `src/disposition.py`, `src/policy_engine.py`)
  - `Playbook` maps each of the 10 failure codes to the actions the agent may take, plus the directions it must follow.
  - `ToolService` is the only writer. Bolna, the console, and the simulator all call it. Tools take real arguments (`target_date`, `channel`, `summary`, `reason`). A disallowed action returns 422 with a speakable message and the allowed list.
  - Guardrails live in the tool, not the prompt: reschedule within 14 days, one late-fee waiver per year, principal never waived, a second identical payment link does not push again, do-not-call blocks later collection, disputed and cancelled accounts cannot be collected.
  - `Ledger` keeps the 10 accounts and an audit row for every tool call. `disposition.py` stamps `last_disposition`, `recovery_probability`, and `next_touch_at` when a tool succeeds or a Bolna webhook arrives. No-answer schedules a retry only while the account is still pending.
- **Intelligence Layer** (`src/bolna_client.py`, `src/simulator.py`, `src/gateway.py`)
  - `gateway.py` is the HTTP face of the tool service, the Bolna webhook, mock checkout, and the console.
  - `bolna_client.py` publishes the same tools to Bolna with the arguments filled in (a reschedule call sends `target_date`, not just `customer_id`). The system prompt says to call `get_account` first and to speak tool rejections.
  - `simulator.py` is a scripted caller for offline tests. It chooses a tool from the utterance. It does not change account state itself.
- **Presentation / Ops** (`static/`, `src/runner.py`, `demo/`)
  - `static/index.html` + `static/app.js` — Merchant Recovery Console (metrics,
    customer table, trigger modal, transcript/timeline/audio drawer).
  - `src/runner.py` — `list` / `simulate` / `call` / `serve` commands.

## The 10 Failure Personas (why each needs distinct treatment)

| ID | Persona | Failure | Correct treatment |
|----|---------|---------|-------------------|
| CUST-01 | Priya Sharma | CARD_EXPIRED | Fresh link — card renewed, money available |
| CUST-02 | Rahul Verma | INSUFFICIENT_FUNDS | Reschedule to salary date (5th), never pressure |
| CUST-03 | Ananya Iyer | BANK_GATEWAY_TIMEOUT | Simple retry link — bank's fault, not customer's |
| CUST-04 | Vikram Patel | MANDATE_LIMIT_EXCEEDED | Split checkout link — auto-debit cap can't cover invoice |
| CUST-05 | Sneha Kulkarni | SUSPECTED_PHISHING | Anchor trust on official `pay.nexuscloud.io` domain |
| CUST-06 | Arjun Mehta | DISPUTED_CHARGE | Escalate to billing — never collect a disputed amount |
| CUST-07 | Rohit Roy | CANCELLATION_CLAIMED | Log + escalate — retrying a cancelled plan is a violation |
| CUST-08 | Pooja Nair | LATE_FEE_OBJECTION | Waive Rs.350 once (policy allows 1/yr) or fresh link |
| CUST-09 | Harish Reddy | HARD_REFUSAL_HOSTILE | Honor do-not-call instantly, de-escalate |
| CUST-10 | Neha Joshi | VOICEMAIL_NO_ANSWER | Low-pressure retry link for missed contact |

## Live Demo (hosted)

Console, hosted on AWS with HTTPS: https://nexuscloud-recovery.s3.amazonaws.com/index.html

Open it, hit Trigger on any row, Send payment link, open the checkout URL, tap Pay.
No keys or phone needed.

## Setup & Run (< 2 minutes)

```bash
pip install -r requirements.txt
python3 -m pytest -q            # offline verification, all green
python3 -m src.runner serve     # http://localhost:8000 → Autopay Recovery Console
```

Console: metric cards (Outstanding Dunning ARR / Accounts in Recovery / Recovery Rate),
customer table, per-row **Trigger** modal (**Run Simulation** offline, **Live Call** with
a test number), and a detail drawer (transcript, tool timeline, audio player).

CLI:

```bash
python3 -m src.runner list                          # 10 records + statuses
printf '\n' | python3 -m src.runner simulate --customer CUST-01   # offline dialogue
python3 -m src.runner call --customer CUST-01 --phone +91XXXXXXXXXX  # live (needs BOLNA_API_KEY)
```

## Offline Verification (no keys, no network)

```bash
python3 -m pytest -v
printf '\n' | python3 -m src.runner simulate --customer CUST-06
```

`pytest` covers models, policy guardrails, all 4 tool endpoints + webhook,
Bolna payload construction (no network), all 10 simulator personas, and UI serving.

## Demo Evidence

- `demo/recordings.json` — per-customer tool/reply/status records from the offline
  simulator, explicitly flagged `"simulated_offline": true`.
- `demo/transcripts/sample_calls.md` — readable offline dialogue logs, labeled simulated.
- `demo/live_call_cust01.json`, `demo/live_call_cust01_take2.json`,
  `demo/live_call_cust02.json`, `demo/live_call_cust03_proof.json` — four real Bolna
  executions against a test number the developer controls, with transcripts and
  recording URLs. The CUST-03 proof call fired `POST /api/tools/send-link` against
  the public gateway (logged 200) and flipped the merchant DB to `LINK_SENT`.

## Limitations & Production Recommendations

- **In-memory store** — `CustomerStore` resets on restart; production needs Postgres
  with optimistic locking and an audit log of every tool call.
- **Scripted simulator** — offline runs pick a tool from the utterance, then the
  tool service accepts or rejects it. Production dialogue is Bolna function calling
  against that same service.
- **Auth** — tool endpoints have no API keys; add merchant-scoped tokens before exposing.
- **Audio** — the drawer player is wired but offline runs produce no audio; live Bolna
  recordings plug in via webhook `transcript`/`recording_url`.
- **Reschedule clock** — `validate_reschedule` defaults to UTC today; pin `current_date`
  per merchant timezone in production.
