"""Calendar event helpers: per-row event icons and the JSON "event text"
column, plus the renderer that draws one event-text block (with the coloured
"24th:" date prefix, word wrap and optional rounded border).
"""
import json
import os
import re
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from ..utils.dates import parse_month_from_flex_date
from ..utils.text import safe_str


def parse_icon_date(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except Exception:
            pass
    return None


def build_event_texts(row, product_config):
    """
    Read JSON list from the configured event text column in this row.
    Expected Excel cell format (string):

        [
        {"date":"11/01/1969","value":"Husband's Birthday"},
        {"date":"03/09/2023","value":"Hospital Opening"}
        ]

    Only 'month' is used from date to decide which month the text goes to.
    The *day* is used only to build a coloured prefix like "24th:".

    Returns list of dictionaries:
        {
        "month_idx": 1..12,
        "text": "24th: Husband's Birthday",
        plus all style/layout properties from
        product_config["calendar_event_text_style"]
        }
    """
    colname = product_config.get("calendar_event_text_column")
    if not colname or colname not in row:
        return []

    raw = safe_str(row.get(colname, ""))
    if not raw:
        return []

    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            return []
    except Exception:
        return []

    style = product_config.get("calendar_event_text_style", {}) or {}

    # ---- helpers for "24th" style prefix ---------------------------------
    def extract_day_from_date_string(s: str):
        s = safe_str(s)
        if not s:
            return None
        m = re.search(r"(\d{1,2})", s)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    def format_day_ordinal(day: int):
        if not day:
            return ""
        if 11 <= (day % 100) <= 13:
            suf = "th"
        else:
            suf = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{suf}"

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue

        date_s = safe_str(item.get("date", ""))
        text_s = safe_str(item.get("value", ""))
        if not date_s or not text_s:
            continue

        # Which month does this event belong to?
        m_idx = parse_month_from_flex_date(date_s)
        if not m_idx:
            continue

        # Build "24th:" prefix from the *day* part
        day = extract_day_from_date_string(date_s)
        prefix = format_day_ordinal(day)
        if prefix:
            full_text = f"{prefix}: {text_s}"
        else:
            full_text = text_s

        cfg = {
            "month_idx": m_idx,
            "text": full_text,
            "x": int(style.get("x", 0)),
            "y": int(style.get("y", 0)),
            "font_size": int(style.get("font_size", 20)),
            "font_weight": (style.get("font_weight") or "normal").lower(),
            "max_width": int(style.get("max_width", 300)),
            "h_align": (style.get("h_align") or "left").lower(),
            "v_align": (style.get("v_align") or "top").lower(),
            "line_height": float(style.get("line_height", 1.2)),
            "font_path": style.get("font_path")
            or product_config.get("calendar_date_font_path"),
            # colours
            "color": style.get("color", "#000000"),  # fallback / legacy
            "text_color": style.get("text_color", style.get("color", "#000000")),
            "date_color": style.get("date_color", "#ff0000"),
            # border
            "border_color": style.get("border_color", None),
        }
        # Box geometry: draw_event_text_block already supports these; they
        # are only forwarded when the style sets them, so its defaults
        # (4px border, 90px radius, 10px padding) apply otherwise.
        for key in ("border_thickness", "border_radius", "padding"):
            if style.get(key) is not None:
                cfg[key] = style[key]
        out.append(cfg)

    return out


def build_event_icons(row, product_config):
    """Resolve each configured event icon's date from its Excel column.
    Icons whose column is missing/empty/unparseable are dropped."""
    event_icons = []
    for cfg in product_config.get("calendar_event_icons", []) or []:
        col = cfg.get("excel_column")
        if not col or col not in row:
            continue
        dt = parse_icon_date(safe_str(row.get(col, "")))
        if not dt:
            continue
        event_icons.append(
            {
                "path": cfg.get("path"),
                "offset_x": cfg.get("offset_x", 0),
                "offset_y": cfg.get("offset_y", 0),
                "scale": cfg.get("scale", 0.35),
                "excel_date": dt,
            }
        )
    return event_icons


def draw_event_text_block(base_img, text_cfg, product_config):
    """
    Draw a single event text block and return the pixel height used.

    Supports:
    - date prefix color highlight
    - wrapped text within max_width
    - rounded or sharp border
    - customizable padding
    """
    full_text = text_cfg.get("text", "")
    if not full_text:
        return 0

    # Position
    x = int(text_cfg.get("x", 0))
    y = int(text_cfg.get("y", 0))

    # Dimensions
    max_width = int(text_cfg.get("max_width", 300))
    line_height_factor = float(text_cfg.get("line_height", 1.2))
    h_align = (text_cfg.get("h_align") or "left").lower()
    v_align = (text_cfg.get("v_align") or "top").lower()

    # Colors
    date_color = text_cfg.get("date_color", "#ff0000")
    text_color = text_cfg.get("text_color", "#000000")
    border_color = text_cfg.get("border_color")
    border_thick = int(text_cfg.get("border_thickness", 4))
    radius = int(text_cfg.get("border_radius", 90))  # 0 = sharp corners

    # PADDING SUPPORT
    pad = text_cfg.get("padding", 10)
    pad_left = int(text_cfg.get("padding_left", pad+15))
    pad_right = int(text_cfg.get("padding_right", pad))
    pad_top = int(text_cfg.get("padding_top", pad+5))
    pad_bottom = int(text_cfg.get("padding_bottom", pad))




    # Font
    font_path = text_cfg.get("font_path") or product_config.get("calendar_date_font_path")
    font_size = int(text_cfg.get("font_size", 20))

    try:
        if font_path and os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size)
        else:
            font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(base_img)

    # Split prefix / body
    if ":" in full_text:
        prefix, body = full_text.split(":", 1)
        prefix = prefix.strip()
        body = body.strip()
    else:
        prefix = ""
        body = full_text.strip()

    # Token list for color separation
    tokens = []
    if prefix:
        tokens.append((prefix + ":", True))
    for w in body.split():
        tokens.append((w, False))

    # WORD WRAP
    lines = []
    current = []
    for w, is_date in tokens:
        test_line = " ".join([cw for cw, _ in current] + [w]).strip()
        if draw.textlength(test_line, font=font) > (max_width - pad_left - pad_right) and current:
            lines.append(current)
            current = [(w, is_date)]
        else:
            current.append((w, is_date))
    if current:
        lines.append(current)

    # Measure line height
    ascent, descent = font.getmetrics()
    base_h = ascent + descent
    line_h = int(base_h * line_height_factor)

    # Total text height
    text_h = len(lines) * line_h
    total_h = text_h + pad_top + pad_bottom

    # Compute y anchor
    if v_align == "middle":
        y0 = y - total_h // 2
    elif v_align == "bottom":
        y0 = y - total_h
    else:
        y0 = y

    # Compute x box anchor
    if h_align == "center":
        bx = x - max_width // 2
    elif h_align == "right":
        bx = x - max_width
    else:
        bx = x

    # DRAW BORDER BOX (sharp or rounded)
    if border_color:
       # --- High-quality anti-aliased rounded border ---
        scale = 4  # 4x resolution for smoothness

        w = max_width * scale
        h = total_h * scale
        rx = radius * scale
        th = border_thick * scale

        # Create high-res canvas
        hr = Image.new("RGBA", (w, h), (0,0,0,0))
        hr_draw = ImageDraw.Draw(hr)

        # Draw border at high resolution
        hr_draw.rounded_rectangle(
            [0, 0, w, h],
            radius=rx,
            outline=border_color,
            width=th,
            fill=None,
        )

        # Downscale smoothly
        border_img = hr.resize((max_width, total_h), Image.LANCZOS)

        # Paste final anti-aliased border
        base_img.alpha_composite(border_img, dest=(bx, y0))

    # DRAW TEXT LINES
    cy = y0 + pad_top
    for line_tokens in lines:

        plain = " ".join(w for w, _ in line_tokens)
        lw = draw.textlength(plain, font=font)

        if h_align == "center":
            lx = x - lw // 2
        elif h_align == "right":
            lx = x - lw
        else:
            lx = x + pad_left

        cx = lx
        for w, is_date in line_tokens:
            if is_date:
                # Example w = "24th:"
                m = re.match(r"(\d+)(st|nd|rd|th)(:?)", w.lower())
                if m:
                    num = m.group(1)
                    suf = m.group(2)
                    colon = m.group(3)

                    # Draw number at normal baseline
                    draw.text((cx, cy), num, font=font, fill=date_color)
                    nx = cx + draw.textlength(num, font=font)

                    # Draw suffix (superscript) with smaller font
                    sup_font_size = max(10, int(font.size * 0.55))
                    try:
                        sup_font = ImageFont.truetype(font.path, sup_font_size)
                    except:
                        sup_font = ImageFont.truetype("arial.ttf", sup_font_size)

                    # Raise the superscript
                    sup_y = cy - int(sup_font_size * 0.5)

                    draw.text((nx, sup_y), suf, font=sup_font, fill=date_color)

                    sx = nx + draw.textlength(suf, font=sup_font)

                    # Draw optional trailing colon
                    if colon:
                        draw.text((sx, cy), colon + " ", font=font, fill=date_color)
                        cx = sx + draw.textlength(colon + " ", font=font)
                    else:
                        cx = sx + draw.textlength(" ", font=font)

                    continue
            # NORMAL PATH (non-prefix words)
            color = date_color if is_date else text_color
            draw.text((cx, cy), w + " ", font=font, fill=color)
            cx += draw.textlength(w + " ", font=font)


        cy += line_h

    return total_h
