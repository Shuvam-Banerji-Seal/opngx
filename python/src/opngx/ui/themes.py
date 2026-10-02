"""Colour themes for the Qt studio (v2.0).

The stylesheet and the painted widgets were written against one palette
("Midnight": black + coffee green). Rather than maintaining a copy of the
stylesheet per theme, every colour of that palette is assigned a ROLE
(window background, card, input, border, text, accent, …) and a theme is
just a value per role. `recolor()` rewrites any stylesheet/HTML string, and
widgets that paint themselves ask `qcolor(role)` at paint time, so a theme
switch is live: View → Theme, or a custom accent from the colour picker.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------- roles --
# every Midnight colour used anywhere in the studio -> its role
ROLE_OF: dict[str, str] = {
    "#050505": "bg", "#000000": "viewer_bg",
    "#0d0f0d": "surface", "#0a0c0a": "surface_low", "#0d120d": "surface",
    "#10140f": "button", "#070807": "input",
    "#182018": "hover", "#16200f": "hover", "#14200f": "hover", "#22301f": "pressed",
    "#1f261f": "border", "#161b16": "border", "#2a332a": "border_input", "#1b221b": "grid",
    "#2f4a2c": "border_accent", "#3e6b3a": "accent_dim", "#3a4a38": "border_accent",
    "#e8ede8": "text", "#e6ece6": "text", "#dfe6df": "text", "#f0f4f0": "text", "#eaf2ea": "text",
    "#ffffff": "text_bright", "#f0fff0": "text_bright", "#d9ead3": "accent_light",
    "#fefefe": "on_accent",
    "#9ab294": "text_dim", "#8a948a": "text_dim", "#7d8a7d": "text_dim", "#a8c9a3": "text_dim",
    "#94a3b8": "text_dim", "#7fa277": "heading3",
    "#4a554a": "text_muted", "#5d6b5d": "text_muted", "#475569": "text_muted",
    "#4d8248": "accent", "#588157": "accent", "#57914f": "accent_hover",
    "#7fb069": "accent_fg", "#8fbf7f": "accent_fg", "#35542f": "selection",
    "#7a2222": "danger", "#962b2b": "danger_hover", "#2a1414": "danger_off",
    "#ffecec": "on_danger", "#6b4444": "danger_off_text",
    "#60a5fa": "heading", "#93c5fd": "heading2",
    "#fbbf24": "warn", "#34d399": "ok", "#f87171": "err",
    "#ff5d8f": "marker", "#ffc440": "trace",
}

ROLES = sorted(set(ROLE_OF.values()))

# ---------------------------------------------------------------- themes --
MIDNIGHT = {
    "bg": "#050505", "viewer_bg": "#000000", "surface": "#0d0f0d", "surface_low": "#0a0c0a",
    "button": "#10140f", "input": "#070807", "hover": "#182018", "pressed": "#22301f",
    "border": "#1f261f", "border_input": "#2a332a", "grid": "#1b221b", "border_accent": "#2f4a2c",
    "accent_dim": "#3e6b3a", "text": "#e8ede8", "text_bright": "#ffffff", "accent_light": "#d9ead3",
    "on_accent": "#ffffff", "text_dim": "#9ab294", "heading3": "#7fa277", "text_muted": "#4a554a",
    "accent": "#4d8248", "accent_hover": "#57914f", "accent_fg": "#7fb069", "selection": "#35542f",
    "danger": "#7a2222", "danger_hover": "#962b2b", "danger_off": "#2a1414", "on_danger": "#ffecec",
    "danger_off_text": "#6b4444", "heading": "#60a5fa", "heading2": "#93c5fd", "warn": "#fbbf24",
    "ok": "#34d399", "err": "#f87171", "marker": "#ff5d8f", "trace": "#ffc440",
    "dark": True,
}


def _catppuccin(base, mantle, crust, s0, s1, s2, o0, o1, text, sub0, sub1, accent, accent2,
                red, green, yellow, blue, sky, pink, peach, dark=True):
    return {
        "bg": crust, "viewer_bg": crust if dark else mantle, "surface": mantle, "surface_low": crust,
        "button": s0, "input": base, "hover": s1, "pressed": s2,
        "border": s0, "border_input": s1, "grid": s0, "border_accent": s2,
        "accent_dim": accent2, "text": text, "text_bright": text, "accent_light": base,
        "on_accent": crust if dark else base, "text_dim": sub0, "heading3": accent, "text_muted": o0,
        "accent": accent, "accent_hover": accent2, "accent_fg": accent, "selection": s2,
        "danger": red, "danger_hover": peach, "danger_off": s0, "on_danger": crust if dark else base,
        "danger_off_text": o1, "heading": blue, "heading2": sky, "warn": yellow,
        "ok": green, "err": red, "marker": pink, "trace": peach, "dark": dark,
    }


THEMES: dict[str, dict] = {
    "Midnight": MIDNIGHT,
    "Catppuccin Latte": _catppuccin(
        "#eff1f5", "#e6e9ef", "#dce0e8", "#ccd0da", "#bcc0cc", "#acb0be", "#9ca0b0", "#8c8fa1",
        "#4c4f69", "#6c6f85", "#5c5f77", "#8839ef", "#7287fd", "#d20f39", "#40a02b", "#df8e1d",
        "#1e66f5", "#04a5e5", "#ea76cb", "#fe640b", dark=False),
    "Catppuccin Frappé": _catppuccin(
        "#303446", "#292c3c", "#232634", "#414559", "#51576d", "#626880", "#737994", "#838ba7",
        "#c6d0f5", "#a5adce", "#b5bfe2", "#ca9ee6", "#babbf1", "#e78284", "#a6d189", "#e5c890",
        "#8caaee", "#99d1db", "#f4b8e4", "#ef9f76"),
    "Catppuccin Macchiato": _catppuccin(
        "#24273a", "#1e2030", "#181926", "#363a4f", "#494d64", "#5b6078", "#6e738d", "#8087a2",
        "#cad3f5", "#a5adcb", "#b8c0e0", "#c6a0f6", "#b7bdf8", "#ed8796", "#a6da95", "#eed49f",
        "#8aadf4", "#91d7e3", "#f5bde6", "#f5a97f"),
    "Catppuccin Mocha": _catppuccin(
        "#1e1e2e", "#181825", "#11111b", "#313244", "#45475a", "#585b70", "#6c7086", "#7f849c",
        "#cdd6f4", "#a6adc8", "#bac2de", "#cba6f7", "#b4befe", "#f38ba8", "#a6e3a1", "#f9e2af",
        "#89b4fa", "#89dceb", "#f5c2e7", "#fab387"),
    "Tokyo Night": {
        "bg": "#16161e", "viewer_bg": "#101014", "surface": "#1a1b26", "surface_low": "#16161e",
        "button": "#24283b", "input": "#1f2335", "hover": "#292e42", "pressed": "#3b4261",
        "border": "#292e42", "border_input": "#3b4261", "grid": "#24283b", "border_accent": "#3d59a1",
        "accent_dim": "#3d59a1", "text": "#c0caf5", "text_bright": "#c0caf5", "accent_light": "#c0caf5",
        "on_accent": "#1a1b26", "text_dim": "#a9b1d6", "heading3": "#7aa2f7", "text_muted": "#565f89",
        "accent": "#7aa2f7", "accent_hover": "#7dcfff", "accent_fg": "#7aa2f7", "selection": "#33467c",
        "danger": "#f7768e", "danger_hover": "#ff9e64", "danger_off": "#292e42", "on_danger": "#1a1b26",
        "danger_off_text": "#565f89", "heading": "#7aa2f7", "heading2": "#7dcfff", "warn": "#e0af68",
        "ok": "#9ece6a", "err": "#f7768e", "marker": "#bb9af7", "trace": "#ff9e64", "dark": True,
    },
    "Tokyo Day": {
        "bg": "#d0d5e3", "viewer_bg": "#c4c8da", "surface": "#e1e2e7", "surface_low": "#d5d6db",
        "button": "#d0d5e3", "input": "#e9e9ed", "hover": "#c4c8da", "pressed": "#b6bfe2",
        "border": "#c4c8da", "border_input": "#a8aecb", "grid": "#d0d5e3", "border_accent": "#7890dd",
        "accent_dim": "#7890dd", "text": "#3760bf", "text_bright": "#343b58", "accent_light": "#e1e2e7",
        "on_accent": "#ffffff", "text_dim": "#6172b0", "heading3": "#2e7de9", "text_muted": "#8990b3",
        "accent": "#2e7de9", "accent_hover": "#007197", "accent_fg": "#2e7de9", "selection": "#b6bfe2",
        "danger": "#f52a65", "danger_hover": "#b15c00", "danger_off": "#d0d5e3", "on_danger": "#ffffff",
        "danger_off_text": "#8990b3", "heading": "#2e7de9", "heading2": "#007197", "warn": "#8c6c3e",
        "ok": "#587539", "err": "#f52a65", "marker": "#9854f1", "trace": "#b15c00", "dark": False,
    },
    "Cappuccino": {  # warm espresso + milk foam
        "bg": "#17110d", "viewer_bg": "#0f0b08", "surface": "#241b15", "surface_low": "#1b1410",
        "button": "#2f241c", "input": "#1d1611", "hover": "#3a2d23", "pressed": "#4a392c",
        "border": "#3a2d23", "border_input": "#4a392c", "grid": "#2f241c", "border_accent": "#6b4f38",
        "accent_dim": "#8a6441", "text": "#f3e9dc", "text_bright": "#fff8ef", "accent_light": "#f3e9dc",
        "on_accent": "#1b1410", "text_dim": "#c8b6a6", "heading3": "#d4a373", "text_muted": "#7d6a5a",
        "accent": "#c69c6d", "accent_hover": "#d9b38c", "accent_fg": "#d4a373", "selection": "#5a4230",
        "danger": "#b5523b", "danger_hover": "#cf6a50", "danger_off": "#2f241c", "on_danger": "#fff8ef",
        "danger_off_text": "#7d6a5a", "heading": "#e0b88a", "heading2": "#f0d2a8", "warn": "#e9c46a",
        "ok": "#9cbf7a", "err": "#e07a5f", "marker": "#f28482", "trace": "#e9c46a", "dark": True,
    },
}
DEFAULT = "Midnight"

# per-theme series colours for plots and code highlighting
_SERIES = {
    True: ("#7fb069", "#60a5fa", "#fbbf24", "#f472b6", "#a78bfa", "#34d399"),
    False: ("#40a02b", "#1e66f5", "#df8e1d", "#ea76cb", "#8839ef", "#179299"),
}

_state = {"name": DEFAULT, "accent": None}
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def names() -> list[str]:
    return list(THEMES)


def _mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def palette(name: Optional[str] = None, accent: Optional[str] = None) -> dict:
    """The role -> colour map for a theme, with an optional custom accent
    (hover/dim/selection shades are derived from it)."""
    th = dict(THEMES.get(name or _state["name"], MIDNIGHT))
    acc = accent if accent is not None else _state["accent"]
    if acc:
        acc = acc.lower()
        bg = th["surface"]
        th.update(
            accent=acc, accent_fg=_mix(acc, th["text"], 0.25), accent_hover=_mix(acc, "#ffffff", 0.18),
            accent_dim=_mix(acc, bg, 0.35), border_accent=_mix(acc, bg, 0.55),
            selection=_mix(acc, bg, 0.6), heading3=_mix(acc, th["text"], 0.3),
        )
    return th


def current() -> str:
    return _state["name"]


def custom_accent() -> Optional[str]:
    return _state["accent"]


def set_theme(name: str, accent: Optional[str] = "keep") -> None:
    if name not in THEMES:
        raise KeyError(f"unknown theme {name!r}; one of {names()}")
    _state["name"] = name
    if accent != "keep":
        _state["accent"] = accent


def hexc(role: str) -> str:
    return palette()[role]


def qcolor(role: str, alpha: Optional[int] = None):
    from PySide6 import QtGui

    c = QtGui.QColor(palette()[role])
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def is_dark() -> bool:
    return bool(palette().get("dark", True))


def series() -> tuple:
    return _SERIES[is_dark()]


def recolor(text: str, name: Optional[str] = None, accent: Optional[str] = None) -> str:
    """Rewrite every Midnight colour in a stylesheet / HTML string to the
    theme's colour for the same role. Unknown colours are left alone."""
    pal = palette(name, accent)
    if (name or _state["name"]) == "Midnight" and not (accent or _state["accent"]):
        return text

    def sub(m):
        role = ROLE_OF.get(m.group(0).lower())
        return pal[role] if role else m.group(0)

    return _HEX.sub(sub, text)


def syntax() -> dict:
    """Code-editor colours for the current theme."""
    if is_dark():
        return dict(keyword="#c792ea", builtin="#f78c6c", api="#82aaff", decorator="#ffcb6b",
                    number="#f78c6c", string="#c3e88d", comment="#6f8f6f", defname="#82aaff",
                    current_line=hexc("hover"), gutter_bg=hexc("surface_low"),
                    gutter_fg=hexc("text_muted"), error_bg="#4a1818", match_bg="#5a5a1e")
    return dict(keyword="#8839ef", builtin="#fe640b", api="#1e66f5", decorator="#df8e1d",
                number="#fe640b", string="#40a02b", comment="#8c8fa1", defname="#1e66f5",
                current_line=hexc("hover"), gutter_bg=hexc("surface_low"),
                gutter_fg=hexc("text_muted"), error_bg="#f5c2c7", match_bg="#f9e2af")


def apply(app, name: Optional[str] = None, accent: Optional[str] = "keep", base_qss: Optional[str] = None) -> None:
    """Switch the whole application: palette, stylesheet (via the scaling
    layer, so the size factor is kept) and a repaint of every widget."""
    from PySide6 import QtGui

    if name is not None:
        set_theme(name, accent)
    pal = palette()
    qp = QtGui.QPalette()
    cr, cg = QtGui.QPalette.ColorRole, QtGui.QPalette.ColorGroup
    C = QtGui.QColor
    for g in (cg.Active, cg.Inactive, cg.Disabled):
        dis = g == cg.Disabled
        qp.setColor(g, cr.Window, C(pal["surface"]))
        qp.setColor(g, cr.WindowText, C(pal["text_dim"] if dis else pal["text"]))
        qp.setColor(g, cr.Base, C(pal["input"]))
        qp.setColor(g, cr.AlternateBase, C(pal["surface"]))
        qp.setColor(g, cr.Text, C(pal["text_dim"] if dis else pal["text"]))
        qp.setColor(g, cr.Button, C(pal["button"]))
        qp.setColor(g, cr.ButtonText, C(pal["text_muted"] if dis else pal["text_bright"]))
        qp.setColor(g, cr.Highlight, C(pal["accent"]))
        qp.setColor(g, cr.HighlightedText, C(pal["on_accent"]))
        qp.setColor(g, cr.ToolTipBase, C(pal["input"]))
        qp.setColor(g, cr.ToolTipText, C(pal["text"]))
        qp.setColor(g, cr.PlaceholderText, C(pal["text_dim"]))
        qp.setColor(g, cr.Link, C(pal["accent_fg"]))
    app.setPalette(qp)
    from opngx.ui import scaling

    sc = scaling.get()
    if base_qss is not None and sc is not None:
        sc.raw_qss = base_qss
    if sc is not None:
        sc.base_qss = recolor(getattr(sc, "raw_qss", sc.base_qss))
        sc.apply(force=True)
    try:  # v2.1: vector icons take the new theme's colours too
        from opngx.ui import icons

        icons.refresh(app)
    except Exception:  # noqa: BLE001 - icons are cosmetic; never block a theme switch
        pass
    for w in app.allWidgets():
        w.update()
