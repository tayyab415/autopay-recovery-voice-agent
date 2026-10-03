# System Design: Autopay Recovery Voice Agent

**Date:** 2026-10-03  
**Role Context:** Forward-Deployed Engineer Take-Home Project  
**Target:** Automated Autopay Failure Recovery via Bolna Voice AI & Merchant Knowledge Layer

---

## 1. Executive Summary & Merchant Problem

When recurring card and e-mandate payments fail, merchants face a delicate tradeoff:
* Automated dunning emails and SMS alerts have low open rates (<18%).
* Aggressive collections agencies damage brand equity and drive customer churn.
* Manual call centers are cost-prohibitive for accounts with low-to-medium average revenue per user.

This project delivers an automated voice recovery system that acts as a polite, helpful billing concierge. The agent calls customers immediately following a failed auto-debit, informs them of the exact reason, and resolves the payment friction directly on the call through real-time merchant tool execution (instant SMS payment links, debit rescheduling, or human escalation).

---

## 2. System Architecture: The Two-Layer Framework

The architecture divides the system into two distinct operational layers:

```
+-------------------------------------------------------------------------------+
|                         Merchant Recovery Console                             |
|        (Single-page Web Dashboard: customer roster, call triggers,            |
|         live timeline, transcript viewer, audio recording player)             |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                      Knowledge Layer: Merchant Gateway                        |
|                               (FastAPI Core)                                  |
|                                                                               |
|  - Customer Ledger: 10 synthetic customer profiles with failure codes         |
|  - Policy Engine: Deterministic rules governing waivers and rescheduling       |
|  - Tool Endpoints (Invoked mid-call by Bolna):                                |
|      * POST /api/tools/send-link                                              |
|      * POST /api/tools/reschedule                                             |
|      * POST /api/tools/waive-fee                                              |
|      * POST /api/tools/escalate-dispute                                       |
|  - Webhook Sink (POST /api/webhook/bolna):                                    |
|      * Ingests call-disconnected and completed execution events               |
|      * Extracts dispositions, durations, costs, transcripts, recordings       |
|      * Updates customer record status in real time                            |
+---------------------------------------+---------------------------------------+
                                        |
                      POST /call with injected user_data
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                     Intelligence Layer: Bolna Voice AI                        |
|                                                                               |
|  - Pipeline: Deepgram Nova-3 (STT) -> GPT-4.1-mini (LLM) -> ElevenLabs (TTS)  |
|  - Context Injection: {{customer_name}}, {{amount}}, {{failure_reason}}       |
|  - Function Calling: Triggers Merchant Gateway tools during spoken dialogue   |
|  - Telephony: Dials recipient phone numbers via shared outbound pool          |
+-------------------------------------------------------------------------------+
```

---

## 3. The 10 Customer Personas & Failure Taxonomy

The dataset (`data/customers.json`) captures ten distinct recovery archetypes:

| Customer ID | Name | Plan & Amount | Failure Code | Real-World Scenario | Allowed Resolution / Tool |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `CUST-01` | Priya Sharma | Pro Annual (₹12,499) | `CARD_EXPIRED` | Card expired last month; customer was unaware. | `send_payment_link(method="sms")` |
| `CUST-02` | Rahul Verma | Team Monthly (₹4,999) | `INSUFFICIENT_FUNDS` | Salary credited on the 5th; short on funds today. | `reschedule_debit(target_date="2026-10-05")` |
| `CUST-03` | Ananya Iyer | Business Starter (₹2,199) | `BANK_GATEWAY_TIMEOUT` | Bank CBS failure during mandate run; customer has funds. | Immediate backend re-poll; no friction |
| `CUST-04` | Vikram Patel | Enterprise Cloud (₹24,999) | `MANDATE_LIMIT_EXCEEDED` | Invoice exceeded the default ₹15,000 auto-debit cap. | `send_payment_link(method="whatsapp")` |
| `CUST-05` | Sneha Kulkarni | Starter Monthly (₹999) | `SUSPECTED_PHISHING` | Customer fears caller is a scammer. | Guide to in-app verification; send push auth |
| `CUST-06` | Arjun Mehta | Scale Tier (₹8,500) | `DISPUTED_CHARGE` | Customer claims unused seats were billed incorrectly. | `escalate_dispute(reason="seat_count_discrepancy")` |
| `CUST-07` | Rohit Roy | Developer Plan (₹1,499) | `CANCELLATION_CLAIMED` | Customer claims they submitted cancellation form. | Pause dunning; open cancellation ticket |
| `CUST-08` | Pooja Nair | Growth Plan (₹6,200) | `LATE_FEE_OBJECTION` | Refuses to pay ₹350 late fee caused by bank delay. | `waive_late_fee()` (policy permits 1 waiver) |
| `CUST-09` | Harish Reddy | Pro Monthly (₹3,499) | `HARD_REFUSAL_HOSTILE` | Angry customer refusing to pay and shouting. | De-escalate politely; set `DO_NOT_CALL` |
| `CUST-10` | Neha Joshi | Standard Annual (₹9,999) | `VOICEMAIL_NO_ANSWER` | Call drops or answering machine answers. | Detect silence/voicemail; leave standard notice |

---

## 4. Merchant Tool Specifications (Callable Mid-Call)

All tools are exposed via REST on the Merchant Gateway and configured in Bolna's `tools_config`:

### 4.1. Send Payment Link
* **Endpoint:** `POST /api/tools/send-link`
* **Payload:**
  ```json
  {
    "customer_id": "CUST-01",
    "channel": "sms",
    "custom_amount": null
  }
  ```
* **Response:**
  ```json
  {
    "status": "success",
    "message": "Payment link sent to customer registered mobile via SMS.",
    "short_url": "https://pay.nexuscloud.io/l/7f8a9b",
    "expires_at": "2026-10-04T12:00:00Z"
  }
  ```

### 4.2. Reschedule Auto-Debit
* **Endpoint:** `POST /api/tools/reschedule`
* **Payload:**
  ```json
  {
    "customer_id": "CUST-02",
    "target_date": "2026-10-05"
  }
  ```
* **Guardrail:** The target date cannot exceed 14 days from current date. Requests exceeding this return HTTP 422 with a message instructing the agent to offer a split payment instead.

### 4.3. Waive Late Fee
* **Endpoint:** `POST /api/tools/waive-fee`
* **Payload:**
  ```json
  {
    "customer_id": "CUST-08",
    "reason": "bank_processing_delay"
  }
  ```
* **Guardrail:** Policy engine allows at most 1 late fee waiver per account per 12 months. Principal subscription amount cannot be waived.

### 4.4. Escalate Dispute
* **Endpoint:** `POST /api/tools/escalate-dispute`
* **Payload:**
  ```json
  {
    "customer_id": "CUST-06",
    "dispute_type": "billing_error",
    "summary": "Customer states they deactivated 5 seats prior to cycle end."
  }
  ```
* **Behavior:** Automatically pauses active dunning sequences for 10 business days and issues a support ticket number.

---

## 5. Intelligence Layer: Bolna Agent Configuration

### 5.1. Toolchain & Provider Stack
* **Transcriber:** `deepgram` (`nova-3`, language: `en`, endpointing: `250ms`).
* **LLM:** `openai` (`gpt-4.1-mini`, streaming: `true`, temperature: `0.2`, max tokens: `150`).
* **Synthesizer:** `elevenlabs` (`model`: `eleven_turbo_v2_5`, `voice`: `Viraj`, `voice_id`: `iWNf11sz1GrUE4ppxTOL`).
* **Input/Output Telephony:** `plivo` audio bridge.

### 5.2. Conversational Policy & Prompt Guardrails
1. **Introduction:** Identify as "Nexus Cloud Customer Support", greet the customer by name, and state the call purpose clearly within the first sentence.
2. **Conciseness:** Keep spoken turns under 2 sentences. Spoken dialogue must be punchy.
3. **No Financial Pressure:** Avoid threatening service termination on the first objection. Frame every interaction around preventing service disruption.
4. **Immediate Tool Confirmation:** As soon as the customer agrees to an action, trigger the corresponding tool and confirm: *"I've just sent the direct link to your mobile number. You can complete it whenever you are ready."*
5. **Hostility Circuit Breaker:** If the customer asks not to be contacted or uses abusive language, apologize calmly, inform them the account has been noted, and disconnect without retaliation.

---

## 6. Merchant Web Console (UI Specification)

A single-page application served directly by FastAPI:
* **Header & Metrics:** Total accounts in dunning, total recovered revenue, recovery success rate (%).
* **Customer Table:** Lists the 10 customer records with status badges (`Pending`, `Link Dispatched`, `Rescheduled`, `Dispute Escalated`, `DNC`).
* **Interactive Trigger Modal:** Allows selecting a customer record and either:
  1. Entering a custom phone number to receive a live phone call.
  2. Running a local simulation step-by-step.
* **Call Inspector Drawer:**
  * Displays full live or historical transcript.
  * Timeline of tool calls made during the call.
  * Embedded HTML5 audio player playing the Bolna call recording URL.

---

## 7. Reviewer Verification & Test Suite

To ensure smooth evaluation without external dependencies, the repository provides two test pathways:

1. **Unit & Integration Suite (`pytest`):**
   * `tests/test_policy_engine.py`: Verifies waiver limits, reschedule date bounds, and fee calculation.
   * `tests/test_tools_api.py`: Validates all REST tool endpoints and error responses.
   * `tests/test_customer_scenarios.py`: Runs deterministic mock conversations across all 10 customer personas to verify correct tool selection and state transitions.
2. **Live Test Harness (`python runner.py`):**
   * CLI command to trigger a live call to a designated phone number using `BOLNA_API_KEY`.
   * CLI option `--simulate` to test the prompt and tool calling loop offline without spending credits.
3. **Recorded Evidence:**
   * Audio recordings and verified transcripts from test executions saved in `demo/`.

---

## 8. Directory Structure

```
workspaces/autopay-recovery-voice-agent/
├── README.md                           # Architecture writeup, run guide, and merchant design notes
├── requirements.txt                    # FastAPI, uvicorn, requests, pytest, pydantic
├── data/
│   └── customers.json                  # 10 rich customer failure records
├── src/
│   ├── config.py                       # Configuration & environment loader
│   ├── models.py                       # Pydantic models for customers, tools, webhooks
│   ├── policy_engine.py                # Business rules for waivers, grace periods, rescheduling
│   ├── gateway.py                      # FastAPI server (tools API + webhook receiver + static UI)
│   ├── bolna_client.py                 # Bolna agent creator, patcher, and call trigger
│   └── runner.py                       # CLI interface for live calls and simulations
├── static/
│   └── index.html                      # Single-page Merchant Recovery Console (Tailwind + JS)
├── demo/
│   ├── recordings.json                 # URLs and metadata for completed test calls
│   └── transcripts/                    # Markdown transcripts of key failure modes
└── tests/
    ├── conftest.py
    ├── test_policy_engine.py
    ├── test_tools_api.py
    └── test_customer_scenarios.py
```
