"""Top bar: brand + project name, product-mode switch, project file actions."""
import tkinter as tk
from tkinter import ttk

from ...models.project import MODE_CALENDAR, MODE_NORMAL
from ..theme import C, F_BRAND, F_SMALL, Sym, font, px
from ..widgets import SegmentedControl, Tooltip


class TopBar(tk.Frame):
    def __init__(self, parent, state, on_new, on_open, on_save):
        super().__init__(parent, bg=C.surface)
        self.state = state

        left = tk.Frame(self, bg=C.surface)
        left.pack(side="left", padx=(px(16), 0), pady=px(10))
        tk.Label(left, text="T", bg=C.primary, fg="white", font=font(12, "bold"),
                 width=2, pady=px(2)).pack(side="left")
        names = tk.Frame(left, bg=C.surface)
        names.pack(side="left", padx=(px(10), 0))
        tk.Label(names, text="Template Designer Pro", bg=C.surface, fg=C.text,
                 font=F_BRAND).pack(anchor="w")
        self._project = tk.Label(names, bg=C.surface, fg=C.text_muted, font=F_SMALL)
        self._project.pack(anchor="w")

        mode_box = tk.Frame(self, bg=C.surface)
        mode_box.pack(side="left", padx=px(40))
        tk.Label(mode_box, text="Product", bg=C.surface, fg=C.text_muted,
                 font=F_SMALL).pack(side="left", padx=(0, px(8)))
        self._mode = SegmentedControl(
            mode_box,
            [(MODE_NORMAL, "Normal  ·  1 per row"), (MODE_CALENDAR, "Calendar  ·  12 per row")],
            state.project.mode,
            state.set_mode,
        )
        self._mode.pack(side="left")

        right = tk.Frame(self, bg=C.surface)
        right.pack(side="right", padx=px(16))
        new = ttk.Button(right, text="New", command=on_new)
        new.pack(side="left", padx=(0, px(6)))
        opn = ttk.Button(right, text="Open" + Sym.ellipsis, command=on_open)
        opn.pack(side="left", padx=(0, px(6)))
        save = ttk.Button(right, text="Save project", style="Primary.TButton", command=on_save)
        save.pack(side="left")
        Tooltip(new, "New project  (Ctrl+N)")
        Tooltip(opn, "Open a saved project  (Ctrl+O)")
        Tooltip(save, "Save project  (Ctrl+S)\nSave as a new file  (Ctrl+Shift+S)")

        for topic in ("project", "changed", "mode"):
            state.subscribe(topic, lambda **_: self.refresh())
        self.refresh()

    def refresh(self):
        marker = f"  {Sym.dot} unsaved" if self.state.dirty else ""
        self._project.configure(text=f"{self.state.project_name}{marker}")
        self._mode.set(self.state.project.mode)
