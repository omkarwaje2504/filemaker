"""BaseView: page header (title + subtitle + actions) and a body that is
either scrollable (forms) or fixed (the data table)."""
from tkinter import ttk

from ..theme import px
from ..widgets import Card, ScrollableFrame

PAGE_PAD = 24
CONTENT_MAX_WIDTH = 980


class BaseView(ttk.Frame):
    key = ""
    title = ""
    subtitle = ""
    scrollable = True

    def __init__(self, parent, state, app):
        super().__init__(parent, style="App.TFrame")
        self.state = state
        self.app = app

        header = ttk.Frame(self, style="App.TFrame")
        header.pack(fill="x", padx=px(PAGE_PAD), pady=(px(20), px(12)))
        text = ttk.Frame(header, style="App.TFrame")
        text.pack(side="left", fill="x", expand=True)
        ttk.Label(text, text=self.title, style="PageTitle.TLabel").pack(anchor="w")
        if self.subtitle:
            ttk.Label(text, text=self.subtitle, style="PageSub.TLabel").pack(anchor="w", pady=(px(2), 0))
        self.header_actions = ttk.Frame(header, style="App.TFrame")
        self.header_actions.pack(side="right", anchor="s")

        if self.scrollable:
            self._scroll = ScrollableFrame(self, max_width=px(CONTENT_MAX_WIDTH + 2 * PAGE_PAD))
            self._scroll.pack(fill="both", expand=True)
            self.body = self._scroll.inner
        else:
            self._scroll = None
            self.body = ttk.Frame(self, style="App.TFrame")
            self.body.pack(fill="both", expand=True, padx=px(PAGE_PAD), pady=(0, px(PAGE_PAD)))

    # ----- helpers for subclasses ----------------------------------------

    def rebuild(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.build()

    def build(self):
        raise NotImplementedError

    def card(self, title=None, subtitle=None, fill="x", expand=False, parent=None):
        card = Card(parent or self.body, title=title, subtitle=subtitle)
        pad = (px(PAGE_PAD), px(PAGE_PAD)) if self.scrollable and parent is None else (0, 0)
        card.pack(fill=fill, expand=expand, padx=pad, pady=(0, px(16)))
        return card

    def setter(self, obj, attr, section):
        """Callback that writes `value` to obj.attr and announces the change."""

        def set_(value):
            if getattr(obj, attr) != value:
                setattr(obj, attr, value)
                self.state.changed(section)

        return set_

    def status(self) -> str:
        """Sidebar completion state: "done", "warn" or "todo"."""
        return "todo"
