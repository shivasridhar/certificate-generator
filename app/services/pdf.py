import os
from datetime import date
from pathlib import Path
from typing import Union
import uuid

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas


def generate_certificate_pdf(
    recipient_name: str,
    event_name: str,
    issuer: str,
    issue_date: Union[date, str],
    output_path: Union[str, Path],
) -> None:
    """
    Generates a single-page landscape A4 PDF certificate.

    Layout structure:
    - Landscape A4 (841.89 x 595.27 points)
    - Double border (outer and inner decorative lines)
    - Header: "Certificate of Participation"
    - Subtitle: "This certificate is proudly presented to"
    - Recipient name: Centered, auto-scaled to prevent page overflow
    - Body: "for successfully completing"
    - Event name: Prominent bold title
    - Footer: Issue date on left, Issuer signature on right

    FONT LIMITATION NOTE:
    ReportLab's built-in standard Helvetica font only supports Latin-1 character encodings.
    Non-Latin scripts (such as Cyrillic, Arabic, Chinese, or Devanagari) require registering
    a custom TrueType (TTF) font (e.g. Noto Sans or DejaVu Sans). This is a known limitation
    documented for the assignment README.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write pattern: Write to a temporary file first, then replace into output_path.
    # This guarantees that a process crash or disk interruption never leaves a corrupted
    # or half-written PDF file at the target path.
    temp_path = output_path.with_name(f"{output_path.stem}.tmp_{uuid.uuid4().hex}.pdf")

    try:
        page_width, page_height = landscape(A4)
        c = canvas.Canvas(str(temp_path), pagesize=landscape(A4))

        # ----------------------------------------------------------------------
        # 1. Decorative Borders
        # ----------------------------------------------------------------------
        margin = 35
        # Outer border
        c.setLineWidth(3)
        c.setStrokeColor(colors.HexColor("#1E3A8A"))  # Classic navy blue
        c.rect(margin, margin, page_width - 2 * margin, page_height - 2 * margin)

        # Inner border
        inner_margin = margin + 6
        c.setLineWidth(1)
        c.setStrokeColor(colors.HexColor("#93C5FD"))  # Light slate blue
        c.rect(
            inner_margin,
            inner_margin,
            page_width - 2 * inner_margin,
            page_height - 2 * inner_margin,
        )

        # ----------------------------------------------------------------------
        # 2. Certificate Header
        # ----------------------------------------------------------------------
        c.setFont("Helvetica-Bold", 32)
        c.setFillColor(colors.HexColor("#1E3A8A"))
        c.drawCentredString(page_width / 2, page_height - 130, "Certificate of Participation")

        c.setFont("Helvetica-Oblique", 15)
        c.setFillColor(colors.HexColor("#4B5563"))
        c.drawCentredString(
            page_width / 2,
            page_height - 170,
            "This certificate is proudly presented to",
        )

        # ----------------------------------------------------------------------
        # 3. Recipient Name (Auto-scaled to fit within margins)
        # ----------------------------------------------------------------------
        font_name = "Helvetica-Bold"
        font_size = 36
        max_name_width = page_width - 2 * (margin + 40)

        # Reduce font size down to a readable minimum if the recipient name is long
        while font_size > 10 and c.stringWidth(recipient_name, font_name, font_size) > max_name_width:
            font_size -= 1

        c.setFont(font_name, font_size)
        c.setFillColor(colors.HexColor("#111827"))
        c.drawCentredString(page_width / 2, page_height - 235, recipient_name)

        # Decorative underline beneath the recipient's name
        underline_half_width = min(220, max_name_width / 2)
        c.setLineWidth(1.5)
        c.setStrokeColor(colors.HexColor("#CBD5E1"))
        c.line(
            page_width / 2 - underline_half_width,
            page_height - 247,
            page_width / 2 + underline_half_width,
            page_height - 247,
        )

        # ----------------------------------------------------------------------
        # 4. Event Details
        # ----------------------------------------------------------------------
        c.setFont("Helvetica", 15)
        c.setFillColor(colors.HexColor("#4B5563"))
        c.drawCentredString(
            page_width / 2,
            page_height - 285,
            "for active participation in",
        )

        c.setFont("Helvetica-Bold", 24)
        c.setFillColor(colors.HexColor("#1E3A8A"))
        c.drawCentredString(page_width / 2, page_height - 330, event_name)

        # ----------------------------------------------------------------------
        # 5. Footer (Issue Date & Issuer)
        # ----------------------------------------------------------------------
        footer_y = 110
        footer_line_y = footer_y + 20

        # Left Column: Issue Date
        date_str = str(issue_date)
        c.setLineWidth(1)
        c.setStrokeColor(colors.HexColor("#94A3B8"))
        c.line(margin + 60, footer_line_y, margin + 260, footer_line_y)

        c.setFont("Helvetica", 12)
        c.setFillColor(colors.HexColor("#64748B"))
        c.drawString(margin + 60, footer_y, f"Date: {date_str}")

        # Right Column: Issuer
        c.line(page_width - margin - 260, footer_line_y, page_width - margin - 60, footer_line_y)
        c.drawRightString(page_width - margin - 60, footer_y, f"Issued by: {issuer}")

        # Save and finish PDF document
        c.save()

        # Atomically replace temporary file to target path
        # Note: os.replace is atomic and safely overwrites on both POSIX and Windows,
        # avoiding the Windows-specific 'FileExistsError' raised by os.rename.
        os.replace(temp_path, output_path)

    finally:
        # Clean up temporary file if an error occurred prior to the atomic replace
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
