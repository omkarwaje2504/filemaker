"""Step 3 (calendar mode) - month artwork, calendar grid, event icons, event text."""
import json
import os
from tkinter import filedialog, ttk

from ...core.events import build_event_texts
from ...models.project import EventIcon
from ...services.data_service import ARTWORK_FILETYPES, FONT_FILETYPES, IMAGE_FILETYPES
from ...utils.months import MONTH_NAMES, sort_by_month
from ...utils.text import safe_str
from ..theme import C, F_BOLD, F_SMALL, Sym, font, px
from ..widgets import (
    CheckField,
    ChoiceField,
    ColorField,
    EmptyState,
    Form,
    Notice,
    NumberField,
    PathField,
    Tooltip,
    thumbnail,
)
from .base import BaseView

ALIGN_H = ["left", "center", "right"]
ALIGN_V = ["top", "middle", "bottom"]


class CalendarView(BaseView):
    key = "calendar"
    title = "Calendar"
    subtitle = "Each row becomes 12 outputs, January to December, each on its month's artwork."

    def __init__(self, parent, state, app):
        super().__init__(parent, state, app)
        self.build()
        for topic in ("project", "data", "design"):
            state.subscribe(topic, lambda **_: self.rebuild())
        state.subscribe("row", lambda **_: self._refresh_events_preview())
        state.subscribe("month", lambda **_: self._refresh_month_list())

    @property
    def cal(self):
        return self.state.project.calendar

    def status(self):
        return "done" if (self.cal.base_files or self.state.project.base_file) else "todo"

    def build(self):
        self._build_months_card()
        self._build_grid_card()
        self._build_icons_card()
        self._build_event_text_card()

    # ----- month artwork --------------------------------------------------

    def _build_months_card(self):
        card = self.card(
            "Month artwork",
            "Month N uses file N. With fewer than 12 files, the last file repeats for the remaining "
            "months. Click a month to preview it.",
        )
        for text, cmd, tip in (
            ("Choose files" + Sym.ellipsis, self._choose_files, "Replace the list (sorted by month name)"),
            ("Add" + Sym.ellipsis, self._add_files, "Append files to the end of the list"),
            ("Sort by name", self._sort, "Order files by the month name in their file names"),
        ):
            b = ttk.Button(card.actions, text=text, style="Small.TButton", command=cmd)
            b.pack(side="left", padx=(px(6), 0))
            Tooltip(b, tip)
        self._months_frame = ttk.Frame(card.body)
        self._months_frame.pack(fill="x")
        self._refresh_month_list()

    def _refresh_month_list(self):
        frame = getattr(self, "_months_frame", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()

        files = self.cal.base_files
        if not files:
            EmptyState(frame, "No month artwork",
                       "Choose up to 12 images or PDFs. Files named after months "
                       "(jan.png, February.pdf, 03.png) are ordered automatically.",
                       "Choose files" + Sym.ellipsis, self._choose_files).pack(fill="x")
            return

        frame.columnconfigure(2, weight=1)
        rows = max(12, len(files))
        for i in range(rows):
            month = i + 1
            own = i < len(files)
            active = month == self.state.month and month <= 12
            name = (f"{Sym.next} " if active else "  ") + (MONTH_NAMES[i] if month <= 12 else "Not used")
            lbl = ttk.Label(frame, text=name, font=F_BOLD if month <= 12 else F_SMALL,
                            foreground=C.primary if active else (C.text if month <= 12 else C.text_subtle),
                            width=12, cursor="hand2" if month <= 12 else "")
            lbl.grid(row=i, column=0, sticky="w", pady=px(2), padx=(px(4), px(8)))

            path = files[i] if own else files[-1]
            photo = thumbnail(path, px(36)) if own else None
            thumb = ttk.Label(frame, image=photo or "", text="" if photo else " ", width=5, anchor="center")
            thumb.image = photo
            thumb.grid(row=i, column=1, sticky="w", padx=(0, px(10)))

            if own:
                text = os.path.basename(path)
                style = "TLabel" if os.path.exists(path) else "Danger.TLabel"
                if not os.path.exists(path):
                    text += "  (file not found)"
            else:
                text, style = f"repeats {os.path.basename(path)}", "Subtle.TLabel"
            name_lbl = ttk.Label(frame, text=text, style=style)
            name_lbl.grid(row=i, column=2, sticky="w")
            if own:
                Tooltip(name_lbl, path)

            if month <= 12:
                for w in (lbl, thumb, name_lbl):
                    w.bind("<Button-1>", lambda e, m=month: self.state.select_month(m))

            if own:
                tools = ttk.Frame(frame)
                tools.grid(row=i, column=3, sticky="e")
                up = ttk.Button(tools, text=Sym.up, width=2, style="Icon.TButton",
                                command=lambda i=i: self._move(i, -1))
                down = ttk.Button(tools, text=Sym.down, width=2, style="Icon.TButton",
                                  command=lambda i=i: self._move(i, 1))
                rm = ttk.Button(tools, text=Sym.close, width=2, style="Icon.TButton",
                                command=lambda i=i: self._remove(i))
                up.pack(side="left")
                down.pack(side="left", padx=px(2))
                rm.pack(side="left")
                if i == 0:
                    up.state(["disabled"])
                if i == len(files) - 1:
                    down.state(["disabled"])

    def _set_files(self, files, message=None):
        self.cal.base_files = files
        self.state.changed("calendar_files")
        self._refresh_month_list()
        if message:
            self.state.status(message)

    def _ask_files(self):
        paths = filedialog.askopenfilenames(parent=self, title="Choose month artwork",
                                            filetypes=ARTWORK_FILETYPES)
        return [os.path.normpath(p) for p in paths]

    def _choose_files(self):
        files = self._ask_files()
        if files:
            self._set_files(sort_by_month(files), f"{len(files)} month file(s) selected")

    def _add_files(self):
        files = self._ask_files()
        if files:
            self._set_files(self.cal.base_files + files, f"Added {len(files)} file(s)")

    def _sort(self):
        self._set_files(sort_by_month(self.cal.base_files), "Sorted by month name")

    def _move(self, i, delta):
        files = list(self.cal.base_files)
        j = i + delta
        if 0 <= j < len(files):
            files[i], files[j] = files[j], files[i]
            self._set_files(files)

    def _remove(self, i):
        files = list(self.cal.base_files)
        del files[i]
        self._set_files(files)

    # ----- grid -----------------------------------------------------------

    def _build_grid_card(self):
        cal = self.cal
        card = self.card(
            "Calendar grid",
            "Where the 7-column day grid sits on the artwork (in output pixels). "
            "Event icons are placed into its day cells.",
        )
        form = Form(card.body, columns=2, label_width=110)
        form.add("Year", NumberField(form, cal.year, self.setter(cal, "year", "calendar"), from_=1900, to=2200))
        form.add("Cell borders", CheckField(form, "Show", cal.show_borders,
                                            self.setter(cal, "show_borders", "calendar")),
                 hint="Draws cell outlines on the output. Use it to line things up, then turn it off.")
        form.add("Grid left (X)", NumberField(form, cal.start_x, self.setter(cal, "start_x", "calendar")))
        form.add("Grid top (Y)", NumberField(form, cal.start_y, self.setter(cal, "start_y", "calendar")))
        form.add("Cell width", NumberField(form, cal.cell_width, self.setter(cal, "cell_width", "calendar"),
                                           from_=1))
        form.add("Cell height", NumberField(form, cal.cell_height, self.setter(cal, "cell_height", "calendar"),
                                            from_=1))
        form.pack(fill="x")

    # ----- event icons ----------------------------------------------------

    def _build_icons_card(self):
        card = self.card(
            "Event icons",
            "Place an icon on the day whose date is in a column (month and day are used, the year "
            "is ignored). Dates like 2024-03-18, 18-03-2024, 2024/03/18 or 18/03/2024.",
        )
        ttk.Button(card.actions, text="+ Add icon", style="Small.TButton", command=self._add_icon).pack()
        self._icons_frame = ttk.Frame(card.body)
        self._icons_frame.pack(fill="x")
        self._refresh_icons()

    def _refresh_icons(self):
        frame = self._icons_frame
        for child in frame.winfo_children():
            child.destroy()
        icons = self.cal.icons
        if not icons:
            ttk.Label(frame, text="No icons yet.", style="Subtle.TLabel").pack(anchor="w")
            return
        frame.columnconfigure(1, weight=1)
        for c, text in enumerate(["", "Icon image", "Date column", "X", "Y", "Scale %", ""]):
            ttk.Label(frame, text=text.upper(), style="Subtle.TLabel", font=font(8, "bold")).grid(
                row=0, column=c, sticky="w", padx=(0, px(8)), pady=(0, px(4)))
        for r, icon in enumerate(icons, start=1):
            photo = thumbnail(icon.path, px(28))
            thumb = ttk.Label(frame, image=photo or "", text="" if photo else " ", width=4)
            thumb.image = photo
            thumb.grid(row=r, column=0, padx=(0, px(8)), pady=px(3))
            PathField(frame, icon.path, lambda v, i=icon: self._set_icon_path(i, v),
                      filetypes=IMAGE_FILETYPES, placeholder="Choose icon", clearable=False,
                      title="Choose icon image", width=16).grid(row=r, column=1, sticky="ew", padx=(0, px(8)))
            ChoiceField(frame, self.state.columns, icon.excel_column,
                        self.setter(icon, "excel_column", "icons"), width=16).grid(
                row=r, column=2, sticky="ew", padx=(0, px(8)))
            NumberField(frame, icon.offset_x, self.setter(icon, "offset_x", "icons"), width=6).grid(
                row=r, column=3, padx=(0, px(8)))
            NumberField(frame, icon.offset_y, self.setter(icon, "offset_y", "icons"), width=6).grid(
                row=r, column=4, padx=(0, px(8)))
            NumberField(frame, round(icon.scale * 100), lambda v, i=icon: self._set_icon_scale(i, v),
                        from_=1, to=1000, width=6).grid(row=r, column=5, padx=(0, px(8)))
            rm = ttk.Button(frame, text=Sym.close, width=2, style="Icon.TButton",
                            command=lambda i=icon: self._remove_icon(i))
            rm.grid(row=r, column=6)
            Tooltip(rm, "Remove icon")
        ttk.Label(frame, text="X / Y offset the icon inside its day cell; scale is a % of the cell width.",
                  style="Subtle.TLabel").grid(row=len(icons) + 1, column=0, columnspan=7, sticky="w", pady=(px(6), 0))

    def _add_icon(self):
        self.cal.icons.append(EventIcon())
        self.state.changed("icons")
        self._refresh_icons()

    def _remove_icon(self, icon):
        self.cal.icons.remove(icon)
        self.state.changed("icons")
        self._refresh_icons()

    def _set_icon_path(self, icon, path):
        icon.path = path
        self.state.changed("icons")
        self._refresh_icons()

    def _set_icon_scale(self, icon, percent):
        icon.scale = percent / 100.0
        self.state.changed("icons")

    # ----- event text -----------------------------------------------------

    def _build_event_text_card(self):
        cal, st = self.cal, self.cal.event_text_style
        card = self.card(
            "Event text",
            'Print each month\'s events from a column holding a JSON list, e.g. '
            '[{"date": "24/01/1990", "value": "Birthday"}]. Events land in the month of their '
            'date, prefixed with the day ("24th:").',
        )
        form = Form(card.body, columns=2, label_width=110)
        form.add("Events column", ChoiceField(form, self.state.columns, cal.event_text_column,
                                              self._set_event_column), span=2)
        form.pack(fill="x")

        self._events_preview = ttk.Frame(card.body)
        self._events_preview.pack(fill="x", pady=(px(4), px(4)))
        self._refresh_events_preview()

        s = "event_style"
        form = Form(card.body, columns=2, label_width=110)
        form.section("Position")
        form.add("X", NumberField(form, st.x, self.setter(st, "x", s)))
        form.add("Y", NumberField(form, st.y, self.setter(st, "y", s)))
        form.add("Max width", NumberField(form, st.max_width, self.setter(st, "max_width", s), from_=1))
        form.add("Gap between", NumberField(form, cal.event_line_spacing,
                                            self.setter(cal, "event_line_spacing", "calendar")),
                 hint="Pixels between one event block and the next.")
        form.add("Align", ChoiceField(form, ALIGN_H, st.h_align, self.setter(st, "h_align", s),
                                      allow_none=False, width=10))
        form.add("Anchor", ChoiceField(form, ALIGN_V, st.v_align, self.setter(st, "v_align", s),
                                       allow_none=False, width=10))

        form.section("Text")
        form.add("Font", PathField(form, st.font_path, self.setter(st, "font_path", s),
                                   filetypes=FONT_FILETYPES, placeholder="Uses the fallback font",
                                   title="Choose event font"), span=2)
        form.add("Fallback font", PathField(form, cal.font_path, self.setter(cal, "font_path", "calendar"),
                                            filetypes=FONT_FILETYPES, placeholder="Arial",
                                            title="Choose fallback font"), span=2)
        form.add("Size", NumberField(form, st.font_size, self.setter(st, "font_size", s), from_=1, to=1000))
        form.add("Line height", NumberField(form, st.line_height, self.setter(st, "line_height", s),
                                            kind=float, from_=0.5, to=5, increment=0.1))

        form.section("Colors & box")
        form.add("Text", ColorField(form, st.text_color, self.setter(st, "text_color", s)))
        form.add("Date", ColorField(form, st.date_color, self.setter(st, "date_color", s)))
        form.add("Border", ColorField(form, st.border_color, self.setter(st, "border_color", s),
                                      allow_empty=True),
                 hint="Leave empty for no border.")
        form.add("Border width", NumberField(form, st.border_thickness,
                                             self.setter(st, "border_thickness", s), from_=0, to=100))
        form.add("Corner radius", NumberField(form, st.border_radius, self.setter(st, "border_radius", s),
                                              from_=0, to=1000))
        form.add("Padding", NumberField(form, st.padding, self.setter(st, "padding", s), from_=0, to=500))
        form.pack(fill="x", pady=(px(8), 0))

    def _set_event_column(self, column):
        self.cal.event_text_column = column
        self.state.changed("calendar")
        self._refresh_events_preview()

    def _refresh_events_preview(self):
        frame = getattr(self, "_events_preview", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()

        column = self.cal.event_text_column
        row = self.state.current_row()
        if not column:
            return
        if row is None:
            Notice(frame, "Load data to check the events of a row.").pack(fill="x")
            return
        if column not in row.index:
            Notice(frame, f"Column '{column}' is not in the loaded data.", "danger").pack(fill="x")
            return
        raw = safe_str(row[column])
        if not raw:
            Notice(frame, "The preview row has no events (empty cell).").pack(fill="x")
            return
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                raise ValueError
        except ValueError:
            Notice(frame, "The preview row's cell is not a valid JSON list, so no events will print.",
                   "danger").pack(fill="x")
            return

        events = build_event_texts(row, {"calendar_event_text_column": column})
        if not events:
            Notice(frame, f"{len(items)} item(s) in the cell but none have a usable date and value.",
                   "warning").pack(fill="x")
            return
        lines = [f"{MONTH_NAMES[e['month_idx'] - 1][:3]}  {Sym.bullet}  {e['text']}" for e in events[:6]]
        if len(events) > 6:
            lines.append(f"{Sym.ellipsis} and {len(events) - 6} more")
        Notice(frame, f"Preview row has {len(events)} event(s):\n" + "\n".join(lines), "success").pack(fill="x")
