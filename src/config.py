import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DEMO_DIR = BASE_DIR / "demo"

BOLNA_API_KEY = os.environ.get("BOLNA_API_KEY", "")
BOLNA_BASE_URL = "https://api.bolna.ai"
GATEWAY_PORT = int(os.environ.get("PORT", "8000"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "nexuscloud-pay-q7x2k9")
NTFY_BASE_URL = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")
BOLNA_AGENT_ID = os.environ.get("BOLNA_AGENT_ID", "")
CALL_ALLOWLIST = [p.strip() for p in os.environ.get("CALL_ALLOWLIST", "").split(",") if p.strip()]
