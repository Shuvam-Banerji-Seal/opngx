"""Reusable modern Tk widgets: tooltips, section headers, chips."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

try:
    from . import theme
except ImportError:  # direct execution fallback
    import theme


class Tooltip:
    """Rich tooltip bound to a widget.

    Shows after a short hover delay near the cursor; supports a title line
    (bold, accent) plus body text with manual line wrapping.
    """

    _ACTIVE: "Optional[Tooltip]" = None

    def __init__(self, widget: tk.Widget, title: str, body: str, wraplen: int = 380):
        self.widget = widget
        self.title = title
        self.body = body
        self.wraplen = wraplen
        self._tip: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide_soon, add="+")
        widget.bind("<ButtonPress>", self._hide_now, add="+")

    def _schedule(self, _e=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(420, self._show)

    def _hide_soon(self, _e=None) -> None:
        self._cancel()
        if self._tip is not None:
            self._after_id = self.widget.after(120, self._destroy)

    def _hide_now(self, _e=None) -> None:
        self._cancel()
        self._destroy()

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _destroy(self) -> None:
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None
            Tooltip._ACTIVE = None

    def _show(self) -> None:
        if Tooltip._ACTIVE is not None:
            Tooltip._ACTIVE._destroy()
        Tooltip._ACTIVE = self

        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        frame = tk.Frame(
            tip,
            background="#0b1220",
            highlightthickness=1,
            highlightbackground="#3b82f6",
        )
        tk.Label(
            frame,
            text=self.title,
            background="#0b1220",
            foreground="#60a5fa",
            font=("TkDefaultFont", 9, "bold"),
            justify="left",
        ).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(
            frame,
            text=self.body,
            background="#0b1220",
            foreground="#dbe4f0",
            font=("TkDefaultFont", 9),
            justify="left",
            wraplength=self.wraplen,
        ).pack(anchor="w", padx=10, pady=(0, 9))
        frame.pack()
        self._tip = tip

        # position near the widget, clamped to screen
        self.widget.update_idletasks()
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        sw = self.widget.winfo_screenwidth()
        sh = self.widget.winfo_screenheight()
        tip.update_idletasks()
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        x = min(max(6, x), max(6, sw - w - 12))
        y = min(max(6, y), max(6, sh - h - 12))
        tip.wm_geometry(f"+{x}+{y}")


def tip(widget: tk.Widget, title: str, body: str) -> Tooltip:
    """Convenience constructor."""
    return Tooltip(widget, title, body)


class ScrollableFrame(ttk.Frame):
    """Vertically scrollable container (mousewheel included)."""

    def __init__(self, master, height: int | None = None, **kw):
        super().__init__(master, **kw)
        bg = getattr(theme, "BG", "#0f172a")
        self.canvas = tk.Canvas(self, highlightthickness=0,
                                background=bg, height=height or 260)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, background=bg)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(
                            scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(
                             self._win, width=e.width))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 * (e.delta // 120 or -1), "units")
