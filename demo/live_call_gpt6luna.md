# Live calls on the gpt-6-luna brain — 2026-10-04

## Attempt 1 (execution ff16a50e, Rs 8.52): voice works, tools unreachable

A fresh agent was built by `runner.py call` with empty `PUBLIC_BASE_URL`,
so its tool URLs were relative and Bolna could not reach them. The call
connected and GPT-6 Luna spoke gracefully throughout, but every `get_account`
failed and no account action was possible. Wiring fault on our side, not a
model failure.

Transcript (510 chars, verbatim):

user:  hello hello
assistant: Let me pull up the account.
assistant: Hello Ananya, this is Nexus Cloud calling about your failed autopay
  of Rs. 2, 199. Do you have a minute? I couldn't retrieve your account
  details, so I can't take an account action right now. [...]
user:  yeah yeah yeah
assistant: Sorry, the call was interrupted. I couldn't retrieve your account
  details, so I can't take an account action right now.
user:  alright
assistant: Thanks for your time. Goodbye.

What this proves: the new brain speaks on a live call and degrades politely
when tools are down. What it does NOT prove: tool firing on the new brain.

## Attempt 2 (execution 2021da28, Rs 0): no-answer

Redial placed directly against agent bf210d9e (absolute Cloud Run tool URLs
+ webhook). Phone was not picked up. Nothing spent, nothing learned.

## Still open

One answered call against bf210d9e is the only remaining proof: tool firing
on the gpt-6-luna brain with the account-id prompt fix. ~Rs 9.
