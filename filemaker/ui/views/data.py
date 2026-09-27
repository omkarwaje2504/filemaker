"""Step 1 - Data: load the spreadsheet, browse/filter rows, pick the preview row."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from ...services.data_service import DATA_FILETYPES
from ...utils.text import safe_str
from ..theme import C, F_BASE, F_BOLD, Sym, px
from ..widgets import Badge, Card, EmptyState
from .base import BaseView

MAX_COL_WIDTH = 280
MIN_COL_WIDTH = 70
SAMPLE_ROWS = 100
FILTER_DEBOUNCE_MS = 200


class DataView(BaseView):
    key = "data"
    title = "Data"
    subtitle = "The spreadsheet that drives production - one output (or 12 in calendar mode) per row."
    scrollable = False

    def __init__(self, parent, state, app):
        super().__init__(parent, state, app)
        self._search_rows = []
        self._filter_after = None
        self._syncing = False
        self.tree = None
        self.build()
        state.subscribe("project", lambda **_: self.rebuild())
        state.subscribe("data", lambda **_: self.rebuild())
        state.subscribe("row", lambda **_: self._select_current())

    def status(self):
        return "done" if self.state.df is not None else "todo"

    # ----- build ----------------------------------------------------------

    def build(self):
        self.tree = None
        if self.state.df is None:
            card = Card(self.body)
            card.pack(fill="both", expand=True)
            EmptyState(
                card.body, "No data loaded",
                "Load an Excel (.xlsx/.xls) or CSV file. Each row becomes one output; "
                "columns become fields you can map onto the template.",
                "Load spreadsheet" + Sym.ellipsis, self.choose_file,
            ).pack(fill="both", expand=True)
            return

        self._build_source_card()
        self._build_table_card()

    def _build_source_card(self):
        df = self.state.df
        path = self.state.project.data_path
        card = Card(self.body)
        card.pack(fill="x", pady=(0, px(16)))
        row = ttk.Frame(card.body)
        row.pack(fill="x")

        info = ttk.Frame(row)
        info.pack(side="left", fill="x", expand=True)
        line = ttk.Frame(info)
        line.pack(anchor="w")
        ttk.Label(line, text=os.path.basename(path) or "Data", font=F_BOLD).pack(side="left")
        Badge(line, f"{len(df)} rows", "info").pack(side="left", padx=(px(10), px(4)))
        Badge(line, f"{len(df.columns)} columns", "neutral").pack(side="left")
        ttk.Label(info, text=path, style="Small.TLabel").pack(anchor="w", pady=(px(2), 0))

        ttk.Button(row, text="Reload", command=self.reload_file).pack(side="right", padx=(px(6), 0))
        ttk.Button(row, text="Replace" + Sym.ellipsis, command=self.choose_file).pack(side="right")

    def _build_table_card(self):
        df = self.state.df
        card = Card(self.body)
        card.pack(fill="both", expand=True)

        bar = ttk.Frame(card.body)
        bar.pack(fill="x", pady=(0, px(10)))
        ttk.Label(bar, text="Filter", style="Muted.TLabel").pack(side="left", padx=(0, px(8)))
        self._filter_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self._filter_var, width=34)
        entry.pack(side="left")
        self._filter_var.trace_add("write", lambda *_: self._schedule_filter())
        self._count = ttk.Label(bar, style="Muted.TLabel")
        self._count.pack(side="left", padx=px(12))
        ttk.Label(bar, text="Click a row to preview it", style="Subtle.TLabel").pack(side="right")

        wrap = ttk.Frame(card.body)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        cols = [str(c) for c in df.columns]
        self.tree = ttk.Treeview(wrap, columns=["#"] + cols, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("odd", background=C.surface_alt)

        measure = tkfont.Font(font=F_BASE).measure
        self.tree.heading("#", text="#", anchor="e")
        self.tree.column("#", width=px(48), minwidth=px(40), anchor="e", stretch=False)
        sample = df.head(SAMPLE_ROWS)
        for c in cols:
            longest = max([measure(c)] + [measure(safe_str(v)) for v in sample[c]])
            width = max(px(MIN_COL_WIDTH), min(px(MAX_COL_WIDTH), longest + px(24)))
            self.tree.heading(c, text=c, anchor="w")
            self.tree.column(c, width=width, minwidth=px(50), anchor="w", stretch=False)

        self._rows = [[safe_str(v) for v in values] for values in df.itertuples(index=False, name=None)]
        self._search_rows = [" ".join(r).lower() for r in self._rows]
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self._apply_filter()

    # ----- filtering & selection -----------------------------------------

    def _schedule_filter(self):
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(FILTER_DEBOUNCE_MS, self._apply_filter)

    def _apply_filter(self):
        self._filter_after = None
        if self.tree is None:
            return
        needle = self._filter_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for pos, (values, haystack) in enumerate(zip(self._rows, self._search_rows)):
            if needle and needle not in haystack:
                continue
            self.tree.insert("", "end", iid=str(pos), values=[pos + 1] + values,
                             tags=("odd",) if shown % 2 else ())
            shown += 1
        total = len(self._rows)
        self._count.configure(text=f"{shown} of {total} rows" if needle else f"{total} rows")
        self._select_current()

    def _on_select(self, _e=None):
        if self._syncing:
            return
        sel = self.tree.selection()
        if sel:
            self.state.select_row(int(sel[0]))

    def _select_current(self):
        if self.tree is None or self.state.row_pos is None:
            return
        iid = str(self.state.row_pos)
        if self.tree.exists(iid) and self.tree.selection() != (iid,):
            self._syncing = True
            try:
                self.tree.selection_set(iid)
                self.tree.see(iid)
            finally:
                self._syncing = False

    # ----- actions --------------------------------------------------------

    def choose_file(self):
        path = filedialog.askopenfilename(parent=self, title="Load spreadsheet", filetypes=DATA_FILETYPES)
        if path:
            self._load(os.path.normpath(path))

    def reload_file(self):
        if self.state.project.data_path:
            self._load(self.state.project.data_path)

    def _load(self, path):
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.state.load_data(path)
        except Exception as e:
            messagebox.showerror("Could not load data", f"{os.path.basename(path)}\n\n{e}", parent=self)
        finally:
            self.config(cursor="")
