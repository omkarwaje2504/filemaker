"""Main window: assembles top bar, sidebar, page views, preview and status bar,
and owns app-level actions (project files, shortcuts, closing)."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import APP_TITLE, MIN_WINDOW_SIZE
from ..services.project_store import PROJECT_EXTENSION, PROJECT_FILETYPES
from .dispatch import Dispatcher
from .panels.preview import PreviewPanel
from .panels.sidebar import Sidebar
from .panels.statusbar import StatusBar
from .panels.topbar import TopBar
from .state import AppState
from .theme import C, init_theme, px
from .views.calendar import CalendarView
from .views.data import DataView
from .views.output import OutputView
from .views.path_builder import PathBuilderView
from .views.template import TemplateView
from .widgets import install_wheel_router

NAV = [
    ("data", "Data", "workflow"),
    ("template", "Template", "workflow"),
    ("calendar", "Calendar", "workflow"),
    ("output", "Output", "workflow"),
    ("paths", "Path builder", "tools"),
]
VIEW_CLASSES = {
    "data": DataView,
    "template": TemplateView,
    "calendar": CalendarView,
    "output": OutputView,
    "paths": PathBuilderView,
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_theme(self)
        self.title(APP_TITLE)
        self._size_window()

        self.app_state = AppState()
        self.dispatch = Dispatcher(self)
        self.current_view = None

        self._build()
        install_wheel_router(self)
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        s = self.app_state
        s.subscribe("mode", lambda **_: self._on_mode())
        for topic in ("project", "data", "design", "mode", "changed"):
            s.subscribe(topic, lambda **_: self._refresh_nav_status())
        s.subscribe("project", lambda **_: self._on_mode())

        self._on_mode()
        self.show_view("data")
        self._refresh_nav_status()
        self.after(80, self._place_sash)

    # ----- layout ---------------------------------------------------------

    def _size_window(self):
        min_w, min_h = MIN_WINDOW_SIZE
        self.minsize(px(min_w), px(min_h))
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(px(min_w), min(int(sw * 0.9), px(1920)))
        h = max(px(min_h), min(int(sh * 0.88), px(1100)))
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")

    def _build(self):
        s = self.app_state
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        self.topbar = TopBar(self, s, self.new_project, self.open_project, self.save_project)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        tk.Frame(self, bg=C.border, height=1).grid(row=1, column=0, columnspan=2, sticky="ew")

        self.sidebar = Sidebar(self, NAV, self.show_view)
        self.sidebar.grid(row=2, column=0, sticky="ns")

        self.paned = ttk.Panedwindow(self, orient="horizontal")
        self.paned.grid(row=2, column=1, sticky="nsew")

        host = ttk.Frame(self.paned, style="App.TFrame")
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        self.views = {}
        for key, cls in VIEW_CLASSES.items():
            view = cls(host, s, self)
            view.grid(row=0, column=0, sticky="nsew")
            self.views[key] = view
        self.paned.add(host, weight=3)

        preview_wrap = tk.Frame(self.paned, bg=C.border)
        self.preview = PreviewPanel(preview_wrap, s, self.dispatch)
        self.preview.pack(fill="both", expand=True, padx=(1, 0))
        self.paned.add(preview_wrap, weight=2)

        self.statusbar = StatusBar(self, s)
        self.statusbar.grid(row=3, column=0, columnspan=2, sticky="ew")

    def _place_sash(self):
        width = self.paned.winfo_width()
        if width < 100:
            self.after(80, self._place_sash)
            return
        self.paned.sashpos(0, int(width * 0.6))

    # ----- navigation -----------------------------------------------------

    def show_view(self, key):
        if key == "calendar" and not self.app_state.project.is_calendar:
            key = "template"
        view = self.views[key]
        view.tkraise()
        self.current_view = key
        self.sidebar.set_active(key)

    def _on_mode(self):
        is_calendar = self.app_state.project.is_calendar
        self.sidebar.set_visible("calendar", is_calendar)
        if self.current_view == "calendar" and not is_calendar:
            self.show_view("template")

    def _refresh_nav_status(self):
        for key, view in self.views.items():
            self.sidebar.set_status(key, view.status())

    # ----- shortcuts ------------------------------------------------------

    def _bind_shortcuts(self):
        s = self.app_state
        self.bind_all("<Control-n>", lambda e: self.new_project())
        self.bind_all("<Control-o>", lambda e: self.open_project())
        self.bind_all("<Control-s>", lambda e: self.save_project())
        self.bind_all("<Control-S>", lambda e: self.save_project(save_as=True))
        self.bind_all("<F5>", lambda e: self.preview.schedule(0, force=True))
        self.bind_all("<Alt-Left>", lambda e: s.step_row(-1))
        self.bind_all("<Alt-Right>", lambda e: s.step_row(1))
        for i, (key, _label, _section) in enumerate(NAV, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self.show_view(k))

    # ----- project files --------------------------------------------------

    def _confirm_discard(self):
        """True if it's OK to drop the current project (saving it if asked)."""
        if not self.app_state.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes", f"Save changes to {self.app_state.project_name}?", parent=self)
        if answer is None:
            return False
        if answer:
            return self.save_project()
        return True

    def _guard_running(self):
        if self.app_state.is_running:
            messagebox.showinfo("Production running", "Stop the running production first.", parent=self)
            return False
        return True

    def new_project(self):
        if self._guard_running() and self._confirm_discard():
            self.app_state.new_project()
            self.show_view("data")

    def open_project(self):
        if not (self._guard_running() and self._confirm_discard()):
            return
        path = filedialog.askopenfilename(parent=self, title="Open project", filetypes=PROJECT_FILETYPES)
        if not path:
            return
        try:
            warnings = self.app_state.open_project(os.path.normpath(path))
        except Exception as e:
            messagebox.showerror("Could not open project", f"{os.path.basename(path)}\n\n{e}", parent=self)
            return
        if warnings:
            messagebox.showwarning("Opened with warnings", "\n\n".join(warnings), parent=self)
        self.show_view("output" if self.app_state.df is not None else "data")

    def save_project(self, save_as=False):
        """Returns True if saved."""
        path = self.app_state.project_path
        if save_as or not path:
            path = filedialog.asksaveasfilename(
                parent=self, title="Save project", filetypes=PROJECT_FILETYPES,
                defaultextension=PROJECT_EXTENSION,
                initialfile=(self.app_state.project_name if self.app_state.project_path
                             else "project") + PROJECT_EXTENSION,
            )
            if not path:
                return False
            if not path.endswith(PROJECT_EXTENSION):
                path = os.path.splitext(path)[0]
                path = path[: -len(".tdtpl")] if path.endswith(".tdtpl") else path
                path += PROJECT_EXTENSION
        try:
            self.app_state.save_project(os.path.normpath(path))
            return True
        except Exception as e:
            messagebox.showerror("Could not save", str(e), parent=self)
            return False

    def on_close(self):
        if self.app_state.is_running:
            if not messagebox.askyesno("Production running",
                                       "Production is still running. Stop it and quit?", parent=self):
                return
            self.app_state.production.abort()
        if self._confirm_discard():
            self.destroy()


def enable_windows_dpi_awareness():
    """Crisp text on high-DPI Windows displays (otherwise Tk is bitmap-scaled)."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    enable_windows_dpi_awareness()
    App().mainloop()
