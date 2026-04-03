import os
from dotenv import load_dotenv

load_dotenv()

# ── Twilio ──────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip('"').strip("'")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "").strip('"').strip("'")
TWILIO_PHONE       = os.getenv("TWILIO_PHONE_NUMBER", "").strip('"').strip("'")
TWILIO_WHATSAPP    = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886").strip('"').strip("'")

# ── Google Gemini ────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip('"').strip("'")

# ── App ─────────────────────────────────────────────
BASE_URL   = os.getenv("BASE_URL", "http://localhost:5000").strip('"').strip("'")
SECRET_KEY = os.getenv("SECRET_KEY", "agrispark-dev-secret").strip('"').strip("'")
PDF_DIR    = os.path.join(os.path.dirname(__file__), "static", "pdf")
