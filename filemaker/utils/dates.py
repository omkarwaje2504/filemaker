"""Flexible date parsing helpers."""
from datetime import datetime

from .text import safe_str


def parse_month_from_flex_date(date_str: str):
    """
    Accepts strings like:
      '11/01/1969', '11/01/69', '11/01/', '11/01'
      '11-01-2023', '11-01'
    Returns month index (1..12) or None.
    """
    if not date_str:
        return None

    s = safe_str(date_str).strip()
    if not s:
        return None

    s = s.replace("-", "/")

    # Case: DD/MM/
    if s.endswith("/"):
        s += "2000"

    # Case: DD/MM
    if s.count("/") == 1:
        s += "/2000"

    # Try full date formats
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.month
        except:
            pass

    # Fallback: extract month manually
    parts = s.split("/")
    if len(parts) >= 2:
        try:
            m = int(parts[1])
            if 1 <= m <= 12:
                return m
        except:
            pass

    # Final fallback: regex (rare)
    import re
    m = re.search(r"\b(0?[1-9]|1[0-2])\b", s)
    if m:
        return int(m.group(1))

    return None

