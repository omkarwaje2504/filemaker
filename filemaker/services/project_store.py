"""Save / open project files (*.tdtpl.json).

v2 files store the whole Project. v1 files (written by the old single-file
app: product_type / design / product_config / slot_vars) still open.
"""
import json
import os
from datetime import datetime

from ..models.project import MODE_CALENDAR, MODE_NORMAL, CalendarSettings, Project
from .data_service import build_mappings

FILE_FORMAT = "template-designer-project"
FILE_VERSION = 2
PROJECT_FILETYPES = [("Template project", "*.tdtpl.json"), ("JSON", "*.json"), ("All files", "*.*")]
PROJECT_EXTENSION = ".tdtpl.json"


def save_project(path: str, project: Project) -> None:
    payload = {
        "format": FILE_FORMAT,
        "version": FILE_VERSION,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "project": project.to_dict(),
    }
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def load_project(path: str) -> Project:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") == FILE_FORMAT:
        return Project.from_dict(data.get("project"))
    return _from_v1(data)


def _from_v1(data: dict) -> Project:
    project = Project(
        mode=MODE_CALENDAR if data.get("product_type") == MODE_CALENDAR else MODE_NORMAL,
        design=data.get("design"),
        calendar=CalendarSettings.from_product_config(data.get("product_config") or {}),
    )
    project.mappings = build_mappings(project.design)
    slot_vars = data.get("slot_vars") or {}
    for m in project.mappings:
        column = (slot_vars.get(m.slot_id) or {}).get("value")
        if column:
            m.column = column
        font = (slot_vars.get(f"{m.slot_id}_FONT") or {}).get("path")
        if font:
            m.font_path = font
    return project
