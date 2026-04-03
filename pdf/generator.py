"""
AgriSpark 2.0 — PDF Farm Plan Generator
Builds a professional, branded PDF using ReportLab.
"""

import os
import uuid
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

import config

# ─── Brand Colours ────────────────────────────────────────────────────────────
GREEN_DARK  = colors.HexColor("#1B4332")
GREEN_MID   = colors.HexColor("#40916C")
GREEN_LIGHT = colors.HexColor("#D8F3DC")
GOLD        = colors.HexColor("#F4A261")
WHITE       = colors.white
GREY_TEXT   = colors.HexColor("#4A4A4A")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold",
                                fontSize=24, textColor=WHITE,
                                spaceAfter=8, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica-Bold",
                                   fontSize=14, textColor=GOLD,
                                   spaceAfter=6, alignment=TA_CENTER),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold",
                                  fontSize=15, textColor=colors.HexColor("#0D3B16"),
                                  spaceBefore=16, spaceAfter=6),
        "body": ParagraphStyle("body", fontName="Helvetica",
                               fontSize=11, textColor=GREY_TEXT,
                               spaceAfter=6, leading=16),
        "small": ParagraphStyle("small", fontName="Helvetica",
                                fontSize=9, textColor=GREY_TEXT,
                                alignment=TA_CENTER),
    }


def generate_pdf(profile: dict, plan_text: str, lang: str = "EN") -> str:
    """
    Generate a PDF farm plan and return the absolute file path.
    profile: dict with farmer fields
    plan_text: full AI-generated advisory text
    lang: 'EN' or 'TH'
    """
    os.makedirs(config.PDF_DIR, exist_ok=True)
    farmer_id = str(uuid.uuid4())[:8]
    filename  = f"agrispark_plan_{farmer_id}.pdf"
    filepath  = os.path.join(config.PDF_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    st  = _styles()
    story = []

    # ── Header Banner ────────────────────────────────────────────────────────
    header_data = [[
        Paragraph("🌾 AGRISPARK MASTER ADVISORY", st["title"]),
    ]]
    header_table = Table(header_data, colWidths=[17*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0D361F")), # High-Authority Dark Green
        ("TOPPADDING",    (0, 0), (-1, -1), 22),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("ROUNDEDCORNERS", [8]),
    ]))
    story.append(header_table)

    subtitle = ("MISSION-CRITICAL FARM COMMANDS" if lang == "EN"
                else "คำสั่งการทำฟาร์มที่สำคัญยิ่ง")
    story.append(Paragraph(subtitle, st["subtitle"]))
    story.append(Spacer(1, 0.4*cm))

    # ── Date & ID ────────────────────────────────────────────────────────────
    date_str = datetime.now().strftime("%d %B %Y")
    story.append(Paragraph(f"GENRATED: {date_str}  |  ARCHIVE ID: {farmer_id}", st["small"]))
    story.append(HRFlowable(width="100%", thickness=2.5, color=GREEN_DARK, spaceAfter=12))

    # ── Farmer Profile Table ──────────────────────────────────────────────────
    heading = "FARMER PROFILE" if lang == "EN" else "ข้อมูลเกษตรกร"
    story.append(Paragraph(heading, st["section"]))

    labels_en = ["Name", "Location", "Past Crop", "Planned Crop", "Soil Type", "Terrain"]
    labels_th = ["ชื่อ", "ที่ตั้ง", "พืชที่ผ่านมา", "พืชที่วางแผน", "ประเภทดิน", "สภาพพื้นที่"]
    labels = labels_th if lang == "TH" else labels_en
    fields = ["name", "location", "past_crop", "current_crop", "soil_type", "terrain"]

    table_data = [[
        Paragraph(f"<b>{lbl}</b>", st["body"]),
        Paragraph(str(profile.get(f, "—")), st["body"])
    ] for lbl, f in zip(labels, fields)]

    profile_table = Table(table_data, colWidths=[5*cm, 12*cm])
    profile_table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (0, -1), GREEN_LIGHT),
        ("GRID",         (0, 0), (-1, -1), 0.5, GREEN_MID),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(profile_table)
    story.append(Spacer(1, 0.4*cm))

    # ── AI Plan Content ───────────────────────────────────────────────────────
    plan_heading = "YOUR FARM ADVISORY PLAN" if lang == "EN" else "แผนการเกษตรของคุณ"
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN_MID, spaceAfter=6))
    story.append(Paragraph(plan_heading, st["section"]))

    # Split plan text into paragraphs by double newlines or numbered sections
    for para in plan_text.split("\n"):
        stripped = para.strip()
        if not stripped:
            story.append(Spacer(1, 0.2*cm))
            continue
        # Detect section headers (numbered or all-caps lines)
        if stripped and (stripped[0].isdigit() and "." in stripped[:3]):
            story.append(Paragraph(stripped, st["section"]))
        elif stripped.isupper() and len(stripped) > 3:
            story.append(Paragraph(stripped, st["section"]))
        else:
            story.append(Paragraph(stripped, st["body"]))

    # ── Footer ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.6*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN_MID, spaceAfter=6))
    footer_text = ("AgriSpark 2.0 — AI Agricultural Advisory for Southeast Asia | "
                   "WhatsApp your questions anytime for ongoing support.")
    story.append(Paragraph(footer_text, st["small"]))

    doc.build(story)
    return filepath


def get_pdf_url(filepath: str) -> str:
    """Convert local path to public URL for WhatsApp delivery."""
    filename = os.path.basename(filepath)
    base = config.BASE_URL.strip("/")
    
    # 🕵️‍♂️ SMART PROTOCOL: Ensure the URL has http/https
    if base and not (base.startswith("http://") or base.startswith("https://")):
        # Default to https for security unless it's localhost
        if "localhost" in base or "127.0.0.1" in base:
            base = f"http://{base}"
        else:
            base = f"https://{base}"
            
    return f"{base}/static/pdf/{filename}"
