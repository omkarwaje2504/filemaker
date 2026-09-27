"""Step 2 - Template: base artwork, design JSON, and field -> column mapping."""
import os
from tkinter import messagebox, ttk

from ...models.project import KIND_IMAGE
from ...services.data_service import (
    ARTWORK_FILETYPES,
    DESIGN_FILETYPES,
    FONT_FILETYPES,
    build_mappings,
    design_summary,
)
from ...utils.text import is_qr_data_static, safe_str
from ..theme import C, F_MONO, F_SMALL, Sym, font, px
from ..widgets import Badge, CheckField, ChoiceField, EmptyState, Notice, PathField, Tooltip, thumbnail
from .base import BaseView

VALUE_PREVIEW_CHARS = 42


class TemplateView(BaseView):
    key = "template"
    title = "Template"
    subtitle = "The artwork to draw on, the design that defines the fields, and which column fills each one."

    def __init__(self, parent, state, app):
        super().__init__(parent, state, app)
        self._value_labels = []
        self.build()
        for topic in ("project", "data", "design", "mode"):
            state.subscribe(topic, lambda **_: self.rebuild())
        state.subscribe("row", lambda **_: self._refresh_values())

    def status(self):
        p = self.state.project
        if not p.design:
            return "todo"
        mapped = sum(1 for m in p.mappings if m.column)
        return "done" if mapped else "warn"

    def build(self):
        self._value_labels = []
        if not self.state.project.is_calendar:
            self._build_base_card()
        self._build_design_card()
        self._build_mapping_card()

    # ----- base artwork ---------------------------------------------------

    def _build_base_card(self):
        p = self.state.project
        card = self.card(
            "Base artwork",
            "The background every output is drawn on. A PDF base produces vector PDFs; "
            "an image base produces 300 DPI PNG or JPG.",
        )
        row = ttk.Frame(card.body)
        row.pack(fill="x")
        self._thumb = ttk.Label(row, style="Alt.TLabel", anchor="center", width=12)
        self._thumb.pack(side="left", padx=(0, px(16)), ipady=px(6))
        right = ttk.Frame(row)
        right.pack(side="left", fill="x", expand=True)
        PathField(right, p.base_file, self._set_base, filetypes=ARTWORK_FILETYPES,
                  placeholder="No base artwork - outputs use a white background",
                  title="Choose base artwork").pack(fill="x")
        self._format = ttk.Label(right, style="Small.TLabel")
        self._format.pack(anchor="w", pady=(px(8), 0))
        self._refresh_base()

    def _set_base(self, path):
        self.state.project.base_file = path
        self.state.changed("base")
        self._refresh_base()

    def _refresh_base(self):
        p = self.state.project
        photo = thumbnail(p.base_file, px(96))
        self._thumb.configure(image=photo or "", text="" if photo else "No preview")
        self._thumb.image = photo
        fmt = p.effective_output_format().upper()
        note = "vector PDF (from PDF base)" if fmt == "PDF" else f"{fmt}, 300 DPI (change in Output)"
        self._format.configure(text=f"Output format: {note}" if p.base_file else "")

    # ----- design ---------------------------------------------------------

    def _build_design_card(self):
        p = self.state.project
        card = self.card(
            "Design",
            "The JSON exported from your template editor. Every {{key}} in it becomes a field below.",
        )
        if p.is_calendar:
            Notice(card.body, "Calendar mode draws on the month artwork chosen in the Calendar step. "
                              "A design is optional there.").pack(fill="x", pady=(0, px(12)))
        PathField(card.body, p.design_path, self._set_design, filetypes=DESIGN_FILETYPES,
                  placeholder="Embedded in project file" if p.design and not p.design_path
                  else "No design loaded",
                  title="Choose design JSON").pack(fill="x")
        if p.design:
            line = ttk.Frame(card.body)
            line.pack(fill="x", pady=(px(8), 0))
            ttk.Label(line, text=design_summary(p.design), style="Small.TLabel").pack(side="left")
            if p.design_path and os.path.exists(p.design_path):
                ttk.Button(line, text=f"{Sym.refresh} Reload", style="Small.Ghost.TButton",
                           command=lambda: self._set_design(p.design_path)).pack(side="right")

    def _set_design(self, path):
        if not path:
            p = self.state.project
            p.design, p.design_path, p.mappings = None, "", []
            self.state.changed("design")
            self.state.publish("design")
            return
        try:
            self.state.load_design(path)
        except Exception as e:
            messagebox.showerror("Could not load design", f"{os.path.basename(path)}\n\n{e}", parent=self)

    # ----- mapping --------------------------------------------------------

    def _build_mapping_card(self):
        p = self.state.project
        card = self.card(
            "Field mapping",
            "Pick the data column that fills each field. The value column shows what the "
            "preview row will insert.",
        )
        if not p.design:
            EmptyState(card.body, "No fields yet", "Load a design JSON to list its image and text fields.").pack(fill="x")
            return
        if not p.mappings:
            p.mappings = build_mappings(p.design)
        if not p.mappings:
            EmptyState(card.body, "This design has no fields",
                       "It contains no overlayImages or textBlocks.").pack(fill="x")
            return

        self._mapped_badge = Badge(card.actions)
        self._mapped_badge.pack(side="left", padx=(0, px(8)))
        auto = ttk.Button(card.actions, text="Auto-map", style="Small.TButton", command=self._auto_map)
        auto.pack(side="left")
        Tooltip(auto, "Match fields to columns with the same name (ignores case)")

        if self.state.df is None:
            Notice(card.body, "Load a data file to choose columns.", "warning").pack(fill="x", pady=(0, px(12)))

        grid = ttk.Frame(card.body)
        grid.pack(fill="x")
        grid.columnconfigure(2, weight=1)
        grid.columnconfigure(3, weight=1)
        headers = ["Field", "Template key", "Data column", "Preview row value", "Options"]
        for c, text in enumerate(headers):
            ttk.Label(grid, text=text.upper(), style="Subtle.TLabel", font=font(8, "bold")).grid(
                row=0, column=c, sticky="w", padx=(0, px(14)), pady=(0, px(6)))

        columns = self.state.columns
        for r, m in enumerate(p.mappings, start=1):
            kind_badge = Badge(grid, m.title, "info" if m.kind == KIND_IMAGE else "neutral")
            kind_badge.grid(row=r, column=0, sticky="w", padx=(0, px(14)), pady=px(4))
            ttk.Label(grid, text="{{" + m.key + "}}" if m.key else "(no key)", font=F_MONO,
                      style="Mono.TLabel").grid(row=r, column=1, sticky="w", padx=(0, px(14)))
            value_label = ttk.Label(grid, style="Small.TLabel")
            ChoiceField(grid, columns, m.column, lambda v, m=m, lbl=value_label: self._set_column(m, v, lbl),
                        width=20).grid(row=r, column=2, sticky="ew", padx=(0, px(14)))
            value_label.grid(row=r, column=3, sticky="w", padx=(0, px(14)))
            self._value_labels.append((m, value_label))
            self._options_cell(grid, m).grid(row=r, column=4, sticky="ew")

        self._refresh_values()

    def _options_cell(self, parent, m):
        p = self.state.project
        if m.kind == KIND_IMAGE:
            if p.is_calendar:
                cell = CheckField(parent, "Per month", m.month_specific,
                                  self.setter(m, "month_specific", "mapping"))
                Tooltip(cell, "For each month, use '<month>_cropped-...' found next to the file in "
                              "the cell (falls back to earlier months). Turn off for images that "
                              "stay the same all year.")
                return cell
            return ttk.Label(parent, text="—", style="Subtle.TLabel")
        return PathField(parent, m.font_path, self.setter(m, "font_path", "mapping"),
                         filetypes=FONT_FILETYPES, placeholder="Template font",
                         browse_text="Font" + Sym.ellipsis, title="Choose font", width=14)

    def _set_column(self, mapping, column, label):
        mapping.column = column
        self.state.changed("mapping")
        self._refresh_value(mapping, label)
        self._refresh_badge()

    def _auto_map(self):
        filled = self.state.auto_map()
        self.state.status(f"Auto-mapped {filled} field(s)" if filled else "No more matching columns found",
                          "success" if filled else "info")

    # ----- live values ----------------------------------------------------

    def _refresh_values(self):
        for m, label in self._value_labels:
            self._refresh_value(m, label)
        self._refresh_badge()

    def _refresh_badge(self):
        badge = getattr(self, "_mapped_badge", None)
        if badge is None or not badge.winfo_exists():
            return
        total = len(self.state.project.mappings)
        mapped = sum(1 for m in self.state.project.mappings if m.column)
        badge.set(f"{mapped} of {total} mapped", "success" if mapped == total else "warning")

    def _refresh_value(self, m, label):
        if not label.winfo_exists():
            return
        row = self.state.current_row()
        if row is None or not m.column or m.column not in row.index:
            label.configure(text="", foreground=C.text_muted)
            return
        value = safe_str(row[m.column])
        text, color = value, C.text_muted
        if not value:
            text = "(empty)"
            color = C.text_subtle
        elif m.kind == KIND_IMAGE:
            low = value.lower()
            if low.startswith(("http://", "https://")):
                text = "URL " + os.path.basename(value)
            elif is_qr_data_static(value):
                text = "QR: " + value
            elif os.path.exists(value):
                text = os.path.basename(value)
            else:
                text, color = f"missing: {os.path.basename(value)}", C.warning
        if len(text) > VALUE_PREVIEW_CHARS:
            text = text[: VALUE_PREVIEW_CHARS - 1] + Sym.ellipsis
        label.configure(text=text, foreground=color, font=F_SMALL)
