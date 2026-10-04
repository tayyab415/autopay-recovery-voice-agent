# Autopay recovery voice agent

My submission for the voice-agent option of the Forward-Deployed Engineer take-home. The merchant is fictional. I called it Nexus Cloud. Ten customers missed an autopay, each for a different reason, and a voice agent calls them to recover it.

## What the brief asked for

One working build, setup notes, no real customer data or secrets in the repo. I chose the autopay recovery agent.

- Ten fictional accounts live in `data/customers.json`.
- A judge can run the whole thing end to end. The hosted console places the call, the agent uses merchant tools while the person is still talking, and a mock checkout marks the account recovered.
- Live demo calls are rate-limited (one per number per day, ten a day). Setting `CALL_ALLOWLIST` restricts them to your own numbers instead. Judges can also pick up a phone drawn right on the console, so the demo never needs their number.
- No API keys, passwords, or card data in this repo. Keys stay in the server environment.

## Try it

https://autopay-recovery-1027824348124.us-central1.run.app

### 2 ways to test the app

**1. Free, no phone.** Hit Trigger on any row: Run Simulation, fire the tool buttons, open the checkout link, tap Pay. Nothing leaves the page. Start here.

**2. Real voice.** Two flavors. Talk in browser uses your microphone against the on-screen customer phone: press Answer, say hello. Comfortable testing on your phone? Open any row, type your number in the Trigger box (+91 format), hit Call my phone. Fair use: one live call per number per day, ten a day across the demo.

The customer phone has two tabs. Call is the handset: it rings, you answer, talk. Messages is the SMS inbox: payment links land there as texts, with a badge count.

Click a row. Nexus Cloud rings that phone. Press Answer, allow the microphone, say hello. The agent stays quiet until it hears a greeting, then introduces itself once and pulls the account. Talk the way that customer would. When the agent sends a payment link, switch to the Messages tab on the same phone. The text holds a checkout link, and paying it marks the account recovered.

### The built-in phone

No SIM, no real number, no telecom. The phone on the right is a full simulation of the customer's handset, and the whole voice loop runs through it.

**It receives calls.** Trigger a row and the phone rings with the merchant name on screen. Answer or Decline. Answering with the microphone opens a live Bolna voice session, the same agent and tools as a real call. A timer runs while you talk, and hanging up ends the session.

**It receives SMS.** Every payment link the agent sends is stored as a text message on that customer's phone, readable from the Messages tab. A badge counts unread texts, and a "new text" hint appears mid-call so you know to look.

**Its links work.** Each text carries an Open-checkout hyperlink. Tapping it opens the mock checkout with the right customer, amount, and failure. Tapping Pay marks the account recovered, and the table status flips. Ask for the link twice and you get the same URL back, not a second text, exactly like a real sender's duplicate handling.

Run Simulation skips the phone entirely and runs the same tools headless. The drawer on each row keeps the transcript, the tool timeline, and the recording for whatever path you took.

The ledger is in memory. A restart, including Cloud Run scaling to zero, puts all ten accounts back to their starting state.

## My rationale: the agentic harness

A model is not an agent. On its own it talks fluently, remembers nothing, promises anything, and leaves no record behind. The harness is everything around it that turns talk into accountable action, and the harness is the thing I actually built here.

Mine has four parts. Hands: ten tools that move money, dates, and tickets, each carrying the full decision it needs. Memory: a ledger with every account, an audit row for every tool call, and a stamp after each outcome saying what happened, how likely recovery looks now, and when to try again. Ears after the call: the webhook brings transcripts and recordings back into the drawer, so a conversation is evidence, not vapor. And a playground: the simulator, the console, and the built-in phone, so every path can be prodded for free before it ever touches a real handset.

Engaging, to me, is structural, not charm. The agent waits for hello instead of talking over the pickup. It keeps turns under two sentences so the customer can interrupt. When policy says no, it speaks the tool's own refusal plus what it can still do, which is why "I can't do that" lands as help instead of a wall. It answers in Hindi when spoken to in Hindi. The payment text buzzes mid-call so the loop closes while the voice is still warm. None of that is personality tuning. It is the loop staying alive until the account resolves.

## Why I split it in two

Inside that harness I keep two jobs strictly apart, because a voice model is fluent and unaccountable. Give it a merchant's billing rules as prompt text and it will agree to a date past policy, waive a fee twice, or collect a bill the customer already disputed, all in a perfectly polite tone. I did not want politeness to be the thing standing between the merchant and its money. So the rules live somewhere the model cannot rewrite them mid-call.

The intelligence layer listens and talks. Here that is Bolna: Deepgram transcribes, GPT-6 Luna answers on my own OpenAI key, ElevenLabs speaks. I treat all of that as replaceable. If a better voice stack appears next quarter, it should slot in without touching a single billing rule.

The knowledge layer is the merchant system the voice model has to ask before it acts. It owns three things.

First, tools that carry the full decision. A reschedule brings the date the customer agreed to. A payment link brings the channel. A dispute brings a summary. A tool that only got a customer id could check none of that, and that gap is exactly where a polite agent books the wrong outcome.

Second, a playbook per failure code in `src/playbook.py`. On its first spoken turn the agent calls `get_account`, and the answer tells it what this account allows plus a short instruction. An expired card gets one fresh link. A salary-day miss gets a reschedule inside 14 days before anyone mentions a link. A disputed bill gets a ticket and a pause. A hostile refusal gets do-not-call and the call ends.

Third, one door everything walks through. Bolna, the console buttons, and the offline simulator all call `ToolService` in `src/tools.py`. When the model asks for something the playbook refuses, the tool answers 422 with a sentence the agent can read out plus the actions still allowed. So the spoken "I can't do that, but I can do this" comes from code, not from the model's judgment. After a tool succeeds, the ledger updates, an audit row lands, and the account gets stamped with what happened, how likely recovery looks now, and when to try again.

The prompt in `src/bolna_client.py` stays short on purpose. It tells the model to wait for hello, call `get_account`, read rejections word for word, and confirm only what a tool already approved. Dates, the one-waiver rule, and "do not collect this bill" are enforced in `src/policy_engine.py` and `src/tools.py`, where `pytest` hits them without placing a single call.

That is the bet of this submission. The voice provider is a commodity. The books, the policy, and the next touch are the product, and they survive a change of voice provider untouched.

## How a call actually flows

The page sends only a customer id when a browser call starts. The server fills in the name, amount, and failure code from the ledger and mints the Bolna session. The key never reaches the browser.

A payment link is stored as a message on that customer's console phone. Asking for the same link twice on the same channel returns the existing URL instead of sending a second text. When the call ends, the Bolna webhook stores the transcript. A no-answer schedules a retry only while the account is still pending, so an account that already got its link is left alone.

## The ten accounts

| ID | Customer | Failure | What the playbook allows |
|----|----------|---------|--------------------------|
| CUST-01 | Priya Sharma | Card expired | One fresh checkout link |
| CUST-02 | Rahul Verma | Insufficient funds | Reschedule to a date they agree to, inside 14 days |
| CUST-03 | Ananya Iyer | Bank timeout | Re-poll the mandate. A manual link only if they ask to pay that way |
| CUST-04 | Vikram Patel | Mandate limit exceeded | One-time checkout for the full amount |
| CUST-05 | Sneha Kulkarni | Suspected phishing | In-app verification. The only domain the agent may name is pay.nexuscloud.io |
| CUST-06 | Arjun Mehta | Disputed charge | Open a dispute and pause dunning. A payment link is refused |
| CUST-07 | Rohit Roy | Cancellation claimed | Log the cancellation and pause. A payment link is refused |
| CUST-08 | Pooja Nair | Late fee objection | Waive the Rs 350 fee once. The principal stays |
| CUST-09 | Harish Reddy | Hostile refusal | Do-not-call, then stop |
| CUST-10 | Neha Joshi | Voicemail | Schedule a retry |

## Evidence

Judge the loop on the console call for Priya Sharma, execution `3e7ce7ba-feb6-4ef6-8416-bc0f38d2f0ad`. She said hello, the agent pulled the account, she asked for SMS, the gateway accepted the link, and the account moved to `LINK_SENT`. Transcript and recording URL are in `demo/live_call_app_e2e.json`. That call ran on the previous brain; the current one is GPT-6 Luna on my own key, exercised without a phone in `demo/brain_adversarial_gpt6luna.md` (9 probes) and `demo/live_call_gpt6luna.md` (live voice proof).

The older live files in `demo/` predate the finished tool arguments. Use the console call above.

Offline dialogues for all ten personas sit in `demo/transcripts/sample_calls.md` and are labeled simulated. `pytest` covers the policy refusals, all ten personas, the webhook, and the console page. No network, no key.

## Setup

```bash
pip install -r requirements.txt
python3 -m pytest -q
python3 -m src.runner serve
```

The console is at http://localhost:8000.

Live calling needs `BOLNA_API_KEY` and `BOLNA_AGENT_ID` on the server. Set `CALL_ALLOWLIST` to the E.164 numbers you control. With that list set, any other number is refused. `PUBLIC_BASE_URL` is the origin Bolna uses to reach the tools, and the origin checkout links point at.

```bash
python3 -m src.runner list
printf '\n' | python3 -m src.runner simulate --customer CUST-02
python3 -m src.runner call --customer CUST-01 --phone +91XXXXXXXXXX
```

## Limits

The ledger resets on restart. Production would be Postgres, with the same audit log the tool service already writes.

Tool routes have no merchant auth. They are open so the demo and the voice agent can reach them. Real merchant traffic needs scoped tokens first.

Browser calling needs Bolna's web-call beta enabled on the account. If it is off, Answer fails with that reason on the phone screen. Outbound to an allowlisted number still works.

The live agent answers in English and Hindi. Hindi runs on a Sarvam voice with a Hindi prompt; the tools and policy stay the same in both languages.

If I kept one thing from this repo, it would not be the console. It would be the playbook, the tool refusals, and the ledger. That part outlives any voice provider.
