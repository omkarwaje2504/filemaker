"""String / value helpers shared across the app."""
import os


def extract_key(value: str) -> str:
    if not isinstance(value, str):
        return ""
    v = value.strip()
    if v.startswith("{{") and v.endswith("}}"):
        return v[2:-2]
    return v


def is_qr_data_static(data_str):
    """Check if data is QR code data"""
    data_str = str(data_str).strip()
    low = data_str.lower()

    if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        return False

    if low.startswith("http://") or low.startswith("https://"):
        return True
    

    if "/" in data_str or "\\" in data_str:
        return False

    return True


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def safe_str(val):
    if val is None:
        return ""

    try:
        import math
        if isinstance(val, float):
            if math.isnan(val):
                return ""
            if val.is_integer():
                return str(int(val))  # removes .0
    except Exception:
        pass

    s = str(val).strip()
    return "" if s.lower() == "nan" else s

