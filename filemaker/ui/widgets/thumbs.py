"""Small cached thumbnails for image and PDF files (main thread only)."""
import os

import pymupdf as fitz
from PIL import Image, ImageTk

_cache = {}


def _load(path):
    if path.lower().endswith(".pdf"):
        doc = fitz.open(path)
        try:
            pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(0.25, 0.25))
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()
    img = Image.open(path)
    img.draft("RGB", (400, 400))  # fast downscale for big JPEGs
    return img.convert("RGBA")


def thumbnail(path, max_size):
    """PhotoImage fitting in max_size x max_size, or None if unreadable."""
    if not path or not os.path.exists(path):
        return None
    try:
        key = (path, os.path.getmtime(path), max_size)
    except OSError:
        return None
    if key not in _cache:
        try:
            img = _load(path)
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            _cache[key] = ImageTk.PhotoImage(img)
        except Exception:
            _cache[key] = None
    return _cache[key]
