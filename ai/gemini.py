"""
AgriSpark 2.0 — Google Gemini AI Wrapper
Handles: text chat, multi-turn conversation, image analysis
"""

import google.generativeai as genai
import requests
from PIL import Image
from io import BytesIO

from config import GEMINI_API_KEY, GROQ_API_KEY
from utils import prompts

genai.configure(api_key=GEMINI_API_KEY)

# Initialize Groq if key is present
try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

# Try these models in order of preference (confirmed in diagnosis)
_MODELS = [
    "models/gemini-flash-latest",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash",
    "models/gemini-pro-latest", 
]

# Cache for the first model that actually works to prevent timeouts
_WORKING_MODEL_NAME = None

def _get_working_model(system_instruction=None):
    """Attempt to initialize a model, caching the result for speed."""
    global _WORKING_MODEL_NAME
    
    # If we already found a working model, use it directly!
    if _WORKING_MODEL_NAME:
        return genai.GenerativeModel(_WORKING_MODEL_NAME, system_instruction=system_instruction)

    for model_name in _MODELS:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            # Test it briefly (only on the very first call)
            model.generate_content("test", generation_config={"max_output_tokens": 1})
            _WORKING_MODEL_NAME = model_name
            return model
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                continue
            raise e
    raise Exception("No working Gemini models found in your region/project.")


# ─── Quick Query (IVR single-turn) ───────────────────────────────────────────

def quick_answer(lang: str, question: str) -> str:
    """Single-turn conversational reply for IVR quick query with Groq fallback."""
    try:
        system = prompts.quick_system(lang)
        model = _get_working_model(system_instruction=system)
        resp  = model.generate_content(question)
        return resp.text.strip()
    except Exception as e:
        if ("429" in str(e) or "quota" in str(e).lower()) and groq_client:
            return _groq_chat(lang, question, [], prompts.quick_system(lang))
        return _handle_err(lang, e)


# ─── Detailed Farm Plan ───────────────────────────────────────────────────────

def generate_farm_plan(lang: str, profile: dict, weather_summary: str = "Not available") -> str:
    """Generate the full AI farm plan with Groq fallback."""
    prompt = prompts.plan_prompt(
        lang,
        **profile,
        weather_summary=weather_summary
    )
    try:
        model = _get_working_model()
        resp  = model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        if ("429" in str(e) or "quota" in str(e).lower()) and groq_client:
            return _groq_chat(lang, prompt, [])
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
    """Multi-turn WhatsApp chat with Groq fallback."""
    try:
        system = prompts.chat_system(lang)
        model = _get_working_model(system_instruction=system)
        chat  = model.start_chat(history=_format_history(history))
        resp  = chat.send_message(message)
        return resp.text.strip()
    except Exception as e:
        # 🚨 THE SAFETY SWITCH: Catch 429 and use Groq
        if ("429" in str(e) or "quota" in str(e).lower()) and groq_client:
            return _groq_chat(lang, message, history, prompts.chat_system(lang))
        return _handle_err(lang, e)

def _groq_chat(lang: str, message: str, history: list, system: str = None) -> str:
    """Fallback engine using Llama-3-70B on Groq."""
    if not groq_client: return "AI currently unavailable."
    
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    
    for turn in history:
        messages.append({"role": "user" if turn["role"] == "user" else "assistant", "content": turn["text"]})
    
    messages.append({"role": "user", "content": message})
    
    try:
        # Use the latest high-quality model
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )
        return completion.choices[0].message.content.strip()
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


def extract_profile_from_history(history: list) -> dict:
    """Uses Gemini to extract structured farmer info from chat history JSON."""
    model = _get_working_model()
    
    # Format the history for the extraction prompt
    history_str = "\n".join([f"{m['role'].upper()}: {m['text']}" for m in history])
    
    prompt = f"""
    Based on the agricultural conversation history below, extract the farmer's profile.
    If a field is unknown, leave it as 'Unknown'.
    
    HISTORY:
    {history_str}
    
    Respond ONLY with a JSON block in this format:
    {{
      "name": "Full Name",
      "location": "Province or Region",
      "past_crop": "Last Season's Crop",
      "current_crop": "Planned/Current Crop",
      "soil_type": "Soil Type",
      "terrain": "Terrain"
    }}
    """
    
    try:
        raw = model.generate_content(prompt).text.strip()
        import json
        # Basic JSON cleanup in case of markdown
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        
        return json.loads(raw)
    except Exception:
        return {
            "name": "Farmer", "location": "Unknown", "past_crop": "Unknown",
            "current_crop": "Unknown", "soil_type": "Unknown", "terrain": "Unknown"
        }


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
