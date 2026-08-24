#!/usr/bin/env python3
"""PyInstaller entry point for the opngx studio GUI.

Uses the Qt edition (PySide6, bundled); falls back to Tkinter if Qt is
unavailable at runtime.
"""

import multiprocessing

multiprocessing.freeze_support()  # required for onefile pools

import sys  # noqa: E402


def _selftest_video() -> int:
    """Prove the BUNDLED ffmpeg works inside this exe: synthesize a tiny
    recording, render 10 frames, verify the MP4. Exit code 0 = pass."""
    import struct, tempfile, os
    from pathlib import Path
    import numpy as np
    from opngx.video import render_video

    w, h, n = 64, 48, 10
    d = Path(tempfile.mkdtemp(prefix="opngx_selftest_"))
    rng = np.random.default_rng(7)
    binp = d / "st.bin"
    with open(binp, "wb") as f:
        for i in range(n):
            f.write(struct.pack("<Q", 1_000_000 + i * 2000))
            f.write(rng.integers(0, 256, size=(h * w), dtype=np.uint8).tobytes())
    out = d / "selftest.mp4"
    st = render_video(
        str(binp),
        str(out),
        mode="raw",
        width=w,
        height=h,
        start=0,
        count=n,
        fps=10,
        crf=30,
    )
    ok = st["frames_written"] == n and out.exists() and out.stat().st_size > 1024
    print(
        f"SELFTEST {'PASS' if ok else 'FAIL'} "
        f"({st['frames_written']} frames, {out.stat().st_size} bytes)"
    )
    return 0 if ok else 1


def _debug_ffmpeg():
    import sys, os

    print(f"sys._MEIPASS = {getattr(sys, '_MEIPASS', 'NOT SET')}")
    print(f"sys.executable = {sys.executable}")
    mei = getattr(sys, "_MEIPASS", None)
    if mei and os.path.isdir(mei):
        for root, dirs, files in os.walk(mei):
            for f in files:
                if "ffmpeg" in f.lower() or "ffbin" in f.lower():
                    print(f"  FOUND: {os.path.join(root, f)}")
            # only go 2 levels deep
            if root.count(os.sep) - mei.count(os.sep) > 2:
                dirs.clear()
    # also check for any exe/binary in _MEIPASS root
    if mei and os.path.isdir(mei):
        for f in os.listdir(mei):
            fp = os.path.join(mei, f)
            if os.path.isfile(fp) and os.access(fp, os.X_OK):
                sz = os.path.getsize(fp)
                if sz > 1000000:
                    print(f"  BIG BIN: {f} ({sz:,} bytes)")
    return 0


def _selftest_ui() -> int:
    """Construct the full studio offscreen inside the packaged exe.

    v1.4.0 shipped a studio that crashed at launch on Windows
    (AttributeError: '_log') because CI never executed MainWindow.
    This selftest closes that gap: exit 0 = the window builds with every
    action wired; anything else fails the CI job.

    Windowed (console=False) exes have no stdout on Windows, so ALL
    output — including C-level Qt messages — is dup2'd into a log file
    (OPNGX_SELFTEST_LOG, default selftest-ui.log) that CI prints.
    """
    import os
    import sys
    import traceback

    log_path = os.environ.get("OPNGX_SELFTEST_LOG", "selftest-ui.log")
    logf = open(log_path, "w", buffering=1)
    try:
        os.dup2(logf.fileno(), 1)
        os.dup2(logf.fileno(), 2)
    except OSError:
        pass
    sys.stdout = sys.stderr = logf

    print(f"SELFTEST-UI start (pid={os.getpid()})")

    from PySide6 import QtWidgets  # noqa: PLC0415

    app = None
    for platform in ("offscreen", "minimal"):
        os.environ["QT_QPA_PLATFORM"] = platform
        try:
            app = QtWidgets.QApplication([])
            print(f"QApplication ok on platform={platform}")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"QApplication failed on platform={platform}: {exc}")
            app = None
    if app is None:
        print("SELFTEST-UI FAIL: no usable Qt platform plugin")
        logf.flush()
        return 1

    try:
        from opngx.ui.qt_app import MainWindow  # noqa: PLC0415

        win = MainWindow()
        required = (
            "_probe",
            "_start",
            "_cancel",
            "_verify",
            "_log",
            "_on_dialog",
            "_refresh_frame",
            "w_spin",
            "h_spin",
            "cpu_chip",
            "ram_chip",
        )
        missing = [a for a in required if not hasattr(win, a)]
        if missing:
            print(f"SELFTEST-UI FAIL: MainWindow lacks {missing}")
            return 1
        # NOTE: icon presence is style-dependent (some Windows styles return
        # null for certain QStyle standard icons), so it is intentionally
        # NOT gated here — this selftest guards MainWindow construction.
        print(
            f"SELFTEST-UI PASS (cpu chip: {win.cpu_chip.text()}, "
            f"ram chip: {win.ram_chip.text()})"
        )
        return 0
    except Exception:
        traceback.print_exc()
        print("SELFTEST-UI FAIL: exception constructing MainWindow")
        return 1
    finally:
        logf.flush()


if __name__ == "__main__":
    if "--debug-ffmpeg" in sys.argv:
        raise SystemExit(_debug_ffmpeg())
    if "--selftest-video" in sys.argv:
        raise SystemExit(_selftest_video())
    if "--selftest-ui" in sys.argv:
        raise SystemExit(_selftest_ui())
    from opngx.ui import main  # noqa: E402

    raise SystemExit(main())
