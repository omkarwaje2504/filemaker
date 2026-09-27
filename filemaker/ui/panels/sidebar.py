"""Left navigation: the workflow steps (with completion dots) and tools."""
import tkinter as tk

from ..theme import C, F_BASE, F_SMALL, Sym, font, px

STATUS_COLORS = {"done": C.success, "warn": C.warning, "todo": C.sidebar_muted}


class _NavItem(tk.Frame):
    def __init__(self, parent, key, text, on_click):
        super().__init__(parent, bg=C.sidebar_bg, cursor="hand2")
        self.key = key
        self._active = False
        self._bar = tk.Frame(self, bg=C.sidebar_bg, width=px(3))
        self._bar.pack(side="left", fill="y")
        self._num = tk.Label(self, bg=C.sidebar_bg, fg=C.sidebar_muted, font=font(9, "bold"), width=2)
        self._num.pack(side="left", padx=(px(12), px(6)), pady=px(9))
        self._text = tk.Label(self, text=text, bg=C.sidebar_bg, fg=C.sidebar_text, font=F_BASE, anchor="w")
        self._text.pack(side="left", fill="x", expand=True)
        self._dot = tk.Label(self, text=Sym.dot, bg=C.sidebar_bg, fg=C.sidebar_muted, font=F_SMALL)
        self._dot.pack(side="right", padx=px(14))
        for w in (self, self._num, self._text, self._dot):
            w.bind("<Button-1>", lambda e: on_click(key))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))

    def set_number(self, n):
        self._num.configure(text=str(n) if n else "")

    def set_status(self, status):
        self._dot.configure(fg=STATUS_COLORS.get(status, C.sidebar_muted))

    def set_active(self, active):
        self._active = active
        self._paint(C.sidebar_active if active else C.sidebar_bg)
        self._bar.configure(bg=C.primary if active else C.sidebar_bg)
        self._text.configure(fg="white" if active else C.sidebar_text,
                             font=font(10, "bold") if active else F_BASE)

    def _hover(self, inside):
        if not self._active:
            self._paint(C.sidebar_hover if inside else C.sidebar_bg)

    def _paint(self, bg):
        for w in (self, self._num, self._text, self._dot):
            w.configure(bg=bg)


class Sidebar(tk.Frame):
    """items: list of (key, label, section) - section "workflow" gets numbers."""

    def __init__(self, parent, items, on_select):
        super().__init__(parent, bg=C.sidebar_bg, width=px(220))
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._items = {}
        self._order = []
        self._hidden = set()
        self._sections = {}

        for key, label, section in items:
            if section not in self._sections:
                head = tk.Label(self, text=section.upper(), bg=C.sidebar_bg, fg=C.sidebar_muted,
                                font=font(8, "bold"), anchor="w")
                self._sections[section] = head
                self._order.append(("section", section))
            self._items[key] = (_NavItem(self, key, label, on_select), section)
            self._order.append(("item", key))

        self._footer = tk.Label(
            self, bg=C.sidebar_bg, fg=C.sidebar_muted, font=font(8), justify="left", anchor="w",
            text="Ctrl+S  save\nF5  refresh preview\nAlt+← / →  previous / next row",
        )
        self._layout()

    def _layout(self):
        for kind, key in self._order:
            widget = self._sections[key] if kind == "section" else self._items[key][0]
            widget.pack_forget()
        self._footer.pack_forget()

        number = 0
        for kind, key in self._order:
            if kind == "section":
                self._sections[key].pack(fill="x", padx=px(18), pady=(px(22), px(6)))
                continue
            if key in self._hidden:
                continue
            item, section = self._items[key]
            if section == "workflow":
                number += 1
                item.set_number(number)
            else:
                item.set_number(None)
            item.pack(fill="x")
        self._footer.pack(side="bottom", fill="x", padx=px(18), pady=px(16))

    def set_visible(self, key, visible):
        changed = (key in self._hidden) == visible
        if visible:
            self._hidden.discard(key)
        else:
            self._hidden.add(key)
        if changed:
            self._layout()

    def set_active(self, key):
        for k, (item, _section) in self._items.items():
            item.set_active(k == key)

    def set_status(self, key, status):
        if key in self._items:
            self._items[key][0].set_status(status)
