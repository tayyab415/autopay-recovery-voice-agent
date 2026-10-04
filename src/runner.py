"""CLI runner: list / simulate / call / serve. Offline-safe except `call`."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import GATEWAY_PORT
from src.gateway import db
from src.simulator import DialogueSimulator, SCENARIO_UTTERANCES


def cmd_list() -> int:
    for c in db.list_customers():
        print(f"{c.customer_id} | {c.name} | {c.failure_code.value} | Rs.{c.amount_due:.0f} | {c.status.value}")
    return 0


def cmd_simulate(customer_id: str) -> int:
    sim = DialogueSimulator()
    cust = db.get_customer(customer_id)
    if cust is None:
        print(f"Unknown customer: {customer_id}", file=sys.stderr)
        return 1
    print(f"Simulating {cust.customer_id} — {cust.name} ({cust.failure_code.value})")
    print(f"Failure context: {cust.failure_reason}")
    print("Type messages (empty line quits). Offline — no phone calls placed.")
    seed = SCENARIO_UTTERANCES.get(customer_id)
    if seed:
        result = sim.simulate(customer_id, user_inputs=[seed])
        print(f"Customer ({customer_id}): {seed}")
        print(f"Agent [{result.tool_called}]: {result.agent_reply}")
    while True:
        try:
            line = input("You: ").strip()
        except EOFError:
            break
        if not line:
            break
        result = sim.simulate(customer_id, user_inputs=[line])
        print(f"Agent [{result.tool_called}]: {result.agent_reply} (status={result.final_status.value})")
    return 0


def cmd_call(customer_id: str, phone: str) -> int:
    from src.bolna_client import BolnaRecoveryClient
    from src.config import BOLNA_API_KEY, PUBLIC_BASE_URL

    if not BOLNA_API_KEY:
        print("BOLNA_API_KEY is not set; refusing to place a live call.", file=sys.stderr)
        return 2
    if not PUBLIC_BASE_URL:
        print("PUBLIC_BASE_URL is not set; refusing to place a live call. "
              "Without it the agent is built with relative tool URLs that "
              "Bolna cannot reach, so every tool fails mid-call (seen 2026-10-04). "
              "Export it first, e.g. PUBLIC_BASE_URL=https://<cloud-run-url>.",
              file=sys.stderr)
        return 2
    cust = db.get_customer(customer_id)
    if cust is None:
        print(f"Unknown customer: {customer_id}", file=sys.stderr)
        return 1
    client = BolnaRecoveryClient()
    webhook = f"{PUBLIC_BASE_URL}/api/webhook/bolna" if PUBLIC_BASE_URL else ""
    agents = client.create_or_get_agent(webhook_url=webhook, gateway_base_url=PUBLIC_BASE_URL)
    agent_id = agents.get("agent_id", "") if isinstance(agents, dict) else ""
    result = client.trigger_outbound_call(agent_id, cust, phone=phone or cust.phone)
    print(result)
    return 0


def cmd_serve(port: int) -> int:
    import uvicorn

    uvicorn.run("src.gateway:app", host="0.0.0.0", port=port, reload=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autopay recovery runner")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Print the 10 customer records and statuses.")
    ps = sub.add_parser("simulate", help="Interactive offline conversation test.")
    ps.add_argument("--customer", required=True, help="Customer ID, e.g. CUST-01")
    pc = sub.add_parser("call", help="Trigger a live Bolna phone call.")
    pc.add_argument("--customer", required=True)
    pc.add_argument("--phone", required=True)
    pv = sub.add_parser("serve", help="Launch the FastAPI server.")
    pv.add_argument("--port", type=int, default=GATEWAY_PORT)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "simulate":
        return cmd_simulate(args.customer)
    if args.command == "call":
        return cmd_call(args.customer, args.phone)
    if args.command == "serve":
        return cmd_serve(args.port)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
