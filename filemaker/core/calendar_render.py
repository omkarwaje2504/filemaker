"""Render one calendar month for one data row.

Used by BOTH the production worker and the GUI preview, so the preview is
pixel-identical to what production writes for that month.
"""
import os
import json
import calendar as pycalendar
from datetime import datetime

import pymupdf as fitz
from PIL import Image, ImageDraw

from ..utils.text import safe_str
from .calendar_overlay import generate_calendar_overlay_image
from .events import draw_event_text_block
from .render_static import (
    draw_overlay_static,
    draw_text_static,
    render_row_to_pil_image_static,
)

PDF_RASTER_DPI = 300


def resolve_month_base(month, product_config, base_file_or_list):
    """Pick the base artwork for a month.

    Month N uses the Nth calendar base file; if fewer than 12 were given the
    last one is reused. Falls back to the single base file otherwise.
    """
    base_files = product_config.get("calendar_base_files", []) or []
    if isinstance(base_file_or_list, (list, tuple)) and base_file_or_list:
        if month - 1 < len(base_files) and base_files[month - 1]:
            return base_files[month - 1]
        return base_files[-1] if base_files else base_file_or_list[0]
    return base_file_or_list


def _rasterize_pdf_first_page(path):
    doc = fitz.open(path)
    try:
        page = doc.load_page(0)
        zoom = PDF_RASTER_DPI / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def render_calendar_month(
    row,
    month,
    base_path,
    design,
    slot_vars,
    base_folder,
    df_columns,
    product_config,
    event_icons,
    event_texts,
):
    """Return (PIL RGBA image, base extension) for `row` rendered as `month`.

    `row` is a pandas Series; its "__current_month__" is set so month-aware
    overlay images resolve to that month's file.
    """
    row["__current_month__"] = month
    ext = os.path.splitext(base_path)[1].lower()

    if ext == ".pdf":
        base_img = _rasterize_pdf_first_page(base_path)
        if design:
            tpl = json.loads(json.dumps(design)).get("template", {})
            ctx = {str(c): safe_str(row.get(c, "")) for c in df_columns}
            ctx["__current_month__"] = month

            for i, ov in enumerate(tpl.get("overlayImages", [])):
                if ov.get("behindBackground", False):
                    draw_overlay_static(base_img, ov, i, ctx, slot_vars)
            for i, ov in enumerate(tpl.get("overlayImages", [])):
                if not ov.get("behindBackground", False):
                    draw_overlay_static(base_img, ov, i, ctx, slot_vars)

            draw = ImageDraw.Draw(base_img)
            for i, tb in enumerate(tpl.get("textBlocks", [])):
                draw_text_static(draw, base_img, tb, i, ctx, slot_vars)
    elif design:
        base_img = render_row_to_pil_image_static(
            row, design, slot_vars, base_folder, base_path, df_columns
        )
    else:
        base_img = Image.open(base_path).convert("RGBA")

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
        excel_event_date=None,
        event_icons=event_icons,
    )
    base_img.alpha_composite(
        overlay,
        dest=(
            int(product_config.get("calendar_start_x", 0)),
            int(product_config.get("calendar_start_y", 0)),
        ),
    )

    # Event texts for this month, stacked vertically from the style's Y.
    line_spacing = int(product_config.get("calendar_event_text_line_spacing", 4))
    base_y = (product_config.get("calendar_event_text_style", {}) or {}).get("y", 0)
    offset = 0
    for tcfg in event_texts:
        if tcfg.get("month_idx") != month:
            continue
        local_cfg = tcfg.copy()
        local_cfg["y"] = base_y + offset
        used_h = draw_event_text_block(base_img, local_cfg, product_config)
        offset += used_h + line_spacing

    return base_img, ext


def month_output_basename(base_name, month):
    return f"{base_name}_{month:02d}_{pycalendar.month_name[month]}"
