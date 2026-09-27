"""Row renderers shared by production and preview (no tkinter, no `self`).

Two backends:
  * PDF base  -> build_row_pdf_document / render_row_to_pdf_static (vector-safe)
  * image base -> render_row_to_pil_image_static (PIL, 300 DPI output)
"""
import os
import io
import json
import calendar as pycalendar

import pymupdf as fitz
import qrcode
import requests
from PIL import Image, ImageDraw, ImageFont

from ..utils.text import is_qr_data_static, safe_str
from .gradient import draw_text_with_gradient


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


def build_row_pdf_document(row, design, slot_vars, base_file, df_columns):
    """Open the PDF base and draw one row's overlays/text onto page 1.
    Returns the open fitz document; the caller saves or rasterizes it."""
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

    return doc


def render_row_to_pdf_static(row, output_path, design, slot_vars, base_file, df_columns):
    """Render one row onto a PDF base and save it (production path)."""
    doc = build_row_pdf_document(row, design, slot_vars, base_file, df_columns)
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
        if not path:
            # An empty cell would otherwise be treated as QR data and draw
            # a QR code of the empty string.
            return

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

