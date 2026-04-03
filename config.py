import os
from dotenv import load_dotenv

load_dotenv()

# ── Twilio ──────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE       = os.getenv("TWILIO_PHONE_NUMBER", "")
TWILIO_WHATSAPP    = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

# ── Google Gemini ────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SECRET_TRIGGER_CODE = os.getenv("SECRET_TRIGGER_CODE", "agrispark123")  # Simple protection

# ── App ─────────────────────────────────────────────
BASE_URL   = os.getenv("BASE_URL", "http://localhost:5000")
SECRET_KEY = os.getenv("SECRET_KEY", "agrispark-dev-secret")
PDF_DIR    = os.path.join(os.path.dirname(__file__), "static", "pdf")
