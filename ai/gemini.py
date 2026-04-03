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

if not GEMINI_API_KEY:
    print("🚨 WARNING: GEMINI_API_KEY is missing in environmental variables!")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# Initialize Groq if key is present
try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

# Try these models in order of preference
_MODELS = [
    "models/gemini-flash-latest",
    "models/gemini-2.0-flash",
    "models/gemini-2.5-flash",
    "models/gemini-pro-latest", 
]

# Cache for the first model that actually works
_WORKING_MODEL_NAME = None

def _get_working_model(system_instruction=None):
    """Attempt to initialize a model, caching the result for speed."""
    global _WORKING_MODEL_NAME
    
    if _WORKING_MODEL_NAME:
        return genai.GenerativeModel(_WORKING_MODEL_NAME, system_instruction=system_instruction)

    for model_name in _MODELS:
        try:
            model = genai.GenerativeModel(model_name, system_instruction=system_instruction)
            model.generate_content("test", generation_config={"max_output_tokens": 1})
            _WORKING_MODEL_NAME = model_name
            return model
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                continue
            raise e
    raise Exception("No working Gemini models found in your region.")


# ─── Quick Query (IVR single-turn) ───────────────────────────────────────────

def quick_answer(lang: str, question: str) -> str:
    """Single-turn conversational reply for IVR quick query with Groq fallback."""
    try:
        system = prompts.quick_system(lang)
        model = _get_working_model(system_instruction=system)
        resp  = model.generate_content(question)
        return resp.text.strip()
    except Exception as e:
        if groq_client:
            print(f"📡 AI FALLBACK (IVR): Gemini hit an issue ({str(e)[:40]}). Switching to GROQ...")
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
        if groq_client:
            print(f"📡 AI FALLBACK (PLAN): Gemini hit an issue. Switching to GROQ...")
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
    except Exception:
        return f"AgriSpark: Full plan for {profile.get('name', 'you')} is ready. See WhatsApp."


# ─── WhatsApp Multi-turn Chat ─────────────────────────────────────────────────

def chat_reply(lang: str, message: str, history: list) -> str:
    """Multi-turn WhatsApp chat with aggressive Groq fallback."""
    try:
        system = prompts.chat_system(lang)
        model = _get_working_model(system_instruction=system)
        chat  = model.start_chat(history=_format_history(history))
        resp  = chat.send_message(message)
        return resp.text.strip()
    except Exception as e:
        if groq_client:
            print(f"📡 AI FALLBACK (CHAT): Gemini is busy ({str(e)[:40]}). Switching to GROQ...")
            return _groq_chat(lang, message, history, prompts.chat_system(lang))
        return _handle_err(lang, e)


def _groq_chat(lang: str, message: str, history: list, system: str = None) -> str:
    """Fallback engine using Llama-3-7b on Groq."""
    if not groq_client: return "AgriSpark Brain is currently busy. Please message back in a minute!"
    
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    
    for turn in history:
        role = "user" if turn.get("role") == "user" else "assistant"
        content = turn.get("text", "")
        if content:
            messages.append({"role": role, "content": content})
    
    messages.append({"role": "user", "content": message})
    
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
            max_tokens=1024
        )
        return str(completion.choices[0].message.content or "AI is thinking...").strip()
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
    """Uses Gemini to extract structured farmer info from chat history JSON with Groq fallback."""
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
        model = _get_working_model()
        raw = model.generate_content(prompt).text.strip()
        return _parse_profile_json(raw)
    except Exception as e:
        # 🛡️ THE SAFETY SWITCH: Use Groq if Gemini hits a quota limit
        if groq_client:
            print(f"📡 AI FALLBACK (EXTRACT): Gemini hit an issue ({str(e)[:40]}). Switching to GROQ...")
            try:
                # Use a simple chat completion with same prompt
                messages = [{"role": "system", "content": "You are a data extraction bot. Respond only in JSON."},
                            {"role": "user", "content": prompt}]
                completion = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    temperature=0.1 # Low temperature for strict JSON
                )
                raw = str(completion.choices[0].message.content or "{}").strip()
                return _parse_profile_json(raw)
            except Exception:
                pass
        
        return {
            "name": "Farmer", "location": "Unknown", "past_crop": "Unknown",
            "current_crop": "Unknown", "soil_type": "Unknown", "terrain": "Unknown"
        }

def _parse_profile_json(raw: str) -> dict:
    """Helper to clean and parse the profile JSON."""
    import json
    try:
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

def clean_ivr_answer(lang: str, field_key: str, transcript: str) -> str:
    """Takes a messy IVR transcript and returns a clean, single-value category."""
    if not transcript or len(transcript) < 2: return "Unknown"
    
    prompt = f"""
    You are a data cleaner for an agricultural IVR. 
    Convert this messy spoken transcript for field '{field_key}' into a CLEAN, CONCISE value.
    If the field is 'location', return ONLY the city or province name.
    If the field is 'soil_type', return one of: [Sandy, Clay, Loam, Unknown].
    If the field is 'terrain', return one of: [Flat, Hilly, Sloped, Near Water, Unknown].
    
    TRANSCRIPT: "{transcript}"
    
    Respond ONLY with the cleaned value. No explanation.
    """
    try:
        model = _get_working_model()
        resp = model.generate_content(prompt, generation_config={"max_output_tokens": 10})
        return resp.text.strip()
    except Exception:
        return transcript.strip()

def detect_language(text: str) -> str:
    """Returns 'TH' or 'EN' based on text content."""
    try:
        from langdetect import detect
        code = detect(text)
        return "TH" if code == "th" else "EN"
    except Exception:
        return "EN"

def _handle_err(lang: str, e: Exception) -> str:
    """Consistently handle errors and return a string."""
    msg = str(e)[:100]
    if lang == "TH":
        return f"ขอโทษ มีปัญหาการเชื่อมต่อเล็กน้อย: {msg}"
    return f"Sorry, I had a processing hiccup. Please try that again! ({msg})"
