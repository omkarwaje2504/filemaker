"""The Project: every user setting in one serializable object.

The UI edits a Project; the preview and production services read it. Nothing
here touches tkinter, so it can be saved, loaded and tested on its own.
"""
from __future__ import annotations

import copy
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from multiprocessing import cpu_count

MODE_NORMAL = "normal"
MODE_CALENDAR = "calendar"

KIND_IMAGE = "image"
KIND_TEXT = "text"


def _from_dict(cls, data: dict | None):
    """Build a dataclass from a dict, ignoring unknown keys (forward compat)."""
    data = data or {}
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class FieldMapping:
    """One template slot (overlay image or text block) -> one data column."""

    slot_id: str  # "OVL_0" / "TXT_0" - the id the renderer looks up
    kind: str  # KIND_IMAGE | KIND_TEXT
    index: int  # position inside overlayImages / textBlocks
    key: str  # the {{key}} written in the design
    column: str = ""
    font_path: str = ""  # text only
    month_specific: bool = True  # image only: swap in the month's file (calendar)

    @property
    def title(self) -> str:
        kind = "Image" if self.kind == KIND_IMAGE else "Text"
        return f"{kind} {self.index + 1}"


@dataclass
class EventIcon:
    path: str = ""
    excel_column: str = ""
    offset_x: int = 0
    offset_y: int = 0
    scale: float = 0.35


@dataclass
class EventTextStyle:
    x: int = 0
    y: int = 0
    font_size: int = 20
    font_weight: str = "normal"
    max_width: int = 300
    line_height: float = 1.2
    h_align: str = "left"
    v_align: str = "top"
    font_path: str = ""
    text_color: str = "#000000"
    date_color: str = "#ff0000"
    border_color: str = ""
    border_thickness: int = 4
    border_radius: int = 90
    padding: int = 10


@dataclass
class CalendarSettings:
    year: int = field(default_factory=lambda: datetime.now().year)
    base_files: list = field(default_factory=list)  # index 0 = January
    start_x: int = 0
    start_y: int = 0
    cell_width: int = 100
    cell_height: int = 80
    show_borders: bool = False
    font_path: str = ""  # default font for event texts
    icons: list = field(default_factory=list)  # list[EventIcon]
    event_text_column: str = ""
    event_text_style: EventTextStyle = field(default_factory=EventTextStyle)
    event_line_spacing: int = 4
    # Date-number settings. The renderer does not currently draw date
    # numbers (the base artwork carries them); kept so saved files keep
    # round-tripping these values unchanged.
    date_offset_x: int = 5
    date_offset_y: int = 5
    date_align: str = "left"
    date_font_size: int = 18
    date_fill: str = "#000000"

    def to_product_config(self, fallback_base_file: str = "") -> dict:
        """The dict shape the core renderer/worker consumes."""
        style = asdict(self.event_text_style)
        style["color"] = style["text_color"]
        style["border_color"] = style["border_color"] or None
        base_files = list(self.base_files)
        if not base_files and fallback_base_file:
            base_files = [fallback_base_file]
        return {
            "type": MODE_CALENDAR,
            "calendar_year": int(self.year),
            "calendar_base_files": base_files,
            "calendar_start_x": int(self.start_x),
            "calendar_start_y": int(self.start_y),
            "calendar_cell_width": int(self.cell_width),
            "calendar_cell_height": int(self.cell_height),
            "calendar_show_borders": bool(self.show_borders),
            "calendar_date_font_path": self.font_path or None,
            "calendar_date_offset_x": int(self.date_offset_x),
            "calendar_date_offset_y": int(self.date_offset_y),
            "calendar_date_align": self.date_align,
            "calendar_date_font_size": int(self.date_font_size),
            "calendar_date_fill": self.date_fill,
            "calendar_event_icons": [asdict(i) for i in self.icons],
            "calendar_event_text_column": self.event_text_column or None,
            "calendar_event_text_style": style,
            "calendar_event_text_line_spacing": int(self.event_line_spacing),
            "calendar_event_texts": [],
        }

    @classmethod
    def from_product_config(cls, pc: dict) -> "CalendarSettings":
        """Read the legacy (v1 template) product_config dict."""
        pc = pc or {}
        style = dict(pc.get("calendar_event_text_style") or {})
        if "text_color" not in style and "color" in style:
            style["text_color"] = style["color"]
        style["border_color"] = style.get("border_color") or ""
        style["font_path"] = style.get("font_path") or ""
        return cls(
            year=int(pc.get("calendar_year") or datetime.now().year),
            base_files=list(pc.get("calendar_base_files") or []),
            start_x=int(pc.get("calendar_start_x", 0) or 0),
            start_y=int(pc.get("calendar_start_y", 0) or 0),
            cell_width=int(pc.get("calendar_cell_width", 100) or 100),
            cell_height=int(pc.get("calendar_cell_height", 80) or 80),
            show_borders=bool(pc.get("calendar_show_borders", False)),
            font_path=pc.get("calendar_date_font_path") or "",
            icons=[_from_dict(EventIcon, i) for i in pc.get("calendar_event_icons") or []],
            event_text_column=pc.get("calendar_event_text_column") or "",
            event_text_style=_from_dict(EventTextStyle, style),
            event_line_spacing=int(pc.get("calendar_event_text_line_spacing", 4) or 4),
            date_offset_x=int(pc.get("calendar_date_offset_x", 5) or 0),
            date_offset_y=int(pc.get("calendar_date_offset_y", 5) or 0),
            date_align=pc.get("calendar_date_align") or "left",
            date_font_size=int(pc.get("calendar_date_font_size", 18) or 18),
            date_fill=pc.get("calendar_date_fill") or "#000000",
        )


@dataclass
class PathBuilderSettings:
    base_folder: str = ""
    folder1_column: str = ""
    folder2_column: str = ""
    file_column: str = ""
    prefix: str = ""
    suffix: str = ""
    extension: str = ".png"
    output_column: str = "IMAGE_PATH"


@dataclass
class Project:
    mode: str = MODE_NORMAL
    data_path: str = ""
    design_path: str = ""
    design: dict | None = None
    base_file: str = ""
    output_folder: str = ""
    output_format: str = ""  # "" = automatic from the base file
    filename_column: str = ""
    workers: int = field(default_factory=cpu_count)
    mappings: list = field(default_factory=list)  # list[FieldMapping]
    calendar: CalendarSettings = field(default_factory=CalendarSettings)
    path_builder: PathBuilderSettings = field(default_factory=PathBuilderSettings)

    # ----- derived values used by preview + production -------------------

    @property
    def is_calendar(self) -> bool:
        return self.mode == MODE_CALENDAR

    def effective_output_format(self) -> str:
        """PDF base -> pdf (vector). Image base -> png/jpg (override or by ext)."""
        ext = os.path.splitext(self.base_file)[1].lower()
        if ext == ".pdf":
            return "pdf"
        if self.output_format in ("png", "jpg"):
            return self.output_format
        if ext in (".jpg", ".jpeg"):
            return "jpg"
        return "png"

    def slot_vars(self) -> dict:
        """Mappings in the serialized shape the core renderer expects."""
        out = {}
        for m in self.mappings:
            out[m.slot_id] = {"value": m.column, "key": m.key}
            if m.kind == KIND_TEXT:
                out[f"{m.slot_id}_FONT"] = {"path": m.font_path or None}
        return out

    def design_for_render(self) -> dict | None:
        """Copy of the design with each overlay's month-specific flag applied."""
        if not self.design:
            return None
        design = copy.deepcopy(self.design)
        overlays = design.get("template", {}).get("overlayImages", [])
        for m in self.mappings:
            if m.kind == KIND_IMAGE and m.index < len(overlays):
                overlays[m.index]["calendar_image"] = bool(m.month_specific)
        return design

    def product_config(self) -> dict:
        if self.is_calendar:
            return self.calendar.to_product_config(self.base_file)
        return {"type": MODE_NORMAL}

    def base_file_or_list(self):
        if self.is_calendar and self.calendar.base_files:
            return list(self.calendar.base_files)
        return self.base_file or ""

    # ----- serialization -------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        data = dict(data or {})
        cal = dict(data.get("calendar") or {})
        cal["icons"] = [_from_dict(EventIcon, i) for i in cal.get("icons") or []]
        cal["event_text_style"] = _from_dict(EventTextStyle, cal.get("event_text_style"))
        data["calendar"] = _from_dict(CalendarSettings, cal)
        data["path_builder"] = _from_dict(PathBuilderSettings, data.get("path_builder"))
        data["mappings"] = [_from_dict(FieldMapping, m) for m in data.get("mappings") or []]
        return _from_dict(cls, data)
