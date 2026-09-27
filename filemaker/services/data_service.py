"""Loading data tables and design files, and building field mappings."""
from __future__ import annotations

import json
import os

import pandas as pd

from ..models.project import KIND_IMAGE, KIND_TEXT, FieldMapping
from ..utils.text import extract_key

DATA_FILETYPES = [("Spreadsheets", "*.xlsx *.xls *.csv"), ("All files", "*.*")]
DESIGN_FILETYPES = [("Design JSON", "*.json"), ("All files", "*.*")]
ARTWORK_FILETYPES = [("Images / PDF", "*.png *.jpg *.jpeg *.bmp *.pdf"), ("All files", "*.*")]
IMAGE_FILETYPES = [("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")]
FONT_FILETYPES = [("Fonts", "*.ttf *.otf"), ("All files", "*.*")]


def load_table(path: str) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        return pd.read_csv(path)
    df = pd.read_excel(path)
    # Excel stores whole numbers as floats (5 -> 5.0); keep them as ints so
    # they render and name files the way they appear in the sheet.
    return df.map(lambda x: int(x) if isinstance(x, float) and x.is_integer() else x)


def load_design(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        design = json.load(f)
    if not isinstance(design, dict) or "template" not in design:
        raise ValueError("This JSON has no \"template\" section - is it a design export?")
    return design


def design_summary(design: dict | None) -> str:
    if not design:
        return ""
    tpl = design.get("template", {})
    return (
        f"{tpl.get('width', '?')}×{tpl.get('height', '?')} px  ·  "
        f"{len(tpl.get('overlayImages', []))} images  ·  "
        f"{len(tpl.get('textBlocks', []))} text blocks"
    )


def build_mappings(design: dict | None, previous: list | None = None) -> list:
    """One FieldMapping per overlay/text slot. Keeps earlier choices for slots
    whose key is unchanged (e.g. when re-loading an edited design)."""
    if not design:
        return []
    prev = {(m.slot_id, m.key): m for m in (previous or [])}
    tpl = design.get("template", {})
    mappings = []

    for i, ov in enumerate(tpl.get("overlayImages", [])):
        key = extract_key(ov.get("src", ""))
        m = FieldMapping(
            slot_id=f"OVL_{i}", kind=KIND_IMAGE, index=i, key=key,
            month_specific=bool(ov.get("calendar_image", True)),
        )
        old = prev.get((m.slot_id, key))
        if old:
            m.column, m.month_specific = old.column, old.month_specific
        mappings.append(m)

    for i, tb in enumerate(tpl.get("textBlocks", [])):
        key = extract_key(tb.get("text", ""))
        m = FieldMapping(slot_id=f"TXT_{i}", kind=KIND_TEXT, index=i, key=key)
        old = prev.get((m.slot_id, key))
        if old:
            m.column, m.font_path = old.column, old.font_path
        mappings.append(m)

    return mappings


def auto_map(mappings: list, columns: list) -> int:
    """Fill empty mappings whose key matches a column (exact, then
    case-insensitive). Returns how many were filled."""
    by_lower = {str(c).strip().lower(): c for c in columns}
    filled = 0
    for m in mappings:
        if m.column and m.column in columns:
            continue
        if m.key in columns:
            m.column = m.key
        elif m.key.strip().lower() in by_lower:
            m.column = by_lower[m.key.strip().lower()]
        else:
            continue
        filled += 1
    return filled


def file_label(path: str) -> str:
    return os.path.basename(path) if path else ""
