"""
AgriSpark 2.0 — Google Gemini AI Wrapper
Handles: text chat, multi-turn conversation, image analysis
"""

import google.generativeai as genai
import requests
from PIL import Image
from io import BytesIO

from config import GEMINI_API_KEY
from utils import prompts

genai.configure(api_key=GEMINI_API_KEY)

# Try these models in order of preference
_MODELS = [
    "models/gemini-1.5-flash",
    "models/gemini-1.5-flash-latest",
    "models/gemini-pro",  # Very stable fallback
]

def _get_working_model(system_instruction=None):
    """Attempt to initialize a model, falling back if one is not found."""
    for model_name in _MODELS:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            # Test it briefly
            model.generate_content("hello", generation_config={"max_output_tokens": 1})
            return model
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                continue
            # If it's a different error (like Auth), raise it immediately
            raise e
    raise Exception("No working Gemini models found in your region/project.")


# ─── Quick Query (IVR single-turn) ───────────────────────────────────────────

def quick_answer(lang: str, question: str) -> str:
    """Single-turn conversational reply for IVR quick query."""
    system = prompts.quick_system(lang)
    try:
        model = _get_working_model(system_instruction=system)
        resp  = model.generate_content(question)
        return resp.text.strip()
    except Exception as e:
        return _handle_err(lang, e)


# ─── Detailed Farm Plan ───────────────────────────────────────────────────────

def generate_farm_plan(lang: str, profile: dict, weather_summary: str = "Not available") -> str:
    """Generate the full AI farm plan from farmer profile."""
    prompt = prompts.plan_prompt(
        lang,
        name=profile.get("name", "Farmer"),
        location=profile.get("location", "Unknown"),
        past_crop=profile.get("past_crop", "Unknown"),
        current_crop=profile.get("current_crop", "Unknown"),
        soil_type=profile.get("soil_type", "Unknown"),
        terrain=profile.get("terrain", "Unknown"),
        weather_summary=weather_summary,
    )
    try:
        model = _get_working_model()
        resp  = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        return _handle_err(lang, e)


# ─── SMS Summary ─────────────────────────────────────────────────────────────

def generate_sms_summary(lang: str, profile: dict, key_points: str) -> str:
    """Generate a 160-char SMS summary."""
    prompt = prompts.sms_summary_prompt(
        lang,
        name=profile.get("name", "Farmer"),
        current_crop=profile.get("current_crop", "crop"),
        location=profile.get("location", "your area"),
        key_points=key_points,
    )
    try:
        model = _get_working_model()
        resp  = model.generate_content(prompt)
        return resp.text.strip()[:320]
    except Exception as e:
        return _handle_err(lang, e)


# ─── WhatsApp Multi-turn Chat ─────────────────────────────────────────────────

def chat_reply(lang: str, message: str, history: list) -> str:
    """Multi-turn WhatsApp chat with conversation history."""
    system = prompts.chat_system(lang)
    try:
        model = _get_working_model(system_instruction=system)
        chat  = model.start_chat(history=_format_history(history))
        resp  = chat.send_message(message)
        return resp.text.strip()
    except Exception as e:
        return _handle_err(lang, e)


def _format_history(history: list) -> list:
    """Convert stored history to Gemini format."""
    gemini_history = []
    for turn in history:
        role = "user" if turn["role"] == "user" else "model"
        gemini_history.append({
            "role": role,
            "parts": [turn["text"]]
        })
    return gemini_history


# ─── Image Analysis (WhatsApp) ────────────────────────────────────────────────

def analyze_image(lang: str, image_url: str, twilio_sid: str, twilio_token: str) -> str:
    """Download image from Twilio and analyze with Gemini Vision."""
    try:
        response = requests.get(image_url, auth=(twilio_sid, twilio_token), timeout=15)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content))

        prompt_text = prompts.image_prompt(lang)
        model = _get_working_model()
        resp  = model.generate_content([prompt_text, image])
        return resp.text.strip()
    except Exception as e:
        return _handle_err(lang, e)


# ─── Utilities ────────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Returns 'TH' or 'EN' based on text content."""
    try:
        from langdetect import detect
        code = detect(text)
        return "TH" if code == "th" else "EN"
    except Exception:
        return "EN"

def _handle_err(lang: str, e: Exception) -> str:
    msg = str(e)[:100]
    if lang == "TH":
        return f"ขอโทษ เกิดปัญหาในการประมวลผล AI: {msg}"
    return f"Sorry, I had an AI processing issue: {msg}"
