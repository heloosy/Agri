"""
AgriSpark 2.0 — WhatsApp Bot Routes
Handles inbound WhatsApp messages: text and images.
"""

from flask import Blueprint, request, Response
from twilio.twiml.messaging_response import MessagingResponse

from utils import session
from ai import gemini
from utils.weather import get_weather_summary
from pdf.generator import generate_pdf, get_pdf_url
from utils.delivery import send_whatsapp_pdf, send_sms
from ai.gemini import generate_sms_summary, generate_farm_plan
import config

wa_bp = Blueprint("whatsapp", __name__, url_prefix="")

# ─── Menu messages ────────────────────────────────────────────────────────────

MENU_EN = """🌾 *AgriSpark 2.0* — Your AI Farming Advisor

Commands:
• *plan* — Get a personalised farm plan (PDF)
• *weather* — 7-day weather for your location
• *price* — Crop market price guidance
• *help* — Show this menu

Or just ask me anything about farming! Send a photo of your crop for instant diagnosis. 🌿"""

MENU_TH = """🌾 *AgriSpark 2.0* — ที่ปรึกษาการเกษตร AI ของคุณ

คำสั่ง:
• *plan* — รับแผนการเกษตรส่วนตัว (PDF)
• *weather* — พยากรณ์อากาศ 7 วัน
• *price* — ข้อมูลราคาพืชผล
• *help* — แสดงเมนูนี้

หรือถามฉันเรื่องการเกษตรได้เลย! ส่งรูปพืชของคุณเพื่อการวินิจฉัยทันที 🌿"""

# ─── Plan collection state machine ───────────────────────────────────────────

PLAN_STEPS_EN = [
    ("name",         "What is your name?"),
    ("location",     "What is the location or province of your farm?"),
    ("past_crop",    "What crop did you grow last season?"),
    ("current_crop", "What crop are you planning to grow now?"),
    ("soil_type",    "What is your soil type? (sandy / clay / loam / unknown)"),
    ("terrain",      "Describe your terrain. (flat / hilly / sloped / near water)"),
]

PLAN_STEPS_TH = [
    ("name",         "ชื่อของคุณคืออะไร?"),
    ("location",     "ฟาร์มของคุณอยู่ที่ไหน?"),
    ("past_crop",    "ฤดูที่ผ่านมาปลูกพืชอะไร?"),
    ("current_crop", "ตอนนี้วางแผนจะปลูกพืชอะไร?"),
    ("soil_type",    "ประเภทดิน? (ดินทราย / ดินเหนียว / ดินร่วน / ไม่ทราบ)"),
    ("terrain",      "สภาพพื้นที่? (ราบ / ลูกคลื่น / ลาดเอียง / ใกล้น้ำ)"),
]


# ─── Main WhatsApp webhook ────────────────────────────────────────────────────

@wa_bp.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    from_number  = request.form.get("From", "")     # e.g. whatsapp:+66812345678
    body         = request.form.get("Body", "").strip()
    num_media    = int(request.form.get("NumMedia", 0))
    media_url    = request.form.get("MediaUrl0", "")
    media_type   = request.form.get("MediaContentType0", "")

    # Load / initialize session
    sess = session.get(from_number)
    lang = sess.get("lang", None)

    # Auto-detect language if not yet set
    if lang is None:
        if body:
            lang = gemini.detect_language(body)
        else:
            lang = "EN"
        session.update(from_number, lang=lang)

    resp = MessagingResponse()
    msg  = resp.message()

    # ─── Image received ───────────────────────────────────────────────────────
    if num_media > 0 and media_url and "image" in media_type:
        analysis = gemini.analyze_image(
            lang, media_url,
            config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN
        )
        session.append_wa_history(from_number, "user", "[Image sent]")
        session.append_wa_history(from_number, "model", analysis)
        msg.body(analysis)
        return Response(str(resp), mimetype="application/xml")

    # ─── Text commands ────────────────────────────────────────────────────────
    body_lower = body.lower().strip()

    if body_lower in ("help", "menu", "ช่วย", "เมนู", "start"):
        reply = MENU_TH if lang == "TH" else MENU_EN
        msg.body(reply)
        return Response(str(resp), mimetype="application/xml")

    if body_lower in ("stop", "cancel", "exit", "หยุด", "ยกเลิก"):
        session.update(from_number, plan_step=0, awaiting=None)
        reply = "✅ Stopped. You are back in general chat. Ask me anything!" if lang == "EN" else "✅ ยกเลิกแล้ว คุณกลับมาสู่การแชทปกติ ถามฉันได้เลย!"
        msg.body(reply)
        return Response(str(resp), mimetype="application/xml")

    if body_lower == "plan":
        # Start plan collection wizard
        session.update(from_number, plan_step=1, plan_data={})
        steps = PLAN_STEPS_TH if lang == "TH" else PLAN_STEPS_EN
        intro = (
            "🌾 Let's build your personalised farm plan! I'll ask you 6 quick questions.\n\n"
            if lang == "EN"
            else "🌾 มาสร้างแผนการเกษตรส่วนตัวของคุณกัน! ฉันจะถาม 6 คำถามสั้นๆ\n\n"
        )
        msg.body(intro + "1️⃣ " + steps[0][1])
        return Response(str(resp), mimetype="application/xml")

    if body_lower in ("weather", "อากาศ"):
        stored_loc = sess.get("plan_data", {}).get("location") or sess.get("location")
        if stored_loc:
            summary = get_weather_summary(stored_loc)
            prefix  = f"🌦 Weather for {stored_loc}:\n" if lang == "EN" else f"🌦 อากาศที่ {stored_loc}:\n"
            msg.body(prefix + summary)
        else:
            ask = "Which location do you want weather for?" if lang == "EN" else "คุณต้องการพยากรณ์อากาศของที่ไหน?"
            session.update(from_number, awaiting="weather_location")
            msg.body(ask)
        return Response(str(resp), mimetype="application/xml")

    if body_lower in ("price", "ราคา"):
        price_msg = _market_price_info(lang)
        msg.body(price_msg)
        return Response(str(resp), mimetype="application/xml")

    # ─── Plan collection wizard (in progress) ────────────────────────────────
    plan_step = sess.get("plan_step", 0)
    if plan_step and plan_step <= 6:
        reply_text = _handle_plan_step(from_number, lang, body, plan_step)
        msg.body(reply_text)
        return Response(str(resp), mimetype="application/xml")

    # ─── Awaiting weather location ────────────────────────────────────────────
    if sess.get("awaiting") == "weather_location":
        session.update(from_number, location=body, awaiting=None)
        summary = get_weather_summary(body)
        prefix  = f"🌦 Weather for {body}:\n" if lang == "EN" else f"🌦 อากาศที่ {body}:\n"
        msg.body(prefix + summary)
        return Response(str(resp), mimetype="application/xml")

    # ─── General conversation ─────────────────────────────────────────────────
    history = session.get_wa_history(from_number)
    session.append_wa_history(from_number, "user", body)
    try:
        ai_reply = gemini.chat_reply(lang, body, history)
    except Exception as e:
        ai_reply = (f"Sorry, I had an issue: {str(e)[:80]}" if lang == "EN"
                    else f"ขอโทษ เกิดปัญหา: {str(e)[:80]}")
    session.append_wa_history(from_number, "model", ai_reply)
    msg.body(ai_reply)
    return Response(str(resp), mimetype="application/xml")


# ─── Plan Wizard Logic ────────────────────────────────────────────────────────

def _handle_plan_step(phone: str, lang: str, answer: str, step: int) -> str:
    sess  = session.get(phone)
    steps = PLAN_STEPS_TH if lang == "TH" else PLAN_STEPS_EN
    field = steps[step - 1][0]

    # Save this answer
    plan_data = sess.get("plan_data", {})
    plan_data[field] = answer
    session.update(phone, plan_data=plan_data)

    if step < len(steps):
        session.update(phone, plan_step=step + 1)
        next_q = steps[step][1]
        num_emoji = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣"]
        return f"{num_emoji[step]} {next_q}"
    else:
        # All 6 questions answered — generate plan
        session.update(phone, plan_step=0)
        return _generate_and_deliver_plan(phone, lang, plan_data)


def _generate_and_deliver_plan(phone: str, lang: str, profile: dict) -> str:
    """Generate PDF plan and deliver via WhatsApp + SMS. Return status message."""
    try:
        # Building message
        thinking = (
            "⏳ Generating your personalised farm plan... This may take 30 seconds."
            if lang == "EN"
            else "⏳ กำลังสร้างแผนการเกษตรส่วนตัวของคุณ... อาจใช้เวลา 30 วินาที"
        )

        weather = get_weather_summary(profile.get("location", "Thailand"))
        plan_text = generate_farm_plan(lang, profile, weather)

        pdf_path = generate_pdf(profile, plan_text, lang)
        pdf_url  = get_pdf_url(pdf_path)

        sms_text = generate_sms_summary(lang, profile, plan_text[:500])

        # Send PDF on WhatsApp
        wa_body = (
            f"🌾 *Your AgriSpark Farm Plan is Ready!*\n\n"
            f"Hello {profile.get('name', 'Farmer')}! Here is your personalised advisory. "
            f"Download the PDF for your full 6-month calendar and recommendations."
            if lang == "EN"
            else
            f"🌾 *แผนการเกษตร AgriSpark ของคุณพร้อมแล้ว!*\n\n"
            f"สวัสดี {profile.get('name', 'เกษตรกร')}! นี่คือคำแนะนำส่วนตัวของคุณ"
        )
        try:
            send_whatsapp_pdf(phone, wa_body, pdf_url)
        except Exception:
            pass

        # Send SMS
        try:
            send_sms(phone, sms_text)
        except Exception:
            pass

        success = (
            "✅ Your farm plan PDF has been sent! Check WhatsApp and your SMS for a quick summary. "
            "Ask me anything else anytime — just type your question! 🌱"
            if lang == "EN"
            else
            "✅ ส่ง PDF แผนการเกษตรแล้ว! ตรวจสอบ WhatsApp และ SMS สำหรับสรุปย่อ "
            "ถามฉันได้ตลอดเวลา 🌱"
        )
        return success

    except Exception as e:
        return (
            f"Sorry, something went wrong generating your plan: {str(e)[:100]}"
            if lang == "EN"
            else f"ขอโทษ เกิดข้อผิดพลาด: {str(e)[:100]}"
        )


# ─── Market Price Info ────────────────────────────────────────────────────────

def _market_price_info(lang: str) -> str:
    if lang == "TH":
        return (
            "💰 *ราคาพืชผลล่าสุด (ประมาณการ ประเทศไทย)*\n\n"
            "🌾 ข้าวหอมมะลิ: 12,000–14,000 บาท/ตัน\n"
            "🌽 ข้าวโพด: 7,000–9,000 บาท/ตัน\n"
            "🍬 อ้อย: 900–1,100 บาท/ตัน\n"
            "🥜 มันสำปะหลัง: 2,000–2,800 บาท/ตัน\n"
            "🫘 ถั่วเหลือง: 15,000–18,000 บาท/ตัน\n\n"
            "💡 ราคาขึ้นอยู่กับตลาดท้องถิ่นและฤดูกาล "
            "ถามฉันเพื่อคำแนะนำเฉพาะพืช!"
        )
    return (
        "💰 *Approximate Crop Prices (Thailand)*\n\n"
        "🌾 Jasmine Rice: 12,000–14,000 THB/ton\n"
        "🌽 Corn/Maize: 7,000–9,000 THB/ton\n"
        "🍬 Sugarcane: 900–1,100 THB/ton\n"
        "🥜 Cassava: 2,000–2,800 THB/ton\n"
        "🫘 Soybean: 15,000–18,000 THB/ton\n\n"
        "💡 Prices vary by local market and season. "
        "Ask me for advice on the best time to sell!"
    )
