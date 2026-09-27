"""Layout building blocks: Card, ScrollableFrame, Form, EmptyState, Badge, Tooltip."""
import tkinter as tk
from tkinter import ttk

from ..theme import C, F_H2, F_SMALL, F_TINY, font, px

# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


class Card(tk.Frame):
    """White surface with a 1px border, optional title row + action area.
    Put content in `card.body`; header buttons in `card.actions`."""

    def __init__(self, parent, title=None, subtitle=None, padding=16):
        super().__init__(
            parent, bg=C.surface, highlightthickness=1,
            highlightbackground=C.border, highlightcolor=C.border,
        )
        pad = px(padding)
        self.actions = None
        if title:
            head = ttk.Frame(self)
            head.pack(fill="x", padx=pad, pady=(pad, 0))
            text = ttk.Frame(head)
            text.pack(side="left", fill="x", expand=True)
            ttk.Label(text, text=title, font=F_H2).pack(anchor="w")
            if subtitle:
                ttk.Label(text, text=subtitle, style="Small.TLabel", wraplength=px(560),
                          justify="left").pack(anchor="w", pady=(px(2), 0))
            self.actions = ttk.Frame(head)
            self.actions.pack(side="right", anchor="n")
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)


# ---------------------------------------------------------------------------
# ScrollableFrame + global mouse-wheel routing
# ---------------------------------------------------------------------------

_NATIVE_SCROLLERS = (ttk.Treeview, tk.Text, tk.Listbox)


class ScrollableFrame(ttk.Frame):
    """Vertically scrolling container. Content goes in `.inner`, which always
    matches the visible width (capped at max_width and centred), so forms
    reflow instead of forcing a horizontal scrollbar."""

    def __init__(self, parent, bg=C.app_bg, max_width=None, style="App.TFrame"):
        super().__init__(parent, style=style)
        self.max_width = max_width
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0,
                                yscrollincrement=px(20))
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style=style)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas._scroll_host = self  # found by the wheel router

    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.vsb.grid_remove()
        else:
            self.vsb.grid()

    def _on_inner_configure(self, _e=None):
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.inner.winfo_reqheight()))

    def _on_canvas_configure(self, e):
        width = e.width if not self.max_width else min(e.width, self.max_width)
        x = max(0, (e.width - width) // 2)
        self.canvas.itemconfigure(self._win, width=width)
        self.canvas.coords(self._win, x, 0)
        self._on_inner_configure()

    def wheel(self, delta_units):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(delta_units, "units")

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)


def install_wheel_router(root):
    """One global handler: scroll whichever ScrollableFrame is under the
    pointer, unless a natively scrolling widget (table, text) is there."""

    def on_wheel(event):
        try:
            w = root.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        while w is not None:
            if isinstance(w, _NATIVE_SCROLLERS):
                return
            host = getattr(w, "_scroll_host", None)
            if host is not None:
                host.wheel(int(-event.delta / 120) * 2 or (-2 if event.delta > 0 else 2))
                return
            w = getattr(w, "master", None)

    root.bind_all("<MouseWheel>", on_wheel, add="+")


# ---------------------------------------------------------------------------
# Form: label/field grid
# ---------------------------------------------------------------------------


class Form(ttk.Frame):
    """Grid of (label, field) pairs, `columns` pairs per row.

        form = Form(card.body, columns=2)
        form.add("Width", NumberField(form, ...))
    """

    def __init__(self, parent, columns=1, label_width=None, style="TFrame"):
        super().__init__(parent, style=style)
        self._columns = columns
        self._slot = 0
        self._line = 0  # each line uses two grid rows: fields, then hints
        for c in range(columns):
            self.columnconfigure(c * 2 + 1, weight=1, uniform="field")
            if label_width:
                self.columnconfigure(c * 2, minsize=px(label_width))

    def add(self, label, widget, hint=None, span=1):
        if self._slot + span > self._columns:
            self._next_line()
        row, col = self._line * 2, self._slot * 2
        gap_left = px(24) if self._slot else 0
        ttk.Label(self, text=label, style="Muted.TLabel").grid(
            row=row, column=col, sticky="w", padx=(gap_left, px(12)), pady=px(5))
        widget.grid(row=row, column=col + 1, columnspan=span * 2 - 1, sticky="ew", pady=px(5))
        if hint:
            ttk.Label(self, text=hint, style="Subtle.TLabel", wraplength=px(440), justify="left").grid(
                row=row + 1, column=col + 1, columnspan=span * 2 - 1, sticky="w", pady=(0, px(4)))
        self._slot += span
        if self._slot >= self._columns:
            self._next_line()
        return widget

    def _next_line(self):
        self._line += 1
        self._slot = 0

    def section(self, title):
        """A small-caps sub-heading spanning the full width."""
        if self._slot:
            self._next_line()
        ttk.Label(self, text=title.upper(), style="Subtle.TLabel", font=font(8, "bold")).grid(
            row=self._line * 2, column=0, columnspan=self._columns * 2, sticky="w",
            pady=(px(14) if self._line else 0, px(2)))
        self._line += 1


# ---------------------------------------------------------------------------
# Small pieces
# ---------------------------------------------------------------------------

_LEVEL_COLORS = {
    "info": (C.primary_soft, C.primary_pressed),
    "success": (C.success_soft, C.success),
    "warning": (C.warning_soft, C.warning),
    "danger": (C.danger_soft, C.danger),
    "neutral": (C.surface_alt, C.text_muted),
}


class Badge(tk.Label):
    def __init__(self, parent, text="", level="neutral"):
        super().__init__(parent, text=text, font=font(8, "bold"), padx=px(7), pady=px(1))
        self.set(text, level)

    def set(self, text, level="neutral"):
        bg, fg = _LEVEL_COLORS.get(level, _LEVEL_COLORS["neutral"])
        self.configure(text=text, bg=bg, fg=fg)


class Notice(tk.Frame):
    """Tinted inline message (info / warning / danger)."""

    def __init__(self, parent, text, level="info"):
        bg, fg = _LEVEL_COLORS.get(level, _LEVEL_COLORS["info"])
        super().__init__(parent, bg=bg)
        tk.Frame(self, bg=fg, width=px(3)).pack(side="left", fill="y")
        self.label = tk.Label(self, text=text, bg=bg, fg=fg if level != "info" else C.text,
                              font=F_SMALL, justify="left", anchor="w", wraplength=px(560),
                              padx=px(10), pady=px(8))
        self.label.pack(side="left", fill="x", expand=True)


class EmptyState(ttk.Frame):
    def __init__(self, parent, title, message="", action_text=None, action=None, style="TFrame"):
        super().__init__(parent, style=style)
        label_style = "TLabel" if style == "TFrame" else "Alt.TLabel"
        inner = ttk.Frame(self, style=style)
        inner.pack(expand=True, pady=px(28))
        ttk.Label(inner, text=title, font=F_H2, style=label_style).pack()
        if message:
            ttk.Label(inner, text=message, style="Muted.TLabel", wraplength=px(420),
                      justify="center").pack(pady=(px(4), 0))
        if action_text and action:
            ttk.Button(inner, text=action_text, style="Primary.TButton", command=action).pack(pady=(px(14), 0))


class Tooltip:
    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set(self, text):
        self.text = text

    def _schedule(self, _e=None):
        self._cancel()
        if self.text:
            self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + px(8)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(4)
        self._tip = tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self.text, bg=C.text, fg="white", font=F_TINY, padx=px(8), pady=px(4),
                 justify="left", wraplength=px(360)).pack()

    def _hide(self, _e=None):
        self._cancel()
        if self._tip:
            self._tip.destroy()
            self._tip = None


def hline(parent, pady=8):
    tk.Frame(parent, bg=C.border, height=1).pack(fill="x", pady=px(pady))
