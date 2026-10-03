"""Bolna agent spec builder + live client (payload construction only in tests).

No live Bolna calls are made during tests — the client builds payloads;
network methods are only invoked explicitly by operators/runners.
"""
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel

from src.config import BOLNA_API_KEY, BOLNA_BASE_URL
from src.models import CustomerRecord


class ToolSpec(BaseModel):
    name: str
    description: str
    endpoint: str


DEFAULT_TOOLS = [
    {"name": "send_payment_link", "description": "Send a secure checkout link via SMS/WhatsApp.", "endpoint": "/api/tools/send-link"},
    {"name": "reschedule_debit", "description": "Reschedule the auto-debit within 14 days.", "endpoint": "/api/tools/reschedule"},
    {"name": "waive_late_fee", "description": "Waive an eligible late fee (once per year).", "endpoint": "/api/tools/waive-fee"},
    {"name": "escalate_dispute", "description": "Escalate a billing dispute to a human agent.", "endpoint": "/api/tools/escalate-dispute"},
    {"name": "mark_do_not_call", "description": "Honor a do-not-call request immediately.", "endpoint": "/api/tools/donotcall"},
]


def build_agent_payload(webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
    """Return the complete Bolna V2 agent spec.

    Includes Deepgram STT + GPT-4.1-mini LLM + ElevenLabs Viraj TTS + tools schema.
    """
    base = gateway_base_url.rstrip("/")
    tools = []
    for t in DEFAULT_TOOLS:
        tools.append(
            {
                "name": t["name"],
                "description": t["description"],
                "url": f"{base}{t['endpoint']}" if base else t["endpoint"],
                "method": "POST",
            }
        )
    return {
        "agent_name": "autopay-recovery-agent",
        "transcriber": {"provider": "deepgram", "model": "nova-2", "language": "en-IN"},
        "llm": {"provider": "openai", "model": "gpt-4.1-mini", "system_prompt": _system_prompt()},
        "voice": {"provider": "elevenlabs", "voice": "Viraj", "language": "en-IN"},
        "tools": tools,
        "webhook": {"url": webhook_url, "events": ["completed", "call-disconnected"]},
    }


def _system_prompt() -> str:
    return (
        "You are a polite autopay recovery agent for NexusCloud. "
        "Help customers resolve failed auto-debits: offer a payment link, "
        "reschedule within 14 days, waive an eligible late fee once, "
        "escalate disputes, and honor do-not-call requests immediately."
    )


class BolnaRecoveryClient:
    """Thin wrapper around the Bolna V2 REST API."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = BOLNA_BASE_URL):
        self.api_key = api_key if api_key is not None else BOLNA_API_KEY
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def build_payload(self, webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
        return build_agent_payload(webhook_url, gateway_base_url)

    def create_or_get_agent(self, webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
        payload = self.build_payload(webhook_url, gateway_base_url)
        resp = requests.post(f"{self.base_url}/v2/agents", json=payload, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def trigger_outbound_call(self, agent_id: str, customer: CustomerRecord, phone: Optional[str] = None) -> Dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "recipient_phone_number": phone or customer.phone,
            "user_data": {
                "customer_id": customer.customer_id,
                "name": customer.name,
                "amount_due": customer.amount_due,
                "failure_code": customer.failure_code.value,
            },
        }
        resp = requests.post(f"{self.base_url}/v2/calls", json=body, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()
