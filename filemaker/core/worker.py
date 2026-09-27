"""Production worker: renders and saves every output for ONE data row.

Runs inside the production thread pool. Must stay free of tkinter.

Task tuple (built by services.production):
    (idx, row_dict, design, slot_vars, base_folder, base_file_or_list,
     output_folder, output_format, df_columns, filename_column, product_config)

Returns (idx, success, error_message_or_None, outputs_produced).
"""
import io
import os

import pandas as pd
import pymupdf as fitz

from ..utils.text import ensure_dir
from .calendar_render import (
    month_output_basename,
    render_calendar_month,
    resolve_month_base,
)
from .events import build_event_icons, build_event_texts
from .render_static import (
    render_row_to_pdf_static,
    render_row_to_pil_image_static,
    validate_row_images,
)

OUTPUT_DPI = (300, 300)


def _row_base_name(row, filename_column, fallback):
    if filename_column and filename_column in row and str(row[filename_column]).strip():
        return os.path.splitext(str(row[filename_column]).strip())[0]
    return fallback


def _save_image_as_pdf(img, path):
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG", dpi=OUTPUT_DPI)
    img_bytes.seek(0)
    doc = fitz.open()
    rect = fitz.Rect(0, 0, img.width, img.height)
    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(rect, stream=img_bytes.getvalue())
    doc.save(path, deflate=True)
    doc.close()


def _process_calendar_row(idx, row, design, slot_vars, base_folder, base_file_or_list,
                          output_folder, df_columns, filename_column, product_config):
    base_name = _row_base_name(row, filename_column, f"row{idx}")
    ensure_dir(output_folder)

    event_icons = build_event_icons(row, product_config)
    event_texts = build_event_texts(row, product_config)

    errors = []
    produced = 0
    for month in range(1, 13):
        base_path = resolve_month_base(month, product_config, base_file_or_list)
        if not base_path or not os.path.exists(base_path):
            errors.append(f"Missing base file for month {month}: {base_path}")
            continue
        try:
            img, ext = render_calendar_month(
                row, month, base_path, design, slot_vars, base_folder,
                df_columns, product_config, event_icons, event_texts,
            )
            out_base = month_output_basename(base_name, month)
            if ext == ".pdf":
                _save_image_as_pdf(img, os.path.join(output_folder, f"{out_base}.pdf"))
            else:
                img.save(os.path.join(output_folder, f"{out_base}.png"), "PNG", dpi=OUTPUT_DPI)
            produced += 1
        except Exception as e:
            errors.append(f"Month {month} render error: {e}")

    if errors:
        return (idx, False, "; ".join(errors), produced)
    return (idx, True, None, produced)


def _pick_single_base(base_file_or_list):
    if isinstance(base_file_or_list, str):
        return base_file_or_list
    if isinstance(base_file_or_list, (list, tuple)) and base_file_or_list:
        return base_file_or_list[0]
    return ""


def _process_normal_row(idx, row, design, slot_vars, base_folder, base_file_or_list,
                        output_folder, output_format, df_columns, filename_column):
    missing = validate_row_images(row.to_dict(), design, slot_vars, df_columns)
    if missing:
        return (idx, False, f"Missing images: {', '.join(missing)}", 0)

    if filename_column and filename_column in row:
        base_name = os.path.splitext(str(row[filename_column]).strip())[0]
    else:
        base_name = f"output_{idx}"

    base_file = _pick_single_base(base_file_or_list)
    try:
        if output_format == "pdf":
            render_row_to_pdf_static(
                row, os.path.join(output_folder, f"{base_name}.pdf"),
                design, slot_vars, base_file, df_columns,
            )
        else:
            img = render_row_to_pil_image_static(
                row, design, slot_vars, base_folder, base_file, df_columns
            )
            if output_format == "jpg":
                img.convert("RGB").save(
                    os.path.join(output_folder, f"{base_name}.jpg"),
                    "JPEG", dpi=OUTPUT_DPI, quality=95,
                )
            else:
                img.save(os.path.join(output_folder, f"{base_name}.png"), "PNG", dpi=OUTPUT_DPI)
        return (idx, True, None, 1)
    except Exception as e:
        return (idx, False, str(e), 0)


def process_row(task):
    idx = task[0] if task else None
    try:
        (
            idx, row_dict, design, slot_vars, base_folder, base_file_or_list,
            output_folder, output_format, df_columns, filename_column, product_config,
        ) = task
        row = pd.Series(row_dict)

        if (product_config or {}).get("type", "").lower() == "calendar":
            return _process_calendar_row(
                idx, row, design, slot_vars, base_folder, base_file_or_list,
                output_folder, df_columns, filename_column, product_config,
            )
        return _process_normal_row(
            idx, row, design, slot_vars, base_folder, base_file_or_list,
            output_folder, output_format, df_columns, filename_column,
        )
    except Exception as e:
        return (idx, False, str(e), 0)
