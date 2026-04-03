"""
AgriSpark 2.0 — IVR Routes
All Twilio Voice webhook endpoints.
"""

from flask import Blueprint, request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather

from utils import session
from ai import gemini
from utils.weather import get_weather_summary
from pdf.generator import generate_pdf, get_pdf_url
from utils.delivery import send_whatsapp_pdf, send_sms
from ai.gemini import generate_sms_summary

ivr_bp = Blueprint("ivr", __name__, url_prefix="/ivr")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _say(resp: VoiceResponse, text: str, lang: str) -> None:
    """Add a <Say> with the correct voice for the language."""
    voice   = "Polly.Joanna"        if lang == "EN" else "Polly.Saara"
    langcode = "en-US"              if lang == "EN" else "th-TH"
    resp.say(text, voice=voice, language=langcode)


def _twiml(resp: VoiceResponse) -> Response:
    return Response(str(resp), mimetype="application/xml")


def _speech_lang(lang: str) -> str:
    return "en-US" if lang == "EN" else "th-TH"


# ─── STEP 0: Language Gate ────────────────────────────────────────────────────

@ivr_bp.route("/welcome", methods=["POST"])
def welcome():
    call_sid = request.form.get("CallSid", "unknown")
    session.set(call_sid, {"lang": "EN", "step": 1})   # default

    resp    = VoiceResponse()
    gather  = Gather(num_digits=1, action="/ivr/set-language", method="POST",
                     timeout=10)
    gather.say(
        "Welcome to AgriSpark. Your AI farming advisor. "
        "Press 1 for English. Press 2 for Thai. "
        "ยินดีต้อนรับสู่ AgriSpark กด 1 สำหรับภาษาอังกฤษ กด 2 สำหรับภาษาไทย",
        voice="Polly.Joanna", language="en-US"
    )
    resp.append(gather)
    # Fallback if no input
    resp.redirect("/ivr/welcome")
    return _twiml(resp)


@ivr_bp.route("/set-language", methods=["POST"])
def set_language():
    call_sid = request.form.get("CallSid", "unknown")
    digit    = request.form.get("Digits", "1")
    lang     = "TH" if digit == "2" else "EN"
    session.update(call_sid, lang=lang)

    resp   = VoiceResponse()
    gather = Gather(num_digits=1, action="/ivr/set-mode", method="POST", timeout=10)

    if lang == "EN":
        gather.say(
            "Great! Press 1 for a quick question. Press 2 for a full personalised farm plan.",
            voice="Polly.Joanna", language="en-US"
        )
    else:
        gather.say(
            "ดีมาก! กด 1 สำหรับคำถามด่วน กด 2 สำหรับแผนการเกษตรแบบละเอียด",
            voice="Polly.Saara", language="th-TH"
        )

    resp.append(gather)
    resp.redirect("/ivr/set-language")
    return _twiml(resp)


# ─── STEP 1: Mode Gate ────────────────────────────────────────────────────────

@ivr_bp.route("/set-mode", methods=["POST"])
def set_mode():
    call_sid = request.form.get("CallSid", "unknown")
    digit    = request.form.get("Digits", "1")
    lang     = session.get_lang(call_sid)
    mode     = "detailed" if digit == "2" else "quick"
    session.update(call_sid, mode=mode)

    resp = VoiceResponse()
    if mode == "quick":
        resp.redirect("/ivr/quickchat")
    else:
        resp.redirect("/ivr/collect")
    return _twiml(resp)


# ─── QUICK QUERY MODE: Conversation Loop ─────────────────────────────────────

@ivr_bp.route("/quickchat", methods=["POST"])
def quickchat():
    call_sid = request.form.get("CallSid", "unknown")
    lang     = session.get_lang(call_sid)
    resp     = VoiceResponse()

    prompt_text = (
        "Please speak your question after the tone. I am listening."
        if lang == "EN"
        else "กรุณาพูดคำถามของคุณหลังจากเสียงสัญญาณ ฉันกำลังฟังอยู่"
    )

    gather = Gather(
        input="speech",
        language=_speech_lang(lang),
        action="/ivr/quickreply",
        method="POST",
        speech_timeout="auto",
        timeout=5,
    )
    _say_gather(gather, prompt_text, lang)
    resp.append(gather)

    # Fallback if nothing spoken
    if lang == "EN":
        resp.say("I didn't catch that. Let me try again.", voice="Polly.Joanna", language="en-US")
    else:
        resp.say("ฉันไม่ได้ยิน ลองอีกครั้ง", voice="Polly.Saara", language="th-TH")
    resp.redirect("/ivr/quickchat")
    return _twiml(resp)


def _say_gather(gather, text: str, lang: str):
    voice    = "Polly.Joanna" if lang == "EN" else "Polly.Saara"
    langcode = "en-US"        if lang == "EN" else "th-TH"
    gather.say(text, voice=voice, language=langcode)


@ivr_bp.route("/quickreply", methods=["POST"])
def quickreply():
    call_sid   = request.form.get("CallSid", "unknown")
    lang       = session.get_lang(call_sid)
    transcript = request.form.get("SpeechResult", "").strip()

    resp = VoiceResponse()

    if not transcript:
        resp.redirect("/ivr/quickchat")
        return _twiml(resp)

    # Store conversation for context
    history = session.get(call_sid).get("history", [])
    history.append({"role": "user", "text": transcript})

    try:
        ai_reply = gemini.quick_answer(lang, transcript)
    except Exception as e:
        ai_reply = ("Sorry, I had trouble with that. Please repeat your question."
                    if lang == "EN"
                    else "ขอโทษ มีปัญหา กรุณาถามอีกครั้ง")

    history.append({"role": "model", "text": ai_reply})
    session.update(call_sid, history=history[-20:])

    _say(resp, ai_reply, lang)

    # Ask if they have another question
    gather = Gather(
        num_digits=1,
        action="/ivr/quickchat-again",
        method="POST",
        timeout=8,
    )
    follow_up = (
        "Press 1 to ask another question, or press 2 to end the call."
        if lang == "EN"
        else "กด 1 เพื่อถามคำถามอื่น หรือกด 2 เพื่อวางสาย"
    )
    _say_gather(gather, follow_up, lang)
    resp.append(gather)
    resp.redirect("/ivr/goodbye")
    return _twiml(resp)


@ivr_bp.route("/quickchat-again", methods=["POST"])
def quickchat_again():
    call_sid = request.form.get("CallSid", "unknown")
    digit    = request.form.get("Digits", "2")
    resp     = VoiceResponse()
    if digit == "1":
        resp.redirect("/ivr/quickchat")
    else:
        resp.redirect("/ivr/goodbye")
    return _twiml(resp)


# ─── DETAILED PLAN MODE: 6-Step Wizard ───────────────────────────────────────

STEPS_EN = [
    ("name",         "What is your name?"),
    ("location",     "What is the location or province of your farm field?"),
    ("past_crop",    "What crop did you grow last season?"),
    ("current_crop", "What crop are you planning to grow this season?"),
    ("soil_type",    "What is your soil type? Say sandy, clay, loam, or unknown."),
    ("terrain",      "Describe your terrain. Say flat, hilly, sloped, or near water."),
]

STEPS_TH = [
    ("name",         "ชื่อของคุณคืออะไร?"),
    ("location",     "ฟาร์มของคุณอยู่ที่ไหน หรือจังหวัดอะไร?"),
    ("past_crop",    "ฤดูที่ผ่านมาคุณปลูกพืชอะไร?"),
    ("current_crop", "ฤดูนี้คุณวางแผนจะปลูกพืชอะไร?"),
    ("soil_type",    "ประเภทดินของคุณคือ ดินทราย ดินเหนียว ดินร่วน หรือไม่ทราบ?"),
    ("terrain",      "สภาพพื้นที่ของคุณเป็นอย่างไร ราบเรียบ ลูกคลื่น ลาดเอียง หรือใกล้น้ำ?"),
]


@ivr_bp.route("/collect", methods=["POST"])
def collect():
    call_sid = request.form.get("CallSid", "unknown")
    lang     = session.get_lang(call_sid)
    step     = session.get_step(call_sid)   # 1–6
    steps    = STEPS_TH if lang == "TH" else STEPS_EN

    if step > len(steps):
        return _twiml(VoiceResponse())  # safety

    _, question = steps[step - 1]

    resp = VoiceResponse()

    # Intro message on step 1
    if step == 1:
        intro = (
            "Great! I will ask you 6 quick questions to build your personalised farm plan. "
            if lang == "EN"
            else "ดีมาก! ฉันจะถามคุณ 6 คำถามสั้นๆ เพื่อสร้างแผนการเกษตรส่วนตัวของคุณ "
        )
        _say(resp, intro, lang)

    gather = Gather(
        input="speech",
        language=_speech_lang(lang),
        action="/ivr/collect-answer",
        method="POST",
        speech_timeout="auto",
        timeout=8,
    )
    _say_gather(gather, question, lang)
    resp.append(gather)

    # Fallback
    no_answer = ("I didn't hear you. Please try again." if lang == "EN"
                 else "ฉันไม่ได้ยิน กรุณาลองอีกครั้ง")
    _say(resp, no_answer, lang)
    resp.redirect("/ivr/collect")
    return _twiml(resp)


@ivr_bp.route("/collect-answer", methods=["POST"])
def collect_answer():
    call_sid   = request.form.get("CallSid", "unknown")
    lang       = session.get_lang(call_sid)
    transcript = request.form.get("SpeechResult", "").strip()
    step       = session.get_step(call_sid)
    steps      = STEPS_TH if lang == "TH" else STEPS_EN

    if not transcript:
        # Re-ask the same question
        resp = VoiceResponse()
        resp.redirect("/ivr/collect")
        return _twiml(resp)

    field_key = steps[step - 1][0]
    session.update(call_sid, **{field_key: transcript})

    resp = VoiceResponse()
    if step < len(steps):
        session.increment_step(call_sid)
        resp.redirect("/ivr/collect")
    else:
        # All 6 steps done
        done_msg = (
            "Thank you! I have everything I need. Generating your personalised farm plan now. "
            "This will take just a moment."
            if lang == "EN"
            else "ขอบคุณ! ฉันมีข้อมูลครบแล้ว กำลังสร้างแผนการเกษตรส่วนตัวของคุณ โปรดรอสักครู่"
        )
        _say(resp, done_msg, lang)
        resp.redirect("/ivr/complete")
    return _twiml(resp)


# ─── COMPLETION: Generate Plan + Send Deliveries ──────────────────────────────

@ivr_bp.route("/complete", methods=["POST"])
def complete():
    call_sid = request.form.get("CallSid", "unknown")
    lang     = session.get_lang(call_sid)
    farmer_no = request.form.get("From", "")
    sess     = session.get(call_sid)

    profile = {
        "name":         sess.get("name",         "Farmer"),
        "location":     sess.get("location",      "Unknown"),
        "past_crop":    sess.get("past_crop",     "Unknown"),
        "current_crop": sess.get("current_crop",  "Unknown"),
        "soil_type":    sess.get("soil_type",     "Unknown"),
        "terrain":      sess.get("terrain",       "Unknown"),
    }

    resp = VoiceResponse()

    try:
        # 1. Get weather context
        weather = get_weather_summary(profile["location"])

        # 2. Generate AI plan
        plan_text = gemini.generate_farm_plan(lang, profile, weather)

        # 3. Generate PDF
        pdf_path = generate_pdf(profile, plan_text, lang)
        pdf_url  = get_pdf_url(pdf_path)

        # 4. Generate SMS summary
        sms_text = generate_sms_summary(lang, profile, plan_text[:500])

        # 5. Send WhatsApp PDF
        if farmer_no:
            try:
                wa_body = (
                    f"🌾 Hello {profile['name']}! Your AgriSpark 2.0 farm plan is ready. "
                    f"See your personalised recommendations below."
                    if lang == "EN"
                    else
                    f"🌾 สวัสดี {profile['name']}! แผนการเกษตร AgriSpark 2.0 ของคุณพร้อมแล้ว"
                )
                send_whatsapp_pdf(farmer_no, wa_body, pdf_url)
            except Exception:
                pass  # Don't fail the call if WhatsApp fails

            # 6. Send SMS summary
            try:
                send_sms(farmer_no, sms_text)
            except Exception:
                pass

        # 7. Read a spoken summary over the phone
        spoken_summary = _extract_spoken_summary(plan_text, lang)
        _say(resp, spoken_summary, lang)

    except Exception as e:
        error_msg = (
            "I'm sorry, I encountered an error generating your plan. "
            "Please WhatsApp us for support."
            if lang == "EN"
            else "ขอโทษ เกิดข้อผิดพลาดในการสร้างแผน กรุณาติดต่อเราทาง WhatsApp"
        )
        _say(resp, error_msg, lang)

    resp.redirect("/ivr/goodbye")
    session.delete(call_sid)
    return _twiml(resp)


def _extract_spoken_summary(plan_text: str, lang: str) -> str:
    """Extract a short spoken version of the plan (first ~200 words)."""
    lines = [l.strip() for l in plan_text.split("\n") if l.strip()]
    excerpt = " ".join(lines[:8])[:600]
    suffix = (
        " Your full plan has been sent to your WhatsApp and SMS. Thank you for using AgriSpark!"
        if lang == "EN"
        else " แผนเต็มของคุณถูกส่งไปยัง WhatsApp และ SMS แล้ว ขอบคุณที่ใช้ AgriSpark!"
    )
    return excerpt + suffix


# ─── Goodbye ─────────────────────────────────────────────────────────────────

@ivr_bp.route("/goodbye", methods=["POST"])
def goodbye():
    call_sid = request.form.get("CallSid", "unknown")
    lang     = session.get_lang(call_sid)
    resp     = VoiceResponse()
    msg = (
        "Thank you for calling AgriSpark. Wishing you a great harvest. Goodbye!"
        if lang == "EN"
        else "ขอบคุณที่โทรหา AgriSpark ขอให้คุณประสบความสำเร็จในการเก็บเกี่ยว ลาก่อน!"
    )
    _say(resp, msg, lang)
    resp.hangup()
    return _twiml(resp)
