"""Month-grid calendar overlay image generator."""
import os
import calendar as pycalendar
from PIL import Image, ImageDraw, ImageFont


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

