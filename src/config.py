import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DEMO_DIR = BASE_DIR / "demo"

BOLNA_API_KEY = os.environ.get("BOLNA_API_KEY", "")
BOLNA_BASE_URL = "https://api.bolna.ai"
GATEWAY_PORT = int(os.environ.get("PORT", "8000"))
