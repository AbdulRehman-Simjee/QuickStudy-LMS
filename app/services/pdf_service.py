from __future__ import annotations

import re
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _new_canvas() -> tuple[BytesIO, canvas.Canvas, float, float]:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    return buffer, c, width, height


def _draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, line_height: float = 14) -> float:
    """
    Draw wrapped text and return updated y-coordinate.
    """

    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    for para in cleaned.split("\n"):
        words = para.split()
        if not words:
            y -= line_height
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if c.stringWidth(candidate, "Helvetica", 10) <= max_width:
                line = candidate
            else:
                c.drawString(x, y, line)
                y -= line_height
                line = word
                if y < 60:
                    c.showPage()
                    c.setFont("Helvetica", 10)
                    y = A4[1] - 50
        c.drawString(x, y, line)
        y -= line_height
        if y < 60:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = A4[1] - 50
    return y


def _extract_key_takeaways(summary_text: str, *, max_items: int = 5) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", summary_text.strip()) if p.strip()]
    return parts[:max_items]


def build_summary_pdf(*, video_title: str, summary_text: str) -> BytesIO:
    buffer, c, width, height = _new_canvas()
    y = height - 50
    left = 50
    max_width = width - 100

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, "QuickStudy LMS - Summary")
    y -= 24

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, f"Video: {video_title}")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Summary")
    y -= 16
    c.setFont("Helvetica", 10)
    y = _draw_wrapped(c, summary_text or "No summary available.", left, y, max_width)

    y -= 10
    if y < 80:
        c.showPage()
        y = height - 50

    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, "Key Takeaways")
    y -= 16
    c.setFont("Helvetica", 10)
    takeaways = _extract_key_takeaways(summary_text or "")
    if not takeaways:
        y = _draw_wrapped(c, "- No key takeaways available.", left, y, max_width)
    else:
        for item in takeaways:
            y = _draw_wrapped(c, f"- {item}", left, y, max_width)

    c.save()
    buffer.seek(0)
    return buffer


def build_flashcards_pdf(*, video_title: str, cards: list[dict[str, str]]) -> BytesIO:
    buffer, c, width, height = _new_canvas()
    y = height - 50
    left = 50
    max_width = width - 100

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, "QuickStudy LMS - Flashcards")
    y -= 24
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, f"Video: {video_title}")
    y -= 24

    for idx, card in enumerate(cards, start=1):
        if y < 120:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(left, y, f"Card {idx}")
        y -= 16
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left, y, "Front:")
        y -= 14
        c.setFont("Helvetica", 10)
        y = _draw_wrapped(c, card.get("front", ""), left + 10, y, max_width - 10)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left, y, "Back:")
        y -= 14
        c.setFont("Helvetica", 10)
        y = _draw_wrapped(c, card.get("back", ""), left + 10, y, max_width - 10)
        y -= 8

    if not cards:
        c.setFont("Helvetica", 10)
        c.drawString(left, y, "No flashcards available.")

    c.save()
    buffer.seek(0)
    return buffer


def build_quiz_pdf(*, video_title: str, mcqs: list[dict[str, str]]) -> BytesIO:
    buffer, c, width, height = _new_canvas()
    y = height - 50
    left = 50
    max_width = width - 100

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, "QuickStudy LMS - MCQ Quiz")
    y -= 24
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, y, f"Video: {video_title}")
    y -= 24

    for idx, q in enumerate(mcqs, start=1):
        if y < 140:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 10)
        c.setFont("Helvetica-Bold", 11)
        y = _draw_wrapped(c, f"{idx}. {q.get('question', '')}", left, y, max_width)
        c.setFont("Helvetica", 10)
        y = _draw_wrapped(c, f"A) {q.get('option_a', '')}", left + 10, y, max_width - 10)
        y = _draw_wrapped(c, f"B) {q.get('option_b', '')}", left + 10, y, max_width - 10)
        y = _draw_wrapped(c, f"C) {q.get('option_c', '')}", left + 10, y, max_width - 10)
        y = _draw_wrapped(c, f"D) {q.get('option_d', '')}", left + 10, y, max_width - 10)
        y -= 8

    c.showPage()
    y = height - 50
    c.setFont("Helvetica-Bold", 14)
    c.drawString(left, y, "Answer Key")
    y -= 22
    c.setFont("Helvetica", 10)
    if not mcqs:
        c.drawString(left, y, "No MCQs available.")
    else:
        for idx, q in enumerate(mcqs, start=1):
            if y < 60:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 10)
            y = _draw_wrapped(c, f"{idx}. {q.get('correct_answer', '')}", left, y, max_width)

    c.save()
    buffer.seek(0)
    return buffer
