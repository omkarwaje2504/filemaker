"""Month-name detection for calendar base artwork filenames."""
import calendar as pycalendar
import os
import re

MONTH_NAMES = [pycalendar.month_name[m] for m in range(1, 13)]

_FULL = [(name.lower(), idx) for idx, name in enumerate(MONTH_NAMES, start=1)]
_ABBR = [(name[:3].lower(), idx) for idx, name in enumerate(MONTH_NAMES, start=1)]


def detect_month_index(filename):
    """1..12 from a filename like 'jan.png', 'March_cover.pdf', '07.png'; else None."""
    name = os.path.basename(filename).lower()
    for token, idx in _FULL:
        if token in name:
            return idx
    for token, idx in _ABBR:
        if token in name:
            return idx
    m = re.search(r"\b(0?[1-9]|1[0-2])\b", name)
    return int(m.group(1)) if m else None


def sort_by_month(files):
    """Detected months in calendar order, then undetected files in given order."""
    detected, unknown = [], []
    for f in files:
        m = detect_month_index(f)
        if m:
            detected.append((m, f))
        else:
            unknown.append(f)
    detected.sort(key=lambda x: x[0])
    return [f for _, f in detected] + unknown
