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
    {"name": "get_account", "description": "Read failure, amount, allowed actions, and directions.", "endpoint": "/api/tools/get-account"},
    {"name": "send_payment_link", "description": "Send one checkout link via SMS or WhatsApp.", "endpoint": "/api/tools/send-link"},
    {"name": "reschedule_debit", "description": "Reschedule the auto-debit within 14 days.", "endpoint": "/api/tools/reschedule"},
    {"name": "waive_late_fee", "description": "Waive an eligible late fee once per year.", "endpoint": "/api/tools/waive-fee"},
    {"name": "escalate_dispute", "description": "Pause dunning and open a dispute ticket.", "endpoint": "/api/tools/escalate-dispute"},
    {"name": "log_cancellation", "description": "Pause dunning and log a claimed cancellation.", "endpoint": "/api/tools/log-cancellation"},
    {"name": "retry_mandate", "description": "Re-poll a bank mandate after a gateway timeout.", "endpoint": "/api/tools/retry-mandate"},
    {"name": "send_app_verification", "description": "Send an in-app verification when the caller is suspected of phishing.", "endpoint": "/api/tools/verify-caller"},
    {"name": "schedule_retry", "description": "Schedule the next touch after voicemail or no answer.", "endpoint": "/api/tools/schedule-retry"},
    {"name": "mark_do_not_call", "description": "Honor a do-not-call request immediately.", "endpoint": "/api/tools/donotcall"},
]


def _custom_function(
    name: str,
    description: str,
    pre_call: str,
    base: str,
    endpoint: str,
    properties: Dict[str, Any],
    required: list,
    param: Dict[str, str],
) -> Dict[str, Any]:
    """One OpenAI-shaped custom function wired to a gateway tool endpoint."""
    return {
        "name": name,
        "description": description,
        "pre_call_message": pre_call,
        "parameters": {"type": "object", "properties": properties, "required": required},
        "key": "custom_task",
        "value": {
            "method": "POST",
            "param": param,
            "url": f"{base}{endpoint}" if base else endpoint,
            "headers": {"Content-Type": "application/json"},
        },
    }


def _customer_id_prop() -> Dict[str, Any]:
    return {"type": "string", "description": "Customer ID from get_account, e.g. CUST-01"}


def _hindi_prompt() -> str:
    # Byte-identical to the live agent's Hindi branch. Devanagari (not Roman)
    # so the Sarvam voice pronounces it as Hindi; tool/customer IDs stay English.
    return (
        "आप Nexus Cloud बिलिंग सहायता हैं। {{customer_name}} (खाता {{customer_id}}) को "
        "Rs. {{amount_due}} के असफल ऑटोपे (कारण {{failure_code}}) के बारे में कॉल कर रहे हैं। "
        "पहले hello या namaste का इंतज़ार करें, फिर एक बार परिचय दें और get_account को कॉल करें। "
        "टूल की मनाही को उसी के शब्दों में बोलें। टूल की पुष्टि के बिना तारीख, छूट या रिफंड का वादा न करें। "
        "हर जवाब दो वाक्यों से छोटा रखें।"
    )


def build_agent_payload(webhook_url: str, gateway_base_url: str = "") -> Dict[str, Any]:
    """Return a complete, working Bolna v2 agent spec.

    Pipeline: Deepgram nova-2 (STT) -> GPT-4.1-mini (LLM) -> ElevenLabs (TTS).
    NOTE: gateway_base_url must be publicly reachable or mid-call tool
    calls fail; the conversation itself still works without it.
    """
    base = gateway_base_url.rstrip("/")
    cid = _customer_id_prop()
    tools = [
        _custom_function(
            "get_account",
            "Call this first on every call. Returns the failure reason, amount, allowed_actions, and the merchant directions you must follow.",
            "Let me pull up the account.",
            base, "/api/tools/get-account",
            {"customer_id": cid},
            ["customer_id"],
            {"customer_id": "%(customer_id)s"},
        ),
        _custom_function(
            "send_payment_link",
            "Send one checkout link. Required only when get_account lists send_payment_link. channel is sms or whatsapp. Set resend true only if the customer says the first link never arrived.",
            "Sending one secure payment link now.",
            base, "/api/tools/send-link",
            {
                "customer_id": cid,
                "channel": {"type": "string", "description": "sms or whatsapp", "enum": ["sms", "whatsapp"]},
                "resend": {"type": "boolean", "description": "True only when the customer says the earlier link never arrived"},
            },
            ["customer_id", "channel"],
            {"customer_id": "%(customer_id)s", "channel": "%(channel)s", "resend": "%(resend)s"},
        ),
        _custom_function(
            "reschedule_debit",
            "Move the auto-debit. target_date is required, format YYYY-MM-DD, and must be within 14 days. Never invent a date the customer did not agree to.",
            "Let me check whether that date is inside policy.",
            base, "/api/tools/reschedule",
            {
                "customer_id": cid,
                "target_date": {"type": "string", "description": "Agreed debit date, YYYY-MM-DD, within 14 days"},
            },
            ["customer_id", "target_date"],
            {"customer_id": "%(customer_id)s", "target_date": "%(target_date)s"},
        ),
        _custom_function(
            "waive_late_fee",
            "Waive the late fee only. One waiver per year. Never waive the principal. Use only if get_account lists waive_late_fee and waivers_remaining is 1.",
            "Checking whether that late fee can be waived.",
            base, "/api/tools/waive-fee",
            {
                "customer_id": cid,
                "reason": {"type": "string", "description": "Short reason, in the customer's words"},
            },
            ["customer_id", "reason"],
            {"customer_id": "%(customer_id)s", "reason": "%(reason)s"},
        ),
        _custom_function(
            "escalate_dispute",
            "Open a billing dispute and pause dunning. Use when the bill is wrong. Do not use this for a claimed cancellation. summary is required.",
            "Opening a dispute so we stop collection while it is reviewed.",
            base, "/api/tools/escalate-dispute",
            {
                "customer_id": cid,
                "dispute_type": {"type": "string", "description": "billing_error or seat_count_discrepancy"},
                "summary": {"type": "string", "description": "What the customer says is wrong"},
            },
            ["customer_id", "summary"],
            {"customer_id": "%(customer_id)s", "dispute_type": "%(dispute_type)s", "summary": "%(summary)s"},
        ),
        _custom_function(
            "log_cancellation",
            "Customer says they already cancelled. Pause dunning and open a cancellation ticket. Do not argue and do not collect.",
            "I'll log that cancellation and pause any further charges.",
            base, "/api/tools/log-cancellation",
            {"customer_id": cid, "reason": {"type": "string", "description": "What the customer says they cancelled"}},
            ["customer_id"],
            {"customer_id": "%(customer_id)s", "reason": "%(reason)s"},
        ),
        _custom_function(
            "retry_mandate",
            "Queue an immediate bank re-poll. Only when get_account lists retry_mandate, which is a bank timeout, not a customer refusal.",
            "I'll retry the debit with the bank. You don't need to do anything.",
            base, "/api/tools/retry-mandate",
            {"customer_id": cid},
            ["customer_id"],
            {"customer_id": "%(customer_id)s"},
        ),
        _custom_function(
            "send_app_verification",
            "Customer thinks the call is a scam. Send an in-app verification. Tell them the only official domain is pay.nexuscloud.io. Never ask for card numbers, OTPs, or passwords.",
            "I'll send a verification inside the Nexus Cloud app.",
            base, "/api/tools/verify-caller",
            {"customer_id": cid},
            ["customer_id"],
            {"customer_id": "%(customer_id)s"},
        ),
        _custom_function(
            "schedule_retry",
            "Nobody answered, or the call reached voicemail. Schedule the next touch. Do not leave a payment demand.",
            "Nobody is available. I'll schedule another attempt.",
            base, "/api/tools/schedule-retry",
            {"customer_id": cid, "reason": {"type": "string", "description": "voicemail or no-answer"}},
            ["customer_id"],
            {"customer_id": "%(customer_id)s", "reason": "%(reason)s"},
        ),
        _custom_function(
            "mark_do_not_call",
            "Call this as soon as the customer says stop calling, never call, or do not contact me. Then apologize and hang up.",
            "I'll make sure we don't call this number again.",
            base, "/api/tools/donotcall",
            {"customer_id": cid, "reason": {"type": "string", "description": "What the customer said"}},
            ["customer_id"],
            {"customer_id": "%(customer_id)s", "reason": "%(reason)s"},
        ),
    ]
    agent_config: Dict[str, Any] = {
        "agent_name": "autopay-recovery-agent",
        "agent_welcome_message": "",
        "tasks": [
            {
                "task_type": "conversation",
                "toolchain": {"execution": "sequential", "pipelines": [["transcriber", "llm", "synthesizer"]]},
                "tools_config": {
                    "llm_agent": {
                        "agent_type": "simple_llm_agent",
                        "agent_flow_type": "streaming",
                        "llm_config": {"provider": "openai", "model": "gpt-6-luna", "max_tokens": 200, "temperature": 1},
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
                    "multilingual_config": {
                        "enabled": True,
                        "active_language": "en",
                        "switch_tool_description": "Switch the conversation language when the caller speaks a different language.",
                        "languages": {
                            "en": {
                                "synthesizer": {
                                    "provider": "elevenlabs",
                                    "provider_config": {"voice": "Angelica", "voice_id": "IkSv4tkouLJ6kYsQA7XD", "model": "eleven_turbo_v2_5"},
                                    "stream": True,
                                    "buffer_size": 250,
                                    "audio_format": "wav",
                                },
                                "system_prompt": None,  # filled below from the English prompt
                                "agent_name": "Nexus Cloud",
                            },
                            "hi": {
                                "transcriber": {"language": "hi"},
                                "synthesizer": {
                                    "provider": "sarvam",
                                    "provider_config": {"voice_id": "anushka", "model": "bulbul:v3"},
                                },
                                "system_prompt": _hindi_prompt(),
                                "handoff_message": "ठीक है, मैं हिंदी में जारी रखता हूँ।",
                                "agent_name": "Nexus Cloud",
                            },
                        },
                    },
                },
                "task_config": {"call_terminate": 120, "hangup_after_silence": 10, "voicemail": True},
            }
        ],
    }
    if webhook_url:
        agent_config["webhook_url"] = webhook_url
    system_prompt = _system_prompt()
    agent_config["tasks"][0]["tools_config"]["multilingual_config"]["languages"]["en"]["system_prompt"] = system_prompt
    return {
        "agent_config": agent_config,
        "agent_prompts": {"task_1": {"system_prompt": system_prompt}},
    }


def _system_prompt() -> str:
    return (
        "You are Nexus Cloud billing support calling {{customer_name}} (account {{customer_id}}) about a failed autopay "
        "of Rs. {{amount_due}} (reason code {{failure_code}}). "
        "You work for the merchant, not a collections agency. Never threaten to shut off service. "
        "Keep each spoken turn under two sentences. "
        "The line opens in silence on purpose. Do not speak until the person says hello, hi, or hey. "
        "People miss the first words if you talk the moment the call connects. "
        "After they greet you, say the introduction once: their name, Nexus Cloud, the failed amount, "
        "and ask if they have a minute. If their first words are not a greeting, give that same introduction "
        "and then answer what they said. Do not repeat the introduction later. "
        "On that first spoken turn, call get_account and obey its directions and allowed_actions. "
        "Do not promise a date, a waiver, or a refund until a tool confirms it. "
        "If a tool returns a rejection, say that message and offer only an allowed action. "
        "reschedule_debit requires target_date as YYYY-MM-DD, never more than 14 days out, and only a date the customer agreed to. "
        "waive_late_fee can succeed only once and never waives the principal. "
        "escalate_dispute is for a wrong bill. log_cancellation is for a plan they say they already cancelled. Do not mix them up. "
        "retry_mandate is only for a bank timeout. send_app_verification is for scam fears. The only official domain is pay.nexuscloud.io. "
        "Never ask for a card number, OTP, or password. "
        "schedule_retry is for voicemail or no answer. "
        "mark_do_not_call as soon as they say stop calling, then apologize and hang up. "
        "After a tool succeeds, confirm only what the tool message says."
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

    def mint_web_session(self, agent_id: str, user_data: Dict[str, Any]) -> Any:
        """Mint a one-time browser-call session. The API key stays on this request."""
        resp = requests.post(
            f"{self.base_url}/web-call/session",
            json={"agent_id": agent_id, "user_data": user_data},
            headers=self._headers(),
            timeout=20,
        )
        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text[:300]}
        return resp.status_code, body

    def get_execution(self, execution_id: str) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/executions/{execution_id}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
