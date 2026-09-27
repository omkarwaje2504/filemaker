"""Preview rendering: the exact production code path, for one row (and one
month in calendar mode), returned as an image instead of written to disk."""
from __future__ import annotations

import os
from dataclasses import dataclass

import pymupdf as fitz
from PIL import Image

from ..core.calendar_render import render_calendar_month, resolve_month_base
from ..core.events import build_event_icons, build_event_texts
from ..core.render_static import build_row_pdf_document, render_row_to_pil_image_static
from ..models.project import Project

PDF_PREVIEW_ZOOM = 2.0


class PreviewUnavailable(Exception):
    """Not an error - the project isn't ready to preview yet (message says why)."""


@dataclass
class PreviewRequest:
    """An immutable snapshot, so rendering can happen off the UI thread."""

    is_calendar: bool
    design: dict | None
    slot_vars: dict
    base_file: str
    base_folder: str
    base_file_or_list: object
    df_columns: list
    product_config: dict
    row: object  # pandas Series (a copy)
    month: int

    @classmethod
    def from_project(cls, project: Project, df, row_pos: int, month: int) -> "PreviewRequest":
        return cls(
            is_calendar=project.is_calendar,
            design=project.design_for_render(),
            slot_vars=project.slot_vars(),
            base_file=project.base_file,
            base_folder=project.path_builder.base_folder,
            base_file_or_list=project.base_file_or_list(),
            df_columns=list(df.columns),
            product_config=project.product_config(),
            row=df.iloc[row_pos].copy(),
            month=month,
        )


def render_preview(req: PreviewRequest) -> Image.Image:
    if req.is_calendar:
        return _render_calendar(req)
    return _render_normal(req)


def _render_normal(req: PreviewRequest) -> Image.Image:
    if not req.design:
        raise PreviewUnavailable("Load a design JSON in the Template step to see a preview.")
    if req.base_file and not os.path.exists(req.base_file):
        raise PreviewUnavailable(f"Base artwork not found:\n{req.base_file}")

    if req.base_file.lower().endswith(".pdf"):
        doc = build_row_pdf_document(
            req.row, req.design, req.slot_vars, req.base_file, req.df_columns
        )
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(PDF_PREVIEW_ZOOM, PDF_PREVIEW_ZOOM), alpha=True)
            return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()

    return render_row_to_pil_image_static(
        req.row, req.design, req.slot_vars, req.base_folder, req.base_file, req.df_columns
    )


def _render_calendar(req: PreviewRequest) -> Image.Image:
    base_path = resolve_month_base(req.month, req.product_config, req.base_file_or_list)
    if not base_path:
        raise PreviewUnavailable("Add month artwork in the Calendar step to see a preview.")
    if not os.path.exists(base_path):
        raise PreviewUnavailable(f"Month artwork not found:\n{base_path}")

    img, _ext = render_calendar_month(
        req.row,
        req.month,
        base_path,
        req.design,
        req.slot_vars,
        req.base_folder,
        req.df_columns,
        req.product_config,
        build_event_icons(req.row, req.product_config),
        build_event_texts(req.row, req.product_config),
    )
    return img
