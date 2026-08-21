"""opngx Tkinter GUI.

Launch with `opngx-ui` or `python -m opngx.ui.app`.
Features:
  - bin picker with automatic .footage sidecar detection
  - metadata panel (geometry, frames, fps, exposure, verified operating point)
  - quality mode: reference / raw / custom (+ B/C/G, bit depth)
  - engine controls: jobs slider, deflate level
  - sidecar exports: timestamps CSV + metadata.json
  - progress bar with ETA and cancel
  - verify button comparing output against a reference directory
"""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from typing import Any
from tkinter import filedialog, messagebox, ttk

import opngx


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("opngx — Optronis footage extractor")
        self.geometry("860x640")
        self.minsize(760, 560)

        self.meta: opngx.FootageMetadata | None = None
        self._job_running = False
        self._cancel_requested = False

        self._build()
        self._log(f"opngx {opngx.__version__} | engine: {opngx.engine_backend()}")

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        pad: dict[str, Any] = {"padx": 8, "pady": 4}

        top = ttk.LabelFrame(self, text="Source")
        top.pack(fill="x", **pad)
        self.bin_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.bin_var).grid(
            row=0, column=0, sticky="ew", padx=6, pady=6
        )
        ttk.Button(top, text="Browse…", command=self._pick_bin).grid(
            row=0, column=1, padx=6
        )
        ttk.Button(top, text="Probe", command=self._probe).grid(
            row=0, column=2, padx=(0, 6)
        )
        top.columnconfigure(0, weight=1)

        self.meta_lbl = tk.StringVar(value="no file probed")
        ttk.Label(self, textvariable=self.meta_lbl, foreground="#444").pack(
            anchor="w", padx=12
        )

        mid = ttk.LabelFrame(self, text="Extraction settings")
        mid.pack(fill="x", **pad)

        self.mode_var = tk.StringVar(value="reference")
        self.prefix_var = tk.StringVar(value="brow_")
        self.jobs_var = tk.IntVar(value=os.cpu_count() or 4)
        self.level_var = tk.IntVar(value=6)
        self.depth_var = tk.StringVar(value="8")
        self.b_var = tk.DoubleVar()
        self.c_var = tk.DoubleVar()
        self.g_var = tk.DoubleVar(value=1.0)
        self.ts_var = tk.BooleanVar(value=False)
        self.mj_var = tk.BooleanVar(value=False)

        r = 0
        for txt, val in (
            ("reference (match vendor PNGs)", "reference"),
            ("raw (sensor-faithful, no clipping)", "raw"),
            ("custom", "custom"),
        ):
            ttk.Radiobutton(
                mid,
                text=txt,
                variable=self.mode_var,
                value=val,
                command=self._mode_changed,
            ).grid(row=r, column=0, columnspan=3, sticky="w", padx=6)
            r += 1
        for lbl, var in (
            ("Brightness", self.b_var),
            ("Contrast", self.c_var),
            ("Gamma", self.g_var),
        ):
            pass
        ttk.Label(mid, text="Brightness").grid(row=0, column=3, sticky="e")
        ttk.Spinbox(mid, from_=-255, to=255, textvariable=self.b_var, width=7).grid(
            row=0, column=4
        )
        ttk.Label(mid, text="Contrast").grid(row=1, column=3, sticky="e")
        ttk.Spinbox(mid, from_=0, to=200, textvariable=self.c_var, width=7).grid(
            row=1, column=4
        )
        ttk.Label(mid, text="Gamma").grid(row=2, column=3, sticky="e")
        ttk.Spinbox(
            mid, from_=0.1, to=4.0, increment=0.05, textvariable=self.g_var, width=7
        ).grid(row=2, column=4)

        ttk.Label(mid, text="Jobs").grid(row=r, column=0, sticky="e", padx=6)
        ttk.Scale(
            mid, from_=1, to=(os.cpu_count() or 4) * 2, variable=self.jobs_var
        ).grid(row=r, column=1, sticky="ew")
        self.jobs_val_lbl = ttk.Label(mid, text=str(self.jobs_var.get()))
        self.jobs_val_lbl.grid(row=r, column=2)
        r += 1
        ttk.Label(mid, text="Deflate level").grid(row=r, column=0, sticky="e", padx=6)
        ttk.Scale(
            mid,
            from_=1,
            to=12,
            variable=self.level_var,
            command=lambda _v: self._sync_labels(),
        ).grid(row=r, column=1, sticky="ew")
        self.level_val_lbl = ttk.Label(mid, text="6")
        self.level_val_lbl.grid(row=r, column=2)
        r += 1
        ttk.Label(mid, text="Bit depth").grid(row=r, column=0, sticky="e", padx=6)
        cb = ttk.Combobox(
            mid,
            textvariable=self.depth_var,
            values=("8", "16"),
            width=5,
            state="readonly",
        )
        cb.grid(row=r, column=1, sticky="w")
        ttk.Checkbutton(mid, text="timestamps CSV", variable=self.ts_var).grid(
            row=r, column=3, columnspan=2, sticky="w"
        )
        r += 1
        ttk.Label(mid, text="Prefix").grid(row=r, column=0, sticky="e", padx=6)
        ttk.Entry(mid, textvariable=self.prefix_var, width=10).grid(
            row=r, column=1, sticky="w"
        )
        ttk.Checkbutton(mid, text="metadata JSON", variable=self.mj_var).grid(
            row=r, column=3, columnspan=2, sticky="w"
        )
        mid.columnconfigure(1, weight=1)

        outf = ttk.LabelFrame(self, text="Output")
        outf.pack(fill="x", **pad)
        self.out_var = tk.StringVar()
        ttk.Entry(outf, textvariable=self.out_var).grid(
            row=0, column=0, sticky="ew", padx=6, pady=6
        )
        ttk.Button(
            outf,
            text="Choose…",
            command=lambda: self.out_var.set(
                filedialog.askdirectory() or self.out_var.get()
            ),
        ).grid(row=0, column=1, padx=6)
        outf.columnconfigure(0, weight=1)

        runf = ttk.Frame(self)
        runf.pack(fill="x", **pad)
        self.start_btn = ttk.Button(runf, text="▶ Extract", command=self._start)
        self.start_btn.pack(side="left", padx=6)
        self.cancel_btn = ttk.Button(
            runf, text="Cancel", command=self._cancel, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=6)
        self.verify_btn = ttk.Button(
            runf, text="Verify vs reference dir…", command=self._verify
        )
        self.verify_btn.pack(side="left", padx=6)

        self.progress = ttk.Progressbar(self, maximum=100)
        self.progress.pack(fill="x", **pad)
        self.stat_lbl = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.stat_lbl).pack(anchor="w", padx=12)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log_txt = tk.Text(logf, height=10, state="disabled", font=("monospace", 9))
        self.log_txt.pack(fill="both", expand=True, padx=4, pady=4)

    def _log(self, msg: str) -> None:
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", msg + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def _sync_labels(self) -> None:
        self.jobs_val_lbl.configure(text=str(int(self.jobs_var.get())))
        self.level_val_lbl.configure(text=str(int(self.level_var.get())))

    def _mode_changed(self) -> None:
        if self.mode_var.get() == "custom":
            if not self.b_var.get():
                self.b_var.set(49)
                self.c_var.set(18)

    # ------------------------------------------------------------- actions
    def _pick_bin(self) -> None:
        p = filedialog.askopenfilename(
            filetypes=[("Optronis bin", "*.bin"), ("All", "*.*")]
        )
        if p:
            self.bin_var.set(p)
            self._probe()

    def _probe(self) -> None:
        try:
            m = opngx.probe(self.bin_var.get())
        except Exception as exc:
            messagebox.showerror("probe failed", str(exc))
            return
        self.meta = m
        vop = (
            "✔ verified operating point"
            if m.verified_operating_point
            else "⚠ unverified settings"
        )
        self.meta_lbl.set(
            f"{m.camera_name or '?'}: {m.width}×{m.height}, "
            f"{m.capacity_frames:,} frames @ stride {m.frame_stride}B | "
            f"fps={m.framerate:.0f} exp={m.exposure_us:.0f}µs | {vop}"
        )
        self._log(f"probed {m.bin_path}")

    def _cancel(self) -> None:
        self._cancel_requested = True

    def _start(self) -> None:
        if not self.meta:
            messagebox.showwarning("opngx", "Probe a bin first.")
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning("opngx", "Choose an output directory.")
            return
        self._job_running = True
        self._cancel_requested = False
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        t0 = time.perf_counter()

        def progress(done: int, total: int) -> None:
            frac = done / max(total, 1)
            self.progress["value"] = 100 * frac
            dt = time.perf_counter() - t0
            eta = dt / frac - dt if frac > 0.005 else float("nan")
            self.stat_lbl.set(f"{done:,}/{total:,} frames | eta {eta:,.0f}s")

        def worker() -> None:
            try:
                meta = self.meta
                assert meta is not None
                st = opngx.Extractor(meta.bin_path).extract(
                    out,
                    mode=self.mode_var.get(),
                    brightness=self.b_var.get(),
                    contrast=self.c_var.get(),
                    gamma=self.g_var.get(),
                    bit_depth=int(self.depth_var.get()),
                    jobs=int(self.jobs_var.get()),
                    level=int(self.level_var.get()),
                    prefix=self.prefix_var.get(),
                    ext=".Png",
                    export_timestamps=self.ts_var.get(),
                    export_metadata=self.mj_var.get(),
                    progress=progress,
                    should_cancel=lambda: self._cancel_requested,
                )
                self._log(f"done: {st}" + (" (CANCELLED)" if st.cancelled else ""))
            except Exception as exc:
                self._log(f"ERROR: {exc}")
            finally:
                self._job_running = False
                self.after(
                    0,
                    lambda: (
                        self.start_btn.configure(state="normal"),
                        self.cancel_btn.configure(state="disabled"),
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _verify(self) -> None:
        ref = filedialog.askdirectory(title="Reference directory")
        if not ref:
            return
        rep = opngx.verify(ref, self.out_var.get(), prefix=self.prefix_var.get())
        self._log(str(rep) + (f" | {rep.first_error}" if rep.first_error else ""))
        messagebox.showinfo("verify", f"{rep}\n\n{rep.first_error}")


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
