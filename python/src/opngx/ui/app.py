"""opngx Tkinter GUI — full-featured control panel for the extraction engine.

Layout
------
┌ Source ──────────────────────────────────────────────┐
│ [bin path………………] [Browse] [Probe]  mode: single/batch │
├ Info ────────────────────────────────────────────────┤
│ camera · geometry · frames · fps · exposure · OP badge│
├ Settings ────────────────────────────────────────────┤
│ quality mode │ range │ container │ engine │ sidecars  │
├ Output ──────────────────────────────────────────────┤
│ [dir] [Choose…]  prefix  ext                          │
├ Run ──────────────────────────────────────────────────┤
│ ▶ Extract  ■ Cancel  ✓ Verify…   ▕██████████▏ 42% ETA │
├ Log ──────────────────────────────────────────────────┤
└ Status bar: engine · gpus · cpus ─────────────────────┘

Threading model: extraction/verify run on worker threads; every UI mutation
is marshalled back through a thread-safe queue drained by the Tk main loop.
"""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from typing import Any, Optional
from tkinter import filedialog, messagebox, ttk

import opngx

PAD = 10


class QueueWriter:
    """file-like object that forwards writes into the UI log queue."""

    def __init__(self, q: "queue.Queue[tuple[str, str]]", tag: str):
        self.q = q
        self.tag = tag

    def write(self, s: str) -> None:
        if s.strip():
            self.q.put((self.tag, s.rstrip("\n")))

    def flush(self) -> None:  # pragma: no cover - interface compliance
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("opngx — Optronis footage extractor")
        self.geometry("980x760")
        self.minsize(860, 680)

        self.meta: Optional[opngx.FootageMetadata] = None
        self._running = False
        self._cancel_requested = False
        self._t_start = 0.0
        self._uiq: "queue.Queue[tuple[str, Any]]" = queue.Queue()

        style = ttk.Style(self)
        style.theme_use("clam")
        accent = "#2563eb"
        style.configure("Accent.TButton", foreground="white", background=accent)
        style.map(
            "Accent.TButton",
            background=[("active", "#1d4ed8"), ("disabled", "#9ca3af")],
        )
        style.configure("Danger.TButton", foreground="white", background="#dc2626")
        style.map(
            "Danger.TButton",
            background=[("active", "#b91c1c"), ("disabled", "#f3f4f6")],
        )
        style.configure("TLabelframe.Label", font=("", 10, "bold"))
        style.configure("Status.TLabel", relief="sunken", padding=(8, 4))

        self._menu()
        self._build()
        self.after(80, self._drain_queue)

    # ------------------------------------------------------------- helpers
    def _log(self, msg: str, tag: str = "info") -> None:
        self.log_txt.configure(state="normal")
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
                elif kind == "error":
                    self._log(f"ERROR: {payload}", "err")
                    messagebox.showerror("opngx", str(payload))
                elif kind == "state":
                    running = payload
                    self.start_btn.configure(state="disabled" if running else "normal")
                    self.cancel_btn.configure(state="normal" if running else "disabled")
                    state = "disabled" if running else "normal"
                    for w in self._lockable:
                        w.configure(state=state)
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    # ---------------------------------------------------------------- menu
    def _menu(self) -> None:
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Open .bin…", command=self._pick_bin, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="Quit", command=self.destroy, accelerator="Ctrl+Q")
        m.add_cascade(label="File", menu=fm)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="About", command=self._about)
        m.add_cascade(label="Help", menu=hm)
        self.config(menu=m)
        self.bind_all("<Control-o>", lambda e: self._pick_bin())
        self.bind_all("<Control-q>", lambda e: self.destroy())

    def _about(self) -> None:
        from opngx._engine import detect_gpus

        gpus = ", ".join(detect_gpus()) or "none detected"
        messagebox.showinfo(
            "About opngx",
            f"opngx {opngx.__version__}\n\n"
            f"engine: {opngx.engine_backend()}\n"
            f"cpus: {os.cpu_count()}   gpus: {gpus}\n\n"
            "Pixel-exact Optronis .bin → PNG extraction.\n"
            "MIT licensed. Format notes: docs/FORMAT.md",
        )

    # -------------------------------------------------------------- build
    def _build(self) -> None:
        pad: dict[str, Any] = {"padx": PAD, "pady": PAD // 2}
        self._lockable: list[tk.Widget] = []

        # ---- source ----
        src = ttk.LabelFrame(self, text="Source footage")
        src.pack(fill="x", **pad)
        self.bin_var = tk.StringVar()
        self.scope_var = tk.StringVar(value="single")
        e = ttk.Entry(src, textvariable=self.bin_var)
        e.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(src, text="Browse…", command=self._pick_bin).grid(
            row=0, column=1, padx=4
        )
        ttk.Button(src, text="Probe", command=self._probe).grid(row=0, column=2, padx=4)
        ttk.Radiobutton(
            src, text="Single bin", value="single", variable=self.scope_var
        ).grid(row=0, column=3, padx=(16, 2))
        ttk.Radiobutton(
            src, text="Batch folder", value="batch", variable=self.scope_var
        ).grid(row=0, column=4, padx=2)
        src.columnconfigure(0, weight=1)

        # ---- info ----
        info = ttk.LabelFrame(self, text="Recording info")
        info.pack(fill="x", **pad)
        self.info_tree = ttk.Treeview(
            info, columns=("k", "v"), show="headings", height=5
        )
        self.info_tree.heading("k", text="field")
        self.info_tree.heading("v", text="value")
        self.info_tree.column("k", width=220, anchor="w")
        self.info_tree.column("v", anchor="w")
        self.info_tree.pack(fill="x", padx=6, pady=6)

        # ---- settings ----
        st = ttk.LabelFrame(self, text="Extraction settings")
        st.pack(fill="x", **pad)

        # quality mode column
        qf = ttk.Frame(st)
        qf.grid(row=0, column=0, rowspan=4, sticky="nw", padx=6, pady=4)
        ttk.Label(qf, text="Quality").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value="reference")
        for i, (txt, val) in enumerate(
            (
                ("reference — match vendor PNGs exactly", "reference"),
                ("raw — sensor-faithful, no highlight clipping", "raw"),
                ("custom brightness / contrast / gamma", "custom"),
            ),
            start=1,
        ):
            rb = ttk.Radiobutton(
                qf,
                text=txt,
                value=val,
                variable=self.mode_var,
                command=self._mode_changed,
            )
            rb.grid(row=i, column=0, sticky="w")
            self._lockable.append(rb)
        cf = ttk.Frame(qf)
        cf.grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.b_var, self.c_var, self.g_var = (
            tk.DoubleVar(value=49),
            tk.DoubleVar(value=18),
            tk.DoubleVar(value=1),
        )
        for j, (lbl, var, lo, hi, inc) in enumerate(
            (
                ("B", self.b_var, -255, 255, 1),
                ("C", self.c_var, 0, 200, 1),
                ("γ", self.g_var, 0.1, 4.0, 0.05),
            )
        ):
            ttk.Label(cf, text=lbl).grid(row=0, column=j * 2, padx=(10 * bool(j), 2))
            sb = ttk.Spinbox(
                cf, from_=lo, to=hi, increment=inc, textvariable=var, width=6
            )
            sb.grid(row=0, column=j * 2 + 1)
            self._lockable.append(sb)

        # range column
        rf = ttk.Frame(st)
        rf.grid(row=0, column=1, rowspan=2, sticky="nw", padx=14)
        ttk.Label(rf, text="Frame range").grid(row=0, column=0, sticky="w")
        self.start_var, self.count_var = tk.IntVar(value=0), tk.StringVar(value="")
        ttk.Label(rf, text="start").grid(row=1, column=0, sticky="e")
        sp = ttk.Spinbox(rf, from_=0, to=10**9, textvariable=self.start_var, width=8)
        sp.grid(row=1, column=1, padx=4)
        ttk.Label(rf, text="count").grid(row=2, column=0, sticky="e")
        cp = ttk.Entry(rf, textvariable=self.count_var, width=9)
        cp.grid(row=2, column=1, padx=4)
        cp.insert(0, "")
        ttk.Label(rf, text="(empty = all)").grid(row=2, column=2, sticky="w")
        self._lockable += [sp, cp]

        # container column
        kf = ttk.Frame(st)
        kf.grid(row=0, column=2, rowspan=2, sticky="nw", padx=14)
        ttk.Label(kf, text="Container").grid(row=0, column=0, sticky="w")
        self.depth_var = tk.StringVar(value="8")
        self.chan_var = tk.StringVar(value="rgba")
        cb = ttk.Combobox(
            kf,
            textvariable=self.depth_var,
            values=("8", "16"),
            width=5,
            state="readonly",
        )
        cb.grid(row=1, column=1, sticky="w")
        ttk.Label(kf, text="bit depth").grid(row=1, column=0, sticky="e", padx=2)
        cb2 = ttk.Combobox(
            kf,
            textvariable=self.chan_var,
            values=("rgba", "gray"),
            width=6,
            state="readonly",
        )
        cb2.grid(row=2, column=1, sticky="w")
        ttk.Label(kf, text="channels").grid(row=2, column=0, sticky="e", padx=2)
        self._lockable += [cb, cb2]

        # engine column
        ef = ttk.Frame(st)
        ef.grid(row=0, column=3, rowspan=2, sticky="nw", padx=14)
        ttk.Label(ef, text="Engine").grid(row=0, column=0, sticky="w")
        maxcores = (os.cpu_count() or 4) * 2
        self.jobs_var = tk.IntVar(value=os.cpu_count() or 4)
        self.level_var = tk.IntVar(value=6)
        sj = ttk.Scale(
            ef,
            from_=1,
            to=maxcores,
            variable=self.jobs_var,
            command=lambda _v: self._sync_labels(),
        )
        sj.grid(row=1, column=1, sticky="ew")
        sl = ttk.Scale(
            ef,
            from_=1,
            to=12,
            variable=self.level_var,
            command=lambda _v: self._sync_labels(),
        )
        sl.grid(row=2, column=1, sticky="ew")
        ttk.Label(ef, text="jobs").grid(row=1, column=0, sticky="e", padx=2)
        ttk.Label(ef, text="level").grid(row=2, column=0, sticky="e", padx=2)
        self.jobs_lbl = ttk.Label(ef, text=str(self.jobs_var.get()), width=3)
        self.jobs_lbl.grid(row=1, column=2)
        self.level_lbl = ttk.Label(ef, text="6", width=3)
        self.level_lbl.grid(row=2, column=2)
        st.columnconfigure(4, weight=1)

        # sidecars
        sf = ttk.Frame(st)
        sf.grid(row=2, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 4))
        self.ts_var = tk.BooleanVar(value=True)
        self.mj_var = tk.BooleanVar(value=True)
        c1 = ttk.Checkbutton(sf, text="export timestamps CSV", variable=self.ts_var)
        c1.grid(row=0, column=0, padx=(0, 12))
        c2 = ttk.Checkbutton(sf, text="export metadata JSON", variable=self.mj_var)
        c2.grid(row=0, column=1)
        self._lockable += [c1, c2]

        # ---- output ----
        out = ttk.LabelFrame(self, text="Output")
        out.pack(fill="x", **pad)
        self.out_var = tk.StringVar()
        oe = ttk.Entry(out, textvariable=self.out_var)
        oe.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(out, text="Choose…", command=self._pick_out).grid(
            row=0, column=1, padx=4
        )
        pf = ttk.Frame(out)
        pf.grid(row=0, column=2, padx=6)
        ttk.Label(pf, text="prefix").grid(row=0, column=0)
        self.prefix_var = tk.StringVar(value="brow_")
        ttk.Entry(pf, textvariable=self.prefix_var, width=8).grid(
            row=0, column=1, padx=2
        )
        ttk.Label(pf, text="ext").grid(row=0, column=2, padx=(8, 0))
        self.ext_var = tk.StringVar(value=".Png")
        ttk.Entry(pf, textvariable=self.ext_var, width=6).grid(row=0, column=3, padx=2)
        out.columnconfigure(0, weight=1)
        self._lockable += [oe]

        # ---- run row ----
        run = ttk.Frame(self)
        run.pack(fill="x", **pad)
        self.start_btn = ttk.Button(
            run, text="▶  Extract", command=self._start, style="Accent.TButton"
        )
        self.start_btn.pack(side="left")
        self.cancel_btn = ttk.Button(
            run,
            text="■  Cancel",
            command=self._cancel,
            style="Danger.TButton",
            state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=8)
        self.verify_btn = ttk.Button(
            run, text="✓  Verify against reference dir…", command=self._verify
        )
        self.verify_btn.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(run, maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(16, 0))
        self.stat_lbl = tk.StringVar(value="idle")
        ttk.Label(run, textvariable=self.stat_lbl, width=46, anchor="e").pack(
            side="left", padx=8
        )

        # ---- log ----
        lg = ttk.LabelFrame(self, text="Log")
        lg.pack(fill="both", expand=True, **pad)
        self.log_txt = tk.Text(
            lg, height=9, state="disabled", font=("monospace", 9), wrap="none"
        )
        ysb = ttk.Scrollbar(lg, orient="vertical", command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=ysb.set)
        self.log_txt.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        ysb.pack(side="right", fill="y", pady=6, padx=(0, 6))
        for tag, color in (
            ("info", "#374151"),
            ("ok", "#047857"),
            ("warn", "#b45309"),
            ("err", "#b91c1c"),
        ):
            self.log_txt.tag_configure(tag, foreground=color)

        # ---- status bar ----
        from opngx._engine import detect_gpus

        gpus = ", ".join(g.split("(")[0].strip() for g in detect_gpus()) or "no GPU"
        ttk.Label(
            self,
            style="Status.TLabel",
            text=f"engine: {opngx.engine_backend()}   •   "
            f"cpus: {os.cpu_count()}   •   gpu: {gpus}",
        ).pack(fill="x", padx=PAD, pady=(0, PAD))

    # ------------------------------------------------------------ actions
    def _sync_labels(self) -> None:
        self.jobs_lbl.configure(text=str(int(self.jobs_var.get())))
        self.level_lbl.configure(text=str(int(self.level_var.get())))

    def _mode_changed(self) -> None:
        custom = self.mode_var.get() == "custom"
        reference = self.mode_var.get() == "reference"
        if custom and not self.b_var.get():
            self.b_var.set(49)
            self.c_var.set(18)

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
            import glob

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

    def _set_info(self, rows: list[tuple[str, str]]) -> None:
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
            import glob

            root = self.bin_var.get().strip()
            bins = sorted(glob.glob(os.path.join(root, "*", "*.bin"))) + sorted(
                glob.glob(os.path.join(root, "*.bin"))
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

        def run_one(bin_path: str, out_dir: str) -> opngx.ExtractStats:
            emit_log("info", f"extract {os.path.basename(bin_path)} → {out_dir}")
            ex = opngx.Extractor(bin_path)
            return ex.extract(
                out_dir,
                progress=progress,
                should_cancel=lambda: self._cancel_requested,
                **opts,
            )

        def worker() -> None:
            try:
                last: Optional[opngx.ExtractStats] = None
                for i, b in enumerate(bins):
                    if self._cancel_requested:
                        break
                    stem = os.path.splitext(os.path.basename(b))[0]
                    od = (
                        out
                        if len(bins) == 1
                        else os.path.join(out, stem.replace(".", "_"))
                    )
                    last = run_one(b, od)
                if last is not None:
                    self._uiq.put(("done", last))
            except Exception as exc:  # surfaced on UI thread
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
                self.after(0, lambda: messagebox.showinfo("verification", msg))
            except Exception as exc:
                self._uiq.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
