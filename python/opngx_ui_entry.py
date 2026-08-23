#!/usr/bin/env python3
"""PyInstaller entry point for the opngx studio GUI.

Uses the Qt edition (PySide6, bundled); falls back to Tkinter if Qt is
unavailable at runtime.
"""
import multiprocessing

multiprocessing.freeze_support()          # required for onefile pools

import sys                                # noqa: E402

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
    st = render_video(str(binp), str(out), mode="raw", width=w, height=h,
                      start=0, count=n, fps=10, crf=30)
    ok = (st["frames_written"] == n and out.exists()
          and out.stat().st_size > 1024)
    print(f"SELFTEST {'PASS' if ok else 'FAIL'} "
          f"({st['frames_written']} frames, {out.stat().st_size} bytes)")
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


if __name__ == "__main__":
    if "--debug-ffmpeg" in sys.argv:
        raise SystemExit(_debug_ffmpeg())
    if "--selftest-video" in sys.argv:
        raise SystemExit(_selftest_video())
    from opngx.ui import main                 # noqa: E402
    raise SystemExit(main())
