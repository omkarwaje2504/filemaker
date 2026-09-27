"""Batch production: readiness checks + a background run with progress,
per-row logging, abort, and a log file of every failure."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from multiprocessing.dummy import Pool as ThreadPool
from threading import Event, Thread

from ..core.worker import process_row
from ..models.project import Project


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""
    blocking: bool = True


def check_readiness(project: Project, df) -> list:
    checks = []
    rows = 0 if df is None else len(df)
    checks.append(Check("Data loaded", rows > 0, f"{rows} rows" if rows else "Load a spreadsheet in Data"))

    if project.is_calendar:
        checks.append(Check(
            "Design loaded", bool(project.design),
            "Optional in calendar mode" if not project.design else "",
            blocking=False,
        ))
        months = len(project.calendar.base_files) or (1 if project.base_file else 0)
        checks.append(Check(
            "Month artwork", months > 0,
            f"{months} file(s)" if months else "Add month artwork in Calendar",
        ))
    else:
        checks.append(Check(
            "Design loaded", bool(project.design),
            "" if project.design else "Load a design JSON in Template",
        ))
        checks.append(Check(
            "Base artwork", bool(project.base_file),
            os.path.basename(project.base_file) if project.base_file
            else "None - outputs get a white background",
            blocking=False,
        ))

    mapped = sum(1 for m in project.mappings if m.column)
    if project.mappings:
        checks.append(Check(
            "Fields mapped", mapped > 0,
            f"{mapped} of {len(project.mappings)}",
            blocking=False,
        ))

    checks.append(Check(
        "Output folder", bool(project.output_folder),
        project.output_folder or "Choose where files are written",
    ))
    return checks


def is_ready(checks) -> bool:
    return all(c.ok for c in checks if c.blocking)


@dataclass
class ProductionStats:
    rows_total: int
    outputs_expected: int
    rows_done: int = 0
    outputs_done: int = 0
    errors: int = 0
    skipped: int = 0
    aborted: bool = False
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    log_path: str = ""

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.monotonic()) - self.started_at

    @property
    def eta_seconds(self) -> float | None:
        if not self.rows_done or self.rows_done >= self.rows_total:
            return None
        return self.elapsed / self.rows_done * (self.rows_total - self.rows_done)


class ProductionRun:
    """Runs one production batch on a worker thread.

    Every callback is delivered through `dispatch(fn, *args)`, which the UI
    sets to `root.after(0, ...)` so handlers always run on the Tk thread.
    """

    def __init__(self, project: Project, df, dispatch, on_progress, on_log, on_finished):
        self.project = project
        self.df = df
        self._dispatch = dispatch
        self._on_progress = on_progress
        self._on_log = on_log
        self._on_finished = on_finished
        self._stop = Event()
        self._thread: Thread | None = None
        per_row = 12 if project.is_calendar else 1
        self.stats = ProductionStats(rows_total=len(df), outputs_expected=len(df) * per_row)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        os.makedirs(self.project.output_folder, exist_ok=True)
        # Snapshot everything now (caller's thread) so edits made while the
        # batch runs cannot leak into it.
        tasks = self._build_tasks()
        self._thread = Thread(target=self._run, args=(tasks,), daemon=True)
        self._thread.start()

    def abort(self) -> None:
        self._stop.set()

    def _build_tasks(self) -> list:
        p = self.project
        design = p.design_for_render()
        slot_vars = p.slot_vars()
        product_config = p.product_config()
        base = p.base_file_or_list()
        output_format = p.effective_output_format()
        columns = list(self.df.columns)
        filename_column = p.filename_column or None
        return [
            (
                idx, row.to_dict(), design, slot_vars, p.path_builder.base_folder,
                base, p.output_folder, output_format, columns, filename_column,
                product_config,
            )
            for idx, row in self.df.iterrows()
        ]

    def _run(self, tasks) -> None:
        stats = self.stats
        failures = []
        try:
            workers = max(1, int(self.project.workers or 1))
            with ThreadPool(processes=workers) as pool:
                for result in pool.imap_unordered(process_row, tasks):
                    if self._stop.is_set():
                        stats.aborted = True
                        pool.terminate()
                        break
                    self._record(result, failures)
        except Exception as e:
            stats.aborted = True
            failures.append(f"Production stopped: {e}")
            self._dispatch(self._on_log, f"Production stopped: {e}", "error")

        stats.finished_at = time.monotonic()
        if failures:
            stats.log_path = os.path.join(self.project.output_folder, "production_log.txt")
            try:
                with open(stats.log_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(failures))
            except OSError:
                stats.log_path = ""
        self._dispatch(self._on_finished, stats)

    def _record(self, result, failures) -> None:
        stats = self.stats
        idx, success, error, produced = result
        stats.rows_done += 1
        stats.outputs_done += produced or 0

        if not success:
            if error and "Missing images:" in error:
                stats.skipped += 1
                line = f"Row {idx} SKIPPED: {error}"
                level = "warning"
            else:
                stats.errors += 1
                line = f"Row {idx} ERROR: {error}"
                level = "error"
            failures.append(line)
            self._dispatch(self._on_log, line, level)

        self._dispatch(self._on_progress, stats)
