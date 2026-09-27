"""Design system: colors, fonts, DPI-aware sizing, and ttk styles.

Every screen pulls its look from here, so restyling the app means editing
this one file.
"""
import tkinter as tk
from tkinter import ttk


class C:
    """Color palette (slate neutrals + indigo accent)."""

    app_bg = "#f1f5f9"
    surface = "#ffffff"
    surface_alt = "#f8fafc"
    border = "#e2e8f0"
    border_strong = "#cbd5e1"

    text = "#0f172a"
    text_muted = "#64748b"
    text_subtle = "#94a3b8"

    primary = "#4f46e5"
    primary_hover = "#4338ca"
    primary_pressed = "#3730a3"
    primary_soft = "#eef2ff"
    primary_disabled = "#a5b4fc"

    success = "#16a34a"
    success_soft = "#dcfce7"
    warning = "#d97706"
    warning_soft = "#fef3c7"
    danger = "#dc2626"
    danger_hover = "#b91c1c"
    danger_soft = "#fee2e2"

    sidebar_bg = "#0f172a"
    sidebar_hover = "#1e293b"
    sidebar_active = "#1e293b"
    sidebar_text = "#cbd5e1"
    sidebar_muted = "#64748b"

    canvas_bg = "#e2e8f0"


class Sym:
    """Symbols that Tk renders reliably on Windows (no emoji)."""

    prev = "◀"  # ◀
    next = "▶"  # ▶
    up = "▲"  # ▲
    down = "▼"  # ▼
    dot = "●"  # ●
    close = "✕"  # ✕
    check = "✓"  # ✓
    refresh = "↻"  # ↻
    arrow = "→"  # →
    bullet = "·"  # ·
    ellipsis = "…"  # …


FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"
_scale = 1.0


def px(value: float) -> int:
    """Scale a pixel measurement for the current screen DPI."""
    return int(round(value * _scale))


def font(size=10, weight="normal", family=None):
    return (family or FONT_FAMILY, size, weight)


F_BASE = font(10)
F_SMALL = font(9)
F_TINY = font(8)
F_BOLD = font(10, "bold")
F_H1 = font(17, "bold")
F_H2 = font(11, "bold")
F_BRAND = font(12, "bold")
F_MONO = (MONO_FAMILY, 9)
F_MONO_SMALL = (MONO_FAMILY, 8)


def init_theme(root: tk.Tk) -> None:
    global _scale
    _scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

    root.option_add("*Font", F_BASE)
    root.option_add("*TCombobox*Listbox.font", F_BASE)
    root.option_add("*TCombobox*Listbox.selectBackground", C.primary)
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    root.configure(bg=C.app_bg)

    s = ttk.Style(root)
    s.theme_use("clam")

    s.configure(
        ".",
        font=F_BASE,
        background=C.surface,
        foreground=C.text,
        bordercolor=C.border,
        lightcolor=C.surface,
        darkcolor=C.surface,
        troughcolor=C.app_bg,
        focuscolor=C.primary,
        selectbackground=C.primary,
        selectforeground="white",
        insertcolor=C.text,
    )

    # ---- frames & labels ------------------------------------------------
    s.configure("TFrame", background=C.surface)
    s.configure("App.TFrame", background=C.app_bg)
    s.configure("Alt.TFrame", background=C.surface_alt)
    s.configure("TLabel", background=C.surface, foreground=C.text)
    s.configure("Muted.TLabel", foreground=C.text_muted)
    s.configure("Subtle.TLabel", foreground=C.text_subtle, font=F_SMALL)
    s.configure("Small.TLabel", font=F_SMALL, foreground=C.text_muted)
    s.configure("Bold.TLabel", font=F_BOLD)
    s.configure("H2.TLabel", font=F_H2)
    s.configure("Mono.TLabel", font=F_MONO, foreground=C.text_muted)
    s.configure("Alt.TLabel", background=C.surface_alt)
    s.configure("AltMuted.TLabel", background=C.surface_alt, foreground=C.text_muted, font=F_SMALL)
    s.configure("PageTitle.TLabel", background=C.app_bg, font=F_H1)
    s.configure("PageSub.TLabel", background=C.app_bg, foreground=C.text_muted)
    s.configure("Success.TLabel", foreground=C.success)
    s.configure("Warning.TLabel", foreground=C.warning)
    s.configure("Danger.TLabel", foreground=C.danger)

    # ---- buttons --------------------------------------------------------
    s.configure(
        "TButton",
        padding=(px(12), px(6)),
        relief="flat",
        borderwidth=1,
        background=C.surface,
        foreground=C.text,
        bordercolor=C.border_strong,
        lightcolor=C.surface,
        darkcolor=C.surface,
        focusthickness=0,
        focuscolor=C.surface,
        anchor="center",
    )
    s.map(
        "TButton",
        background=[("disabled", C.surface_alt), ("pressed", C.border), ("active", C.surface_alt)],
        foreground=[("disabled", C.text_subtle)],
        lightcolor=[("pressed", C.border), ("active", C.surface_alt)],
        darkcolor=[("pressed", C.border), ("active", C.surface_alt)],
    )
    _solid_button(s, "Primary.TButton", C.primary, C.primary_hover, C.primary_pressed, C.primary_disabled)
    _solid_button(s, "Danger.TButton", C.danger, C.danger_hover, C.danger_hover, "#fca5a5")
    s.configure("Ghost.TButton", bordercolor=C.surface, foreground=C.primary, padding=(px(6), px(4)))
    s.map(
        "Ghost.TButton",
        background=[("active", C.primary_soft)],
        bordercolor=[("active", C.primary_soft)],
        lightcolor=[("active", C.primary_soft)],
        darkcolor=[("active", C.primary_soft)],
        foreground=[("disabled", C.text_subtle)],
    )
    for base in ("TButton", "Primary.TButton", "Ghost.TButton", "Danger.TButton"):
        s.configure(f"Small.{base}", padding=(px(8), px(3)), font=F_SMALL)
    s.configure("Icon.TButton", padding=(px(6), px(2)), font=F_SMALL)
    s.configure("Large.Primary.TButton", padding=(px(20), px(10)), font=F_BOLD)
    s.configure("Large.Danger.TButton", padding=(px(20), px(10)), font=F_BOLD)

    # ---- inputs ---------------------------------------------------------
    field_opts = dict(
        padding=(px(8), px(5)),
        fieldbackground=C.surface,
        bordercolor=C.border_strong,
        lightcolor=C.surface,
        darkcolor=C.surface,
        arrowcolor=C.text_muted,
        arrowsize=px(12),
    )
    field_map = dict(
        bordercolor=[("focus", C.primary)],
        lightcolor=[("focus", C.primary)],
        fieldbackground=[("readonly", C.surface), ("disabled", C.surface_alt)],
        foreground=[("disabled", C.text_subtle)],
    )
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        s.configure(name, **field_opts)
        s.map(name, **field_map)
        s.configure(f"Invalid.{name}", bordercolor=C.danger, lightcolor=C.danger)
    s.configure("Path.TEntry", foreground=C.text_muted)

    s.configure("TCheckbutton", background=C.surface, focuscolor=C.surface, indicatorbackground=C.surface,
                indicatorforeground="white", indicatormargin=(0, 0, px(6), 0))
    s.map("TCheckbutton", indicatorbackground=[("selected", C.primary)],
          background=[("active", C.surface)])

    # ---- data, progress, scroll, panes ---------------------------------
    s.configure("Treeview", background=C.surface, fieldbackground=C.surface, foreground=C.text,
                rowheight=px(26), borderwidth=0)
    s.configure("Treeview.Heading", background=C.surface_alt, foreground=C.text_muted,
                font=font(9, "bold"), relief="flat", padding=(px(8), px(6)), bordercolor=C.border)
    s.map("Treeview", background=[("selected", C.primary)], foreground=[("selected", "white")])
    s.map("Treeview.Heading", background=[("active", C.border)])

    s.configure("Accent.Horizontal.TProgressbar", troughcolor=C.border, background=C.primary,
                bordercolor=C.border, lightcolor=C.primary, darkcolor=C.primary, thickness=px(8))

    for orient in ("Vertical", "Horizontal"):
        s.configure(f"{orient}.TScrollbar", background=C.border, troughcolor=C.surface,
                    bordercolor=C.surface, lightcolor=C.border, darkcolor=C.border,
                    arrowcolor=C.text_muted, arrowsize=px(12), gripcount=0)
        s.map(f"{orient}.TScrollbar", background=[("active", C.border_strong)])

    s.configure("TPanedwindow", background=C.app_bg)
    s.configure("Sash", sashthickness=px(6), background=C.app_bg, gripcount=0)

    s.configure("TSeparator", background=C.border)


def _solid_button(s, name, bg, hover, pressed, disabled):
    s.configure(name, background=bg, foreground="white", bordercolor=bg, lightcolor=bg, darkcolor=bg)
    s.map(
        name,
        background=[("disabled", disabled), ("pressed", pressed), ("active", hover)],
        bordercolor=[("disabled", disabled), ("pressed", pressed), ("active", hover)],
        lightcolor=[("disabled", disabled), ("pressed", pressed), ("active", hover)],
        darkcolor=[("disabled", disabled), ("pressed", pressed), ("active", hover)],
        foreground=[("disabled", "white")],
    )
