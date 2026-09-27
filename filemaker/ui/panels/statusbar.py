"""Bottom status bar: last message on the left, project summary + batch
progress on the right."""
import tkinter as tk
from tkinter import ttk

from ..theme import C, F_SMALL, Sym, px

LEVEL_COLORS = {"info": C.text_subtle, "success": C.success, "warning": C.warning, "error": C.danger}


class StatusBar(tk.Frame):
    def __init__(self, parent, state):
        super().__init__(parent, bg=C.surface)
        self.state = state
        tk.Frame(self, bg=C.border, height=1).pack(side="top", fill="x")
        row = tk.Frame(self, bg=C.surface)
        row.pack(fill="x", padx=px(14), pady=px(5))

        self._dot = tk.Label(row, text=Sym.dot, bg=C.surface, fg=C.text_subtle, font=F_SMALL)
        self._dot.pack(side="left")
        self._msg = tk.Label(row, text="Ready", bg=C.surface, fg=C.text, font=F_SMALL, anchor="w")
        self._msg.pack(side="left", padx=(px(6), 0), fill="x", expand=True)

        self._summary = tk.Label(row, bg=C.surface, fg=C.text_muted, font=F_SMALL)
        self._summary.pack(side="right")
        self._progress = ttk.Progressbar(row, style="Accent.Horizontal.TProgressbar",
                                         length=px(160), mode="determinate")

        state.subscribe("status", self.show)
        state.subscribe("production", self._on_production)
        for topic in ("project", "data", "mode", "design"):
            state.subscribe(topic, lambda **_: self._refresh_summary())
        self._refresh_summary()

    def show(self, text, level="info"):
        self._dot.configure(fg=LEVEL_COLORS.get(level, C.text_subtle))
        self._msg.configure(text=text.replace("\n", "  "))

    def _refresh_summary(self):
        p = self.state.project
        parts = []
        if self.state.df is not None:
            parts.append(f"{self.state.row_count} rows")
        if p.design:
            tpl = p.design.get("template", {})
            parts.append(f"{tpl.get('width', '?')}×{tpl.get('height', '?')} template")
        parts.append("Calendar mode" if p.is_calendar else "Normal mode")
        self._summary.configure(text=f"  {Sym.bullet}  ".join(parts))

    def _on_production(self, phase, stats):
        if phase == "started":
            self._progress.configure(maximum=max(1, stats.rows_total), value=0)
            self._progress.pack(side="right", padx=(0, px(12)))
        elif phase == "progress":
            self._progress.configure(value=stats.rows_done)
        elif phase == "finished":
            self._progress.pack_forget()
