"""Modern ttk theme for opngx UI.

Uses platform-appropriate fonts and a clean flat palette; safe on every
Tk build from 8.6 onwards.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Any


# palette ------------------------------------------------------------------
BG = "#0f172a"  # window background  (deep slate)
CARD = "#1e293b"  # card background
CARD2 = "#273449"  # input background
FG = "#e2e8f0"  # primary text
MUTED = "#94a3b8"  # secondary text
ACCENT = "#3b82f6"  # primary action blue
ACCENT_H = "#2563eb"
DANGER = "#dc2626"
DANGER_H = "#b91c1c"
OK = "#10b981"
BORDER = "#334155"


def font_family(root: tk.Misc) -> str:
    """Pick the best sans font available per platform."""
    fams = set(tkfont.families(root))
    for cand in (
        "Segoe UI",
        "SF Pro Text",
        "Ubuntu",
        "DejaVu Sans",
        "Noto Sans",
        "Helvetica",
    ):
        if cand in fams:
            return cand
    return "TkDefaultFont"


def mono_family(root: tk.Misc) -> str:
    fams = set(tkfont.families(root))
    for cand in (
        "Cascadia Mono",
        "Consolas",
        "JetBrains Mono",
        "DejaVu Sans Mono",
        "Menlo",
        "Courier New",
    ):
        if cand in fams:
            return cand
    return "TkFixedFont"


def apply_theme(root: tk.Tk) -> dict[str, Any]:
    """Configure the ttk theme; returns useful font objects."""
    fam = font_family(root)
    mono = mono_family(root)
    normal = tkfont.Font(family=fam, size=10)
    small = tkfont.Font(family=fam, size=9)
    bold = tkfont.Font(family=fam, size=10, weight="bold")
    title = tkfont.Font(family=fam, size=13, weight="bold")
    monof = tkfont.Font(family=mono, size=9)

    style = ttk_style = root.nametowidget(".") if False else None  # noqa
    from tkinter import ttk

    style = ttk.Style(root)

    root.configure(bg=BG)

    style.theme_use("clam")

    style.configure(".", background=BG, foreground=FG, font=normal)
    style.configure("TFrame", background=BG)
    style.configure(
        "TLabelframe",
        background=CARD,
        foreground=FG,
        bordercolor=BORDER,
        relief="solid",
        borderwidth=1,
    )
    style.configure("TLabelframe.Label", background=CARD, foreground=MUTED, font=small)
    style.configure("TLabel", background=CARD, foreground=FG)
    style.configure("Muted.TLabel", foreground=MUTED, font=small)
    style.configure("Title.TLabel", font=title, background=BG, foreground="#f8fafc")
    style.configure(
        "Status.TLabel", background=CARD2, foreground=MUTED, font=small, padding=(10, 5)
    )

    # buttons ----------------------------------------------------------
    style.configure(
        "TButton",
        background=CARD2,
        foreground=FG,
        bordercolor=BORDER,
        focusthickness=0,
        padding=(12, 7),
        font=normal,
    )
    style.map(
        "TButton",
        background=[("active", BORDER), ("disabled", "#1b2436")],
        foreground=[("disabled", "#475569")],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="white",
        bordercolor=ACCENT,
        padding=(16, 8),
        font=bold,
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_H), ("disabled", "#26456b")],
        foreground=[("disabled", "#7d97bd")],
    )
    style.configure(
        "Danger.TButton",
        background=DANGER,
        foreground="white",
        bordercolor=DANGER,
        padding=(14, 8),
        font=bold,
    )
    style.map(
        "Danger.TButton", background=[("active", DANGER_H), ("disabled", "#5b2323")]
    )

    # entries / spins / combos -----------------------------------------
    style.configure(
        "TEntry",
        fieldbackground=CARD2,
        foreground=FG,
        insertcolor=FG,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=5,
    )
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure(
        "TSpinbox",
        fieldbackground=CARD2,
        foreground=FG,
        arrowcolor=FG,
        bordercolor=BORDER,
        padding=4,
    )
    style.configure(
        "TCombobox",
        fieldbackground=CARD2,
        foreground=FG,
        arrowcolor=FG,
        bordercolor=BORDER,
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", CARD2)],
        foreground=[("readonly", FG)],
    )
    root.option_add("*TCombobox*Listbox.background", CARD2)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    # radio / check ------------------------------------------------------
    style.configure(
        "TRadiobutton", background=CARD, foreground=FG, focuscolor=ACCENT, font=normal
    )
    style.map(
        "TRadiobutton",
        background=[("active", CARD)],
        indicatorcolor=[("selected", ACCENT)],
    )
    style.configure("TCheckbutton", background=CARD, foreground=FG, focuscolor=ACCENT)
    style.map(
        "TCheckbutton",
        background=[("active", CARD)],
        indicatorcolor=[("selected", ACCENT)],
    )

    # scale ---------------------------------------------------------------
    style.configure(
        "Horizontal.TScale",
        background=CARD,
        troughcolor=CARD2,
        bordercolor=CARD2,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )

    # progress ------------------------------------------------------------
    style.configure(
        "Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=CARD2,
        bordercolor=CARD2,
        thickness=10,
    )

    # treeview (info table) ------------------------------------------------
    style.configure(
        "Treeview",
        background=CARD2,
        foreground=FG,
        fieldbackground=CARD2,
        rowheight=24,
        bordercolor=CARD2,
        font=normal,
    )
    style.configure(
        "Treeview.Heading", background=CARD, foreground=MUTED, font=small, relief="flat"
    )
    style.map("Treeview", background=[("selected", ACCENT)])

    # scrollbar -------------------------------------------------------------
    style.configure(
        "Vertical.TScrollbar",
        background=CARD2,
        troughcolor=CARD,
        bordercolor=CARD,
        arrowcolor=MUTED,
    )

    return {
        "normal": normal,
        "small": small,
        "bold": bold,
        "title": title,
        "mono": monof,
        "family": fam,
    }
