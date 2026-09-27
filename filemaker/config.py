"""App-wide constants: color palette and the default per-product config.

Centralising these here means the theme and the default calendar/normal
production settings can be tweaked in one place instead of hunting through
the UI code.
"""
from datetime import datetime

COLORS = {
    "primary": "#2563eb",
    "primary_dark": "#1e40af",
    "secondary": "#10b981",
    "bg_light": "#f5f7fa",
    "bg_white": "#ffffff",
    "border": "#e5e7eb",
    "text_dark": "#1f2937",
    "text_light": "#6b7280",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger": "#ef4444",
}

APP_TITLE = "Template Designer Pro - Excel to Design Automation"

# Sensible floor so the 3-pane layout never gets crushed unreadable.
MIN_WINDOW_SIZE = (1100, 650)


def default_product_config() -> dict:
    """A fresh product_config dict (never share/mutate a module-level literal)."""
    return {
        "type": "normal",
        "calendar_start_x": 0,
        "calendar_start_y": 0,
        "calendar_cell_width": 100,
        "calendar_cell_height": 80,
        "calendar_date_offset_x": 5,
        "calendar_date_offset_y": 5,
        "calendar_date_align": "left",
        "calendar_date_font_path": None,
        "calendar_date_font_size": 18,
        "calendar_date_fill": "#000000",
        "calendar_base_files": [],
        "calendar_year": datetime.now().year,
        "calendar_event_icons": [],
        "calendar_event_texts": [],
    }
