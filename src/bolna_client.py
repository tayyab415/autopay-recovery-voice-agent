"""Bolna agent spec builder + live client (real Bolna v2 REST schema).

Endpoints (per Bolna API quickstart):
  GET  /user/me            verify key + wallet (free, read-only)
  POST /v2/agent           create agent -> {agent_id, state, version_id}
  POST /call               place call {agent_id, recipient_phone_number}
  GET  /executions/{id}    poll transcript / recording / cost

Tests never touch the network — the client builds payloads; network
methods are only invoked explicitly by operators/runners.
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


def _custom_function(name: str, description: str, pre_call: str, base: str, endpoint: str) -> Dict[str, Any]:
    """One OpenAI-shaped custom function wired to a gateway tool endpoint."""
    return {
        "name": name,
        "description": description,
        "pre_call_message": pre_call,
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID, e.g. CUST-01"},
            },
            "required": ["customer_id"],
        },
        "key": "custom_task",
        "value": {
            "method": "POST",
            "param": {"customer_id": "%(customer_id)s"},
            "url": f"{base}{endpoint}" if base else endpoint,
            "headers": {"Content-Type": "application/json"},
        },
    }


def build_agent_payload(webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
    """Return a complete, working Bolna v2 agent spec.

    Pipeline: Deepgram nova-2 (STT) -> GPT-4.1-mini (LLM) -> ElevenLabs (TTS).
    NOTE: gateway_base_url must be publicly reachable or mid-call tool
    calls fail; the conversation itself still works without it.
    """
    base = gateway_base_url.rstrip("/")
    tools = [
        _custom_function(
            "send_payment_link",
            "Use when the customer agrees to pay now or asks for a payment link, UPI link, or checkout SMS/WhatsApp for their failed autopay.",
            "Sending you a secure payment link now.",
            base, "/api/tools/send-link",
        ),
        _custom_function(
            "reschedule_debit",
            "Use when the customer asks to pay later, mentions salary day, or wants the auto-debit retried on a later date within 14 days.",
            "Let me reschedule that debit for you.",
            base, "/api/tools/reschedule",
        ),
        _custom_function(
            "waive_late_fee",
            "Use when the customer objects to the late fee or asks for a waiver. Only one waiver per customer is allowed.",
            "Checking whether that fee can be waived.",
            base, "/api/tools/waive-fee",
        ),
        _custom_function(
            "escalate_dispute",
            "Use when the customer says the bill is wrong, disputes seats/charges, or claims they cancelled.",
            "Escalating this to our billing team right away.",
            base, "/api/tools/escalate-dispute",
        ),
    ]
    agent_config: Dict[str, Any] = {
        "agent_name": "autopay-recovery-agent",
        "agent_welcome_message": "Hi {{customer_name}}! This is NexusCloud calling about your recent autopay of Rs. {{amount_due}}, which could not be debited. Do you have a quick minute?",
        "tasks": [
            {
                "task_type": "conversation",
                "toolchain": {"execution": "sequential", "pipelines": [["transcriber", "llm", "synthesizer"]]},
                "tools_config": {
                    "llm_agent": {
                        "agent_type": "simple_llm_agent",
                        "agent_flow_type": "streaming",
                        "llm_config": {"provider": "openai", "model": "gpt-4.1-mini", "max_tokens": 200, "temperature": 0.2},
                    },
                    "synthesizer": {
                        "provider": "elevenlabs",
                        "provider_config": {"voice": "Angelica", "voice_id": "IkSv4tkouLJ6kYsQA7XD", "model": "eleven_turbo_v2_5"},
                        "stream": True,
                        "buffer_size": 250,
                        "audio_format": "wav",
                    },
                    "transcriber": {
                        "provider": "deepgram",
                        "model": "nova-2",
                        "language": "en",
                        "stream": True,
                        "encoding": "linear16",
                        "sampling_rate": 16000,
                        "endpointing": 250,
                    },
                    "input": {"provider": "plivo", "format": "wav"},
                    "output": {"provider": "plivo", "format": "wav"},
                    "api_tools": tools,
                },
                "task_config": {"call_terminate": 120, "hangup_after_silence": 10, "voicemail": True},
            }
        ],
    }
    if webhook_url:
        agent_config["webhook_url"] = webhook_url
    return {
        "agent_config": agent_config,
        "agent_prompts": {"task_1": {"system_prompt": _system_prompt()}},
    }


def _system_prompt() -> str:
    return (
        "You are a polite autopay recovery agent for NexusCloud calling {{customer_name}} "
        "about a failed auto-debit of Rs. {{amount_due}} (reason: {{failure_code}}). "
        "Keep every reply under two sentences. "
        "If they agree to pay, call send_payment_link. "
        "If they ask to pay later or mention salary day, call reschedule_debit (max 14 days out; never offer more). "
        "If they object to the late fee, call waive_late_fee (allowed at most once). "
        "If they say the bill is wrong or they cancelled, call escalate_dispute. "
        "If they ask to never be called again, apologize, end the call, no tools. "
        "If voicemail or silence, leave the standard callback notice and hang up."
    )


class BolnaRecoveryClient:
    """Thin wrapper around the real Bolna REST API."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = BOLNA_BASE_URL):
        self.api_key = api_key if api_key is not None else BOLNA_API_KEY
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def verify_key(self) -> Dict[str, Any]:
        """Free read-only check: account details + wallet balance."""
        resp = requests.get(f"{self.base_url}/user/me", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def build_payload(self, webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
        return build_agent_payload(webhook_url, gateway_base_url)

    def create_or_get_agent(self, webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
        """Create the agent. Falls back to a tool-less agent if the API
        rejects the custom-tools shape (wire tools via dashboard instead)."""
        payload = self.build_payload(webhook_url, gateway_base_url)
        resp = requests.post(f"{self.base_url}/v2/agent", json=payload, headers=self._headers(), timeout=30)
        tools_fallback = False
        if resp.status_code == 400 and "tool" in resp.text.lower():
            minimal = self.build_payload(webhook_url, gateway_base_url)
            del minimal["agent_config"]["tasks"][0]["tools_config"]["api_tools"]
            resp = requests.post(f"{self.base_url}/v2/agent", json=minimal, headers=self._headers(), timeout=30)
            tools_fallback = True
        resp.raise_for_status()
        data = resp.json()
        data["tools_fallback"] = tools_fallback
        return data

    def trigger_outbound_call(self, agent_id: str, customer: CustomerRecord, phone: Optional[str] = None) -> Dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "recipient_phone_number": phone or customer.phone,
            "user_data": {
                "customer_id": customer.customer_id,
                "customer_name": customer.name,
                "amount_due": customer.amount_due,
                "failure_code": customer.failure_code.value,
            },
        }
        resp = requests.post(f"{self.base_url}/call", json=body, headers=self._headers(), timeout=30)
        if resp.status_code == 400:
            body = {"agent_id": agent_id, "recipient_phone_number": phone or customer.phone}
            resp = requests.post(f"{self.base_url}/call", json=body, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_execution(self, execution_id: str) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/executions/{execution_id}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
