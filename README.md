# Autopay Recovery Voice Agent (Nexus Cloud)

Offline-first autopay dunning system: a merchant gateway with policy guardrails,
an offline dialogue simulator, a Bolna voice client, a recovery console UI,
and a CLI runner — with 10 synthetic failure personas covering every dunning path.

## Architecture

Two layers, per the design spec:

- **Knowledge Layer** (`src/models.py`, `data/customers.json`, `src/policy_engine.py`)
  - `CustomerRecord` / `FailureCode` (10 codes) / `CustomerStatus` — the dunning source of truth.
  - `PolicyEngine` — hard guardrails: reschedule ≤ 14 days out (`validate_reschedule`),
    at most 1 late-fee waiver per year (`validate_waiver`). The agent can never
    promise what policy forbids; violations return 422 with an explanatory error.
- **Intelligence Layer** (`src/gateway.py`, `src/bolna_client.py`, `src/simulator.py`)
  - `gateway.py` — FastAPI merchant backend: `GET /api/customers`,
    `POST /api/tools/{send-link, reschedule, waive-fee, escalate-dispute}`,
    `POST /api/webhook/bolna`, `POST /api/simulate`, plus `GET /` serving the console.
  - `bolna_client.py` — Bolna V2 agent spec (Deepgram nova-2 STT + GPT-4.1-mini +
    ElevenLabs Viraj TTS + 5 tool schemas) and live outbound-call trigger.
  - `simulator.py` — deterministic offline `DialogueSimulator`: keyword intent routing
    (do-not-call > dispute > reschedule > payment-link) that mutates the same store
    the tools use. No network, no cost.
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

Console, hosted on AWS S3 with the API on Beanstalk behind it:

http://nexuscloud-recovery.s3-website-us-east-1.amazonaws.com

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
- **Keyword intent routing** — the simulator is deterministic by design; production
  should use the LLM function-calling path with the policy engine as a server-side
  validator (defense in depth, already the pattern here).
- **Auth** — tool endpoints have no API keys; add merchant-scoped tokens before exposing.
- **Audio** — the drawer player is wired but offline runs produce no audio; live Bolna
  recordings plug in via webhook `transcript`/`recording_url`.
- **Reschedule clock** — `validate_reschedule` defaults to UTC today; pin `current_date`
  per merchant timezone in production.
