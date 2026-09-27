"""Final step - Output: where/how files are written, a readiness checklist,
and the production run (progress, ETA, live problem log)."""
import os
import tkinter as tk
from multiprocessing import cpu_count
from tkinter import messagebox, ttk

from ...core.calendar_render import month_output_basename
from ...services.production import ProductionRun, check_readiness, is_ready
from ...utils.text import safe_str
from ..theme import C, F_BOLD, F_MONO_SMALL, Sym, px
from ..widgets import Badge, ChoiceField, Form, Notice, NumberField, PathField, Tooltip
from .base import BaseView

FORMAT_LABELS = {"png": "PNG", "jpg": "JPG"}


def _fmt_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class OutputView(BaseView):
    key = "output"
    title = "Output & production"
    subtitle = "Choose where files go, check everything is ready, then run the batch."

    def __init__(self, parent, state, app):
        super().__init__(parent, state, app)
        self.build()
        state.subscribe("project", lambda **_: self._on_project())
        for topic in ("data", "design", "mode"):
            state.subscribe(topic, lambda **_: self._refresh_settings())
        state.subscribe("changed", lambda **_: self._refresh_dynamic())
        state.subscribe("row", lambda **_: self._refresh_example())

    def status(self):
        checks = check_readiness(self.state.project, self.state.df)
        if is_ready(checks):
            return "done" if all(c.ok for c in checks) else "warn"
        return "todo"

    def _on_project(self):
        if not self.state.is_running:
            self.rebuild()

    def build(self):
        self._build_settings_card()
        self._build_checklist_card()
        self._build_run_card()
        self._refresh_dynamic()

    # ----- settings -------------------------------------------------------

    def _build_settings_card(self):
        p = self.state.project
        card = self.card("Destination", "Where outputs are written and how they are named.")
        form = Form(card.body, columns=1, label_width=120)

        folder_row = ttk.Frame(form)
        folder_row.columnconfigure(0, weight=1)
        self._folder = PathField(folder_row, p.output_folder, self._set_folder, mode="folder",
                                 placeholder="Choose an output folder", title="Choose output folder")
        self._folder.grid(row=0, column=0, sticky="ew")
        self._open_folder = ttk.Button(folder_row, text="Open", style="Small.TButton",
                                       command=self._open_output_folder)
        self._open_folder.grid(row=0, column=1, padx=(px(6), 0))
        form.add("Output folder", folder_row)

        self._filename = ChoiceField(form, self.state.columns, p.filename_column,
                                     self.setter(p, "filename_column", "output"),
                                     none_label="— row number (output_0, output_1, …) —",
                                     width=36)
        self._example = ttk.Label(form, style="Small.TLabel")
        form.add("Name files by", self._filename)
        form.add("", self._example)

        self._format_cell = ttk.Frame(form)
        form.add("File format", self._format_cell)
        self._build_format()

        form.add("Parallel workers", NumberField(form, p.workers, self.setter(p, "workers", "output"),
                                                 from_=1, to=max(4, cpu_count() * 4), width=6),
                 hint=f"Rows rendered at the same time. Your CPU has {cpu_count()} threads.")
        form.pack(fill="x")

    def _build_format(self):
        cell = self._format_cell
        for child in cell.winfo_children():
            child.destroy()
        p = self.state.project
        if p.is_calendar:
            ttk.Label(cell, text="Per month artwork: PNG for image months, PDF for PDF months (300 DPI).",
                      style="Small.TLabel").pack(anchor="w")
            return
        if p.effective_output_format() == "pdf" and p.base_file.lower().endswith(".pdf"):
            ttk.Label(cell, text="PDF (vector) - set by the PDF base artwork", style="Small.TLabel").pack(anchor="w")
            return
        auto = "JPG" if p.base_file.lower().endswith((".jpg", ".jpeg")) else "PNG"
        ChoiceField(cell, ["", "png", "jpg"], p.output_format, self._set_format, allow_none=False,
                    labels={"": f"Automatic ({auto}, from base artwork)", **FORMAT_LABELS},
                    width=32).pack(anchor="w")

    def _set_folder(self, path):
        self.state.project.output_folder = path
        self.state.changed("output")

    def _set_format(self, value):
        self.state.project.output_format = value
        self.state.changed("output")

    def _refresh_settings(self):
        if not self._format_cell.winfo_exists():
            return
        self._filename.set_choices(self.state.columns)
        self._build_format()
        self._refresh_dynamic()

    def _refresh_example(self):
        if not self._example.winfo_exists():
            return
        p = self.state.project
        row = self.state.current_row()
        if row is None:
            self._example.configure(text="")
            return
        idx = row.name
        col = p.filename_column
        if col and col in row.index and safe_str(row[col]):
            base = os.path.splitext(safe_str(row[col]))[0]
        else:
            base = f"row{idx}" if p.is_calendar else f"output_{idx}"
        if p.is_calendar:
            text = f"{month_output_basename(base, 1)}.png  {Sym.ellipsis}  {month_output_basename(base, 12)}.png"
        else:
            text = f"{base}.{p.effective_output_format()}"
        self._example.configure(text=f"Preview row {Sym.arrow} {text}")

    # ----- checklist ------------------------------------------------------

    def _build_checklist_card(self):
        card = self.card("Ready to run?")
        self._ready_badge = Badge(card.actions)
        self._ready_badge.pack()
        self._checks = ttk.Frame(card.body)
        self._checks.pack(fill="x")

    def _refresh_checklist(self):
        checks = check_readiness(self.state.project, self.state.df)
        ready = is_ready(checks)
        self._ready_badge.set("Ready" if ready else "Not ready", "success" if ready else "danger")
        for child in self._checks.winfo_children():
            child.destroy()
        self._checks.columnconfigure(2, weight=1)
        for r, check in enumerate(checks):
            if check.ok:
                color, mark = C.success, Sym.check
            elif check.blocking:
                color, mark = C.danger, Sym.close
            else:
                color, mark = C.warning, "!"
            tk.Label(self._checks, text=mark, fg=color, bg=C.surface, font=F_BOLD, width=2).grid(
                row=r, column=0, sticky="w", pady=px(3))
            ttk.Label(self._checks, text=check.label, width=16).grid(row=r, column=1, sticky="w")
            ttk.Label(self._checks, text=check.detail, style="Small.TLabel").grid(row=r, column=2, sticky="w")
        return ready

    # ----- run ------------------------------------------------------------

    def _build_run_card(self):
        card = self.card("Production")
        self._summary = ttk.Label(card.body, style="Muted.TLabel")
        self._summary.pack(anchor="w", pady=(0, px(12)))

        buttons = ttk.Frame(card.body)
        buttons.pack(fill="x")
        self._start = ttk.Button(buttons, text=f"{Sym.next}  Start production", style="Large.Primary.TButton",
                                 command=self.start)
        self._start.pack(side="left")
        self._abort = ttk.Button(buttons, text="Stop", style="Large.Danger.TButton", command=self.abort)
        Tooltip(self._abort, "Stop after the rows already in progress finish")
        self._after_tools = ttk.Frame(buttons)

        self._progress = ttk.Progressbar(card.body, style="Accent.Horizontal.TProgressbar", mode="determinate")
        self._stats = ttk.Label(card.body, style="Small.TLabel")
        self._result = ttk.Frame(card.body)

        self._log_frame = ttk.Frame(card.body)
        ttk.Label(self._log_frame, text="PROBLEMS", style="Subtle.TLabel").pack(anchor="w", pady=(px(10), px(4)))
        wrap = ttk.Frame(self._log_frame)
        wrap.pack(fill="both", expand=True)
        self._log = tk.Text(wrap, height=8, font=F_MONO_SMALL, bg=C.surface_alt, fg=C.text,
                            relief="flat", borderwidth=0, highlightthickness=1,
                            highlightbackground=C.border, wrap="none", state="disabled")
        log_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=log_scroll.set)
        self._log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        self._log.tag_configure("error", foreground=C.danger)
        self._log.tag_configure("warning", foreground=C.warning)

    def _refresh_dynamic(self):
        if not getattr(self, "_summary", None) or not self._summary.winfo_exists():
            return
        ready = self._refresh_checklist()
        self._refresh_example()
        p = self.state.project
        rows = self.state.row_count
        per_row = 12 if p.is_calendar else 1
        if rows:
            outputs = f"{rows:,} rows × 12 months = {rows * per_row:,} files" if p.is_calendar \
                else f"{rows:,} files"
            where = f"  {Sym.arrow}  {p.output_folder}" if p.output_folder else ""
            self._summary.configure(text=f"{outputs}{where}")
        else:
            self._summary.configure(text="Load data to see how many files will be produced.")
        if not self.state.is_running:
            self._start.state(["!disabled"] if ready else ["disabled"])
        self._open_folder.state(["!disabled"] if p.output_folder and os.path.isdir(p.output_folder)
                                else ["disabled"])

    def start(self):
        state = self.state
        checks = check_readiness(state.project, state.df)
        if not is_ready(checks):
            missing = "\n".join(f"{Sym.bullet} {c.label}: {c.detail}" for c in checks if c.blocking and not c.ok)
            messagebox.showwarning("Not ready", f"Fix these first:\n\n{missing}", parent=self)
            return
        p = state.project
        rows = state.row_count
        total = rows * (12 if p.is_calendar else 1)
        fmt = "PNG/PDF per month" if p.is_calendar else p.effective_output_format().upper()
        if not messagebox.askyesno(
            "Start production",
            f"Produce {total:,} file(s) from {rows:,} row(s)?\n\n"
            f"Format: {fmt}, 300 DPI\nWorkers: {p.workers}\nFolder: {p.output_folder}",
            parent=self,
        ):
            return

        run = ProductionRun(p, state.df, self.app.dispatch, self._on_progress, self._on_log, self._on_finished)
        try:
            run.start()
        except OSError as e:
            messagebox.showerror("Cannot start", f"Could not use the output folder:\n\n{e}", parent=self)
            return
        state.production = run

        self._start.pack_forget()
        self._after_tools.pack_forget()
        self._abort.state(["!disabled"])
        self._abort.pack(side="left")
        for child in self._result.winfo_children():
            child.destroy()
        self._result.pack_forget()
        self._progress.configure(maximum=max(1, run.stats.rows_total), value=0)
        self._progress.pack(fill="x", pady=(px(14), px(4)))
        self._stats.pack(anchor="w")
        self._set_log("")
        self._log_frame.pack_forget()
        self._on_progress(run.stats)
        state.publish("production", phase="started", stats=run.stats)
        state.status(f"Production started: {total:,} file(s)")

    def abort(self):
        if self.state.production:
            self.state.production.abort()
            self._abort.state(["disabled"])
            self.state.status("Stopping after the current rows" + Sym.ellipsis, "warning")

    def _on_progress(self, stats):
        self._progress.configure(value=stats.rows_done)
        eta = stats.eta_seconds
        parts = [
            f"Rows {stats.rows_done:,} / {stats.rows_total:,}",
            f"{stats.outputs_done:,} file(s) written",
        ]
        if stats.errors:
            parts.append(f"{stats.errors} error(s)")
        if stats.skipped:
            parts.append(f"{stats.skipped} skipped")
        parts.append(f"{_fmt_duration(stats.elapsed)} elapsed")
        if eta is not None:
            parts.append(f"~{_fmt_duration(eta)} left")
        self._stats.configure(text=f"  {Sym.bullet}  ".join(parts))
        self.state.publish("production", phase="progress", stats=stats)

    def _on_log(self, line, level):
        if not self._log_frame.winfo_ismapped():
            self._log_frame.pack(fill="both", expand=True)
        self._log.configure(state="normal")
        self._log.insert("end", line + "\n", level)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _on_finished(self, stats):
        self.state.production = None
        self._on_progress(stats)
        self._abort.pack_forget()
        self._start.pack(side="left")
        self._refresh_dynamic()

        for child in self._after_tools.winfo_children():
            child.destroy()
        ttk.Button(self._after_tools, text="Open output folder",
                   command=self._open_output_folder).pack(side="left", padx=(px(8), 0))
        if stats.log_path:
            ttk.Button(self._after_tools, text="Open log",
                       command=lambda: os.startfile(stats.log_path)).pack(side="left", padx=(px(6), 0))
        self._after_tools.pack(side="left")

        problems = stats.errors + stats.skipped
        if stats.aborted:
            text, level = f"Stopped. {stats.outputs_done:,} file(s) were written before stopping.", "warning"
        elif problems:
            text, level = (f"Finished with problems: {stats.outputs_done:,} file(s) written, "
                           f"{stats.errors} error(s), {stats.skipped} skipped (missing images)."), "warning"
        else:
            text, level = f"Done. {stats.outputs_done:,} file(s) written in {_fmt_duration(stats.elapsed)}.", "success"
        if stats.log_path:
            text += f"\nDetails: {stats.log_path}"
        Notice(self._result, text, level).pack(fill="x")
        self._result.pack(fill="x", pady=(px(12), 0), before=self._log_frame
                          if self._log_frame.winfo_ismapped() else None)
        self.state.publish("production", phase="finished", stats=stats)
        self.state.status(text.split("\n")[0], "success" if level == "success" else "warning")
        self.bell()

    def _set_log(self, text):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.insert("end", text)
        self._log.configure(state="disabled")

    def _open_output_folder(self):
        folder = self.state.project.output_folder
        if folder and os.path.isdir(folder):
            os.startfile(folder)
