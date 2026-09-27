"""Input widgets that report typed values through an `on_change` callback.

Views create them bound to a model attribute, e.g.
    NumberField(form, value=cal.cell_width, on_change=lambda v: set_(cal, "cell_width", v))
Invalid input is highlighted red and simply not committed.
"""
import os
import re
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

from ..theme import C, F_SMALL, Sym, px
from .containers import Tooltip

NONE_LABEL = "— none —"  # — none —
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


class TextField(ttk.Entry):
    def __init__(self, parent, value="", on_change=None, width=20, **kw):
        self.var = tk.StringVar(value=value or "")
        super().__init__(parent, textvariable=self.var, width=width, **kw)
        if on_change:
            self.var.trace_add("write", lambda *_: on_change(self.var.get()))


class NumberField(ttk.Spinbox):
    def __init__(self, parent, value, on_change, kind=int, from_=-100000, to=100000,
                 increment=1, width=8):
        self._kind = kind
        self._on_change = on_change
        self.var = tk.StringVar(value=self._fmt(value))
        opts = dict(textvariable=self.var, from_=from_, to=to, increment=increment, width=width)
        if kind is float:
            opts["format"] = "%.2f"
        super().__init__(parent, **opts)
        self.var.trace_add("write", self._changed)

    def _fmt(self, value):
        if self._kind is float:
            return f"{float(value):g}"
        return str(int(value))

    def _parse(self, text):
        number = float(text.strip())
        if self._kind is int:
            if not number.is_integer():
                raise ValueError
            return int(number)
        return number

    def _changed(self, *_):
        try:
            value = self._parse(self.var.get())
        except (ValueError, AttributeError):
            self.configure(style="Invalid.TSpinbox")
            return
        self.configure(style="TSpinbox")
        self._on_change(value)


class ChoiceField(ttk.Combobox):
    """Read-only dropdown. `choices` are raw values; "" is shown as '— none —'.
    A current value missing from choices stays visible, flagged red."""

    def __init__(self, parent, choices, value, on_change, allow_none=True, labels=None, width=22,
                 none_label=NONE_LABEL):
        super().__init__(parent, state="readonly", width=width)
        self._allow_none = allow_none
        self._none_label = none_label
        self._labels = labels or {}
        self._on_change = on_change
        self._raw_by_label = {}
        self._value = value or ""
        self.set_choices(choices)
        self.bind("<<ComboboxSelected>>", self._selected)

    def _label(self, raw):
        if raw == "" and self._allow_none:
            return self._none_label
        return self._labels.get(raw, str(raw))

    def set_choices(self, choices):
        raws = ([""] if self._allow_none else []) + [c for c in choices]
        if self._value and self._value not in raws:
            raws.append(self._value)
        self._raw_by_label = {self._label(r): r for r in raws}
        self["values"] = list(self._raw_by_label)
        self.set(self._label(self._value))
        missing = bool(self._value) and self._value not in choices
        self.configure(style="Invalid.TCombobox" if missing else "TCombobox")

    def _selected(self, _e=None):
        self._value = self._raw_by_label.get(self.get(), "")
        self.configure(style="TCombobox")
        self.selection_clear()
        self._on_change(self._value)

    @property
    def value(self):
        return self._value


class CheckField(ttk.Checkbutton):
    def __init__(self, parent, text, value, on_change, **kw):
        self.var = tk.BooleanVar(value=bool(value))
        super().__init__(parent, text=text, variable=self.var,
                         command=lambda: on_change(self.var.get()), **kw)


class PathField(ttk.Frame):
    """Shows a chosen file/folder path with Browse and Clear buttons.

    mode: "file" | "files" | "folder" | "save"
    """

    def __init__(self, parent, value, on_change, mode="file", filetypes=None,
                 placeholder="Nothing selected", title=None, clearable=True,
                 default_ext=None, browse_text="Browse" + Sym.ellipsis, width=28):
        super().__init__(parent)
        self._on_change = on_change
        self._mode = mode
        self._filetypes = filetypes or [("All files", "*.*")]
        self._placeholder = placeholder
        self._title = title
        self._default_ext = default_ext
        self._value = value or ""

        self.columnconfigure(0, weight=1)
        self._var = tk.StringVar()
        self._entry = ttk.Entry(self, textvariable=self._var, state="readonly", width=width,
                                style="Path.TEntry")
        self._entry.grid(row=0, column=0, sticky="ew")
        self._tip = Tooltip(self._entry, "")
        ttk.Button(self, text=browse_text, style="Small.TButton", command=self.browse).grid(
            row=0, column=1, padx=(px(6), 0))
        self._clear = None
        if clearable:
            self._clear = ttk.Button(self, text=Sym.close, width=2, style="Icon.TButton",
                                     command=lambda: self._commit(""))
            self._clear.grid(row=0, column=2, padx=(px(4), 0))
            Tooltip(self._clear, "Clear")
        self._refresh()

    def _refresh(self):
        self._var.set(self._value or self._placeholder)
        self._entry.configure(foreground=C.text if self._value else C.text_subtle)
        self._tip.set(self._value)
        if self._clear is not None:
            self._clear.state(["!disabled"] if self._value else ["disabled"])

    def _initial_dir(self):
        if not self._value:
            return None
        return self._value if os.path.isdir(self._value) else os.path.dirname(self._value)

    def browse(self):
        opts = dict(parent=self, title=self._title, initialdir=self._initial_dir())
        if self._mode == "folder":
            path = filedialog.askdirectory(**opts)
        elif self._mode == "save":
            path = filedialog.asksaveasfilename(filetypes=self._filetypes,
                                                defaultextension=self._default_ext, **opts)
        else:
            path = filedialog.askopenfilename(filetypes=self._filetypes, **opts)
        if path:
            self._commit(os.path.normpath(path))

    def _commit(self, value):
        self._value = value
        self._refresh()
        self._on_change(value)

    def set(self, value):
        self._value = value or ""
        self._refresh()


class ColorField(ttk.Frame):
    """Hex entry + clickable swatch that opens the system color picker."""

    def __init__(self, parent, value, on_change, allow_empty=False, width=9):
        super().__init__(parent)
        self._on_change = on_change
        self._allow_empty = allow_empty
        self.var = tk.StringVar(value=value or "")
        self._swatch = tk.Label(self, width=3, relief="flat", cursor="hand2",
                                highlightthickness=1, highlightbackground=C.border_strong)
        self._swatch.pack(side="left", fill="y", padx=(0, px(6)))
        self._swatch.bind("<Button-1>", lambda e: self.pick())
        self._entry = ttk.Entry(self, textvariable=self.var, width=width)
        self._entry.pack(side="left", fill="x", expand=True)
        Tooltip(self._swatch, "Pick a color")
        self.var.trace_add("write", self._changed)
        self._paint(self.var.get())

    def _paint(self, color):
        if _HEX.match(color or ""):
            self._swatch.configure(bg=color, text="")
        else:
            self._swatch.configure(bg=C.surface, text="∕", fg=C.text_subtle, font=F_SMALL)

    def _changed(self, *_):
        value = self.var.get().strip()
        ok = _HEX.match(value) or (self._allow_empty and value == "")
        self._entry.configure(style="TEntry" if ok else "Invalid.TEntry")
        self._paint(value)
        if ok:
            self._on_change(value)

    def pick(self):
        current = self.var.get() if _HEX.match(self.var.get()) else None
        _rgb, hex_value = colorchooser.askcolor(color=current, parent=self)
        if hex_value:
            self.var.set(hex_value)


class SegmentedControl(tk.Frame):
    """Pill-style single choice: [ Normal | Calendar ]."""

    def __init__(self, parent, options, value, on_change, bg=C.surface):
        super().__init__(parent, bg=C.border_strong, padx=1, pady=1)
        self._on_change = on_change
        self._value = value
        self._labels = {}
        for i, (key, text) in enumerate(options):
            lbl = tk.Label(self, text=text, font=F_SMALL, padx=px(14), pady=px(5), cursor="hand2")
            lbl.grid(row=0, column=i, padx=(0 if i == 0 else 1, 0))
            lbl.bind("<Button-1>", lambda e, k=key: self._click(k))
            lbl.bind("<Enter>", lambda e, k=key: self._hover(k, True))
            lbl.bind("<Leave>", lambda e, k=key: self._hover(k, False))
            self._labels[key] = lbl
        self._paint()

    def _paint(self):
        for key, lbl in self._labels.items():
            if key == self._value:
                lbl.configure(bg=C.primary, fg="white")
            else:
                lbl.configure(bg=C.surface, fg=C.text)

    def _hover(self, key, inside):
        if key != self._value:
            self._labels[key].configure(bg=C.surface_alt if inside else C.surface)

    def _click(self, key):
        if key != self._value:
            self._value = key
            self._paint()
            self._on_change(key)

    def set(self, value):
        self._value = value
        self._paint()
