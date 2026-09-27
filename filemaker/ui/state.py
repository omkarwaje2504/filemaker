"""AppState: the single source of truth the UI reads and writes.

Panels never talk to each other directly. They call actions here and
subscribe to topics:

    "project"  - a whole new project was created/opened (rebuild everything)
    "data"     - the data table was loaded or its columns changed
    "design"   - the design JSON (and so the field mappings) changed
    "mode"     - normal <-> calendar
    "changed"  - any setting edited (section=...); marks the project dirty
    "row"      - the row shown in the preview changed
    "month"    - the calendar month shown in the preview changed
    "status"   - a message for the status bar (text=, level=)
    "production" - a batch run started/progressed/finished (phase=, stats=)
"""
from __future__ import annotations

import os
from collections import defaultdict

from ..models.project import MODE_CALENDAR, MODE_NORMAL, Project
from ..services import data_service, project_store
from .theme import Sym


class AppState:
    def __init__(self):
        self.project = Project()
        self.project_path = ""
        self.df = None
        self.row_pos: int | None = None
        self.month = 1
        self.dirty = False
        self.production = None  # services.production.ProductionRun while running
        self._subscribers = defaultdict(list)

    # ----- pub/sub -------------------------------------------------------

    def subscribe(self, topic: str, callback) -> None:
        self._subscribers[topic].append(callback)

    def publish(self, topic: str, **data) -> None:
        for callback in list(self._subscribers[topic]):
            callback(**data)

    def status(self, text: str, level: str = "info") -> None:
        self.publish("status", text=text, level=level)

    def changed(self, section: str) -> None:
        self.dirty = True
        self.publish("changed", section=section)

    # ----- derived -------------------------------------------------------

    @property
    def columns(self) -> list:
        return [] if self.df is None else [str(c) for c in self.df.columns]

    @property
    def row_count(self) -> int:
        return 0 if self.df is None else len(self.df)

    def current_row(self):
        if self.df is None or self.row_pos is None or not (0 <= self.row_pos < len(self.df)):
            return None
        return self.df.iloc[self.row_pos]

    @property
    def project_name(self) -> str:
        if not self.project_path:
            return "Untitled project"
        name = os.path.basename(self.project_path)
        return name[: -len(project_store.PROJECT_EXTENSION)] if name.endswith(project_store.PROJECT_EXTENSION) else name

    @property
    def is_running(self) -> bool:
        return self.production is not None and self.production.running

    # ----- project lifecycle --------------------------------------------

    def new_project(self) -> None:
        self.project = Project()
        self.project_path = ""
        self.df = None
        self.row_pos = None
        self.month = 1
        self.dirty = False
        self.publish("project")
        self.status("New project")

    def open_project(self, path: str) -> list:
        """Open a project file. Returns warnings (e.g. data file moved)."""
        project = project_store.load_project(path)
        warnings = []
        df = None
        if project.data_path:
            if os.path.exists(project.data_path):
                df = data_service.load_table(project.data_path)
            else:
                warnings.append(f"Data file not found, load it again:\n{project.data_path}")
        if project.design_path and not project.design and os.path.exists(project.design_path):
            project.design = data_service.load_design(project.design_path)
            project.mappings = data_service.build_mappings(project.design, project.mappings)

        self.project = project
        self.project_path = path
        self.df = df
        self.row_pos = 0 if df is not None and len(df) else None
        self.month = 1
        self.dirty = False
        self.publish("project")
        self.status(f"Opened {os.path.basename(path)}", "success")
        return warnings

    def save_project(self, path: str) -> None:
        project_store.save_project(path, self.project)
        self.project_path = path
        self.dirty = False
        self.publish("changed", section="saved")
        self.status(f"Saved {os.path.basename(path)}", "success")

    # ----- actions --------------------------------------------------------

    def load_data(self, path: str) -> None:
        self.df = data_service.load_table(path)
        self.project.data_path = path
        self.row_pos = 0 if len(self.df) else None
        filled = data_service.auto_map(self.project.mappings, self.columns)
        self.dirty = True
        self.publish("data")
        self.publish("row")
        extra = f" {Sym.bullet} auto-mapped {filled} field(s)" if filled else ""
        self.status(f"Loaded {os.path.basename(path)}: {len(self.df)} rows{extra}", "success")

    def replace_df(self, df, message: str) -> None:
        """The table was modified in place (e.g. path builder added a column)."""
        self.df = df
        data_service.auto_map(self.project.mappings, self.columns)
        self.publish("data")
        self.publish("row")
        self.status(message, "success")

    def load_design(self, path: str) -> None:
        design = data_service.load_design(path)
        self.project.design = design
        self.project.design_path = path
        self.project.mappings = data_service.build_mappings(design, self.project.mappings)
        filled = data_service.auto_map(self.project.mappings, self.columns)
        self.changed("design")
        self.publish("design")
        extra = f", auto-mapped {filled}" if filled else ""
        self.status(f"Loaded design {os.path.basename(path)}{extra}", "success")

    def auto_map(self) -> int:
        filled = data_service.auto_map(self.project.mappings, self.columns)
        if filled:
            self.changed("mapping")
            self.publish("design")
        return filled

    def set_mode(self, mode: str) -> None:
        mode = MODE_CALENDAR if mode == MODE_CALENDAR else MODE_NORMAL
        if mode == self.project.mode:
            return
        self.project.mode = mode
        self.changed("mode")
        self.publish("mode")
        self.status("Calendar mode: 12 outputs per row" if mode == MODE_CALENDAR else "Normal mode: 1 output per row")

    def select_row(self, pos: int | None) -> None:
        if self.df is None or pos is None:
            return
        pos = max(0, min(int(pos), len(self.df) - 1))
        if pos != self.row_pos:
            self.row_pos = pos
            self.publish("row")

    def step_row(self, delta: int) -> None:
        if self.row_pos is not None:
            self.select_row(self.row_pos + delta)

    def select_month(self, month: int) -> None:
        month = max(1, min(12, int(month)))
        if month != self.month:
            self.month = month
            self.publish("month")
