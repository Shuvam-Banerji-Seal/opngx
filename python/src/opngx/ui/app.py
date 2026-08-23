"""opngx Tkinter GUI — modern control panel for the extraction engine.

Design goals
------------
* every control explains itself (hover tooltips) AND is documented in
  Help → Field guide
* machine-adaptive: CPU count/features and GPUs auto-detected & displayed
* worker-thread execution; UI updates marshalled through a queue
"""

from __future__ import annotations

import glob
import os
import queue
import threading
import time
import tkinter as tk
from typing import Any, Optional
from tkinter import filedialog, messagebox, ttk

import opngx
from . import theme
from .widgets import Tooltip

PAD = 12


class App(tk.Tk):
    # ------------------------------------------------------------------ init
    def __init__(self) -> None:
        super().__init__()
        self.title("opngx studio")
        self.geometry("1020x820")
        self.minsize(900, 720)

        self.meta: Optional[opngx.FootageMetadata] = None
        self._running = False
        self._cancel_requested = False
        self._t_start = 0.0
        self._uiq: "queue.Queue[tuple[str, Any]]" = queue.Queue()

        self.fonts = theme.apply_theme(self)

        self._menu()
        self._build()
        self.after(80, self._drain_queue)
        self._log(
            f"opngx {opngx.__version__} ready — engine: {opngx.engine_backend()}", "ok"
        )

    @staticmethod
    def _detect_gpus() -> list[str]:
        try:
            from opngx._engine import detect_gpus

            return detect_gpus()
        except Exception:
            return []

    # ------------------------------------------------------------------ menu
    def _menu(self) -> None:
        m = tk.Menu(self)

        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Open .bin…", command=self._pick_bin, accelerator="Ctrl+O")
        fm.add_command(
            label="Choose output folder…",
            command=self._pick_out,
            accelerator="Ctrl+Shift+O",
        )
        fm.add_separator()
        fm.add_command(label="Quit", command=self.destroy, accelerator="Ctrl+Q")
        m.add_cascade(label="File", menu=fm)

        hm = tk.Menu(m, tearoff=0)
        hm.add_command(
            label="Field guide — what every control means",
            command=self._field_guide,
            accelerator="F1",
        )
        hm.add_command(
            label="Quality modes explained", command=lambda: self._guide_dialog("modes")
        )
        hm.add_command(
            label="Performance tuning (jobs & level)",
            command=lambda: self._guide_dialog("tuning"),
        )
        hm.add_separator()
        hm.add_command(label="About", command=self._about)
        m.add_cascade(label="Help", menu=hm)
        self.config(menu=m)

        self.bind_all("<Control-o>", lambda e: self._pick_bin())
        self.bind_all("<Control-q>", lambda e: self.destroy())
        self.bind_all("<F1>", lambda e: self._field_guide())

    def _about(self) -> None:
        gpus = ", ".join(opngx.detect_gpus()) or "none detected"
        messagebox.showinfo(
            "About opngx",
            f"opngx {opngx.__version__} — opngx studio\n\n"
            f"Developer: Shuvam Banerji Seal\n\n"
            f"engine: {opngx.engine_backend()}\n"
            f"cpus: {os.cpu_count()} logical   •   gpus: {gpus}\n\n"
            "Pixel-exact Optronis .bin → PNG extraction.\n"
            "All CPU cores are used by default.\n\n"
            "docs/FORMAT.md — the reverse-engineered camera format\n"
            "docs/BENCHMARKS.md — measured performance tables\n"
            "License: MIT",
        )

    # ------------------------------------------------------------- field guide
    _GUIDES: dict[str, tuple[str, str]] = {
        "fields": (
            "Field guide — every control explained",
            """
SOURCE
  • Single bin / Batch folder
      Pick one .bin recording, or point at a folder that contains
      <camera>/<name>.bin pairs — every recording found is extracted in turn.

  • Probe
      Reads the recording's metadata (geometry, frame count, framerate,
      exposure, vendor display settings) WITHOUT extracting anything.

QUALITY MODE
  • reference   Reproduces the vendor player's display transform exactly.
                Output pixels match the PNGs exported by Optronis software
                bit-for-bit (verified). Use this to compare against existing exports.
  • raw         Writes sensor bytes unchanged — no brightness/contrast curve.
                The vendor transform clips bright pixels at raw≥139;
                raw mode keeps them. Maximum fidelity, ideal for analysis.
  • custom      Your own brightness / contrast / gamma values.

FRAME RANGE
  • start       First frame index to extract (0 = beginning).
  • count       How many frames from 'start'. Empty = everything.

CONTAINER
  • bit depth 8  Standard PNG channel width (matches vendor exports).
  • bit depth 16 Wider container; each 8-bit value stored as value×257.
                No extra information (source is 8-bit) but convenient
                for pipelines expecting 16-bit input. PNG only.
  • channels rgba  Full RGBA images — identical layout to vendor exports.
  • channels gray  Single-channel images. Same pixel values,
                ~2.5× faster and ~36% smaller files.
  • format png   lossless container (default)
  • format jpg   lossy; quality slider below; tiny files — great for
                previews and sharing, NOT for measurement work
  • format bmp   lossless 8-bit paletted grayscale
  • format tif   lossless uncompressed grayscale
  The filename extension follows the format automatically.

ENGINE
  • jobs        Worker threads. Defaults to ALL logical cores of this
                machine (auto-detected). More threads = more speed until
                disk/CPU limits; fewer leaves the machine responsive.
  • level       DEFLATE compression effort 1–12.
                  1–2 fastest, larger files
                  6     balanced default, size matches vendor exports
                  9+    smallest files, much slower
SIDEcars
  • timestamps CSV  Writes one row per frame with its camera-clock tick.
  • metadata JSON   Writes geometry/settings/engine info for provenance.
""",
        ),
        "modes": (
            "Quality modes explained",
            """
reference ── what the vendor player shows
  Applies  out = clamp(round((raw + Brightness) × (1 + Contrast/50)), 0..255)
  using Brightness/Contrast from the recording's .footage sidecar.
  Verified pixel-exact against Optronis-exported PNGs.

raw ── what the sensor actually captured
  Identity mapping. The vendor transform CLIPS highlights:
  any raw byte ≥ 139 becomes 255. Raw mode preserves those values,
  so it is strictly more informative than reference mode.

custom ── your curve
  Same formula as reference but with YOUR numbers. Gamma > 1 brightens
  midtones, gamma < 1 darkens. Values outside 0..255 clamp.
""",
        ),
        "tuning": (
            "Performance tuning",
            """
jobs (worker threads)
  Auto-set to every logical core on this machine.
  Extraction scales nearly linearly with cores because each frame is an
  independent unit of work. Watch Task Manager / top during a run:
  expect ≈(cores × 100)% total CPU while extracting.

level (DEFLATE effort)
  Compression dominates runtime. Practical table on real footage:
    1–2  fastest (2–5× vs 6), files a few % larger
    3    throughput sweet spot
    6    default — file size parity with vendor exports
    9+   smallest files, several times slower

channels = gray
  Compresses 77 KB instead of 307 KB per frame → ~2.5× faster,
  ~36% smaller files, identical pixel values.

GPU
  Detected and shown in the status bar. Compression libraries on GPU
  are not yet mature for AMD (hipCOMP preview) and CUDA-only for NVIDIA,
  so opngx uses all CPU cores — measurably faster for these frame sizes.
""",
        ),
    }

    def _guide_dialog(self, key: str) -> None:
        title, body = self._GUIDES[key]
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("780x560")
        win.configure(bg=theme.CARD)
        txt = tk.Text(
            win,
            wrap="word",
            background=theme.CARD,
            foreground=theme.FG,
            font=("TkDefaultFont", 10),
            padx=18,
            pady=14,
            borderwidth=0,
            highlightthickness=0,
        )
        ysb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        txt.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        # light markup: lines ending with ':' bolded via tags
        txt.tag_configure(
            "h",
            font=("TkDefaultFont", 11, "bold"),
            foreground="#60a5fa",
            spacing1=8,
            spacing3=2,
        )
        for line in body.splitlines():
            if line.strip().endswith(":") and not line.startswith(" " * 4):
                txt.insert("end", line.rstrip(": ") + "\n", "h")
            else:
                txt.insert("end", line + "\n")
        txt.configure(state="disabled")

    def _field_guide(self) -> None:
        self._guide_dialog("fields")

    # ------------------------------------------------------------- queue/log
    def _log(self, msg: str, tag: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", f"[{stamp}] ", "stamp")
        self.log_txt.insert("end", msg + "\n", tag)
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._uiq.get_nowait()
                if kind == "log":
                    self._log(payload[0], payload[1])
                elif kind == "progress":
                    done, total, fps = payload
                    frac = done / max(total, 1)
                    milestone = max(total // 10, 1)
                    if done and (done % milestone == 0):
                        self._log(
                            f"progress: {done:,}/{total:,} frames "
                            f"({frac * 100:.0f}%, {fps:,.0f} fps)"
                        )
                    self.progress["value"] = 100 * frac
                    elapsed = time.perf_counter() - self._t_start
                    eta = elapsed / frac - elapsed if frac > 0.004 else float("nan")
                    self.stat_lbl.set(
                        f"{done:,} / {total:,} frames ({frac * 100:.1f}%)"
                        f"   •   {fps:,.0f} fps"
                        + (f"   •   eta {eta:,.0f}s" if eta == eta else "")
                    )
                elif kind == "done":
                    st = payload
                    suffix = "  — CANCELLED" if getattr(st, "cancelled", False) else ""
                    self._log(
                        f"finished: {st}{suffix}",
                        "ok" if not getattr(st, "cancelled", False) else "warn",
                    )
                    self.stat_lbl.set(
                        f"last run: {st.frames_written:,} frames in {st.seconds:.2f}s"
                    )
                elif kind == "dialog":
                    title, msg = payload
                    messagebox.showinfo(title, msg)
                elif kind == "error":
                    self._log(f"ERROR: {payload}", "err")
                    messagebox.showerror("opngx", str(payload))
                elif kind == "state":
                    running = payload
                    self.start_btn.configure(state="disabled" if running else "normal")
                    self.cancel_btn.configure(state="normal" if running else "disabled")
                    state = "disabled" if running else "normal"
                    for w in self._lockable:
                        try:
                            w.configure(state=state)
                        except tk.TclError:
                            pass
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        pad: dict[str, Any] = {"padx": PAD, "pady": PAD // 2}
        self._lockable: list[tk.Widget] = []
        T = Tooltip  # shorthand

        header = tk.Frame(self, background=theme.BG)
        header.pack(fill="x", padx=PAD, pady=(PAD, 0))
        ttk.Label(header, text="opngx studio", style="Title.TLabel").pack(side="left")
        from opngx._engine import detect_gpus

        gpus = (
            ", ".join(
                g.split("(")[1].rstrip(")").split(",")[0].strip() for g in detect_gpus()
            )
            or "no GPU"
        )
        chips = tk.Frame(header, background=theme.BG)
        chips.pack(side="right")
        for text in (
            f"{os.cpu_count()} cores",
            gpus,
            opngx.engine_backend().split("(")[0].strip(),
        ):
            lbl = tk.Label(
                chips,
                text=text,
                background=theme.CARD2,
                foreground=theme.MUTED,
                font=("TkDefaultFont", 8),
                padx=8,
                pady=3,
            )
            lbl.pack(side="left", padx=(6, 0))

        # ---- source ----
        src = ttk.Labelframe(self, text="SOURCE FOOTAGE")
        src.pack(fill="x", **pad)
        self.bin_var = tk.StringVar()
        self.scope_var = tk.StringVar(value="single")
        e = ttk.Entry(src, textvariable=self.bin_var)
        e.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        b1 = ttk.Button(src, text="Browse…", command=self._pick_bin)
        b1.grid(row=0, column=1, padx=4)
        b2 = ttk.Button(src, text="Probe", command=self._probe)
        b2.grid(row=0, column=2, padx=4)
        rb1 = ttk.Radiobutton(
            src, text="Single bin", value="single", variable=self.scope_var
        )
        rb1.grid(row=0, column=3, padx=(16, 2))
        rb2 = ttk.Radiobutton(
            src, text="Batch folder", value="batch", variable=self.scope_var
        )
        rb2.grid(row=0, column=4, padx=2)
        src.columnconfigure(0, weight=1)
        T(
            e,
            "Recording path",
            "Path to a .bin recording (single mode) or a folder that contains\n"
            "<camera>/<name>.bin sub-folders (batch mode).",
        )
        T(b1, "Browse", "Open a file dialog to pick the recording.")
        T(
            b2,
            "Probe",
            "Read metadata only — geometry, frames, fps,\n"
            "exposure and the vendor's display settings.\n"
            "Nothing is extracted yet.",
        )
        T(rb1, "Single bin", "Extract exactly one .bin recording.")
        T(
            rb2,
            "Batch folder",
            "Walk the chosen folder tree and extract every *.bin found,\n"
            "writing results to <output>/<camera name>.",
        )

        # ---- info ----
        info = ttk.Labelframe(self, text="RECORDING INFO")
        info.pack(fill="x", **pad)
        self.info_tree = ttk.Treeview(
            info, columns=("k", "v"), show="headings", height=6
        )
        self.info_tree.heading("k", text="field")
        self.info_tree.heading("v", text="value")
        self.info_tree.column("k", width=230, anchor="w")
        self.info_tree.column("v", anchor="w")
        self.info_tree.pack(fill="x", padx=6, pady=6)
        T(
            self.info_tree,
            "Metadata",
            "Filled by Probe. 'operating point' tells you whether this\n"
            "recording uses the settings (B49/C18/G1) under which output\n"
            "is guaranteed pixel-identical to vendor exports.",
        )

        # ---- settings ----
        st = ttk.Labelframe(self, text="EXTRACTION SETTINGS")
        st.pack(fill="x", **pad)

        qf = ttk.Frame(st)
        qf.grid(row=0, column=0, rowspan=4, sticky="nw", padx=8, pady=4)
        ttk.Label(qf, text="Quality mode", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.mode_var = tk.StringVar(value="reference")
        modes = (
            ("reference — match vendor PNGs exactly", "reference"),
            ("raw — sensor-faithful, no highlight clipping", "raw"),
            ("custom brightness / contrast / gamma", "custom"),
        )
        for i, (txt, val) in enumerate(modes, start=1):
            rb = ttk.Radiobutton(
                qf,
                text=txt,
                value=val,
                variable=self.mode_var,
                command=self._mode_changed,
            )
            rb.grid(row=i, column=0, sticky="w")
            self._lockable.append(rb)
            T(
                rb,
                val,
                {
                    "reference": "Vendor display transform (B49/C18).\nPROMISES: pixel-identical to Optronis exports.",
                    "raw": "Identity mapping — nothing clipped or shifted.\nThe most faithful data possible.",
                    "custom": "Your brightness/contrast/gamma below.\nFormula identical to reference mode.",
                }[val],
            )
        cf = ttk.Frame(qf)
        cf.grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.b_var, self.c_var, self.g_var = (
            tk.DoubleVar(value=49),
            tk.DoubleVar(value=18),
            tk.DoubleVar(value=1.0),
        )
        for j, (lbl, var, lo, hi, inc, tt) in enumerate(
            (
                (
                    "B",
                    self.b_var,
                    -255,
                    255,
                    1,
                    "Brightness offset added to every raw byte before scaling.",
                ),
                (
                    "C",
                    self.c_var,
                    0,
                    200,
                    1,
                    "Contrast multiplier = 1 + C/50.  Vendor default 18 → 1.36×.",
                ),
                (
                    "γ",
                    self.g_var,
                    0.1,
                    4.0,
                    0.05,
                    "Gamma applied after B/C.  1.0 = off.",
                ),
            )
        ):
            ttk.Label(cf, text=lbl).grid(row=0, column=j * 2, padx=(10 * bool(j), 3))
            sb = ttk.Spinbox(
                cf, from_=lo, to=hi, increment=inc, textvariable=var, width=6
            )
            sb.grid(row=0, column=j * 2 + 1)
            self._lockable.append(sb)
            T(sb, {"B": "Brightness", "C": "Contrast", "γ": "Gamma"}[lbl], tt)

        rf = ttk.Frame(st)
        rf.grid(row=0, column=1, rowspan=2, sticky="nw", padx=16)
        ttk.Label(rf, text="Frame range", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.start_var, self.count_var = tk.IntVar(value=0), tk.StringVar(value="")
        ttk.Label(rf, text="start").grid(row=1, column=0, sticky="e")
        sp = ttk.Spinbox(rf, from_=0, to=10**9, textvariable=self.start_var, width=8)
        sp.grid(row=1, column=1, padx=4)
        ttk.Label(rf, text="count").grid(row=2, column=0, sticky="e")
        cp = ttk.Entry(rf, textvariable=self.count_var, width=9)
        cp.grid(row=2, column=1, padx=4)
        ttk.Label(rf, text="(empty = all)", style="Muted.TLabel").grid(
            row=2, column=2, sticky="w"
        )
        self._lockable += [sp, cp]
        T(sp, "start", "Index of the first frame extracted (0-based).")
        T(
            cp,
            "count",
            "Number of frames to extract from 'start'.\nLeave empty for all remaining frames.",
        )

        kf = ttk.Frame(st)
        kf.grid(row=0, column=2, rowspan=2, sticky="nw", padx=16)
        ttk.Label(kf, text="Container", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.depth_var = tk.StringVar(value="8")
        self.chan_var = tk.StringVar(value="rgba")
        self.fmt_var = tk.StringVar(value="png")
        cb = ttk.Combobox(
            kf,
            textvariable=self.depth_var,
            values=("8", "16"),
            width=5,
            state="readonly",
        )
        cb.grid(row=1, column=1, sticky="w")
        ttk.Label(kf, text="bit depth", style="Muted.TLabel").grid(
            row=1, column=0, sticky="e", padx=2
        )
        cb2 = ttk.Combobox(
            kf,
            textvariable=self.chan_var,
            values=("rgba", "gray"),
            width=6,
            state="readonly",
        )
        cb2.grid(row=2, column=1, sticky="w")
        ttk.Label(kf, text="channels", style="Muted.TLabel").grid(
            row=2, column=0, sticky="e", padx=2
        )
        cb3 = ttk.Combobox(
            kf,
            textvariable=self.fmt_var,
            values=("png", "jpg", "bmp", "tif"),
            width=6,
            state="readonly",
        )
        cb3.bind("<<ComboboxSelected>>", lambda _e: self._fmt_changed())
        cb3.grid(row=3, column=1, sticky="w")
        kf_lbl3 = ttk.Label(kf, text="format", style="Muted.TLabel")
        kf_lbl3.grid(row=3, column=0, sticky="e", padx=2)
        self.jpgq_var = tk.IntVar(value=90)
        self.jpgq_lbl = ttk.Label(kf, text="90", width=3)
        js = ttk.Scale(
            kf,
            from_=40,
            to=100,
            variable=self.jpgq_var,
            command=lambda _v: self._sync_labels(),
        )
        js.grid(row=4, column=1, sticky="ew")
        kf_lbl4 = ttk.Label(kf, text="jpeg q", style="Muted.TLabel")
        kf_lbl4.grid(row=4, column=0, sticky="e", padx=2)
        self.jpgq_lbl.grid(row=4, column=2)
        self._lockable += [cb, cb2, cb3, js]
        T(
            cb3,
            "Output format",
            "png  lossless container (default; supports 8/16-bit)\n"
            "jpg  lossy, tiny files (quality slider below)\n"
            "bmp  lossless 8-bit paletted grayscale\n"
            "tif  lossless uncompressed grayscale\n\n"
            "The extension auto-follows the format unless you typed one.",
        )
        T(js, "JPEG quality", "40-100. Higher = better fidelity, bigger files.")
        T(
            cb,
            "Bit depth",
            "8-bit: standard, matches vendor exports.\n"
            "16-bit: same values stored ×257 — no extra detail\n(source is 8-bit), useful for 16-bit pipelines.",
        )
        T(
            cb2,
            "Channels",
            "rgba: color-type 6, exactly like vendor files.\n"
            "gray: color-type 0 single channel — SAME pixels,\n~2.5× faster, ~36% smaller files.",
        )

        ef = ttk.Frame(st)
        ef.grid(row=0, column=3, rowspan=2, sticky="nw", padx=16)
        ttk.Label(ef, text="Engine", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        maxcores = max((os.cpu_count() or 4) * 2, 8)
        self.jobs_var = tk.IntVar(value=os.cpu_count() or 4)
        self.level_var = tk.IntVar(value=6)
        sj = ttk.Scale(
            ef,
            from_=1,
            to=maxcores,
            variable=self.jobs_var,
            command=lambda _v: self._sync_labels(),
        )
        sj.grid(row=1, column=1, sticky="ew", padx=4)
        sl = ttk.Scale(
            ef,
            from_=1,
            to=12,
            variable=self.level_var,
            command=lambda _v: self._sync_labels(),
        )
        sl.grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Label(ef, text="jobs", style="Muted.TLabel").grid(
            row=1, column=0, sticky="e"
        )
        ttk.Label(ef, text="level", style="Muted.TLabel").grid(
            row=2, column=0, sticky="e"
        )
        self.jobs_lbl = ttk.Label(ef, text=str(self.jobs_var.get()), width=4)
        self.jobs_lbl.grid(row=1, column=2)
        self.level_lbl = ttk.Label(ef, text="6", width=4)
        self.level_lbl.grid(row=2, column=2)
        st.columnconfigure(4, weight=1)
        T(
            sj,
            "Worker threads (auto-detected)",
            f"This machine reports {os.cpu_count()} logical cores.\n"
            "Every core is used at jobs=all — watch Task Manager:\n"
            "expect ≈(cores×100)% total CPU during a run.\n"
            "Lower it if you need the desktop responsive meanwhile.",
        )
        T(
            sl,
            "Compression level",
            "DEFLATE effort: 1–2 fast/large · 3 sweet spot ·\n6 default (vendor-like size) · 9+ smallest/slowest.\nSee Help → Performance tuning.",
        )

        sf = ttk.Frame(st)
        sf.grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 6))
        self.ts_var = tk.BooleanVar(value=True)
        self.mj_var = tk.BooleanVar(value=True)
        c1 = ttk.Checkbutton(sf, text="timestamps CSV", variable=self.ts_var)
        c1.grid(row=0, column=0, padx=(0, 14))
        c2 = ttk.Checkbutton(sf, text="metadata JSON", variable=self.mj_var)
        c2.grid(row=0, column=1)
        self._lockable += [c1, c2]
        T(
            c1,
            "Timestamps export",
            "Writes <prefix>timestamps.csv: frame_index, raw clock tick\nand hex form. Useful for timing analysis.",
        )
        T(
            c2,
            "Metadata export",
            "Writes metadata.json: geometry, frame count, settings,\neffective fps derived from timestamps, engine version.",
        )

        # ---- output ----
        out = ttk.Labelframe(self, text="OUTPUT")
        out.pack(fill="x", **pad)
        self.out_var = tk.StringVar()
        oe = ttk.Entry(out, textvariable=self.out_var)
        oe.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ob = ttk.Button(out, text="Choose…", command=self._pick_out)
        ob.grid(row=0, column=1, padx=4)
        pf = ttk.Frame(out)
        pf.grid(row=0, column=2, padx=8)
        ttk.Label(pf, text="prefix", style="Muted.TLabel").grid(row=0, column=0)
        self.prefix_var = tk.StringVar(value="brow_")
        pe = ttk.Entry(pf, textvariable=self.prefix_var, width=8)
        pe.grid(row=0, column=1, padx=2)
        ttk.Label(pf, text="ext", style="Muted.TLabel").grid(
            row=0, column=2, padx=(10, 0)
        )
        self.ext_var = tk.StringVar(value=".Png")
        ee = ttk.Entry(pf, textvariable=self.ext_var, width=6)
        ee.grid(row=0, column=3, padx=2)
        out.columnconfigure(0, weight=1)
        self._lockable += [oe]
        T(
            pe,
            "Filename prefix",
            "Files become prefix + 5-digit index + extension,\ne.g. brow_00000.Png — matching vendor naming.",
        )
        T(ee, "Extension", 'Default ".Png" reproduces the vendor capital-P convention.')
        T(oe, "Output directory", "Where the PNGs (and sidecar exports) are written.")

        # ---- run row ----
        run = ttk.Frame(self)
        run.pack(fill="x", **pad)
        self.start_btn = ttk.Button(
            run, text="▶  Extract", command=self._start, style="Accent.TButton"
        )
        self.start_btn.pack(side="left")
        T(
            self.start_btn,
            "Start extraction",
            "Runs with the settings above on every selected recording.\nAll CPU cores are engaged automatically.",
        )
        self.cancel_btn = ttk.Button(
            run,
            text="■  Cancel",
            command=self._cancel,
            style="Danger.TButton",
            state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=8)
        T(self.cancel_btn, "Cancel", "Stops after the frame currently being written.")
        self.verify_btn = ttk.Button(
            run, text="✓  Verify against reference dir…", command=self._verify
        )
        self.verify_btn.pack(side="left", padx=8)
        T(
            self.verify_btn,
            "Pixel-exact verification",
            "Decodes both directories and compares every pixel.\nPASS proves the outputs equal the references exactly.",
        )
        self.progress = ttk.Progressbar(run, maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(16, 0))
        self.stat_lbl = tk.StringVar(value="idle")
        ttk.Label(
            run, textvariable=self.stat_lbl, width=46, anchor="e", style="Muted.TLabel"
        ).pack(side="left", padx=8)

        # ---- log ----
        lg = ttk.Labelframe(self, text="LOG")
        lg.pack(fill="both", expand=True, **pad)
        self.log_txt = tk.Text(
            lg,
            height=8,
            state="disabled",
            font=self.fonts["mono"],
            wrap="none",
            background=theme.CARD2,
            foreground=theme.FG,
            insertbackground=theme.FG,
            borderwidth=0,
            highlightthickness=0,
            padx=8,
            pady=6,
        )
        ysb = ttk.Scrollbar(lg, orient="vertical", command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=ysb.set)
        self.log_txt.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        ysb.pack(side="right", fill="y", pady=6, padx=(0, 6))
        for tag, color in (
            ("info", "#94a3b8"),
            ("ok", "#34d399"),
            ("warn", "#fbbf24"),
            ("err", "#f87171"),
        ):
            self.log_txt.tag_configure(tag, foreground=color)

        # ---- status bar ----
        ttk.Label(
            self,
            style="Status.TLabel",
            text=f"cpus: {os.cpu_count()} logical   •   gpu: {gpus}   •   "
            f"F1 field guide",
        ).pack(fill="x", padx=PAD, pady=(0, PAD))

    # ------------------------------------------------------------ actions
    def _sync_labels(self) -> None:
        self.jobs_lbl.configure(text=str(int(self.jobs_var.get())))
        self.level_lbl.configure(text=str(int(self.level_var.get())))
        if hasattr(self, "jpgq_lbl"):
            self.jpgq_lbl.configure(text=str(int(self.jpgq_var.get())))

    def _fmt_changed(self) -> None:
        """auto-follow extension unless the user typed a custom one"""
        extmap = {"png": ".Png", "jpg": ".jpg", "bmp": ".bmp", "tif": ".tif"}
        want = extmap.get(self.fmt_var.get(), ".Png")
        cur = self.ext_var.get()
        if cur in extmap.values():
            self.ext_var.set(want)

    def _mode_changed(self) -> None:
        pass

    def _pick_bin(self) -> None:
        p = filedialog.askopenfilename(
            filetypes=[("Optronis footage", "*.bin"), ("All files", "*.*")]
        )
        if p:
            self.bin_var.set(p)
            self.scope_var.set("single")
            self._probe()

    def _pick_out(self) -> None:
        d = filedialog.askdirectory()
        if d:
            self.out_var.set(d)

    def _probe(self) -> None:
        target = self.bin_var.get().strip()
        if not target:
            return
        if self.scope_var.get() == "batch":
            bins = sorted(glob.glob(os.path.join(target, "*", "*.bin"))) + sorted(
                glob.glob(os.path.join(target, "*.bin"))
            )
            self._set_info(
                [
                    ("scope", "batch folder"),
                    ("folder", target),
                    ("bins found", str(len(bins))),
                ]
            )
            self._log(f"batch scan: {len(bins)} bin(s) under {target}")
            return
        try:
            m = opngx.probe(target)
        except Exception as exc:
            messagebox.showerror("probe failed", str(exc))
            return
        self.meta = m
        rows = [
            ("camera", m.camera_name or "?"),
            ("geometry", f"{m.width} × {m.height} px"),
            ("frames in XML", f"{m.num_images:,}" if m.num_images > 0 else "?"),
            ("capacity from size", f"{m.capacity_frames:,}"),
            ("frame stride", f"{m.frame_stride:,} B"),
            ("framerate", f"{m.framerate:g} fps" if m.framerate > 0 else "?"),
            ("exposure", f"{m.exposure_us:g} µs" if m.exposure_us > 0 else "?"),
            ("display B/C/G", f"{m.brightness:g} / {m.contrast:g} / {m.gamma:g}"),
            (
                "operating point",
                "✔ verified pixel-exact"
                if m.verified_operating_point
                else "⚠ unverified — fidelity not guaranteed",
            ),
        ]
        self._set_info(rows)
        self._log(f"probed {os.path.basename(m.bin_path)}")
        suggested = os.path.join(
            os.path.dirname(m.bin_path), m.camera_name.replace(".", "_") + "_png"
        )
        if not self.out_var.get():
            self.out_var.set(suggested)

    def _set_info(self, rows) -> None:
        self.info_tree.delete(*self.info_tree.get_children())
        for k, v in rows:
            self.info_tree.insert("", "end", values=(k, v))

    def _collect_opts(self) -> dict[str, Any]:
        count = self.count_var.get().strip()
        return dict(
            mode=self.mode_var.get(),
            brightness=self.b_var.get(),
            contrast=self.c_var.get(),
            gamma=self.g_var.get(),
            bit_depth=int(self.depth_var.get()),
            channels=0 if self.chan_var.get() == "gray" else 6,
            fmt=self.fmt_var.get(),
            jpeg_quality=int(self.jpgq_var.get()),
            jobs=int(self.jobs_var.get()),
            level=int(self.level_var.get()),
            prefix=self.prefix_var.get(),
            ext=self.ext_var.get(),
            start=int(self.start_var.get()),
            frames=int(count) if count else None,
            export_timestamps=self.ts_var.get(),
            export_metadata=self.mj_var.get(),
        )

    def _start(self) -> None:
        if self._running:
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning("opngx", "Choose an output directory.")
            return
        scope_batch = self.scope_var.get() == "batch"

        if scope_batch:
            root_dir = self.bin_var.get().strip()
            bins = sorted(glob.glob(os.path.join(root_dir, "*", "*.bin"))) + sorted(
                glob.glob(os.path.join(root_dir, "*.bin"))
            )
            if not bins:
                messagebox.showwarning("opngx", "No .bin files found under folder.")
                return
        else:
            if not self.meta:
                messagebox.showwarning("opngx", "Probe a bin first.")
                return
            bins = [self.meta.bin_path]

        opts = self._collect_opts()
        self._running = True
        self._cancel_requested = False
        self._uiq.put(("state", True))
        self._t_start = time.perf_counter()

        def emit_log(tag: str, msg: str) -> None:
            self._uiq.put(("log", (msg, tag)))

        def progress(done: int, total: int) -> None:
            dt = time.perf_counter() - self._t_start
            fps = done / dt if dt > 0 else 0.0
            self._uiq.put(("progress", (done, total, fps)))

        def worker() -> None:
            try:
                last: Optional[opngx.ExtractStats] = None
                for b in bins:
                    if self._cancel_requested:
                        break
                    stem = os.path.splitext(os.path.basename(b))[0]
                    od = (
                        out
                        if len(bins) == 1
                        else os.path.join(out, stem.replace(".", "_"))
                    )
                    o = opts
                    emit_log(
                        "info",
                        f"extract {os.path.basename(b)} → {od}  "
                        f"[mode={o['mode']} fmt={o['fmt']} "
                        f"depth={o['bit_depth']}ch={o['channels']} "
                        f"jobs={o['jobs']} level={o['level']}]",
                    )
                    ex = opngx.Extractor(b)
                    last = ex.extract(
                        od,
                        progress=progress,
                        should_cancel=lambda: self._cancel_requested,
                        **opts,
                    )
                if last is not None:
                    self._uiq.put(("done", last))
            except Exception as exc:
                self._uiq.put(("error", exc))
            finally:
                self._running = False
                self._uiq.put(("state", False))

        threading.Thread(target=worker, name="opngx-worker", daemon=True).start()

    def _cancel(self) -> None:
        self._cancel_requested = True
        self._log("cancel requested…", "warn")

    def _verify(self) -> None:
        ref = filedialog.askdirectory(title="Reference PNG directory")
        if not ref or not self.out_var.get().strip():
            messagebox.showwarning(
                "opngx", "Pick both a reference dir and an output dir."
            )
            return

        def worker() -> None:
            try:
                rep = opngx.verify(
                    ref, self.out_var.get().strip(), prefix=self.prefix_var.get()
                )
                self._uiq.put(
                    (
                        "log",
                        (
                            f"verify: {rep}"
                            + (f" | {rep.first_error}" if rep.first_error else ""),
                            "ok" if rep.passed else "err",
                        ),
                    )
                )
                msg = (
                    "PASS — every compared frame is pixel-exact."
                    if rep.passed
                    else f"FAIL — {rep.mismatched_files} mismatched file(s).\n\n"
                    f"{rep.first_error}"
                )
                self._uiq.put(("dialog", ("verification", msg)))
            except Exception as exc:
                self._uiq.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
