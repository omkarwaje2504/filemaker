"""Live preview: renders the selected row (and month) through the same code
as production, on a background thread, and fits it to the canvas."""
import os
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from ...services.preview import PreviewRequest, PreviewUnavailable, render_preview
from ...utils.months import MONTH_NAMES
from ..theme import C, F_H2, F_SMALL, Sym, font, px
from ..widgets import Tooltip

DEBOUNCE_MS = 300
MARGIN = 18


class PreviewPanel(ttk.Frame):
    def __init__(self, parent, state, dispatch):
        super().__init__(parent)
        self.state = state
        self.dispatch = dispatch
        self._generation = 0
        self._pending = None
        self._image = None  # last rendered PIL image
        self._photo = None
        self._fit_key = None
        self._message = ("Load data to preview a row", "info")
        self._busy = False

        self._build()
        for topic in ("project", "data", "design", "mode", "changed", "row", "month"):
            state.subscribe(topic, self._on_state)
        self._sync_controls()

    # ----- layout ---------------------------------------------------------

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", padx=px(16), pady=(px(14), px(8)))
        ttk.Label(head, text="Preview", font=F_H2).pack(side="left")
        self._auto = tk.BooleanVar(value=True)
        open_btn = ttk.Button(head, text="Full size", style="Small.TButton", command=self.open_full_size)
        open_btn.pack(side="right")
        Tooltip(open_btn, "Open the rendered preview at 100% in your image viewer")
        refresh = ttk.Button(head, text=f"{Sym.refresh} Refresh", style="Small.TButton",
                             command=lambda: self.schedule(0, force=True))
        refresh.pack(side="right", padx=(0, px(6)))
        Tooltip(refresh, "Render again  (F5)")
        auto = ttk.Checkbutton(head, text="Auto", variable=self._auto,
                               command=lambda: self._auto.get() and self.schedule(0))
        auto.pack(side="right", padx=(0, px(10)))
        Tooltip(auto, "Re-render automatically when anything changes")

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=px(16), pady=(0, px(10)))
        self._prev = ttk.Button(nav, text=Sym.prev, width=3, style="Icon.TButton",
                                command=lambda: self.state.step_row(-1))
        self._prev.pack(side="left")
        ttk.Label(nav, text="Row", style="Muted.TLabel").pack(side="left", padx=(px(8), px(4)))
        self._row_var = tk.StringVar()
        self._row_spin = ttk.Spinbox(nav, from_=1, to=1, width=6, textvariable=self._row_var,
                                     command=self._row_typed)
        self._row_spin.pack(side="left")
        self._row_spin.bind("<Return>", lambda e: self._row_typed())
        self._row_spin.bind("<FocusOut>", lambda e: self._row_typed())
        self._row_total = ttk.Label(nav, style="Muted.TLabel")
        self._row_total.pack(side="left", padx=(px(4), px(8)))
        self._next = ttk.Button(nav, text=Sym.next, width=3, style="Icon.TButton",
                                command=lambda: self.state.step_row(1))
        self._next.pack(side="left")

        self._month_box = ttk.Frame(nav)
        ttk.Label(self._month_box, text="Month", style="Muted.TLabel").pack(side="left", padx=(0, px(6)))
        self._month = ttk.Combobox(self._month_box, values=MONTH_NAMES, state="readonly", width=11)
        self._month.pack(side="left")
        self._month.bind("<<ComboboxSelected>>",
                         lambda e: self.state.select_month(self._month.current() + 1))

        self.canvas = tk.Canvas(self, bg=C.canvas_bg, highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="both", expand=True, padx=px(16))
        self.canvas.bind("<Configure>", lambda e: self._draw())

        self._info = ttk.Label(self, style="Subtle.TLabel", anchor="w")
        self._info.pack(fill="x", padx=px(16), pady=(px(6), px(12)))

    # ----- state sync -----------------------------------------------------

    def _on_state(self, **_):
        self._sync_controls()
        if self._auto.get():
            self.schedule()

    def _sync_controls(self):
        n = self.state.row_count
        has_rows = n > 0 and self.state.row_pos is not None
        self._row_spin.configure(to=max(1, n))
        self._row_var.set(str(self.state.row_pos + 1) if has_rows else "")
        self._row_total.configure(text=f"of {n}" if n else "no data")
        for w in (self._prev, self._next, self._row_spin):
            w.state(["!disabled"] if has_rows else ["disabled"])
        if has_rows:
            self._prev.state(["disabled"] if self.state.row_pos <= 0 else ["!disabled"])
            self._next.state(["disabled"] if self.state.row_pos >= n - 1 else ["!disabled"])

        if self.state.project.is_calendar:
            self._month.current(self.state.month - 1)
            self._month_box.pack(side="right")
        else:
            self._month_box.pack_forget()

    def _row_typed(self):
        try:
            self.state.select_row(int(self._row_var.get()) - 1)
        except ValueError:
            self._sync_controls()

    # ----- rendering ------------------------------------------------------

    def schedule(self, delay=DEBOUNCE_MS, force=False):
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(delay, lambda: self._render(force))

    def _render(self, force=False):
        self._pending = None
        if not force and not self._auto.get():
            return
        state = self.state
        if state.df is None or state.row_pos is None:
            self._show_message("Load a data file to preview a row", "info")
            return
        try:
            request = PreviewRequest.from_project(state.project, state.df, state.row_pos, state.month)
        except Exception as e:
            self._show_message(f"Preview unavailable: {e}", "error")
            return

        self._generation += 1
        generation = self._generation
        self._busy = True
        self._draw()
        threading.Thread(target=self._work, args=(generation, request), daemon=True).start()

    def _work(self, generation, request):
        started = time.perf_counter()
        image, message = None, None
        try:
            image = render_preview(request)
        except PreviewUnavailable as e:
            message = (str(e), "info")
        except Exception as e:
            message = (f"Preview failed: {e}", "error")
        elapsed = time.perf_counter() - started
        self.dispatch(self._finish, generation, image, message, elapsed, request.row.name)

    def _finish(self, generation, image, message, elapsed, row_label):
        if generation != self._generation:
            return  # a newer render superseded this one
        self._busy = False
        if message:
            self._show_message(*message)
            return
        self._image = image
        self._message = None
        self._fit_key = None
        month = f"  {Sym.bullet}  {MONTH_NAMES[self.state.month - 1]}" if self.state.project.is_calendar else ""
        self._info.configure(
            text=f"{image.width} × {image.height} px{month}  {Sym.bullet}  "
                 f"rendered in {elapsed * 1000:.0f} ms"
        )
        self._draw()

    def _show_message(self, text, level):
        self._busy = False
        self._image = None
        self._message = (text, level)
        self._info.configure(text="")
        self._draw()

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10 or h < 10:
            return

        if self._image is not None:
            m = px(MARGIN)
            scale = min((w - 2 * m) / self._image.width, (h - 2 * m) / self._image.height)
            tw, th = max(1, int(self._image.width * scale)), max(1, int(self._image.height * scale))
            key = (tw, th, id(self._image))
            if key != self._fit_key:
                fitted = self._image.resize((tw, th), Image.LANCZOS)
                self._photo = ImageTk.PhotoImage(fitted)
                self._fit_key = key
            x, y = (w - tw) // 2, (h - th) // 2
            c.create_rectangle(x + 3, y + 3, x + tw + 3, y + th + 3, fill="#cbd5e1", outline="")
            c.create_image(x, y, anchor="nw", image=self._photo)
        elif self._message:
            text, level = self._message
            color = C.danger if level == "error" else C.text_muted
            c.create_text(w // 2, h // 2, text=text, fill=color, font=font(10),
                          width=max(100, w - px(60)), justify="center")

        if self._busy:
            c.create_rectangle(px(10), px(10), px(110), px(34), fill=C.text, outline="")
            c.create_text(px(60), px(22), text="Rendering" + Sym.ellipsis, fill="white", font=F_SMALL)

    def open_full_size(self):
        if self._image is None:
            self.state.status("Nothing rendered yet", "warning")
            return
        path = os.path.join(tempfile.gettempdir(), "template_designer_preview.png")
        self._image.save(path)
        try:
            os.startfile(path)
        except AttributeError:
            self.state.status(f"Preview saved to {path}", "info")
