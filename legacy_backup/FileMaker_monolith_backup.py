

import os
import json
import io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk, ImageDraw, ImageFont
import pandas as pd
from threading import Thread, Event
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
import requests
import qrcode
import fitz  # PyMuPDF
import calendar as pycalendar
from datetime import datetime


# ---------------------------
# Utility helpers
# ---------------------------

def extract_key(value: str) -> str:
    if not isinstance(value, str):
        return ""
    v = value.strip()
    if v.startswith("{{") and v.endswith("}}"):
        return v[2:-2]
    return v


def is_qr_data_static(data_str):
    """Check if data is QR code data"""
    data_str = str(data_str).strip()
    low = data_str.lower()

    if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        return False

    if low.startswith("http://") or low.startswith("https://"):
        return True
    

    if "/" in data_str or "\\" in data_str:
        return False

    return True


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def safe_str(val):
    if val is None:
        return ""

    try:
        import math
        if isinstance(val, float):
            if math.isnan(val):
                return ""
            if val.is_integer():
                return str(int(val))  # removes .0
    except Exception:
        pass

    s = str(val).strip()
    return "" if s.lower() == "nan" else s


# ---------------------------
# Calendar overlay generator (no weekday headers)
# ---------------------------

def create_linear_gradient(size, colors, direction):
    """
    size: (width, height)
    colors: list of hex colors
    direction: string
    """
    w, h = size
    gradient = Image.new("RGBA", size)
    draw = ImageDraw.Draw(gradient)

    # Convert hex to RGB
    rgb = [tuple(int(c.lstrip("#")[i:i+2], 16) for i in (0, 2, 4)) for c in colors]

    def lerp(c1, c2, t):
        return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))

    steps = max(w, h)

    for i in range(steps):
        t = i / max(steps - 1, 1)
        seg = min(int(t * (len(rgb) - 1)), len(rgb) - 2)
        local_t = (t * (len(rgb) - 1)) - seg
        col = lerp(rgb[seg], rgb[seg + 1], local_t)

        if direction == "left_to_right":
            draw.line([(i, 0), (i, h)], fill=col)
        elif direction == "right_to_left":
            draw.line([(w - i, 0), (w - i, h)], fill=col)
        elif direction == "top_to_bottom":
            draw.line([(0, i), (w, i)], fill=col)
        elif direction == "bottom_to_top":
            draw.line([(0, h - i), (w, h - i)], fill=col)
        elif direction == "diagonal_tl_br":
            draw.line([(i, 0), (0, i)], fill=col)
        elif direction == "diagonal_bl_tr":
            draw.line([(i, h), (w, h - i)], fill=col)

    return gradient


def draw_text_with_gradient(base_img, position, text, font, gradient_cfg, align="left"):
    # Measure text
    dummy = ImageDraw.Draw(base_img)
    bbox = dummy.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Text mask
    mask = Image.new("L", (tw, th), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((0, 0), text, font=font, fill=255)

    # Gradient image
    gradient = create_linear_gradient(
        (tw, th),
        gradient_cfg["colors"],
        gradient_cfg.get("direction", "left_to_right"),
    )

    # Composite
    x, y = position
    base_img.paste(gradient, (x, y), mask)


def generate_calendar_overlay_image(
    year: int,
    month: int,
    cell_w: int,
    cell_h: int,
    date_offset_x: int,
    date_offset_y: int,
    align: str,
    font_path: str,
    font_size: int,
    date_fill: str = "#000000",
    cell_bg=None,
    show_borders: bool = False,
    date_icon_path=None,
    date_icon_scale: float = 0.35,
    date_icon_offset_x: int = 0,
    date_icon_offset_y: int = 0,
    excel_event_date=None,
    event_icons=None,
):
    cols = 7
    pycalendar.setfirstweekday(pycalendar.SUNDAY)
    cal = pycalendar.monthcalendar(year, month)
    rows = len(cal)

    width = cols * cell_w
    height = rows * cell_h

    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Optional background fill per cell
    if cell_bg:
        for r in range(rows):
            for c in range(cols):
                x0 = c * cell_w
                y0 = r * cell_h
                draw.rectangle([x0, y0, x0 + cell_w, y0 + cell_h], fill=cell_bg)

    # Load font
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Preload single icon (legacy mode)
    single_icon = None
    if date_icon_path and os.path.exists(date_icon_path):
        try:
            tmp_icon = Image.open(date_icon_path).convert("RGBA")
            target_w = int(cell_w * date_icon_scale)
            if target_w > 0:
                ratio = target_w / tmp_icon.width
                target_h = int(tmp_icon.height * ratio)
                if target_h > 0:
                    single_icon = tmp_icon.resize((target_w, target_h), Image.LANCZOS)
        except Exception as e:
            print("Icon load error:", e)
            single_icon = None

    # Normalise event_icons
    event_icons = event_icons or []

    for r, week in enumerate(cal):
        for c, day in enumerate(week):
            if day == 0:
                continue

            x_cell = c * cell_w
            y_cell = r * cell_h

            text = str(day)

            # Position day number
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]

            if align == "center":
                x_text = x_cell + (cell_w - tw) // 2
            elif align == "right":
                x_text = x_cell + cell_w - tw - date_offset_x
            else:  # left
                x_text = x_cell + date_offset_x

            y_text = y_cell + date_offset_y

            # date text hidden here
            # draw.text((x_text, y_text), text, font=font, fill=date_fill)

            # --- Single legacy icon based on excel_event_date (match on month/day only) ---
            if excel_event_date and single_icon:
                try:
                    if excel_event_date.month == month and excel_event_date.day == day:
                        ix = x_cell + date_icon_offset_x
                        iy = y_cell + date_icon_offset_y
                        img.alpha_composite(single_icon, dest=(ix, iy))
                except Exception:
                    pass

            # --- Multi-icon support ---
            if event_icons:
                for icon_def in event_icons:
                    excel_dt = icon_def.get("excel_date")
                    if not excel_dt:
                        continue

                    # Match ONLY month + day (ignore year)
                    try:
                        if excel_dt.month != month or excel_dt.day != day:
                            continue
                    except Exception:
                        continue

                    icon_path = icon_def.get("path")
                    if not icon_path or not os.path.exists(icon_path):
                        continue

                    try:
                        icon_img = Image.open(icon_path).convert("RGBA")
                    except Exception:
                        continue

                    # Scale factor relative to cell width
                    scale = icon_def.get("scale", 0.35)
                    try:
                        scale = float(scale)
                    except Exception:
                        scale = 0.35

                    if scale > 0:
                        target_w = int(cell_w * scale)
                        if target_w > 0:
                            ratio = target_w / icon_img.width
                            target_h = int(icon_img.height * ratio)
                            if target_h > 0:
                                icon_img = icon_img.resize((target_w, target_h), Image.LANCZOS)

                    ix = x_cell + int(icon_def.get("offset_x", 0))
                    iy = y_cell + int(icon_def.get("offset_y", 0))

                    try:
                        img.alpha_composite(icon_img, dest=(ix, iy))
                    except Exception:
                        # Skip this icon rather than crashing whole calendar
                        continue

    # Optional borders
    if show_borders:
        for r in range(rows):
            for c in range(cols):
                x0 = c * cell_w
                y0 = r * cell_h
                draw.rectangle([x0, y0, x0 + cell_w, y0 + cell_h], outline="#000000", width=1)

    return img


# ---------------------------
# Validation for overlays (images)
# ---------------------------

def validate_row_images(row, design, slot_vars, df_columns):
    """Validate that all required images exist for a row"""
    missing_images = []
    tpl = design.get("template", {}) if design else {}
    ctx = {str(c): safe_str(row.get(c, "")) for c in df_columns}

    for i, ov in enumerate(tpl.get("overlayImages", [])):
        slot_id = f"OVL_{i}"
        if slot_id not in slot_vars:
            continue

        var_data = slot_vars[slot_id]
        col = var_data.get("value", "")
        if not col or col not in ctx:
            continue

        path = str(ctx[col]).strip()
        if not path:
            continue

        # Skip QR codes and URLs
        if is_qr_data_static(path):
            continue
        if path.lower().startswith("http://") or path.lower().startswith("https://"):
            continue

        # Check if local file exists
        if not os.path.exists(path):
            missing_images.append(path)

    return missing_images


# ---------------------------
# Static render functions (kept for normal production)
# ---------------------------

def render_row_to_pdf_static(row, output_path, design, slot_vars, base_file, df_columns):
    """Static function for PDF rendering (for multiprocessing)"""
    t = json.loads(json.dumps(design))
    tpl = t.get("template", {})
    ctx = {str(c): safe_str(row.get(c, "")) for c in df_columns}

    doc = fitz.open(base_file)
    page = doc.load_page(0)

    # Overlay images
    for i, ov in enumerate(tpl.get("overlayImages", [])):
        slot_id = f"OVL_{i}"
        if slot_id not in slot_vars:
            continue

        var_data = slot_vars[slot_id]
        col = var_data.get("value", "")
        if not col or col not in ctx:
            continue

        path = str(ctx[col]).strip()
        if not path:
            continue

        x = int(ov.get("x", 0))
        y = int(ov.get("y", 0))
        w = int(ov.get("width", 0))
        h = int(ov.get("height", 0))
        rect = fitz.Rect(x, y, x + w, y + h)

        try:
            if is_qr_data_static(path):
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_H,
                    box_size=10,
                    border=0,
                )
                qr.add_data(path)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#ffffff", back_color="transparent").convert("RGBA")
                img_bytes = io.BytesIO()
                img.save(img_bytes, format="PNG")
                page.insert_image(rect, stream=img_bytes.getvalue(), overlay=True)
            elif path.lower().startswith("http"):
                response = requests.get(path, timeout=10)
                response.raise_for_status()
                page.insert_image(rect, stream=response.content, overlay=True)
            else:
                if os.path.exists(path):
                    page.insert_image(rect, filename=path, overlay=True)
        except Exception as e:
            print(f"Error inserting overlay image {i}: {e}")

    # Text blocks
    for i, tb in enumerate(tpl.get("textBlocks", [])):
        slot_id = f"TXT_{i}"
        if slot_id not in slot_vars:
            continue

        var_data = slot_vars[slot_id]
        col = var_data.get("value", "")
        text = "" if not col or col not in ctx else str(ctx.get(col, ""))
        if not text:
            continue

        fontsize = int(tb.get("fontSize", 30))
        fontfamily = tb.get("fontFamily", "helvetica").lower()
        fillcolor = tb.get("fill", "#000000")
        align = tb.get("align", "left")

        color = tuple(int(fillcolor.lstrip("#")[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

        fontslot = f"{slot_id}_FONT"
        custom_font_path = None
        if fontslot in slot_vars:
            custom_font_path = slot_vars[fontslot].get("path") or None

        # Determine font name
        if custom_font_path and os.path.exists(custom_font_path):
            fontname = f"CustomFont{i}"
        else:
            font_map = {
                "helvetica": "helv",
                "arial": "helv",
                "times": "times",
                "times new roman": "times",
                "courier": "cour",
                "courier new": "cour",
                "symbol": "symb",
                "zapfdingbats": "zadb",
            }
            fontname = font_map.get(fontfamily, "helv")

        # Calculate text width for alignment
        try:
            text_width = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
        except Exception:
            text_width = len(text) * fontsize * 0.5

        x = int(tb.get("x", 0))
        y = int(tb.get("y", 0))

        if align == "center":
            x = x - text_width / 2
        elif align == "right":
            x = x - text_width

        try:
            if custom_font_path and os.path.exists(custom_font_path):
                page.insert_font(fontname=fontname, fontfile=custom_font_path)
                page.insert_text((x, y + fontsize), text, fontname=fontname, fontsize=fontsize, color=color)
            else:
                page.insert_text((x, y + fontsize), text, fontname=fontname, fontsize=fontsize, color=color)
        except Exception as e:
            print(f"Error inserting text {i}: {e}")
            try:
                page.insert_text((x, y + fontsize), text, fontname="helv", fontsize=fontsize, color=color)
            except Exception as e2:
                print(f"Fallback also failed for text {i}: {e2}")

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


def render_row_to_pil_image_static(row, design, slot_vars, base_folder, base_file, df_columns):
    """Static function for PIL rendering (for multiprocessing)"""
    t = json.loads(json.dumps(design))
    tpl = t.get("template", {})

    width = int(tpl.get("width", 1200))
    height = int(tpl.get("height", 630))

    base_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ctx = {str(c): safe_str(row.get(c, "")) for c in df_columns}
    ctx["__current_month__"] = row.get("__current_month__", None)

    # Behind overlays
    for i, ov in enumerate(tpl.get("overlayImages", [])):
        if not ov.get("behindBackground", False):
            continue
        draw_overlay_static(base_img, ov, i, ctx, slot_vars)

    # Background
    if base_file and os.path.exists(base_file):
        bg_img = Image.open(base_file).convert("RGBA")
        bg_img = bg_img.resize((width, height), Image.LANCZOS)
        base_img.alpha_composite(bg_img, dest=(0, 0))
    else:
        white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        base_img.alpha_composite(white, dest=(0, 0))

    # Front overlays
    for i, ov in enumerate(tpl.get("overlayImages", [])):
        if ov.get("behindBackground", False):
            continue
        draw_overlay_static(base_img, ov, i, ctx, slot_vars)

    # Text
    draw = ImageDraw.Draw(base_img)
    for i, tb in enumerate(tpl.get("textBlocks", [])):
        draw_text_static(draw, base_img, tb, i, ctx, slot_vars)

    return base_img


def draw_overlay_static(base_img, ov, i, ctx, slot_vars):
    """Static function for drawing overlays"""
    slot_id = f"OVL_{i}"
    if slot_id not in slot_vars:
        return

    var_data = slot_vars[slot_id]
    col = var_data.get("value", "")
    if not col or col not in ctx:
        return

    is_calendar_overlay = ov.get("calendar_image", True)

    if is_calendar_overlay:
        base_path = str(ctx.get(col, "")).strip()
        if not base_path:
            return

        folder = os.path.dirname(base_path)
        filename = os.path.basename(base_path)

        # remove the month prefix from filename (VERY IMPORTANT FIX)
        # e.g. "january_cropped-APT..." → "_cropped-APT..."
        if "_cropped-" in filename.lower():
            filename = filename[filename.lower().find("_cropped-") :]
            # filename now becomes: "_cropped-APTGxxxx.png"

        month_num = ctx.get("__current_month__", None)
        if month_num:
            month_name = pycalendar.month_name[int(month_num)].lower()
            
            # Correct expected filename
            expected_filename = f"{month_name}{filename}"  # e.g. "july_cropped-APT..."
            expected_path = os.path.join(folder, expected_filename)

            if os.path.exists(expected_path):
                path = expected_path
            else:
                # ------------------------------------------
                # MONTH-AWARE FALLBACK (NO RANDOM IMAGE)
                # ------------------------------------------
                path = None

                # Try previous months ONLY (Feb → Jan, Mar → Feb → Jan, etc.)
                for m in range(month_num - 1, 0, -1):
                    prev_name = pycalendar.month_name[m].lower()
                    prev_filename = f"{prev_name}{filename}"
                    prev_path = os.path.join(folder, prev_filename)

                    if os.path.exists(prev_path):
                        path = prev_path
                        break

                # If still nothing found → DO NOT FALL BACK
                if not path:
                    print(
                        f"[WARN] Missing calendar overlay for month "
                        f"{pycalendar.month_name[month_num]} "
                        f"(row skipped for this overlay)"
                    )
                    return   # ⬅️ IMPORTANT: skip overlay entirely

        else:
            path = base_path
    else:
        # Normal image
        path = str(ctx.get(col, "")).strip()

    # ---- load image ----
    if is_qr_data_static(path):
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=0,
            )
            qr.add_data(path)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#ffffff", back_color="transparent").convert("RGBA")
        except Exception as e:
            print(f"Error generating QR code for overlay {i}: {e}")
            return
    else:
        try:
            if path.lower().startswith("http"):
                response = requests.get(path, timeout=10)
                response.raise_for_status()
                img = Image.open(io.BytesIO(response.content)).convert("RGBA")
            else:
                if not os.path.exists(path):
                    print(f"Image file not found: {path}")
                    return
                img = Image.open(path).convert("RGBA")
        except Exception as e:
            print(f"Error loading image for overlay {i}: {e}")
            return

    # resize, opacity, rotate, place
    w, h = ov.get("width"), ov.get("height")
    if w and h:
        img = img.resize((int(w), int(h)), Image.LANCZOS)

    opacity = ov.get("opacity", 1.0)
    if opacity < 1.0:
        img.putalpha(Image.eval(img.split()[3], lambda a: int(a * opacity)))

    rot = ov.get("rotation", 0)
    if rot:
        img = img.rotate(-rot, expand=True)

    base_img.alpha_composite(img, dest=(int(ov.get("x", 0)), int(ov.get("y", 0))))


def draw_text_static(draw, base_img, tb, i, ctx, slot_vars):
    """Static function for drawing text with maxWidth + vertical alignment"""
    slot_id = f"TXT_{i}"
    if slot_id not in slot_vars:
        return

    var_data = slot_vars[slot_id]
    col = var_data.get("value", "")
    text = "" if not col or col not in ctx else str(ctx.get(col, ""))
    if not text:
        return

    fontsize = int(tb.get("fontSize", 30))
    fontfamily = tb.get("fontFamily", "arial")
    fontstyle = tb.get("fontStyle", "normal")

    fontslot = f"{slot_id}_FONT"
    custom_font_path = None
    if fontslot in slot_vars:
        custom_font_path = slot_vars[fontslot].get("path") or None

    # ----- load font (your original logic) -----
    try:
        if custom_font_path and os.path.exists(custom_font_path):
            font = ImageFont.truetype(custom_font_path, fontsize)
        elif fontfamily.lower() == "arial":
            if "bold" in fontstyle.lower() and "italic" in fontstyle.lower():
                font = ImageFont.truetype("arialbi.ttf", fontsize)
            elif "bold" in fontstyle.lower():
                font = ImageFont.truetype("arialbd.ttf", fontsize)
            elif "italic" in fontstyle.lower():
                font = ImageFont.truetype("ariali.ttf", fontsize)
            else:
                font = ImageFont.truetype("arial.ttf", fontsize)
        else:
            font = ImageFont.truetype(f"{fontfamily}.ttf", fontsize)
    except Exception:
        font = ImageFont.load_default()

    x = int(tb.get("x", 0))
    y = int(tb.get("y", 0))
    align = tb.get("align", "left")

    # ----- NEW: wrapping + vertical align -----
    # support both "maxWidth" (new) and "width" (old) keys
    max_width = int(tb.get("maxWidth", tb.get("width", 0) or 0))
    vertical_align = tb.get("verticalAlign", "top")  # top / middle / bottom
    line_height_factor = float(tb.get("lineHeight", 1.0))

    # split into lines based on max_width
    print(f"Testing line:(max {max_width})")
    if max_width > 0:
        words = text.split()
        lines = []
        current = ""
        for w in words:
            test = (current + " " + w).strip()
            tw = draw.textlength(test, font=font)
            print(f"Testing line: '{test}' width={tw} (max {max_width})")
            if tw <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = w
        if current:
            lines.append(current)
    else:
        lines = [text]

    # precompute width/height per line
    line_metrics = []
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=font)
        w = bbox[2] - bbox[0]
        h = (bbox[3] - bbox[1]) * line_height_factor
        line_metrics.append((ln, w, h))

    block_height = sum(h for _, _, h in line_metrics)

    # vertical alignment
    if vertical_align == "middle":
        y = int(y - block_height / 2)
    elif vertical_align == "bottom":
        y = int(y - block_height)

    fillcolor = tb.get("fill", "#000000")
    gradient_cfg = tb.get("fillGradient")
    rotation = tb.get("rotation", 0)
    strokewidth = int(tb.get("strokeWidth", 0))
    strokecolor = tb.get("stroke", "#000000")
    shadowcolor = tb.get("shadowColor")
    shadowblur = int(tb.get("shadowBlur", 0))  # not used but kept
    shadowoffsetx = int(tb.get("shadowOffsetX", 0))
    shadowoffsety = int(tb.get("shadowOffsetY", 0))
    opacity = float(tb.get("opacity", 1.0))

    # ----- rotated text: draw on separate layer -----
    if rotation != 0:
        max_line_w = max(w for _, w, _ in line_metrics)
        total_w = int(max_line_w + 200)
        total_h = int(block_height + 200)
        txtlayer = Image.new("RGBA", (total_w, total_h), (255, 255, 255, 0))
        txtdraw = ImageDraw.Draw(txtlayer)

        cy = 100
        for ln, lw, lh in line_metrics:
            # horizontal align inside layer
            if align == "center":
                lx = 100 + int((max_line_w - lw) / 2)
            elif align == "right":
                lx = 100 + int(max_line_w - lw)
            else:
                lx = 100

            if shadowcolor and shadowblur > 0:
                txtdraw.text(
                    (lx + shadowoffsetx, cy + shadowoffsety),
                    ln,
                    font=font,
                    fill=shadowcolor,
                )
            txtdraw.text(
                (lx, cy),
                ln,
                font=font,
                fill=fillcolor,
                stroke_width=strokewidth,
                stroke_fill=strokecolor,
            )
            cy += int(lh)

        if opacity < 1.0:
            alpha = txtlayer.split()[3]
            alpha = alpha.point(lambda a: int(a * opacity))
            txtlayer.putalpha(alpha)

        txtlayer = txtlayer.rotate(-rotation, expand=True)
        base_img.alpha_composite(txtlayer, dest=(x - 100, y - 100))
    else:
        # ----- no rotation: draw directly on base image -----
        cy = y
        for ln, lw, lh in line_metrics:
            lx = x
            if align == "center":
                lx = int(x - lw / 2)
            elif align == "right":
                lx = int(x - lw)

            if shadowcolor and shadowblur > 0:
                draw.text(
                    (lx + shadowoffsetx, cy + shadowoffsety),
                    ln,
                    font=font,
                    fill=shadowcolor,
                )

            if opacity < 1.0:
                txtlayer = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
                txtdraw = ImageDraw.Draw(txtlayer)
                txtdraw.text(
                    (lx, cy),
                    ln,
                    font=font,
                    fill=fillcolor,
                    stroke_width=strokewidth,
                    stroke_fill=strokecolor,
                )
                alpha = txtlayer.split()[3]
                alpha = alpha.point(lambda a: int(a * opacity))
                txtlayer.putalpha(alpha)
                base_img.alpha_composite(txtlayer)
            else:
                if gradient_cfg:
                    draw_text_with_gradient(
                        base_img,
                        (lx, cy),
                        ln,
                        font,
                        gradient_cfg,
                        align=align,
                    )
                else:
                    draw.text(
                        (lx, cy),
                        ln,
                        font=font,
                        fill=fillcolor,
                        stroke_width=strokewidth,
                        stroke_fill=strokecolor,
                    )

            cy += int(lh)


def parse_month_from_flex_date(date_str: str):
    """
    Accepts strings like:
      '11/01/1969', '11/01/69', '11/01/', '11/01'
      '11-01-2023', '11-01'
    Returns month index (1..12) or None.
    """
    if not date_str:
        return None

    s = safe_str(date_str).strip()
    if not s:
        return None

    s = s.replace("-", "/")

    # Case: DD/MM/
    if s.endswith("/"):
        s += "2000"

    # Case: DD/MM
    if s.count("/") == 1:
        s += "/2000"

    # Try full date formats
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.month
        except:
            pass

    # Fallback: extract month manually
    parts = s.split("/")
    if len(parts) >= 2:
        try:
            m = int(parts[1])
            if 1 <= m <= 12:
                return m
        except:
            pass

    # Final fallback: regex (rare)
    import re
    m = re.search(r"\b(0?[1-9]|1[0-2])\b", s)
    if m:
        return int(m.group(1))

    return None



# ---------------------------
# Worker function (handles calendar multi-output)
# ---------------------------
def _merged_row_handler(mode, *, self=None, args=None):
    """
    Unified handler for:
      - GUI preview (mode='preview', uses `self`)
      - Worker production (mode='worker', uses `args`)

    Includes:
      - normal product rendering
      - calendar production (12 months / row)
      - calendar_event_icons
      - calendar_event_text_column (JSON list of {date, value})
    """
    # -----------------------------------------
    # Common helpers used in both branches
    # -----------------------------------------
    def safe_parse_icon_date(date_str):
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str, fmt)
            except Exception:
                pass
        return None

    def build_event_texts_from_json_column(row, product_config):
        """
        Read JSON list from the configured event text column in this row.
        Excel cell format (string):

            [
            {"date":"11/01/1969","value":"Husband's Birthday"},
            {"date":"03/09/2023","value":"Hospital Opening"}
            ]

        Only 'month' is used to choose the calendar month.
        'day' is used to build a coloured prefix like "24th:".

        Returns list of dictionaries:
            {
            "month_idx": 1..12,
            "text": "24th: Husband's Birthday",
            plus layout/style from calendar_event_text_style
            }
        """
        import re

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
                suffix = "th"
            else:
                suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            return f"{day}{suffix}"

        out = []
        for item in items:
            if not isinstance(item, dict):
                continue

            date_s = safe_str(item.get("date", ""))
            text_s = safe_str(item.get("value", ""))
            if not date_s or not text_s:
                continue

            # decide month
            month_idx = parse_month_from_flex_date(date_s)
            if not month_idx:
                continue

            day = extract_day_from_date_string(date_s)
            prefix = format_day_ordinal(day)
            if prefix:
                full_text = f"{prefix}: {text_s}"
            else:
                full_text = text_s

            cfg = {
                "month_idx": month_idx,
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
                "text_color": style.get("text_color", style.get("color", "#000000")),
                "date_color": style.get("date_color", "#ff0000"),
                "border_color": style.get("border_color", None),
            }
            out.append(cfg)

        return out



    def build_event_texts_from_json_column(row, product_config):
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
        import re

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
            out.append(cfg)

        return out


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
                    import re
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


    # ==========================================================
    # PREVIEW BRANCH
    # ==========================================================
    if mode == "preview":
        if self is None:
            raise ValueError("preview mode requires `self` instance")

        if self.product_type == "normal" and self.design is None:
            messagebox.showwarning("Warning", "Load design JSON first.")
            return
        if self.df is None:
            messagebox.showwarning("Warning", "Load Excel first.")
            return
        if self.current_row_index is None:
            messagebox.showwarning("Warning", "Select a row first.")
            return

        try:
            row = self.df.loc[self.current_row_index]

            # --- calendar event icons ---
            event_icons = self.product_config.get("calendar_event_icons", [])
            for icon in event_icons:
                col = icon.get("excel_column")
                if col:
                    raw = safe_str(row.get(col, ""))
                    icon["excel_date"] = safe_parse_icon_date(raw)
                else:
                    icon["excel_date"] = None

            # --- calendar event texts (JSON column) ---
            event_texts_all = build_event_texts_from_json_column(row, self.product_config)

            if self.product_type == "calendar":
                product_config = self.product_config

                # sync UI -> config
                try:
                    product_config["calendar_year"] = int(self.ent_calendar_year.get())
                except Exception:
                    product_config["calendar_year"] = datetime.now().year

                try:
                    product_config["calendar_start_x"] = int(self.ent_calendar_start_x.get())
                    product_config["calendar_start_y"] = int(self.ent_calendar_start_y.get())
                    product_config["calendar_cell_width"] = int(self.ent_calendar_cell_w.get())
                    product_config["calendar_cell_height"] = int(self.ent_calendar_cell_h.get())
                    product_config["calendar_date_offset_x"] = int(self.ent_calendar_date_off_x.get())
                    product_config["calendar_date_offset_y"] = int(self.ent_calendar_date_off_y.get())
                    product_config["calendar_show_borders"] = self.calendar_show_borders.get()
                    product_config["calendar_date_icon_path"] = getattr(
                        self, "product_config", {}
                    ).get("calendar_date_icon_path")
                except Exception:
                    pass

                try:
                    product_config["calendar_icon_offset_x"] = int(self.ent_calendar_icon_offset_x.get())
                except Exception:
                    product_config["calendar_icon_offset_x"] = 0

                try:
                    product_config["calendar_icon_offset_y"] = int(self.ent_calendar_icon_offset_y.get())
                except Exception:
                    product_config["calendar_icon_offset_y"] = 0

                product_config["calendar_date_align"] = self.cb_calendar_align.get()
                try:
                    product_config["calendar_date_font_size"] = int(self.ent_calendar_font_size.get())
                except Exception:
                    product_config["calendar_date_font_size"] = 18

                product_config["calendar_date_fill"] = (
                    self.ent_calendar_date_color.get().strip() or "#000000"
                )

                product_config["calendar_base_files"] = self.calendar_base_files.copy()

                # Preview January only
                month = 1
                base_files = self.product_config.get("calendar_base_files", [])
                if base_files:
                    try:
                        if month - 1 < len(base_files) and base_files[month - 1]:
                            base_path = base_files[month - 1]
                        else:
                            base_path = base_files[0]
                    except:
                        base_path = base_files[0]
                else:
                    # fallback only if no calendar-specific base
                    base_path = self.base_file

                if not base_path or not os.path.exists(base_path):
                    messagebox.showwarning(
                        "Warning",
                        f"Calendar preview base file not found: {base_path}",
                    )
                    return

                try:
                    ext = os.path.splitext(base_path)[1].lower()
                    if ext == ".pdf":
                        doc = fitz.open(base_path)
                        page = doc.load_page(0)
                        zoom = 300.0 / 72.0
                        mat = fitz.Matrix(zoom, zoom)
                        pix = page.get_pixmap(matrix=mat, alpha=True)
                        base_img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
                        doc.close()
                    else:
                        base_img = Image.open(base_path).convert("RGBA")

                    # JSON mappings BEFORE calendar overlay
                    if self.design:
                        tpl = self.design.get("template", {})
                        width = int(tpl.get("width", 1200))
                        height = int(tpl.get("height", 630))

                        base_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                        ctx = {str(c): row[c] for c in self.df.columns}
                        ctx["MONTH_NAME"] = pycalendar.month_name[month]
                        ctx["MONTH_NUM"] = str(month)

                        for i, ov in enumerate(tpl.get("overlayImages", [])):
                            if not ov.get("behindBackground", False):
                                continue
                            self._draw_overlay(base_img, ov, i, ctx)

                        if self.base_file and os.path.exists(self.base_file):
                            bg_img = Image.open(self.base_file).convert("RGBA")
                            bg_img = bg_img.resize((width, height), Image.LANCZOS)
                            base_img.alpha_composite(bg_img, dest=(0, 0))
                        else:
                            white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
                            base_img.alpha_composite(white, dest=(0, 0))

                        for i, ov in enumerate(tpl.get("overlayImages", [])):
                            if ov.get("behindBackground", False):
                                continue
                            self._draw_overlay(base_img, ov, i, ctx)

                        draw = ImageDraw.Draw(base_img)
                        for i, tb in enumerate(tpl.get("textBlocks", [])):
                            self._draw_text(draw, base_img, tb, i, ctx)

                    # Calendar overlay (dates + icons)
                    overlay = generate_calendar_overlay_image(
                        product_config.get("calendar_year", datetime.now().year),
                        month,
                        int(product_config.get("calendar_cell_width", 100)),
                        int(product_config.get("calendar_cell_height", 80)),
                        int(product_config.get("calendar_date_offset_x", 5)),
                        int(product_config.get("calendar_date_offset_y", 5)),
                        product_config.get("calendar_date_align", "left"),
                        product_config.get("calendar_date_font_path"),
                        int(product_config.get("calendar_date_font_size", 18)),
                        date_fill=product_config.get("calendar_date_fill", "#000000"),
                        show_borders=product_config.get("calendar_show_borders", False),
                        date_icon_path=product_config.get("calendar_date_icon_path"),
                        date_icon_scale=0.35,
                        date_icon_offset_x=product_config.get("calendar_icon_offset_x", 0),
                        date_icon_offset_y=product_config.get("calendar_icon_offset_y", 0),
                        excel_event_date=None,
                        event_icons=product_config.get("calendar_event_icons", []),
                    )

                    base_img.alpha_composite(
                        overlay,
                        dest=(
                            int(product_config.get("calendar_start_x", 0)),
                            int(product_config.get("calendar_start_y", 0)),
                        ),
                    )

                    # Draw event texts for January
                    line_spacing = int(
                        self.product_config.get("calendar_event_text_line_spacing", 4)
                    )
                    base_y = self.product_config.get("calendar_event_text_style", {}).get("y", 0)

                    current_offset = 0
                    for tcfg in event_texts_all:
                        if tcfg.get("month_idx") != month:
                            continue
                        local_cfg = tcfg.copy()
                        local_cfg["y"] = base_y + current_offset
                        used_h = draw_event_text_block(base_img, local_cfg, product_config)
                        current_offset += used_h + line_spacing

                    self.show_image_fitted(base_img)
                    self.lbl_status.config(text="✓ Calendar preview (January) rendered")
                except Exception as e:
                    messagebox.showerror("Preview Error", str(e))
            else:
                img = self.render_row_to_image(row)
                self.show_image_fitted(img)
                self.lbl_status.config(
                    text=f"✓ Preview rendered for row {self.current_row_index}"
                )
        except Exception as e:
            messagebox.showerror("Render Error", f"{e}")
        return

    # ==========================================================
    # WORKER BRANCH
    # ==========================================================
    elif mode == "worker":
        if args is None:
            raise ValueError("worker mode requires `args` tuple")

        try:
            (
                idx,
                row_dict,
                design,
                slot_vars,
                base_folder,
                base_file_or_list,
                output_folder,
                output_format,
                df_columns,
                filename_column,
                product_config,
            ) = args

            row = pd.Series(row_dict)

            # calendar production
            if product_config and product_config.get("type", "").lower() == "calendar":
                start_x = int(product_config.get("calendar_start_x", 0))
                start_y = int(product_config.get("calendar_start_y", 0))
                cell_w = int(product_config.get("calendar_cell_width", 100))
                cell_h = int(product_config.get("calendar_cell_height", 80))
                date_off_x = int(product_config.get("calendar_date_offset_x", 5))
                date_off_y = int(product_config.get("calendar_date_offset_y", 5))
                align = product_config.get("calendar_date_align", "left")
                date_font_path = product_config.get("calendar_date_font_path")
                date_font_size = int(product_config.get("calendar_date_font_size", 18))
                date_fill = product_config.get("calendar_date_fill", "#000000")
                base_files = product_config.get("calendar_base_files", []) or []

                if (
                    filename_column
                    and filename_column in row
                    and str(row[filename_column]).strip()
                ):
                    base_name = os.path.splitext(str(row[filename_column]).strip())[0]
                else:
                    base_name = f"row{idx}"

                ensure_dir(output_folder)

                # icons
                raw_icon_cfgs = product_config.get("calendar_event_icons", []) or []
                event_icons = []
                for cfg in raw_icon_cfgs:
                    col = cfg.get("excel_column")
                    if not col or col not in row:
                        continue
                    raw = safe_str(row.get(col, ""))
                    dt = safe_parse_icon_date(raw)
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

                # text events (JSON list column)
                event_texts_all = build_event_texts_from_json_column(row, product_config)

                results_errors = []
                produced_count = 0

                for month in range(1, 13):
                    row["__current_month__"] = month

                    # pick base file
                    if isinstance(base_file_or_list, (list, tuple)) and base_file_or_list:
                        if month - 1 < len(base_files) and base_files[month - 1]:
                            base_path = base_files[month - 1]
                        else:
                            base_path = base_files[-1] if base_files else base_file_or_list[0]
                    else:
                        base_path = base_file_or_list

                    if not base_path or not os.path.exists(base_path):
                        results_errors.append(
                            f"Missing base file for month {month}: {base_path}"
                        )
                        continue

                    try:
                        ext = os.path.splitext(base_path)[1].lower()

                        if ext == ".pdf":
                            doc = fitz.open(base_path)
                            page = doc.load_page(0)
                            zoom = 300.0 / 72.0
                            mat = fitz.Matrix(zoom, zoom)
                            pix = page.get_pixmap(matrix=mat, alpha=True)
                            base_img = Image.frombytes(
                                "RGBA", (pix.width, pix.height), pix.samples
                            )
                            doc.close()

                            if design:
                                t = json.loads(json.dumps(design))
                                tpl = t.get("template", {})
                                ctx = {str(c): safe_str(row.get(c, "")) for c in df_columns}
                                ctx["__current_month__"] = row.get("__current_month__", None)

                                for i, ov in enumerate(tpl.get("overlayImages", [])):
                                    if not ov.get("behindBackground", False):
                                        continue
                                    draw_overlay_static(base_img, ov, i, ctx, slot_vars)

                                for i, ov in enumerate(tpl.get("overlayImages", [])):
                                    if ov.get("behindBackground", False):
                                        continue
                                    draw_overlay_static(base_img, ov, i, ctx, slot_vars)

                                draw = ImageDraw.Draw(base_img)
                                for i, tb in enumerate(tpl.get("textBlocks", [])):
                                    draw_text_static(draw, base_img, tb, i, ctx, slot_vars)
                        else:
                            base_img = render_row_to_pil_image_static(
                                row,
                                design,
                                slot_vars,
                                base_folder,
                                base_path,
                                df_columns,
                            )

                        overlay = generate_calendar_overlay_image(
                            product_config.get("calendar_year", datetime.now().year),
                            month,
                            cell_w,
                            cell_h,
                            date_off_x,
                            date_off_y,
                            align,
                            date_font_path,
                            date_font_size,
                            date_fill=date_fill,
                            show_borders=product_config.get("calendar_show_borders", False),
                            excel_event_date=None,
                            event_icons=event_icons,
                        )
                        base_img.alpha_composite(overlay, dest=(start_x, start_y))

                        # draw event texts for this month
                        line_spacing = int(product_config.get("calendar_event_text_line_spacing", 4))
                        base_y = product_config.get("calendar_event_text_style", {}).get("y", 0)
                        current_offset = 0

                        for tcfg in event_texts_all:
                            if tcfg.get("month_idx") != month:
                                continue

                            local_cfg = tcfg.copy()
                            local_cfg["y"] = base_y + current_offset
                            used_h = draw_event_text_block(base_img, local_cfg, product_config)
                            current_offset += used_h + line_spacing

                        out_base = f"{base_name}_{month:02d}_{pycalendar.month_name[month]}"

                        if ext == ".pdf":
                            img_bytes = io.BytesIO()
                            base_img.save(img_bytes, format="PNG", dpi=(300, 300))
                            img_bytes.seek(0)
                            newdoc = fitz.open()
                            rect = fitz.Rect(0, 0, base_img.width, base_img.height)
                            newpage = newdoc.new_page(width=rect.width, height=rect.height)
                            newpage.insert_image(rect, stream=img_bytes.getvalue())
                            outp = os.path.join(output_folder, f"{out_base}.pdf")
                            newdoc.save(outp, deflate=True)
                            newdoc.close()
                        else:
                            outp = os.path.join(output_folder, f"{out_base}.png")
                            base_img.save(outp, "PNG", dpi=(300, 300))

                        produced_count += 1
                    except Exception as e:
                        results_errors.append(f"Month {month} render error: {e}")


                # draw event texts for this month, stacked vertically
                # line_spacing = int(
                #     product_config.get("calendar_event_text_line_spacing", 4)
                # )
                # base_y = product_config.get("calendar_event_text_style", {}).get("y", 0)

                # current_offset = 0
                # for tcfg in event_texts_all:
                #     if tcfg.get("month_idx") != month:
                #         continue
                #     local_cfg = tcfg.copy()
                #     local_cfg["y"] = base_y + current_offset
                #     used_h = draw_event_text_block(base_img, local_cfg, product_config)
                #     current_offset += used_h + line_spacing
    
    
                if results_errors:
                    return (idx, False, "; ".join(results_errors), produced_count)

                return (idx, True, None, produced_count)

            # ---------------- normal product ----------------
            missing_images = validate_row_images(row.to_dict(), design, slot_vars, df_columns)
            if missing_images:
                return (idx, False, f"Missing images: {', '.join(missing_images)}", 0)

            if filename_column and filename_column in row:
                custom_filename = str(row[filename_column]).strip()
                base_name = os.path.splitext(custom_filename)[0]
            else:
                base_name = f"output_{idx}"

            try:
                if output_format == "pdf":
                    output_path = os.path.join(output_folder, f"{base_name}.pdf")
                    render_row_to_pdf_static(
                        row,
                        output_path,
                        design,
                        slot_vars,
                        base_file_or_list
                        if isinstance(base_file_or_list, str)
                        else (
                            base_file_or_list[0]
                            if isinstance(base_file_or_list, (list, tuple)) and base_file_or_list
                            else ""
                        ),
                        df_columns,
                    )
                elif output_format == "jpg":
                    output_path = os.path.join(output_folder, f"{base_name}.jpg")
                    img = render_row_to_pil_image_static(
                        row,
                        design,
                        slot_vars,
                        base_folder,
                        base_file_or_list
                        if isinstance(base_file_or_list, str)
                        else (
                            base_file_or_list[0]
                            if isinstance(base_file_or_list, (list, tuple)) and base_file_or_list
                            else ""
                        ),
                        df_columns,
                    )
                    img.convert("RGB").save(output_path, "JPEG", dpi=(300, 300), quality=95)
                else:
                    output_path = os.path.join(output_folder, f"{base_name}.png")
                    img = render_row_to_pil_image_static(
                        row,
                        design,
                        slot_vars,
                        base_folder,
                        base_file_or_list
                        if isinstance(base_file_or_list, str)
                        else (
                            base_file_or_list[0]
                            if isinstance(base_file_or_list, (list, tuple)) and base_file_or_list
                            else ""
                        ),
                        df_columns,
                    )
                    img.save(output_path, "PNG", dpi=(300, 300))

                return (idx, True, None, 1)
            except Exception as e:
                return (idx, False, str(e), 0)
        except Exception as e:
            return (idx, False, str(e), 0)
    else:
        raise ValueError(f"Unknown mode for _merged_row_handler: {mode!r}")

    
    
def process_single_row_worker(args):
    """
    Worker function wrapper: delegates to unified handler in worker mode.
    Returns: (idx, success_bool, error_or_None, produced_count)
    """
    return _merged_row_handler("worker", args=args)




# ---------------------------
# Main Application UI
# ---------------------------

class TemplateDesignerApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Template Designer Pro - Excel to Design Automation")
        self.geometry("1920x1000")
        self.configure(bg="#f5f7fa")

        self.colors = {
            "primary": "#2563eb",
            "primary_dark": "#1e40af",
            "secondary": "#10b981",
            "bg_light": "#f5f7fa",
            "bg_white": "#ffffff",
            "border": "#e5e7eb",
            "text_dark": "#1f2937",
            "text_light": "#6b7280",
            "success": "#10b981",
            "warning": "#f59e0b",
            "danger": "#ef4444",
        }

        # Data & design
        self.df = None
        self.design = None
        self.base_folder = ""
        self.base_file = ""  # single base file for normal mode OR fallback for calendar
        self.calendar_base_files = []  # list of base files selected in calendar mode
        self.output_folder = ""
        self.output_format = "png"
        self.filename_column = None

        # UI state
        self.preview_img_tk = None
        self.current_row_index = None
        self.slot_vars = {}
        self.is_generating = False
        self.stop_event = Event()
        self.num_workers = cpu_count()
        

        # product config using Option1 names
        self.product_type = "normal"  # "normal" or "calendar"
        self.product_config = {
            "type": "normal",
            "calendar_start_x": 0,
            "calendar_start_y": 0,
            "calendar_cell_width": 100,
            "calendar_cell_height": 80,
            "calendar_date_offset_x": 5,
            "calendar_date_offset_y": 5,
            "calendar_date_align": "left",
            "calendar_date_font_path": None,
            "calendar_date_font_size": 18,
            "calendar_date_fill": "#000000",
            "calendar_base_files": [],
            "calendar_year": datetime.now().year,
            "calendar_event_icons": [],
            "calendar_event_texts": [],
        }
        self.calendar_event_text_rows = []
        self._setup_styles()
        self._build_ui()


    def save_template(self):
        if not self.design:
            messagebox.showwarning("Warning", "No design loaded to save.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".tdtpl.json",
            filetypes=[("Template Files", "*.tdtpl.json")],
            title="Save Template",
        )
        if not path:
            return

        payload = {
            "version": "1.0",
            "saved_at": datetime.now().isoformat(),
            "product_type": self.product_type,
            "design": self.design,
            "product_config": self.product_config,
            "slot_vars": self._serialize_slot_vars(),
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self.lbl_status.config(text=f"✓ Template saved: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def _serialize_slot_vars(self):
        out = {}
        for k, v in self.slot_vars.items():
            out[k] = {
                "value": v.get("value"),
                "path": v.get("path"),
            }
        return out

    def load_template(self):
        path = filedialog.askopenfilename(
            filetypes=[("Template Files", "*.tdtpl.json")],
            title="Load Template",
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.design = data.get("design")
            self.product_type = data.get("product_type", "normal")
            self.product_config = data.get("product_config", {})
            self.slot_vars = self._deserialize_slot_vars(data.get("slot_vars", {}))

            self._refresh_ui_from_template()

            self.lbl_status.config(text=f"✓ Template loaded: {os.path.basename(path)}")

        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _deserialize_slot_vars(self, data):
        out = {}
        for k, v in data.items():
            out[k] = {
                "value": v.get("value"),
                "path": v.get("path"),
            }
        return out


    def _refresh_ui_from_template(self):
        # product type
        self.top_product_type_var.set(
            "Calendar Production" if self.product_type == "calendar" else "Normal Production"
        )

        # rebuild mapping UI
        self._build_mapping_tab()

        # refresh calendar tab if needed
        if self.product_type == "calendar":
            self._build_calendar_tab()

        # redraw preview if possible
        if self.df is not None and self.current_row_index is not None:
            self.preview_current_row()


    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TNotebook", background=self.colors["bg_light"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=self.colors["bg_white"],
            foreground=self.colors["text_dark"],
            padding=[20, 10],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.colors["primary"])],
            foreground=[("selected", "white")],
        )

        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor=self.colors["border"],
            background=self.colors["success"],
            borderwidth=0,
            thickness=20,
        )

    def _build_status_bar(self, parent):
        status = tk.Frame(parent, bg="#1f2937", height=35)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)

        self.lbl_status = tk.Label(
            status,
            text="Ready • Load your data to begin",
            bg="#1f2937",
            fg="#9ca3af",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.lbl_status.pack(side="left", padx=20, fill="x", expand=True)

    def _build_ui(self):
        main = tk.Frame(self, bg=self.colors["bg_light"])
        main.pack(fill="both", expand=True)

        self._build_header(main)

        content = tk.Frame(main, bg=self.colors["bg_light"])
        content.pack(fill="both", expand=True)

        # New: horizontal paned window
        paned = tk.PanedWindow(
            content,
            orient="horizontal",
            sashwidth=6,
            showhandle=True,
        )
        paned.pack(fill="both", expand=True)

        # Create three empty frames and pass them to builders
        left_frame = tk.Frame(paned)
        center_frame = tk.Frame(paned)
        right_frame = tk.Frame(paned)

        paned.add(left_frame, minsize=200)  # initial/safe minimum width
        paned.add(center_frame, minsize=300)
        paned.add(right_frame, minsize=250)

        self._build_left_panel(left_frame)
        self._build_center_panel(center_frame)
        self._build_right_panel(right_frame)
        self._build_status_bar(main)

    def upload_calendar_icon(self):
        path = filedialog.askopenfilename(
            title="Choose Date Cell Icon",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.webp *.bmp")],
        )
        if path:
            self.product_config["calendar_date_icon_path"] = path
            self.lbl_calendar_icon.config(text=os.path.basename(path))

    def _build_header(self, parent):
        header = tk.Frame(parent, bg=self.colors["primary"], height=80)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_frame = tk.Frame(header, bg=self.colors["primary"])
        title_frame.pack(side="left", padx=20, pady=15)

        tk.Label(
            title_frame,
            text="Template Designer Pro",
            font=("Segoe UI", 18, "bold"),
            bg=self.colors["primary"],
            fg="white",
        ).pack(anchor="w")

        tk.Label(
            title_frame,
            text="Excel to Design Automation • 300 DPI • Multi-format Support • Parallel Processing",
            font=("Segoe UI", 9),
            bg=self.colors["primary"],
            fg="#93c5fd",
        ).pack(anchor="w")

        btn_frame = tk.Frame(header, bg=self.colors["primary"])
        btn_frame.pack(side="right", padx=10, pady=15)

        # Top controls: load buttons + product type + base file + output folder
        buttons = [
            ("📄 Load JSON", self.load_design),
            ("📊 Load Excel", self.load_excel),
            ("📁 Base Folder", self.select_base_folder),
        ]
        for text, cmd in buttons:
            btn = tk.Button(
                btn_frame,
                text=text,
                command=cmd,
                bg="white",
                fg=self.colors["primary"],
                font=("Segoe UI", 9, "bold"),
                relief="flat",
                padx=12,
                pady=6,
                cursor="hand2",
                borderwidth=0,
            )
            btn.pack(side="left", padx=4)
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg="#f0f9ff"))
            btn.bind("<Leave>", lambda e, b=btn: b.config(bg="white"))

        # Product Type dropdown (top)
        tk.Label(btn_frame, text="Product Type:", bg=self.colors["primary"], fg="white").pack(
            side="left", padx=(10, 2)
        )

        self.top_product_type_var = tk.StringVar(value="Normal Production")
        top_prod_cb = ttk.Combobox(
            btn_frame,
            textvariable=self.top_product_type_var,
            values=["Normal Production", "Calendar Production"],
            state="readonly",
            width=20,
        )
        top_prod_cb.pack(side="left", padx=(0, 8))
        top_prod_cb.bind("<<ComboboxSelected>>", self._on_top_product_type_change)

        # Base File / Multiple Base Files button
        self.btn_base_file = tk.Button(
            btn_frame,
            text="🖼️ Base File",
            command=self.select_base_file,
            bg="white",
            fg=self.colors["primary"],
            font=("Segoe UI", 9),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )
        self.btn_base_file.pack(side="left", padx=4)

        self.btn_output_folder = tk.Button(
            btn_frame,
            text="💾 Output Folder",
            command=self.select_output_folder,
            bg="white",
            fg=self.colors["primary"],
            font=("Segoe UI", 9),
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        )
        self.btn_output_folder.pack(side="left", padx=4)
        tk.Button(
            btn_frame,
            text="💾 Save Template",
            command=self.save_template,
            bg="white",
            fg=self.colors["primary"],
            font=("Segoe UI", 9),
            relief="flat",
            padx=12,
            pady=6,
        ).pack(side="left", padx=4)
        tk.Button(
            btn_frame,
            text="📂 Load Template",
            command=self.load_template,
            bg="white",
            fg=self.colors["primary"],
            font=("Segoe UI", 9),
            relief="flat",
            padx=12,
            pady=6,
        ).pack(side="left", padx=4)


    def auto_sort_months(self):
        files = self.product_config.get("calendar_base_files", [])
        detected = []
        unknown = []
        for f in files:
            m = self.detect_month_index(f)
            if m:
                detected.append((m, f))
            else:
                unknown.append(f)

        # Sort by month index
        detected.sort(key=lambda x: x[0])

        # Reconstruct list: detected months in order + unknown at end
        new_list = [f for _, f in detected] + unknown
        self.product_config["calendar_base_files"] = new_list
        self.update_calendar_base_display()
        self.refresh_month_thumbnails()

    def move_month_up(self):
        i = self.calendar_base_listbox.curselection()
        if not i:
            return
        idx = i[0]
        if idx == 0:
            return

        files = self.product_config["calendar_base_files"]
        files[idx - 1], files[idx] = files[idx], files[idx - 1]

        self.update_calendar_base_display()
        self.calendar_base_listbox.select_set(idx - 1)
        self.refresh_month_thumbnails()

    def move_month_down(self):
        i = self.calendar_base_listbox.curselection()
        if not i:
            return
        idx = i[0]

        files = self.product_config["calendar_base_files"]
        if idx >= len(files) - 1:
            return
        files[idx + 1], files[idx] = files[idx], files[idx + 1]

        self.update_calendar_base_display()
        self.calendar_base_listbox.select_set(idx + 1)
        self.refresh_month_thumbnails()

    def _on_top_product_type_change(self, _ev=None):
        val = self.top_product_type_var.get()
        if val == "Calendar Production":
            self.product_type = "calendar"
            self.product_config["type"] = "calendar"
            self.lbl_status.config(
                text="Product type: Calendar Production (Base File button will accept multiple files)"
            )
            # show calendar tab automatically
            try:
                # select notebook tab index for calendar if exists...  # safe guard: find calendar tab by name
                for _nb in self.winfo_children():
                    pass
            except Exception:
                pass
        else:
            self.product_type = "normal"
            self.product_config["type"] = "normal"
            self.lbl_status.config(text="Product type: Normal Production")

    def _build_left_panel(self, parent):
        card = tk.Frame(parent, bg=self.colors["bg_white"], relief="flat", borderwidth=1)
        card.pack(side="left", fill="both", expand=True)
        card.configure(width=480)
        card.pack_propagate(False)

        header = tk.Frame(card, bg=self.colors["bg_white"])
        header.pack(fill="x")

        tk.Label(
            header,
            text="📊 Data Table",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["bg_white"],
            fg=self.colors["text_dark"],
        ).pack(side="left")

        self.lbl_row_count = tk.Label(
            header,
            text="0 rows",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
            fg=self.colors["text_light"],
        )
        self.lbl_row_count.pack(side="right")

        tk.Frame(card, height=1, bg=self.colors["border"]).pack(fill="x")

        tree_container = tk.Frame(card, bg=self.colors["bg_white"])
        tree_container.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_container, show="headings")
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.on_row_select)

    def _build_center_panel(self, parent):
        card = tk.Frame(parent, bg=self.colors["bg_white"])
        card.pack(side="left", fill="both", expand=True)

        header = tk.Frame(card, bg=self.colors["bg_white"])
        header.pack(fill="x")

        tk.Label(
            header,
            text="⚙️ Configuration",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["bg_white"],
            fg=self.colors["text_dark"],
        ).pack(side="left")

        tk.Frame(card, height=1, bg=self.colors["border"]).pack(fill="x")

        notebook = ttk.Notebook(card)
        notebook.pack(fill="both", expand=True)

        self.tab_path = tk.Frame(notebook, bg=self.colors["bg_white"])
        self.tab_map = tk.Frame(notebook, bg=self.colors["bg_white"])
        self.tab_output = tk.Frame(notebook, bg=self.colors["bg_white"])
        self.tab_calendar = tk.Frame(notebook, bg=self.colors["bg_white"])

        notebook.add(self.tab_path, text="🔧 Photo Path Builder")
        notebook.add(self.tab_map, text="🔗 JSON Mapping")
        notebook.add(self.tab_output, text="📝 Output Settings")
        notebook.add(self.tab_calendar, text="📅 Calendar")

        self._build_path_tab()
        self._build_mapping_tab()
        self._build_output_tab()
        self._build_calendar_tab()

    def _build_right_panel(self, parent):
        card = tk.Frame(parent, bg=self.colors["bg_white"])
        card.pack(side="left", fill="both", expand=True)

        header = tk.Frame(card, bg=self.colors["bg_white"])
        header.pack(fill="x")

        tk.Label(
            header,
            text="🎨 Live Preview",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["bg_white"],
            fg=self.colors["text_dark"],
        ).pack(side="left")

        btn_container = tk.Frame(header, bg=self.colors["bg_white"])
        btn_container.pack(side="right")

        # Worker count selector
        worker_frame = tk.Frame(btn_container, bg=self.colors["bg_white"])
        worker_frame.pack(side="left")
        tk.Label(
            worker_frame,
            text="Workers:",
            bg=self.colors["bg_white"],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 5))

        self.worker_var = tk.StringVar(value=str(self.num_workers))
        worker_spinbox = tk.Spinbox(
            worker_frame,
            from_=1,
            to=cpu_count() * 2,
            textvariable=self.worker_var,
            width=5,
            font=("Segoe UI", 9),
        )
        worker_spinbox.pack(side="left")

        btn_preview = tk.Button(
            btn_container,
            text="▶ Preview Row",
            command=self.render_selected_row,
            bg=self.colors["secondary"],
            fg="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=15,
            pady=8,
            cursor="hand2",
            borderwidth=0,
        )
        btn_preview.pack(side="left", padx=(0, 5))
        btn_preview.bind("<Enter>", lambda e: btn_preview.config(bg="#059669"))
        btn_preview.bind("<Leave>", lambda e: btn_preview.config(bg=self.colors["secondary"]))

        self.btn_production = tk.Button(
            btn_container,
            text="🚀 Start Production",
            command=self.start_production,
            bg=self.colors["danger"],
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            borderwidth=0,
        )
        self.btn_production.pack(side="left", padx=(0, 5))
        self.btn_production.bind(
            "<Enter>", lambda e: self.btn_production.config(bg="#dc2626")
        )
        self.btn_production.bind(
            "<Leave>", lambda e: self.btn_production.config(bg=self.colors["danger"])
        )

        self.btn_abort = tk.Button(
            btn_container,
            text="⛔ Abort",
            command=self.abort_production,
            bg=self.colors["warning"],
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            borderwidth=0,
            state="disabled",
        )
        self.btn_abort.pack(side="left")
        self.btn_abort.bind(
            "<Enter>",
            lambda e: self.btn_abort.config(bg="#d97706")
            if self.btn_abort["state"] == "normal"
            else None,
        )
        self.btn_abort.bind(
            "<Leave>",
            lambda e: self.btn_abort.config(bg=self.colors["warning"])
            if self.btn_abort["state"] == "normal"
            else None,
        )

        tk.Frame(card, height=1, bg=self.colors["border"]).pack(fill="x", padx=20)

        self.progress_frame = tk.Frame(card, bg=self.colors["bg_white"])
        self.lbl_progress = tk.Label(
            self.progress_frame,
            text="",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
            fg=self.colors["text_dark"],
        )
        self.lbl_progress.pack(pady=(10, 5))

        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            style="Custom.Horizontal.TProgressbar",
            mode="determinate",
            length=400,
        )
        self.progress_bar.pack(pady=(0, 10))

        canvas_frame = tk.Frame(card, bg=self.colors["bg_light"])
        canvas_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.canvas = tk.Canvas(
            canvas_frame,
            bg="#fafafa",
            highlightthickness=1,
            highlightbackground=self.colors["border"],
        )
        self.canvas.pack(fill="both", expand=True)

    def _build_path_tab(self):
        container = tk.Frame(self.tab_path, bg=self.colors["bg_white"])
        container.pack(fill="both", expand=True, padx=15, pady=15)

        info = tk.Frame(container, bg="#eff6ff", relief="flat")
        info.pack(fill="x", pady=(0, 15))

        tk.Label(
            info,
            text="💡 Build dynamic image paths from Excel columns",
            font=("Segoe UI", 9),
            bg="#eff6ff",
            fg="#1e40af",
        ).pack(padx=15, pady=10, anchor="w")

        form = tk.Frame(container, bg=self.colors["bg_white"])
        form.pack(fill="both", expand=True)

        self.path_folder1_var = tk.StringVar()
        self.path_folder2_var = tk.StringVar()
        self.path_file_var = tk.StringVar()
        self.path_prefix_var = tk.StringVar()
        self.path_suffix_var = tk.StringVar()
        self.path_ext_var = tk.StringVar(value=".png")
        self.path_outcol_var = tk.StringVar(value="IMAGE_2")

        fields = [
            ("Folder Level 1", self.path_folder1_var, "cb_path_folder1"),
            ("Folder Level 2 (optional)", self.path_folder2_var, "cb_path_folder2"),
            ("File/Code Column", self.path_file_var, "cb_path_file"),
        ]
        for i, (label, var, attr) in enumerate(fields):
            tk.Label(
                form,
                text=label,
                font=("Segoe UI", 9),
                bg=self.colors["bg_white"],
                fg=self.colors["text_dark"],
            ).grid(row=i, column=0, sticky="w", pady=8, padx=5)
            cb = ttk.Combobox(form, textvariable=var, width=30, state="readonly")
            cb.grid(row=i, column=1, sticky="ew", pady=8, padx=5)
            setattr(self, attr, cb)

        tk.Label(
            form,
            text="Prefix (before filename)",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
        ).grid(row=3, column=0, sticky="w", padx=5, pady=8)
        tk.Entry(form, textvariable=self.path_prefix_var, width=30).grid(
            row=3, column=1, sticky="ew", padx=5, pady=8
        )

        tk.Label(
            form,
            text="Suffix (after filename)",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
        ).grid(row=4, column=0, sticky="w", padx=5, pady=8)
        tk.Entry(form, textvariable=self.path_suffix_var, width=30).grid(
            row=4, column=1, sticky="ew", padx=5, pady=8
        )

        tk.Label(
            form,
            text="Extension",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
        ).grid(row=5, column=0, sticky="w", padx=5, pady=8)
        self.cb_path_ext = ttk.Combobox(
            form,
            textvariable=self.path_ext_var,
            values=[".png", ".jpg", ".jpeg",".pdf"],
            width=15,
            state="readonly",
        )
        self.cb_path_ext.grid(row=5, column=1, sticky="w", padx=5, pady=8)

        tk.Label(
            form,
            text="Output Column Name",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
        ).grid(row=6, column=0, sticky="w", padx=5, pady=8)
        tk.Entry(form, textvariable=self.path_outcol_var, width=32).grid(
            row=6, column=1, sticky="w", padx=5, pady=8
        )

        tk.Button(
            container,
            text="✨ Generate Column",
            command=self.generate_photo_path_column,
            bg=self.colors["primary"],
            fg="white",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=25,
            pady=10,
            cursor="hand2",
        ).pack(pady=15)

        self.lbl_path_status = tk.Label(
            container,
            text="",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
            fg=self.colors["success"],
        )
        self.lbl_path_status.pack()

    def _build_output_tab(self):
        container = tk.Frame(self.tab_output, bg=self.colors["bg_white"])
        container.pack(fill="both", expand=True, padx=15, pady=15)

        info = tk.Frame(container, bg="#eff6ff", relief="flat")
        info.pack(fill="x", pady=(0, 15))

        tk.Label(
            info,
            text="📝 Configure output filename from Excel column",
            font=("Segoe UI", 9),
            bg="#eff6ff",
            fg="#1e40af",
        ).pack(padx=15, pady=10, anchor="w")

        form = tk.Frame(container, bg=self.colors["bg_white"])
        form.pack(fill="both", expand=True)

        self.filename_col_var = tk.StringVar()

        tk.Label(
            form,
            text="Filename Column (optional)",
            font=("Segoe UI", 9),
            bg=self.colors["bg_white"],
            fg=self.colors["text_dark"],
        ).grid(row=0, column=0, sticky="w", pady=8, padx=5)

        self.cb_filename_col = ttk.Combobox(
            form, textvariable=self.filename_col_var, width=30, state="readonly"
        )
        self.cb_filename_col.grid(row=0, column=1, sticky="ew", pady=8, padx=5)

        tk.Label(
            form,
            text="If not selected, files will be named output_0, output_1, etc.",
            font=("Segoe UI", 8),
            bg=self.colors["bg_white"],
            fg=self.colors["text_light"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 8))

    def _build_mapping_tab(self):
        container = tk.Frame(self.tab_map, bg=self.colors["bg_white"])
        container.pack(fill="both", expand=True, padx=15, pady=15)

        info = tk.Frame(container, bg="#eff6ff", relief="flat")
        info.pack(fill="x", pady=(0, 15))

        tk.Label(
            info,
            text="🔗 Map JSON template keys to Excel columns (supports custom fonts & dynamic QR codes)",
            font=("Segoe UI", 9),
            bg="#eff6ff",
            fg="#1e40af",
            anchor="w",
        ).pack(padx=15, pady=10)

        canvas_container = tk.Frame(container, bg=self.colors["bg_white"])
        canvas_container.pack(fill="both", expand=True)

        map_canvas = tk.Canvas(canvas_container, bg=self.colors["bg_white"], highlightthickness=0)
        map_scroll = ttk.Scrollbar(canvas_container, orient="vertical", command=map_canvas.yview)
        self.slot_rows_frame = tk.Frame(map_canvas, bg=self.colors["bg_white"])

        map_canvas.configure(yscrollcommand=map_scroll.set)
        map_scroll.pack(side="right", fill="y")
        map_canvas.pack(side="left", fill="both", expand=True)

        map_canvas.create_window((0, 0), window=self.slot_rows_frame, anchor="nw")
        self.slot_rows_frame.bind(
            "<Configure>",
            lambda e: map_canvas.configure(scrollregion=map_canvas.bbox("all")),
        )

        hdr = tk.Frame(self.slot_rows_frame, bg="#f9fafb")
        hdr.pack(fill="x", pady=(0, 10))

        tk.Label(
            hdr,
            text="Template Key",
            width=30,
            anchor="w",
            bg="#f9fafb",
            fg=self.colors["text_dark"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, padx=10, pady=10)

        tk.Label(
            hdr,
            text="Excel Column",
            width=20,
            anchor="w",
            bg="#f9fafb",
            fg=self.colors["text_dark"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=1, padx=10, pady=10)

        tk.Label(
            hdr,
            text="Custom Font (optional)",
            width=20,
            anchor="w",
            bg="#f9fafb",
            fg=self.colors["text_dark"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=2, padx=10, pady=10)

        self.no_design_label = tk.Label(
            self.slot_rows_frame,
            text="👈 Load JSON and Excel to configure mappings",
            font=("Segoe UI", 10),
            fg=self.colors["text_light"],
            bg=self.colors["bg_white"],
        )
        self.no_design_label.pack(pady=50)

    def select_base_calendar_files(self):
        files = filedialog.askopenfilenames(
            title="Select Calendar Base Files",
            filetypes=[("Images/PDF", "*.png *.jpg *.jpeg *.pdf")],
        )
        if not files:
            return
        self.product_config["calendar_base_files"] = list(files)
        # Update the UI list
        self.update_calendar_base_display()
        self.refresh_month_thumbnails()

    def detect_month_index(self, filename):
        name = os.path.basename(filename).lower()
        months = [
            ("january", 1),
            ("february", 2),
            ("march", 3),
            ("april", 4),
            ("may", 5),
            ("june", 6),
            ("july", 7),
            ("august", 8),
            ("september", 9),
            ("october", 10),
            ("november", 11),
            ("december", 12),
        ]
        for m_name, m_idx in months:
            if m_name in name:
                return m_idx

        abbr = [
            ("jan", 1),
            ("feb", 2),
            ("mar", 3),
            ("apr", 4),
            ("may", 5),
            ("jun", 6),
            ("jul", 7),
            ("aug", 8),
            ("sep", 9),
            ("oct", 10),
            ("nov", 11),
            ("dec", 12),
        ]
        for short, idx in abbr:
            if short in name:
                return idx

        import re

        m = re.search(r"\b(0?[1-9]|1[0-2])\b", name)
        if m:
            return int(m.group(1))
        return None

    def parse_event_date(date_str):
        if not date_str:
            return None

        date_str = date_str.strip().replace("-", "/")

        # Case "03/03/"
        if date_str.endswith("/"):
            date_str = date_str + "2025"  # default year

        # Case "03/03"
        if date_str.count("/") == 1:
            date_str = date_str + "/2025"

        # Try multiple formats
        fmts = ["%d/%m/%Y", "%d/%m/%y"]
        for f in fmts:
            try:
                return datetime.strptime(date_str, f)
            except:
                pass

        return None


    def refresh_excel_column_dropdowns(self):
        """Refresh all UI dropdowns that depend on Excel columns."""
        if self.df is None:
            cols = []
        else:
            cols = list(self.df.columns)

        # Event Text Planner
        if hasattr(self, "cb_evt_text_column"):
            self.cb_evt_text_column["values"] = cols

        # Event Icon Rows
        if hasattr(self, "icon_rows_frame"):
            for child in self.icon_rows_frame.winfo_children():
                for widget in child.winfo_children():
                    if isinstance(widget, ttk.Combobox):
                        widget["values"] = cols
                    
    def _build_calendar_tab(self):
        container = tk.Frame(self.tab_calendar, bg=self.colors["bg_white"])
        container.pack(fill="both", expand=True, padx=15, pady=15)

        tk.Label(
            container,
            text="📅 Calendar Product Configuration",
            font=("Segoe UI", 11, "bold"),
            bg=self.colors["bg_white"],
        ).pack(anchor="w", pady=(0, 10))

        form = tk.Frame(container, bg=self.colors["bg_white"])
        form.pack(fill="x", pady=(0, 10))

        # -------------------------------------------------------------
        # Selected Calendar Base Files (Top display) - placed directly inside container
        # -------------------------------------------------------------
        view_frame = tk.LabelFrame(container, text="Selected Calendar Base Files (Order)")
        view_frame.pack(fill="x", padx=5, pady=(0, 10))

        self.calendar_base_listbox = tk.Listbox(view_frame, height=6, width=70)
        self.calendar_base_listbox.pack(fill="both", padx=5, pady=5)

        def update_calendar_base_display():
            self.calendar_base_listbox.delete(0, tk.END)
            base_files = self.product_config.get("calendar_base_files", [])
            if not base_files:
                self.calendar_base_listbox.insert(tk.END, "(no base files selected)")
                return
            for idx, f in enumerate(base_files, start=1):
                self.calendar_base_listbox.insert(tk.END, f"{idx}. {os.path.basename(f)}")

        self.update_calendar_base_display = update_calendar_base_display

        # --- THUMBNAIL & REORDER SECTION ---
        thumb_frame = tk.LabelFrame(container, text="Month Thumbnails + Reorder")
        thumb_frame.pack(fill="x", padx=5, pady=5)

        def refresh_month_thumbnails():
            self.month_thumb_canvas.delete("all")
            self.month_thumb_items.clear()

            base_files = self.product_config.get("calendar_base_files", [])

            x_offset = 10
            for f in base_files:
                try:
                    ext = os.path.splitext(f)[1].lower()
                    if ext == ".pdf":
                        doc = fitz.open(f)
                        page = doc.load_page(0)
                        pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    else:
                        img = Image.open(f).convert("RGB")

                    img.thumbnail((80, 80))
                    tk_img = ImageTk.PhotoImage(img)

                    item = self.month_thumb_canvas.create_image(x_offset, 60, image=tk_img)
                    self.month_thumb_items.append((tk_img, item, f))

                    self.month_thumb_canvas.create_text(
                        x_offset, 105, text=os.path.basename(f), font=("Segoe UI", 7)
                    )

                    x_offset += 100

                except Exception as e:
                    print("Thumbnail error:", e)

        self.refresh_month_thumbnails = refresh_month_thumbnails
        self.month_thumb_canvas = tk.Canvas(thumb_frame, height=120, bg="#ffffff")
        self.month_thumb_canvas.pack(fill="x")
        self.month_thumb_items = []  # Stores (imageTK, canvas_id, filename)

        tk.Label(
            form,
            text="Base Files (multiple for months)",
            bg=self.colors["bg_white"],
        ).grid(row=0, column=0, sticky="w")
        tk.Button(
            form,
            text="Choose Calendar Base Files",
            command=self.select_calendar_base_files,
            bg="#e0e7ef",
        ).grid(row=0, column=1, sticky="w")
        tk.Button(
            form,
            text="Auto-Sort by Month Name",
            bg="#dbeafe",
            command=self.auto_sort_months,
        ).grid(row=0, column=2, padx=5)

        reorder_frame = tk.Frame(container, bg=self.colors["bg_white"])
        reorder_frame.pack(fill="x", pady=5)

        tk.Button(
            reorder_frame, text="▲ Move Up", bg="#fef3c7",
            command=self.move_month_up,
        ).pack(side="left", padx=3)
        tk.Button(
            reorder_frame, text="▼ Move Down", bg="#fcd34d",
            command=self.move_month_down,
        ).pack(side="left", padx=3)

        tk.Label(form, text="Year", bg=self.colors["bg_white"]).grid(
            row=1, column=0, sticky="w"
        )
        self.ent_calendar_year = tk.Entry(form, width=10)
        self.ent_calendar_year.grid(row=1, column=1, sticky="w")
        self.ent_calendar_year.insert(0, str(self.product_config["calendar_year"]))

        # Option1 variable names mapped to UI controls
        tk.Label(form, text="calendar_start_x", bg=self.colors["bg_white"]).grid(
            row=2, column=0, sticky="w"
        )
        self.ent_calendar_start_x = tk.Entry(form, width=8)
        self.ent_calendar_start_x.grid(row=2, column=1, sticky="w")
        self.ent_calendar_start_x.insert(0, "0")

        tk.Label(form, text="calendar_start_y", bg=self.colors["bg_white"]).grid(
            row=2, column=2, sticky="w"
        )
        self.ent_calendar_start_y = tk.Entry(form, width=8)
        self.ent_calendar_start_y.grid(row=2, column=3, sticky="w")
        self.ent_calendar_start_y.insert(0, "0")

        tk.Label(form, text="calendar_cell_width", bg=self.colors["bg_white"]).grid(
            row=3, column=0, sticky="w"
        )
        self.ent_calendar_cell_w = tk.Entry(form, width=8)
        self.ent_calendar_cell_w.grid(row=3, column=1, sticky="w")
        self.ent_calendar_cell_w.insert(0, "100")

        tk.Label(form, text="calendar_cell_height", bg=self.colors["bg_white"]).grid(
            row=3, column=2, sticky="w"
        )
        self.ent_calendar_cell_h = tk.Entry(form, width=8)
        self.ent_calendar_cell_h.grid(row=3, column=3, sticky="w")
        self.ent_calendar_cell_h.insert(0, "80")

        tk.Label(form, text="calendar_date_offset_x", bg=self.colors["bg_white"]).grid(
            row=4, column=0, sticky="w"
        )
        self.ent_calendar_date_off_x = tk.Entry(form, width=8)
        self.ent_calendar_date_off_x.grid(row=4, column=1, sticky="w")
        self.ent_calendar_date_off_x.insert(0, "5")

        tk.Label(form, text="calendar_date_offset_y", bg=self.colors["bg_white"]).grid(
            row=4, column=2, sticky="w"
        )
        self.ent_calendar_date_off_y = tk.Entry(form, width=8)
        self.ent_calendar_date_off_y.grid(row=4, column=3, sticky="w")
        self.ent_calendar_date_off_y.insert(0, "5")

        tk.Label(form, text="Date Align", bg=self.colors["bg_white"]).grid(
            row=5, column=0, sticky="w"
        )
        self.cb_calendar_align = ttk.Combobox(
            form, values=["left", "center", "right"], state="readonly", width=10
        )
        self.cb_calendar_align.set("left")
        self.cb_calendar_align.grid(row=5, column=1, sticky="w")

        tk.Label(form, text="Font (optional)", bg=self.colors["bg_white"]).grid(
            row=6, column=0, sticky="w"
        )
        self.btn_calendar_font = tk.Button(
            form, text="Upload Font", command=self.upload_calendar_font, bg="#e0e7ef"
        )
        self.btn_calendar_font.grid(row=6, column=1, sticky="w")

        self.lbl_calendar_font = tk.Label(
            form, text="(system default)", bg=self.colors["bg_white"]
        )
        self.lbl_calendar_font.grid(row=6, column=2, columnspan=2, sticky="w")

        tk.Label(form, text="calendar_date_font_size", bg=self.colors["bg_white"]).grid(
            row=7, column=0, sticky="w"
        )
        self.ent_calendar_font_size = tk.Entry(form, width=8)
        self.ent_calendar_font_size.grid(row=7, column=1, sticky="w")
        self.ent_calendar_font_size.insert(0, "18")

        tk.Label(form, text="calendar_date_fill (#hex)", bg=self.colors["bg_white"]).grid(
            row=7, column=2, sticky="w"
        )
        self.ent_calendar_date_color = tk.Entry(form, width=10)
        self.ent_calendar_date_color.grid(row=7, column=3, sticky="w")
        self.ent_calendar_date_color.insert(0, "#000000")

        tk.Label(
            container,
            text=(
                "Note: Option B behavior — the app will generate 12 outputs per row "
                "(Jan→Dec) using the selected base files in order. "
                "If fewer than 12 base files are selected, the last selected file "
                "will be reused for remaining months."
            ),
            bg=self.colors["bg_white"],
            fg=self.colors["text_light"],
        ).pack(anchor="w", pady=(10, 0))

        # --- Calendar Cell Border Toggle ---
        tk.Label(form, text="Show Cell Borders", bg=self.colors["bg_white"]).grid(
            row=8, column=0, sticky="w"
        )
        self.calendar_show_borders = tk.BooleanVar(value=False)
        tk.Checkbutton(
            form,
            text="Enable",
            variable=self.calendar_show_borders,
            bg=self.colors["bg_white"],
        ).grid(row=8, column=1, sticky="w")

        # --- MULTIPLE ICONS SECTION ---
        # Row 9: Event Icons label + rows
        tk.Label(form, text="Event Icons", bg=self.colors["bg_white"]).grid(
            row=9, column=0, sticky="nw", padx=(0, 5), pady=(8, 2)
        )
        self.icon_rows_frame = tk.Frame(form, bg=self.colors["bg_white"])
        self.icon_rows_frame.grid(row=9, column=1, columnspan=3, sticky="w", pady=(8, 2))

        def add_icon_row():
            row_frame = tk.Frame(self.icon_rows_frame, bg=self.colors["bg_white"])
            row_frame.pack(anchor="w", pady=3)

            icon_data = {"path": None, "offset_x": 0, "offset_y": 0, "excel_column": None}
            self.product_config["calendar_event_icons"].append(icon_data)

            # Upload button
            def upload():
                path = filedialog.askopenfilename(
                    title="Choose Icon",
                    filetypes=[("Images", "*.png *.jpg *.jpeg")],
                )
                if path:
                    icon_data["path"] = path
                    btn_upload.config(text=os.path.basename(path))

            btn_upload = tk.Button(row_frame, text="Upload Icon", command=upload, bg="#e0e7ef")
            btn_upload.pack(side="left", padx=3)

            # Excel column dropdown for dynamic date source
            tk.Label(row_frame, text="Excel Field", bg=self.colors["bg_white"]).pack(
                side="left", padx=(5, 0)
            )
            excel_cb = ttk.Combobox(row_frame, state="readonly", width=18)
            excel_cb["values"] = list(self.df.columns)
            excel_cb.pack(side="left", padx=3)

            def on_select_col(_):
                icon_data["excel_column"] = excel_cb.get()

            excel_cb.bind("<<ComboboxSelected>>", on_select_col)

            # Offset X
            tk.Label(row_frame, text="X", bg=self.colors["bg_white"]).pack(side="left")
            ent_x = tk.Entry(row_frame, width=5)
            ent_x.insert(0, "0")
            ent_x.pack(side="left", padx=3)

            # Offset Y
            tk.Label(row_frame, text="Y", bg=self.colors["bg_white"]).pack(side="left")
            ent_y = tk.Entry(row_frame, width=5)
            ent_y.insert(0, "0")
            ent_y.pack(side="left", padx=3)

            tk.Label(row_frame, text="Scale%", bg=self.colors["bg_white"]).pack(side="left")
            ent_scale = tk.Entry(row_frame, width=5)
            ent_scale.insert(0, "35")  # default = 35%
            ent_scale.pack(side="left", padx=3)

            def save_scale(*_):
                try:
                    icon_data["scale"] = float(ent_scale.get()) / 100.0
                except Exception:
                    icon_data["scale"] = 0.35

            ent_scale.bind("<KeyRelease>", save_scale)

            def save_offsets(*_):
                try:
                    icon_data["offset_x"] = int(ent_x.get())
                    icon_data["offset_y"] = int(ent_y.get())
                except Exception:
                    pass

            ent_x.bind("<KeyRelease>", save_offsets)
            ent_y.bind("<KeyRelease>", save_offsets)

        # Row 10: "+" button under icons
        btn_add_icon = tk.Button(
            form, text="+ Add Icon", command=add_icon_row, bg="#d1fae5"
        )
        btn_add_icon.grid(row=10, column=1, sticky="w", pady=(4, 5))
        
        
                # ================================================================
        # EVENT TEXT PLANNER UI (Single Column JSON Event List)
        # ================================================================

        frm_evt_txt = ttk.LabelFrame(container, text="Event Text Planner", padding=10)
        frm_evt_txt.pack(fill="x", pady=10)

        ttk.Label(
            frm_evt_txt,
            text="Excel Column (JSON Event List):",
        ).grid(row=0, column=0, sticky="w")

        self.cb_evt_text_column = ttk.Combobox(
            frm_evt_txt, width=40, state="readonly"
        )
        self.cb_evt_text_column["values"] = (
            list(self.df.columns) if self.df is not None else []
        )
        self.cb_evt_text_column.grid(row=0, column=1, sticky="w")

        def save_evt_text_column(_=None):
            self.product_config["calendar_event_text_column"] = (
                self.cb_evt_text_column.get()
            )

        self.cb_evt_text_column.bind("<<ComboboxSelected>>", save_evt_text_column)

        if "calendar_event_text_column" in self.product_config:
            self.cb_evt_text_column.set(
                self.product_config["calendar_event_text_column"]
            )

        # ---------------- STYLE PANEL ----------------
        frm_style = ttk.Frame(frm_evt_txt)
        frm_style.grid(row=1, column=0, columnspan=3, pady=10, sticky="w")

        self.et_evt_x = tk.Entry(frm_style, width=8)
        self.et_evt_y = tk.Entry(frm_style, width=8)
        self.et_evt_font_size = tk.Entry(frm_style, width=8)
        self.cb_evt_font_weight = ttk.Combobox(
            frm_style, width=12, values=["normal", "semibold", "bold"]
        )
        self.et_evt_max_width = tk.Entry(frm_style, width=10)
        self.et_evt_line_height = tk.Entry(frm_style, width=10)
        self.cb_evt_halign = ttk.Combobox(
            frm_style, width=10, values=["left", "center", "right"]
        )
        self.cb_evt_valign = ttk.Combobox(
            frm_style, width=10, values=["top", "middle", "bottom"]
        )
        self.et_evt_font_path = tk.Entry(frm_style, width=25)

        self.et_evt_text_color = tk.Entry(frm_style, width=10)
        self.et_evt_date_color = tk.Entry(frm_style, width=10)
        self.et_evt_border_color = tk.Entry(frm_style, width=10)
        self.et_evt_line_spacing = tk.Entry(frm_style, width=8)

        row = 0
        ttk.Label(frm_style, text="X:").grid(row=row, column=0)
        self.et_evt_x.grid(row=row, column=1)
        ttk.Label(frm_style, text="Y:").grid(row=row, column=2)
        self.et_evt_y.grid(row=row, column=3)
        row += 1

        ttk.Label(frm_style, text="Font Size:").grid(row=row, column=0)
        self.et_evt_font_size.grid(row=row, column=1)
        ttk.Label(frm_style, text="Font Weight:").grid(row=row, column=2)
        self.cb_evt_font_weight.grid(row=row, column=3)
        row += 1

        ttk.Label(frm_style, text="Max Width:").grid(row=row, column=0)
        self.et_evt_max_width.grid(row=row, column=1)
        ttk.Label(frm_style, text="Line Height:").grid(row=row, column=2)
        self.et_evt_line_height.grid(row=row, column=3)
        row += 1

        ttk.Label(frm_style, text="H Align:").grid(row=row, column=0)
        self.cb_evt_halign.grid(row=row, column=1)
        ttk.Label(frm_style, text="V Align:").grid(row=row, column=2)
        self.cb_evt_valign.grid(row=row, column=3)
        row += 1

        ttk.Label(frm_style, text="Font File:").grid(row=row, column=0)
        self.et_evt_font_path.grid(row=row, column=1)

        def browse_evt_font():
            path = filedialog.askopenfilename(
                filetypes=[("Font Files", "*.ttf;*.otf")]
            )
            if path:
                self.et_evt_font_path.delete(0, tk.END)
                self.et_evt_font_path.insert(0, path)

        ttk.Button(frm_style, text="Browse", command=browse_evt_font).grid(
            row=row, column=2
        )
        row += 1

        ttk.Label(frm_style, text="Text Color:").grid(row=row, column=0)
        self.et_evt_text_color.grid(row=row, column=1)

        def pick_evt_text_color():
            c = colorchooser.askcolor()
            if c and c[1]:
                self.et_evt_text_color.delete(0, tk.END)
                self.et_evt_text_color.insert(0, c[1])

        ttk.Button(frm_style, text="Pick", command=pick_evt_text_color).grid(
            row=row, column=2
        )
        row += 1

        ttk.Label(frm_style, text="Date Color:").grid(row=row, column=0)
        self.et_evt_date_color.grid(row=row, column=1)

        def pick_evt_date_color():
            c = colorchooser.askcolor()
            if c and c[1]:
                self.et_evt_date_color.delete(0, tk.END)
                self.et_evt_date_color.insert(0, c[1])

        ttk.Button(frm_style, text="Pick", command=pick_evt_date_color).grid(
            row=row, column=2
        )
        row += 1

        ttk.Label(frm_style, text="Border Color:").grid(row=row, column=0)
        self.et_evt_border_color.grid(row=row, column=1)

        def pick_evt_border_color():
            c = colorchooser.askcolor()
            if c and c[1]:
                self.et_evt_border_color.delete(0, tk.END)
                self.et_evt_border_color.insert(0, c[1])

        ttk.Button(frm_style, text="Pick", command=pick_evt_border_color).grid(
            row=row, column=2
        )
        row += 1

        ttk.Label(frm_style, text="Event Line Spacing (px):").grid(
            row=row, column=0
        )
        self.et_evt_line_spacing.grid(row=row, column=1)
        row += 1

        def save_evt_style(_=None):
            text_col = self.et_evt_text_color.get().strip() or "#000000"
            date_col = self.et_evt_date_color.get().strip() or "#ff0000"
            border_col = self.et_evt_border_color.get().strip()

            style = {
                "x": int(self.et_evt_x.get() or 0),
                "y": int(self.et_evt_y.get() or 0),
                "font_size": int(self.et_evt_font_size.get() or 20),
                "font_weight": self.cb_evt_font_weight.get() or "normal",
                "max_width": int(self.et_evt_max_width.get() or 300),
                "line_height": float(self.et_evt_line_height.get() or 1.2),
                "h_align": self.cb_evt_halign.get() or "left",
                "v_align": self.cb_evt_valign.get() or "top",
                "font_path": self.et_evt_font_path.get().strip(),
                "text_color": text_col,
                "color": text_col,
                "date_color": date_col,
                "border_color": border_col or None,
            }
            self.product_config["calendar_event_text_style"] = style
            self.product_config["calendar_event_text_line_spacing"] = int(
                self.et_evt_line_spacing.get() or 4
            )

        for w in [
            self.et_evt_x,
            self.et_evt_y,
            self.et_evt_font_size,
            self.et_evt_max_width,
            self.et_evt_line_height,
            self.et_evt_font_path,
            self.et_evt_text_color,
            self.et_evt_date_color,
            self.et_evt_border_color,
            self.et_evt_line_spacing,
        ]:
            w.bind("<KeyRelease>", save_evt_style)

        self.cb_evt_font_weight.bind("<<ComboboxSelected>>", save_evt_style)
        self.cb_evt_halign.bind("<<ComboboxSelected>>", save_evt_style)
        self.cb_evt_valign.bind("<<ComboboxSelected>>", save_evt_style)

        # load existing
        st = self.product_config.get("calendar_event_text_style", {}) or {}
        self.et_evt_x.insert(0, st.get("x", 0))
        self.et_evt_y.insert(0, st.get("y", 0))
        self.et_evt_font_size.insert(0, st.get("font_size", 20))
        self.cb_evt_font_weight.set(st.get("font_weight", "normal"))
        self.et_evt_max_width.insert(0, st.get("max_width", 300))
        self.et_evt_line_height.insert(0, st.get("line_height", 1.2))
        self.cb_evt_halign.set(st.get("h_align", "left"))
        self.cb_evt_valign.set(st.get("v_align", "top"))
        self.et_evt_font_path.insert(0, st.get("font_path", ""))

        self.et_evt_text_color.insert(0, st.get("text_color", "#000000"))
        self.et_evt_date_color.insert(0, st.get("date_color", "#ff0000"))
        self.et_evt_border_color.insert(0, st.get("border_color", "") or "")
        self.et_evt_line_spacing.insert(
            0, self.product_config.get("calendar_event_text_line_spacing", 4)
        )





    

    def upload_calendar_font(self):
        path = filedialog.askopenfilename(
            title="Choose font", filetypes=[("Font files", "*.ttf *.otf")]
        )
        if path:
            self.product_config["calendar_date_font_path"] = path
            self.lbl_calendar_font.config(text=os.path.basename(path))

    # ---------------------------
    # Standard app functions
    # ---------------------------

    def load_design(self):
        path = filedialog.askopenfilename(
            title="Select design JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.design = json.load(f)
            self.lbl_status.config(text=f"✓ Design loaded: {os.path.basename(path)}")
            self.build_mapping_ui()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load design:\n{e}")

    def load_excel(self):
        path = filedialog.askopenfilename(
            title="Select Excel/CSV",
            filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                self.df = pd.read_csv(path)
            else:
                self.df = pd.read_excel(path)
                self.df = self.df.applymap(
                    lambda x: int(x) if isinstance(x, float) and x.is_integer() else x
                )
            
            self.lbl_status.config(
                text=f"✓ Data: {os.path.basename(path)} • {len(self.df)} rows"
            )
            self.lbl_row_count.config(text=f"{len(self.df)} rows")
            self.populate_tree()
            self.refresh_column_comboboxes()
            self.build_mapping_ui()
            self.refresh_excel_column_dropdowns()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load:\n{e}")

    def select_base_folder(self):
        folder = filedialog.askdirectory(title="Select base folder")
        if folder:
            self.base_folder = folder
            self.lbl_status.config(text=f"✓ Base folder: {os.path.basename(folder)}")

    def select_base_file(self):
        # Behavior depends on top product type selection:
        if self.product_type == "calendar":
            # open multi-select dialog
            files = filedialog.askopenfilenames(
                title="Select calendar base files (Jan->Dec order recommended)",
                filetypes=[
                    ("Images/PDF", "*.png *.jpg *.jpeg *.bmp *.pdf"),
                    ("All", "*.*"),
                ],
            )
            if files:
                self.calendar_base_files = list(files)
                self.product_config["calendar_base_files"] = self.calendar_base_files.copy()
                # also set base_file to first as fallback
                self.base_file = self.calendar_base_files[0] if self.calendar_base_files else ""
                self.lbl_status.config(
                    text=f"✓ Selected {len(self.calendar_base_files)} calendar base files"
                )
        else:
            path = filedialog.askopenfilename(
                title="Select base image/PDF",
                filetypes=[
                    ("Images/PDF", "*.png *.jpg *.jpeg *.bmp *.pdf"),
                    ("All", "*.*"),
                ],
            )
            if path:
                self.base_file = path
                ext = os.path.splitext(path)[1].lower()
                if ext == ".pdf":
                    self.output_format = "pdf"
                elif ext in [".jpg", ".jpeg"]:
                    self.output_format = "jpg"
                else:
                    self.output_format = "png"
                self.lbl_status.config(
                    text=f"✓ Base file: {os.path.basename(path)} • Output: {self.output_format.upper()}"
                )

    def select_calendar_base_files(self):
        files = filedialog.askopenfilenames(
            title="Select calendar base files (Jan->Dec recommended)",
            filetypes=[
                ("Images/PDF", "*.png *.jpg *.jpeg *.bmp *.pdf"),
                ("All", "*.*"),
            ],
        )
        if files:
            detected = []
            unknown = []
            for f in files:
                m = self.detect_month_index(f)
                if m:
                    detected.append((m, f))
                else:
                    unknown.append(f)
            # Sort by month index
            detected.sort(key=lambda x: x[0])
            # Reconstruct list: detected months in order + unknown at end
            new_list = [f for _, f in detected] + unknown

            self.calendar_base_files = new_list
            self.product_config["calendar_base_files"] = self.calendar_base_files.copy()
            self.base_file = self.calendar_base_files[0] if self.calendar_base_files else ""
            self.lbl_status.config(
                text=f"✓ Selected {len(self.calendar_base_files)} calendar base files"
            )
            self.product_config["calendar_base_files"] = new_list
            self.update_calendar_base_display()
            self.refresh_month_thumbnails()

    def select_output_folder(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_folder = folder
            self.lbl_status.config(text=f"✓ Output folder: {os.path.basename(folder)}")

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        if self.df is None:
            self.tree["columns"] = ()
            return

        cols = list(self.df.columns)
        self.tree["columns"] = cols

        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="w", stretch=False)

        for idx, row in self.df.iterrows():
            # use safe_str to avoid NaN/horrible display
            values = [safe_str(row[c]) for c in cols]
            self.tree.insert("", "end", iid=str(idx), values=values)

    def on_row_select(self, event):
        sel = self.tree.selection()
        if not sel:
            self.current_row_index = None
            return
        self.current_row_index = int(sel[0])
        self.lbl_status.config(text=f"✓ Row {self.current_row_index} selected")

    def refresh_column_comboboxes(self):
        cols = list(self.df.columns) if self.df is not None else []
        for cb in [
            getattr(self, "cb_path_folder1", None),
            getattr(self, "cb_path_folder2", None),
            getattr(self, "cb_path_file", None),
            getattr(self, "cb_filename_col", None),
        ]:
            if cb:
                cb["values"] = cols

        # update mapping UI values if needed
        for _key, val in self.slot_vars.items():
            if "var" in val:
                # we only stored the variable; the combobox widget isn't tracked separately,
                # so we'll rebuild mapping UI when design or excel reloads.
                pass

    def generate_photo_path_column(self):
        if self.df is None:
            messagebox.showwarning("Warning", "Load Excel first.")
            return
        if not self.base_folder:
            messagebox.showwarning("Warning", "Select base folder first.")
            return

        col_f1 = self.path_folder1_var.get() or None
        col_f2 = self.path_folder2_var.get() or None
        col_file = self.path_file_var.get() or None
        prefix = self.path_prefix_var.get() or ""
        suffix = self.path_suffix_var.get() or ""
        ext = (self.path_ext_var.get() or ".png").strip()
        outcol = self.path_outcol_var.get().strip() or "IMAGE_PATH"

        if not col_file:
            messagebox.showwarning("Warning", "Select File/Code column.")
            return

        paths = []
        for _, row in self.df.iterrows():
            path_parts = [self.base_folder]
            if col_f1:
                sf = safe_str(row[col_f1])
                if sf:
                    path_parts.append(sf)
            if col_f2:
                sf = safe_str(row[col_f2])
                if sf:
                    path_parts.append(sf)

            filename_core = safe_str(row[col_file])
            filename = f"{prefix}{filename_core}{suffix}"
            if not filename.lower().endswith(ext):
                filename += ext
            path_parts.append(filename)
            paths.append(os.path.normpath(os.path.join(*path_parts)))

        self.df[outcol] = paths
        self.lbl_path_status.config(
            text=f"✓ Generated {outcol} with {len(paths)} values"
        )
        self.populate_tree()

    def build_mapping_ui(self):
        for w in self.slot_rows_frame.winfo_children():
            if w != self.slot_rows_frame.winfo_children()[0]:
                w.destroy()
        try:
            self.no_design_label.destroy()
        except Exception:
            pass

        self.slot_vars.clear()

        if self.design is None or "template" not in self.design:
            self.no_design_label = tk.Label(
                self.slot_rows_frame,
                text="👈 Load JSON template",
                font=("Segoe UI", 10),
                fg=self.colors["text_light"],
                bg=self.colors["bg_white"],
            )
            self.no_design_label.pack(pady=50)
            return

        if self.df is None:
            self.no_design_label = tk.Label(
                self.slot_rows_frame,
                text="👈 Load Excel data",
                font=("Segoe UI", 10),
                fg=self.colors["text_light"],
                bg=self.colors["bg_white"],
            )
            self.no_design_label.pack(pady=50)
            return

        cols = list(self.df.columns)
        tpl = self.design["template"]

        for i, ov in enumerate(tpl.get("overlayImages", [])):
            key = extract_key(ov.get("src", ""))
            desc = f"🖼️ Overlay {i+1}: {key}"
            self._add_slot_row(f"OVL_{i}", desc, key, cols, has_font=False)

        for i, tb in enumerate(tpl.get("textBlocks", [])):
            key = extract_key(tb.get("text", ""))
            desc = f"📝 Text {i+1}: {key}"
            self._add_slot_row(f"TXT_{i}", desc, key, cols, has_font=True)

    def _add_slot_row(self, slot_id, description, key, columns, has_font=False):
        frm = tk.Frame(self.slot_rows_frame, bg=self.colors["bg_white"])
        frm.pack(fill="x", pady=3)

        tk.Label(
            frm,
            text=description,
            anchor="w",
            width=30,
            bg=self.colors["bg_white"],
        ).grid(row=0, column=0, padx=10, pady=5, sticky="w")

        var = tk.StringVar()
        cb = ttk.Combobox(
            frm,
            textvariable=var,
            values=columns,
            width=20,
            state="readonly",
        )
        cb.grid(row=0, column=1, padx=10, pady=5, sticky="w")

        if key in columns:
            var.set(key)

        self.slot_vars[slot_id] = {"var": var, "key": key}

        if has_font:
            self.slot_vars[f"{slot_id}_FONT"] = {"path": None}

            def upload_font():
                path = filedialog.askopenfilename(
                    title="Choose TTF/OTF font file for this text field",
                    filetypes=[("Font files", "*.ttf *.otf")],
                )
                if path:
                    self.slot_vars[f"{slot_id}_FONT"]["path"] = path
                    btn_font.config(text=os.path.basename(path))

            btn_font = tk.Button(
                frm,
                text="Upload Font",
                command=upload_font,
                bg="#e0e7ef",
                font=("Segoe UI", 8),
                relief="flat",
                borderwidth=1,
            )
            btn_font.grid(row=0, column=2, padx=8, pady=5, sticky="w")
        else:
            var_calendar = tk.BooleanVar(value=False)
            self.slot_vars[slot_id]["is_calendar"] = var_calendar
            tk.Checkbutton(
                frm,
                text="Calendar Image",
                variable=var_calendar,
                bg=self.colors["bg_white"],
            ).grid(row=0, column=3, sticky="w", padx=8)

    def parse_excel_date(self, date_str):
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_str, fmt)
            except Exception:
                pass
        return None

    def render_selected_row(self):
        return _merged_row_handler("preview", self=self)

    def start_production(self):
        if self.is_generating:
            messagebox.showwarning("Warning", "Production already running!")
            return
        if self.product_type == "normal" and self.design is None:
            messagebox.showwarning("Warning", "Load design JSON first.")
            return
        if self.df is None:
            messagebox.showwarning("Warning", "Load Excel first.")
            return
        if not self.output_folder:
            messagebox.showwarning("Warning", "Select output folder first.")
            return

        try:
            self.num_workers = int(self.worker_var.get())
        except Exception:
            self.num_workers = cpu_count()

        self.filename_column = self.filename_col_var.get() or None

        # update product_config if calendar
        if self.product_type == "calendar":
            product_config = self.product_config  # <<< ADD THIS LINE

            # update calendar product_config from UI
            self.product_config["calendar_start_x"] = int(
                self.ent_calendar_start_x.get() or 0
            )
            self.product_config["calendar_start_y"] = int(
                self.ent_calendar_start_y.get() or 0
            )
            self.product_config["calendar_cell_width"] = int(
                self.ent_calendar_cell_w.get() or 100
            )
            self.product_config["calendar_cell_height"] = int(
                self.ent_calendar_cell_h.get() or 80
            )
            self.product_config["calendar_date_offset_x"] = int(
                self.ent_calendar_date_off_x.get() or 5
            )
            self.product_config["calendar_date_offset_y"] = int(
                self.ent_calendar_date_off_y.get() or 5
            )
            self.product_config["calendar_date_align"] = self.cb_calendar_align.get()
            self.product_config["calendar_date_font_size"] = int(
                self.ent_calendar_font_size.get() or 18
            )
            self.product_config["calendar_date_fill"] = (
                self.ent_calendar_date_color.get() or "#000000"
            )
            self.product_config["calendar_year"] = int(
                self.ent_calendar_year.get() or 2025
            )
            self.product_config["calendar_show_borders"] = (
                self.calendar_show_borders.get()
            )
            self.product_config["calendar_base_files"] = self.product_config.get(
                "calendar_base_files", []
            )

            # if no calendar base files selected, fallback to single base_file if set
            if not self.product_config["calendar_base_files"] and self.base_file:
                self.product_config["calendar_base_files"] = [self.base_file]

        confirm = messagebox.askyesno(
            "Start Production",
            (
                f"Generate outputs at 300 DPI ({self.output_format.upper()}).\n\n"
                f"Product Type: {'Calendar (12 outputs per row)' if self.product_type=='calendar' else 'Normal'}\n"
                f"Rows: {len(self.df)}\nWorkers: {self.num_workers}\n\nProceed?"
            ),
            icon="question",
        )
        if not confirm:
            return

        self.is_generating = True
        self.stop_event.clear()
        self.btn_production.config(state="disabled", text="⏳ Generating...")
        self.btn_abort.config(state="normal")
        self.progress_frame.pack(fill="x", padx=20, pady=(10, 0), before=self.canvas.master)

        thread = Thread(target=self.generate_all_images_parallel, daemon=True)
        thread.start()

    def abort_production(self):
        if self.is_generating:
            self.stop_event.set()
            self.lbl_status.config(text="⚠️ Aborting production...")

    def generate_all_images_parallel(self):
        total_rows = len(self.df)
        # total outputs is rows * 12 for calendar mode, else rows * 1
        total_outputs = total_rows * (12 if self.product_type == "calendar" else 1)
        total = total_outputs

        self.progress_bar["maximum"] = total
        self.progress_bar["value"] = 0

        # Prepare slot_vars for serializable form
        serializable_slot_vars = {}
        for key, val in self.slot_vars.items():
            if "var" in val:
                serializable_slot_vars[key] = {
                    "value": val["var"].get(),
                    "key": val.get("key", ""),
                }
            elif "path" in val:
                serializable_slot_vars[key] = {"path": val["path"]}

        tasks = []
        for idx, row in self.df.iterrows():
            if self.stop_event.is_set():
                break
            # base_file_or_list param: for calendar we pass list of files (calendar_base_files) else single base_file
            base_file_or_list = (
                self.calendar_base_files.copy()
                if (self.product_type == "calendar" and self.calendar_base_files)
                else (self.base_file or "")
            )
            tasks.append(
                (
                    idx,
                    row.to_dict(),
                    self.design,
                    serializable_slot_vars,
                    self.base_folder,
                    base_file_or_list,
                    self.output_folder,
                    self.output_format,
                    list(self.df.columns),
                    self.filename_column,
                    self.product_config.copy(),
                )
            )

        success_count = 0  # counts files produced
        error_count = 0
        skipped_count = 0
        aborted = False
        error_log = []

        try:
            with ThreadPool(processes=self.num_workers) as pool:
                for i, result in enumerate(pool.imap_unordered(process_single_row_worker, tasks)):
                    if self.stop_event.is_set():
                        aborted = True
                        pool.terminate()
                        break

                    try:
                        # result expected: (idx, success, error, produced)
                        if len(result) == 4:
                            idx, success, error, produced = result
                        else:
                            # defensive fallback
                            idx = result[0] if len(result) > 0 else i
                            success = result[1] if len(result) > 1 else False
                            error = result[2] if len(result) > 2 else None
                            produced = result[3] if len(result) > 3 else (
                                1 if success else 0
                            )
                    except Exception:
                        error_log.append(f"Bad worker result at index {i}: {result}")
                        error_count += 1
                        produced = 0
                        continue

                    if success:
                        success_count += produced
                    else:
                        # failed row: could have produced partial files (produced may be >0)
                        if produced > 0:
                            # count partial successes
                            success_count += produced

                        if error and "Missing images:" in error:
                            skipped_count += 1
                            error_log.append(f"Row {idx} SKIPPED: {error}")
                        else:
                            error_count += 1
                            error_log.append(f"Row {idx} ERROR: {error}")

                    # progress update: increment by produced (might be 0..12)
                    self.after(
                        0,
                        lambda add=produced: self.progress_bar.step(add),
                    )
                    # update progress label showing files produced / total
                    self.after(
                        0,
                        lambda done=success_count, tot=total: self.lbl_progress.config(
                            text=(
                                f"Produced {done} of {tot} outputs... "
                                f"({self.num_workers} workers • 300 DPI {self.output_format.upper()})"
                            )
                        ),
                    )

        except Exception as e:
            print(f"Pool error: {e}")
            aborted = True

        self.after(
            0,
            self.production_complete,
            success_count,
            error_count,
            skipped_count,
            aborted,
            error_log,
        )

    def production_complete(self, success, errors, skipped, aborted, error_log):
        self.is_generating = False
        self.btn_production.config(state="normal", text="🚀 Start Production")
        self.btn_abort.config(state="disabled")
        self.progress_frame.pack_forget()

        if aborted:
            msg = f"⚠️ Production aborted!\n\n{success} images generated before stopping"
        else:
            msg = f"✓ Production complete!\n\n{success} outputs produced"

        if self.product_type == "calendar":
            msg += " (calendar mode)"
        if skipped > 0:
            msg += f"\n{skipped} files skipped (missing images)"
        if errors > 0:
            msg += f"\n{errors} errors"

        if error_log:
            log_path = os.path.join(self.output_folder, "production_log.txt")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(error_log))
            msg += f"\n\nSee {log_path} for details"

        self.lbl_status.config(text=msg.replace("\n", " • "))
        messagebox.showinfo("Production Complete" if not aborted else "Production Aborted", msg)

    def render_row_to_image(self, row):
        if self.base_file and str(self.base_file).lower().endswith(".pdf"):
            return self.render_row_to_pdf(row)
        else:
            return self.render_row_to_pil_image(row)

    def render_row_to_pdf(self, row, output_path=None):
        t = json.loads(json.dumps(self.design))
        tpl = t["template"]
        ctx = {str(c): row[c] for c in self.df.columns}

        doc = fitz.open(self.base_file)
        page = doc.load_page(0)

        # overlays
        for i, ov in enumerate(tpl.get("overlayImages", [])):
            slot_id = f"OVL_{i}"
            if slot_id not in self.slot_vars:
                continue

            col = self.slot_vars[slot_id]["var"].get()
            if not col or col not in ctx:
                continue

            path = str(ctx[col]).strip()
            if not path:
                continue

            x = int(ov.get("x", 0))
            y = int(ov.get("y", 0))
            w = int(ov.get("width", 0))
            h = int(ov.get("height", 0))
            rect = fitz.Rect(x, y, x + w, y + h)

            try:
                if self._is_qr_data(path):
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_H,
                        box_size=10,
                        border=0,
                    )
                    qr.add_data(path)
                    qr.make(fit=True)
                    img = qr.make_image(
                        fill_color="#ffffff", back_color="transparent"
                    ).convert("RGBA")
                    img_bytes = io.BytesIO()
                    img.save(img_bytes, format="PNG")
                    page.insert_image(rect, stream=img_bytes.getvalue(), overlay=True)
                elif path.lower().startswith("http"):
                    response = requests.get(path, timeout=10)
                    response.raise_for_status()
                    page.insert_image(rect, stream=response.content, overlay=True)
                else:
                    if os.path.exists(path):
                        page.insert_image(rect, filename=path, overlay=True)
            except Exception as e:
                print(f"Error inserting overlay image {i}: {e}")

        # text blocks
        for i, tb in enumerate(tpl.get("textBlocks", [])):
            slot_id = f"TXT_{i}"
            if slot_id not in self.slot_vars:
                continue

            col = self.slot_vars[slot_id]["var"].get()
            text = "" if not col or col not in ctx else str(ctx.get(col, ""))
            if not text:
                continue

            x = int(tb.get("x", 0))
            y = int(tb.get("y", 0))
            fontsize = int(tb.get("fontSize", 30))
            fontfamily = tb.get("fontFamily", "helvetica").lower()
            fillcolor = tb.get("fill", "#000000")

            color = tuple(
                int(fillcolor.lstrip("#")[i : i + 2], 16) / 255.0 for i in (0, 2, 4)
            )

            fontslot = f"{slot_id}_FONT"
            custom_font_path = None
            if fontslot in self.slot_vars:
                custom_font_path = self.slot_vars[fontslot]["path"] or None

            try:
                if custom_font_path and os.path.exists(custom_font_path):
                    fontname = f"CustomFont{i}"
                    page.insert_font(fontname=fontname, fontfile=custom_font_path)
                    page.insert_text(
                        (x, y + fontsize),
                        text,
                        fontname=fontname,
                        fontsize=fontsize,
                        color=color,
                    )
                else:
                    font_map = {
                        "helvetica": "helv",
                        "arial": "helv",
                        "times": "times",
                        "times new roman": "times",
                        "courier": "cour",
                        "courier new": "cour",
                        "symbol": "symb",
                        "zapfdingbats": "zadb",
                    }
                    pymupdf_font = font_map.get(fontfamily, "helv")
                    page.insert_text(
                        (x, y + fontsize),
                        text,
                        fontname=pymupdf_font,
                        fontsize=fontsize,
                        color=color,
                    )
            except Exception as e:
                print(f"Error inserting text {i}: {e}")
                try:
                    page.insert_text(
                        (x, y + fontsize),
                        text,
                        fontname="helv",
                        fontsize=fontsize,
                        color=color,
                    )
                except Exception as e2:
                    print(f"Fallback also failed for text {i}: {e2}")

        if output_path:
            doc.save(output_path, garbage=4, deflate=True)
            doc.close()
            return None

        target_size = (
            int(tpl.get("width", 1200)),
            int(tpl.get("height", 630)),
        )
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=True)
        img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        img = img.resize(target_size, Image.LANCZOS)
        doc.close()
        return img

    def render_row_to_pil_image(self, row):
        t = json.loads(json.dumps(self.design))
        tpl = t["template"]

        width = int(tpl.get("width", 1200))
        height = int(tpl.get("height", 630))

        base_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ctx = {str(c): row[c] for c in self.df.columns}

        # behind overlays
        for i, ov in enumerate(tpl.get("overlayImages", [])):
            if not ov.get("behindBackground", False):
                continue
            self._draw_overlay(base_img, ov, i, ctx)

        # background
        if self.base_file and os.path.exists(self.base_file):
            bg_img = Image.open(self.base_file).convert("RGBA")
            bg_img = bg_img.resize((width, height), Image.LANCZOS)
            base_img.alpha_composite(bg_img, dest=(0, 0))
        else:
            white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
            base_img.alpha_composite(white, dest=(0, 0))

        # front overlays
        for i, ov in enumerate(tpl.get("overlayImages", [])):
            if ov.get("behindBackground", False):
                continue
            self._draw_overlay(base_img, ov, i, ctx)

        # text
        draw = ImageDraw.Draw(base_img)
        for i, tb in enumerate(tpl.get("textBlocks", [])):
            self._draw_text(draw, base_img, tb, i, ctx)

        return base_img

    def _is_qr_data(self, data_str):
        return is_qr_data_static(data_str)

    def _draw_overlay(self, base_img, ov, i, ctx):
        slot_id = f"OVL_{i}"
        if slot_id not in self.slot_vars:
            return

        col = self.slot_vars[slot_id]["var"].get()
        if not col or col not in ctx:
            return

        path = str(ctx[col]).strip()
        if not path:
            return

        if self._is_qr_data(path):
            try:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_H,
                    box_size=10,
                    border=0,
                )
                qr.add_data(path)
                qr.make(fit=True)
                img = qr.make_image(
                    fill_color="#ffffff", back_color="transparent"
                ).convert("RGBA")
            except Exception as e:
                print(f"Error generating QR code for overlay {i}: {e}")
                return
        else:
            try:
                if path.lower().startswith("http://") or path.lower().startswith("https://"):
                    response = requests.get(path, timeout=10)
                    response.raise_for_status()
                    image_data = io.BytesIO(response.content)
                    img = Image.open(image_data).convert("RGBA")
                else:
                    if not os.path.exists(path):
                        print(f"Image file not found: {path}")
                        return
                    img = Image.open(path).convert("RGBA")
            except Exception as e:
                print(f"Error loading image for overlay {i}: {e}")
                return

        w, h = ov.get("width"), ov.get("height")
        if w and h:
            img = img.resize((int(w), int(h)), Image.LANCZOS)

        opacity = ov.get("opacity", 1.0)
        if opacity < 1.0:
            img.putalpha(Image.eval(img.split()[3], lambda a: int(a * opacity)))

        rot = ov.get("rotation", 0)
        if rot:
            img = img.rotate(-rot, expand=True)

        base_img.alpha_composite(
            img,
            dest=(int(ov.get("x", 0)), int(ov.get("y", 0))),
        )

    def _draw_text(self, draw, base_img, tb, i, ctx):
        slot_id = f"TXT_{i}"
        if slot_id not in self.slot_vars:
            return

        col = self.slot_vars[slot_id]["var"].get()
        text = "" if not col or col not in ctx else str(ctx.get(col, ""))
        if not text:
            return

        fontsize = int(tb.get("fontSize", 30))
        fontfamily = tb.get("fontFamily", "arial")
        fontstyle = tb.get("fontStyle", "normal")

        fontslot = f"{slot_id}_FONT"
        custom_font_path = None
        if fontslot in self.slot_vars:
            custom_font_path = self.slot_vars[fontslot]["path"] or None

        try:
            if custom_font_path and os.path.exists(custom_font_path):
                font = ImageFont.truetype(custom_font_path, fontsize)
            elif fontfamily.lower() == "arial":
                if "bold" in fontstyle.lower() and "italic" in fontstyle.lower():
                    font = ImageFont.truetype("arialbi.ttf", fontsize)
                elif "bold" in fontstyle.lower():
                    font = ImageFont.truetype("arialbd.ttf", fontsize)
                elif "italic" in fontstyle.lower():
                    font = ImageFont.truetype("ariali.ttf", fontsize)
                else:
                    font = ImageFont.truetype("arial.ttf", fontsize)
            else:
                font = ImageFont.truetype(f"{fontfamily}.ttf", fontsize)
        except Exception:
            font = ImageFont.load_default()

        x = int(tb.get("x", 0))
        y = int(tb.get("y", 0))
        align = tb.get("align", "left")

        # NEW: Text wrapping logic
        max_width = int(tb.get("maxWidth", tb.get("width", 0) or 0))
        vertical_align = tb.get("verticalAlign", "top")
        line_height_factor = float(tb.get("lineHeight", 1.0))

        # Split into lines based on max_width
        if max_width > 0:
            words = text.split()
            lines = []
            current = ""
            for w in words:
                test = (current + " " + w).strip()
                tw = draw.textlength(test, font=font)
                if tw <= max_width or not current:
                    current = test
                else:
                    lines.append(current)
                    current = w
            if current:
                lines.append(current)
        else:
            lines = [text]

        # Precompute width/height per line
        line_metrics = []
        for ln in lines:
            bbox = draw.textbbox((0, 0), ln, font=font)
            w = bbox[2] - bbox[0]
            h = (bbox[3] - bbox[1]) * line_height_factor
            line_metrics.append((ln, w, h))

        block_height = sum(h for _, _, h in line_metrics)

        # Vertical alignment
        if vertical_align == "middle":
            y = int(y - block_height / 2)
        elif vertical_align == "bottom":
            y = int(y - block_height)

        fillcolor = tb.get("fill", "#000000")
        rotation = tb.get("rotation", 0)
        strokewidth = int(tb.get("strokeWidth", 0))
        strokecolor = tb.get("stroke", "#000000")
        shadowcolor = tb.get("shadowColor")
        shadowblur = int(tb.get("shadowBlur", 0))
        shadowoffsetx = int(tb.get("shadowOffsetX", 0))
        shadowoffsety = int(tb.get("shadowOffsetY", 0))
        opacity = tb.get("opacity", 1.0)

        if rotation != 0:
            # Rotated text with wrapping
            max_line_w = max(w for _, w, _ in line_metrics)
            total_w = int(max_line_w + 200)
            total_h = int(block_height + 200)
            txtlayer = Image.new("RGBA", (total_w, total_h), (255, 255, 255, 0))
            txtdraw = ImageDraw.Draw(txtlayer)

            cy = 100
            for ln, lw, lh in line_metrics:
                # Horizontal align inside layer
                if align == "center":
                    lx = 100 + int((max_line_w - lw) / 2)
                elif align == "right":
                    lx = 100 + int(max_line_w - lw)
                else:
                    lx = 100

                if shadowcolor and shadowblur > 0:
                    txtdraw.text(
                        (lx + shadowoffsetx, cy + shadowoffsety),
                        ln,
                        font=font,
                        fill=shadowcolor,
                    )

                txtdraw.text(
                    (lx, cy),
                    ln,
                    font=font,
                    fill=fillcolor,
                    stroke_width=strokewidth,
                    stroke_fill=strokecolor,
                )
                cy += int(lh)

            if opacity < 1.0:
                alpha = txtlayer.split()[3]
                alpha = alpha.point(lambda a: int(a * opacity))
                txtlayer.putalpha(alpha)

            txtlayer = txtlayer.rotate(-rotation, expand=True)
            base_img.alpha_composite(txtlayer, dest=(x - 100, y - 100))
        else:
            # No rotation: draw directly on base image with wrapping
            cy = y
            for ln, lw, lh in line_metrics:
                lx = x
                if align == "center":
                    lx = int(x - lw / 2)
                elif align == "right":
                    lx = int(x - lw)

                if shadowcolor and shadowblur > 0:
                    draw.text(
                        (lx + shadowoffsetx, cy + shadowoffsety),
                        ln,
                        font=font,
                        fill=shadowcolor,
                    )

                if opacity < 1.0:
                    txtlayer = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
                    txtdraw = ImageDraw.Draw(txtlayer)
                    txtdraw.text(
                        (lx, cy),
                        ln,
                        font=font,
                        fill=fillcolor,
                        stroke_width=strokewidth,
                        stroke_fill=strokecolor,
                    )
                    alpha = txtlayer.split()[3]
                    alpha = alpha.point(lambda a: int(a * opacity))
                    txtlayer.putalpha(alpha)
                    base_img.alpha_composite(txtlayer)
                else:
                    draw.text(
                        (lx, cy),
                        ln,
                        font=font,
                        fill=fillcolor,
                        stroke_width=strokewidth,
                        stroke_fill=strokecolor,
                    )
                cy += int(lh)

    def show_image_fitted(self, img: Image.Image):
        self.canvas.delete("all")
        self.canvas.update_idletasks()

        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 1:
            cw, ch = 700, 700

        scale = min(cw / img.width, ch / img.height) * 0.9
        new_w, new_h = int(img.width * scale), int(img.height * scale)

        fitted = img.resize((new_w, new_h), Image.LANCZOS)
        self.preview_img_tk = ImageTk.PhotoImage(fitted)
        self.canvas.create_image(
            (cw - new_w) // 2,
            (ch - new_h) // 2,
            anchor="nw",
            image=self.preview_img_tk,
        )


# ---------------------------
# Run app
# ---------------------------

if __name__ == "__main__":
    app = TemplateDesignerApp()
    app.mainloop()
