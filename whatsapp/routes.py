"""
AgriSpark 2.0 — WhatsApp Bot Routes
Handles inbound WhatsApp messages: text and images with full agentic AI.
"""

from flask import Blueprint, request, Response
from twilio.twiml.messaging_response import MessagingResponse
import traceback

from utils import session
from ai import gemini
from utils.weather import get_weather_summary
from pdf.generator import generate_pdf, get_pdf_url
from utils.delivery import send_whatsapp_pdf, send_sms
from ai.gemini import generate_sms_summary, generate_farm_plan, extract_profile_from_history
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

# ─── Main WhatsApp webhook ────────────────────────────────────────────────────

@wa_bp.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    ai_reply = ""
    try:
        from_number  = request.form.get("From", "")
        body         = request.form.get("Body", "").strip()
        num_media    = int(request.form.get("NumMedia", 0))
        media_url    = request.form.get("MediaUrl0", "")
        media_type   = request.form.get("MediaContentType0", "")

        # Load / initialize session
        sess = session.get(from_number)
        lang = sess.get("lang", None)

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

        # Commands
        if body_lower in ("help", "menu", "ช่วย", "เมนู", "start"):
            msg.body(MENU_TH if lang == "TH" else MENU_EN)
            return Response(str(resp), mimetype="application/xml")

        if body_lower in ("reset", "restart", "เริ่มใหม่"):
            session.delete(from_number)
            msg.body("✅ Reset. How can I help you today?" if lang == "EN" else "✅ รีเซ็ตแล้ว มีอะไรให้ฉันช่วยไหม?")
            return Response(str(resp), mimetype="application/xml")

        if body_lower in ("stop", "cancel", "exit", "หยุด", "ยกเลิก"):
            session.update(from_number, plan_step=0, awaiting=None)
            msg.body("✅ Stopped. Ask me anything!" if lang == "EN" else "✅ ยกเลิกแล้ว ถามฉันได้เลย!")
            return Response(str(resp), mimetype="application/xml")

        if body_lower in ("weather", "อากาศ"):
            stored_loc = sess.get("location") or "Thailand"
            summary = get_weather_summary(stored_loc)
            msg.body(f"🌦 Weather for {stored_loc}:\n{summary}" if lang == "EN" else f"🌦 อากาศที่ {stored_loc}:\n{summary}")
            return Response(str(resp), mimetype="application/xml")

        if body_lower in ("price", "ราคา"):
            msg.body(_market_price_info(lang))
            return Response(str(resp), mimetype="application/xml")

        # ─── AGENTIC CHATBOT ──────────────────────────────────────────
        history = session.get_wa_history(from_number)
        
        try:
            # Get response
            ai_reply = gemini.chat_reply(lang, body, history)
            
            # Save history
            session.append_wa_history(from_number, "user", body)
            session.append_wa_history(from_number, "model", ai_reply)

            # Trigger PDF Plan?
            if ai_reply and "[GENERATE_PLAN]" in ai_reply:
                ai_reply = ai_reply.replace("[GENERATE_PLAN]", "").strip()
                
                # Extract profile
                profile = extract_profile_from_history(history + [{"role": "user", "text": body}])
                weather_text = get_weather_summary(profile.get("location", "Unknown"))
                
                # Build plan
                full_plan = generate_farm_plan(lang, profile, weather_text)
                
                try:
                    pdf_path = generate_pdf(profile, full_plan, lang)
                    pdf_url  = get_pdf_url(pdf_path)
                    send_whatsapp_pdf(from_number, f"📄 Plan for {profile.get('name', 'Farmer')} is ready!", pdf_url)
                    
                    sms_short = generate_sms_summary(lang, profile, full_plan[:300])
                    send_sms(from_number, sms_short)
                    
                    ai_reply += "\n\n✅ DONE! I've sent your PDF plan to WhatsApp and SMS."
                except Exception as pdf_err:
                    ai_reply += f"\n\n⚠️ (PDF Issue: {str(pdf_err)[:40]}...)"

        except Exception as e:
            print(f"Chat error: {traceback.format_exc()}")
            ai_reply = (f"I had a thinking hiccup. Please try again! ({str(e)[:40]})" 
                        if lang == "EN" else f"ขอโทษ มีปัญหาในการประมวลผล กรุณาลองอีกครั้ง ({str(e)[:40]})")

        if not str(ai_reply).strip():
            ai_reply = "I'm thinking... please ask that again!" if lang == "EN" else "กำลังประมวลผล... กรุณาลองใหม่อีกครั้ง"
            
        msg.body(ai_reply)
        return Response(str(resp), mimetype="application/xml")
    
    except Exception as fatal_e:
        tb = traceback.format_exc()
        print(f"FATAL: {tb}")
        err_log = f"🆘 *AgriSpark Fatal Error:*\n{str(fatal_e)}\n\n*Traceback:*\n{tb[:400]}"
        resp = MessagingResponse()
        resp.message(err_log)
        return Response(str(resp), mimetype="application/xml")

# ─── Price Helper ─────────────────────────────────────────────────────────────

def _market_price_info(lang: str) -> str:
    if lang == "TH":
        return "💰 *ราคาพืชผลล่าสุด*\n\n🌾 ข้าว: 12,000 บาท/ตัน\n🌽 ข้าวโพด: 8,000 บาท/ตัน"
    return "💰 *Approximate Crop Prices*\n\n🌾 Rice: 12,000 THB/ton\n🌽 Corn: 8,000 THB/ton"
