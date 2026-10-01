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


def _selftest_log():
    """Windowed (console=False) exes have no stdout on Windows — route
    everything (incl. C-level output) into OPNGX_SELFTEST_LOG."""
    import os
    import sys

    log_path = os.environ.get("OPNGX_SELFTEST_LOG", "selftest-ui.log")
    # utf-8: the Windows default (cp1252) could not even print "✗" and the
    # selftest died inside its own error report
    logf = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
    try:
        os.dup2(logf.fileno(), 1)
        os.dup2(logf.fileno(), 2)
    except OSError:
        pass
    sys.stdout = sys.stderr = logf
    return logf


def _selftest_engine() -> int:
    """Full native round-trip INSIDE the packaged exe:
    synthesize a recording -> extract via the ctypes engine -> verify with
    the bundled opngx-engine CLI (verifybin). Proves the exact chain that
    failed on user Windows machines (SQ_100_s1 case)."""
    import os
    import struct
    import tempfile
    from pathlib import Path

    import numpy as np

    logf = _selftest_log()
    print("SELFTEST-ENGINE start")
    try:
        from opngx._engine import load_library
        from opngx.verify import _engine_binary, verify_against_bin

        assert load_library() is not None, "libopngx did not load"
        w, h, n = 64, 48, 30
        rng = np.random.default_rng(11)
        d = Path(tempfile.mkdtemp(prefix="opngx_eng_selftest_"))
        binp = d / "SQ_100_s1.bin"
        with open(binp, "wb") as f:
            for i in range(n):
                f.write(struct.pack("<Q", 5_000_000 + i * 2000))
                f.write(rng.integers(0, 256, size=(h * w), dtype=np.uint8).tobytes())
        out = d / "SQ_100_s1_png"  # spaces-free but real subdir
        from opngx.extractor import Extractor

        st = Extractor(str(binp), width=w, height=h).extract(
            str(out), mode="raw", jobs=2, prefix="SQ_100_"
        )
        assert st.frames_written == n, f"extract wrote {st.frames_written}"
        eng = _engine_binary()
        assert eng, "bundled opngx-engine CLI not found"
        print(f"engine cli: {eng}")
        rep = verify_against_bin(
            str(binp), str(out), mode="raw", width=w, height=h, prefix="SQ_100_"
        )
        assert rep.passed, rep.first_error
        print(f"SELFTEST-ENGINE PASS ({n} frames verified vs source bin)")
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        print("SELFTEST-ENGINE FAIL")
        return 1
    finally:
        logf.flush()


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
    import traceback

    logf = _selftest_log()
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
            # v1.7 additions
            "_open_batch_window",
            "_open_crop_editor",
            "load_batch_item",
            "batch_btn",
            "crop_btn",
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


def _selftest_batch() -> int:
    """Prove the v1.7 batch + crop path INSIDE the packaged exe.

    Builds a two-recording mother folder with IDENTICAL .bin filenames
    (the cycle-22 data-loss case), runs the batch through the UI's own
    BatchWindow, crops both, and verifies the output is cropped, in two
    separate folders. Exit 0 = pass."""
    import os
    import struct
    import tempfile
    from pathlib import Path

    import numpy as np

    logf = _selftest_log()
    print("SELFTEST-BATCH start")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtWidgets  # noqa: PLC0415

        from opngx.ui.batch import BatchWindow  # noqa: PLC0415

        w, h, n = 64, 48, 6
        d = Path(tempfile.mkdtemp(prefix="opngx_batch_selftest_"))
        mother = d / "mother"
        for cam in ("camA", "camB"):  # same .bin name in BOTH folders
            (mother / cam).mkdir(parents=True)
            rng = np.random.default_rng(3)
            with open(mother / cam / "recording.bin", "wb") as f:
                for i in range(n):
                    f.write(struct.pack("<Q", 9_000_000 + i * 2000))
                    f.write(
                        rng.integers(0, 256, size=(h * w), dtype=np.uint8).tobytes()
                    )
            (mother / cam / "recording.footage").write_text(
                '<?xml version="1.0"?><TimeViewer>'
                "<SettingsProcessing><Brightness>49</Brightness>"
                "<Contrast>18</Contrast><Gamma>1.0</Gamma>"
                "</SettingsProcessing>"
                "<ResolutionX>64</ResolutionX><ResolutionY>48</ResolutionY>"
                "<NumberOfImages>6</NumberOfImages><Framerate>500</Framerate>"
                "</TimeViewer>"
            )

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        win = BatchWindow(
            None,
            str(mother),
            str(d / "out"),
            dict(
                fmt="png",
                mode="reference",
                bit_depth=8,
                channels=6,
                jobs=2,
                level=6,
                prefix="brow_",
                ext=".Png",
            ),
        )
        assert len(win.items) == 2, f"expected 2 recordings, got {len(win.items)}"
        assert all(i.thumb is not None for i in win.items), "cards must show a frame"
        outs = {i.out_dir for i in win.items}
        assert len(outs) == 2, f"output folders collide: {outs}"

        crop = (8, 4, 20, 12)
        for i in win.items:
            i.crop = crop
            win.cards[i.bin_path].refresh()

        loop = QtCore.QEventLoop()
        win.finished.connect(lambda _: loop.quit())
        win.start()
        QtCore.QTimer.singleShot(120000, loop.quit)
        loop.exec()

        bad = [(i.name, i.status, i.error) for i in win.items if i.status != "done"]
        assert not bad, f"batch did not finish cleanly: {bad}"
        from PIL import Image  # noqa: PLC0415

        for cam in ("camA", "camB"):
            files = sorted((d / "out" / cam / "PNG").glob("*.Png"))
            assert len(files) == n, f"{cam}: {len(files)} files, expected {n}"
            with Image.open(files[0]) as im:
                assert im.size == (20, 12), f"{cam}: cropped size {im.size}"
        print(
            f"SELFTEST-BATCH PASS (2 recordings, same .bin name, "
            f"crop {crop[2]}x{crop[3]}, {n} frames each)"
        )
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        print("SELFTEST-BATCH FAIL")
        return 1
    finally:
        logf.flush()


def _selftest_analysis() -> int:
    """Prove the v1.10 analysis system INSIDE the packaged exe: the built-in
    modules are bundled, motion tracking recovers a known sub-pixel
    trajectory from a real .bin, a USER module loads from a file on disk,
    and the data files are written. Exit 0 = pass."""
    import os
    import struct
    import tempfile
    from pathlib import Path

    import numpy as np

    logf = _selftest_log()
    print("SELFTEST-ANALYSIS start")
    try:
        d = Path(tempfile.mkdtemp(prefix="opngx_an_selftest_"))
        os.environ["OPNGX_MODULES_DIR"] = str(d / "modules")
        import opngx.analysis as oa  # noqa: PLC0415

        names = [i.name for i in oa.list_modules()]
        assert {"motion_tracking", "luminosity", "contrast"} <= set(names), names
        W, H, n = 96, 80, 40
        truth = np.c_[40 + 0.37 * np.arange(n), 38 + 0.21 * np.arange(n)]
        yy, xx = np.mgrid[0:H, 0:W]
        rec = d / "rec"
        rec.mkdir()
        with open(rec / "rec.bin", "wb") as f:
            for i, (x, y) in enumerate(truth):
                img = 60 + 150 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.2**2))
                f.write(struct.pack("<Q", 7_000_000 + 2000 * i))
                f.write(np.clip(np.round(img), 0, 255).astype(np.uint8).tobytes())
        (rec / "rec.footage").write_text(
            f"<x><ResolutionX>{W}</ResolutionX><ResolutionY>{H}</ResolutionY>"
            f"<NumberOfImages>{n}</NumberOfImages></x>"
        )
        run = oa.analyze(str(rec / "rec.bin"), ["motion_tracking", "luminosity", "contrast"])
        assert run.ok, run.errors
        tr = run["motion_tracking"]
        err = np.hypot(tr.columns["x"] - truth[:, 0], tr.columns["y"] - truth[:, 1])
        assert np.sqrt(np.mean(err**2)) < 0.05, f"tracking RMS {np.sqrt(np.mean(err**2)):.4f} px"
        assert np.allclose(tr.columns["time_s"], 0.002 * np.arange(n))
        for ext in ("csv", "json", "npz"):
            p_ = tr.save(str(d / f"traj.{ext}"))
            assert os.path.getsize(p_) > 0
        # a user module written to disk loads and runs in the frozen app
        md = Path(oa.user_modules_dir(create=True))
        (md / "selftest_mod.py").write_text(oa.template("selftest_mod", "Selftest"), encoding="utf-8")
        v = oa.validate_file(str(md / "selftest_mod.py"))
        assert v.ok, v.messages
        r2 = oa.analyze(str(rec / "rec.bin"), "selftest_mod")
        assert len(r2["selftest_mod"]) == n
        # v2.0.3: the Editor opens built-in modules from their SOURCE file,
        # which a frozen app only has if the spec bundles it (v2.0.0-2.0.2
        # did not: clicking a built-in module silently did nothing)
        for info in oa.discover():
            if info.origin == "builtin":
                assert os.path.isfile(info.path), f"no source for built-in {info.name}: {info.path}"
        # samples land in an EMPTY user folder, validate, and are not re-copied
        sd = d / "fresh"
        got = oa.seed_examples(str(sd / "modules"), str(sd / "docs"))
        pys = sorted(p_.name for p_ in (sd / "modules").glob("example_*.py"))
        assert len(pys) >= 4 and (sd / "modules" / "README.md").is_file(), got
        assert list((sd / "docs").glob("*.md")), "sample doc missing"
        for fn in pys:
            vv = oa.validate_file(str(sd / "modules" / fn))
            assert vv.ok, (fn, vv.messages)
        assert oa.seed_examples(str(sd / "modules"), str(sd / "docs")) == []
        # every guide + the release notes reach the Docs tab
        from opngx.ui.docs_ui import bundled_docs  # noqa: PLC0415

        docs = {os.path.basename(p_) for _t, p_ in bundled_docs()}
        need = {"ANALYSIS.md", "STUDIO.md", "FORMAT.md"}
        assert need <= docs, f"missing docs: {need - docs}"
        assert any(x.startswith("RELEASE-NOTES-") for x in docs), "no release notes bundled"
        print(f"editor sources OK; samples {pys}; {len(docs)} docs")
        print(
            f"SELFTEST-ANALYSIS PASS ({len(names)} built-in modules; tracking RMS "
            f"{np.sqrt(np.mean(err**2)):.4f} px over {n} frames; user module OK)"
        )
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        print("SELFTEST-ANALYSIS FAIL")
        return 1
    finally:
        logf.flush()


def _proc_cpu_seconds(handle=None) -> float:
    """User+kernel CPU seconds of this process (or of a child's handle on
    Windows, where os.times() never reports children)."""
    import os

    if handle is not None and os.name == "nt":
        import ctypes
        from ctypes import wintypes

        ft = [wintypes.FILETIME() for _ in range(4)]
        ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(int(handle)), *[ctypes.byref(f) for f in ft])
        to_s = lambda f: ((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7  # noqa: E731
        return to_s(ft[2]) + to_s(ft[3])
    t = os.times()
    if handle is not None:
        return t.children_user + t.children_system
    return t.user + t.system


def _selftest_speed() -> int:
    """Throughput INSIDE the packaged app, the three ways a user extracts:
    the bundled engine CLI, the in-process API (ctypes -> libopngx) and the
    studio window's Extract button. Same synthetic recording for all.
    Reports frames/s, CPU utilisation, threads, backend and the DLL that
    loaded. Fails if the API or the studio is far behind the CLI, i.e. if
    the Python/Qt layer starves the engine (field report: 'extraction no
    longer uses all cores'). Exit 0 = pass."""
    import os
    import shutil
    import struct
    import subprocess
    import tempfile
    import time
    from pathlib import Path

    import numpy as np

    logf = _selftest_log()
    print("SELFTEST-SPEED start")
    try:
        import opngx
        from opngx._engine import library_path, load_library
        from opngx.verify import _engine_binary

        assert load_library() is not None, "libopngx did not load"
        cores = os.cpu_count() or 1
        n = int(os.environ.get("OPNGX_SPEED_FRAMES", "6000"))
        w, h = 256, 300  # this project's sensor window
        d = Path(tempfile.mkdtemp(prefix="opngx_speed_"))
        rec = d / "speed"
        rec.mkdir()
        rng = np.random.default_rng(5)
        yy, xx = np.mgrid[0:h, 0:w]
        base = 40 + 8 * rng.standard_normal((h, w))
        with open(rec / "speed.bin", "wb") as f:
            for i in range(n):
                cx, cy = 128 + 3 * np.sin(i / 40), 150 + 3 * np.cos(i / 55)
                r = np.hypot(xx - cx, yy - cy)
                img = base + 90 * np.exp(-((r - 18) ** 2) / 8) + rng.normal(0, 3, (h, w))
                f.write(struct.pack("<Q", 9_000_000 + 2000 * i))
                f.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())
        # a real TimeViewer layout, so the default (reference) mode applies
        (rec / "speed.footage").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<Optronis-TimeViewer-Footage>'
            f"<Footage><ResolutionX>{w}</ResolutionX><ResolutionY>{h}</ResolutionY>"
            f"<NumberOfImages>{n}</NumberOfImages><Framerate>500</Framerate></Footage>"
            "<SettingsProcessing><Brightness>49</Brightness><Contrast>18</Contrast>"
            "<Gamma>1</Gamma></SettingsProcessing><Camera><Name>speed</Name></Camera>"
            "</Optronis-TimeViewer-Footage>",
            encoding="utf-8",
        )
        binp = str(rec / "speed.bin")
        open(binp, "rb").read()  # warm the file cache: measure the engine, not the disk
        print(f"cores={cores} frames={n} size={w}x{h} lib={library_path()}")
        res = {}

        # 1. bundled CLI (the reference: pure C, no Python)
        eng = _engine_binary()
        assert eng, "bundled opngx-engine CLI not found"
        out = d / "o_cli"
        t0 = time.perf_counter()
        p = subprocess.Popen([eng, "extract", "--bin", binp, "--footage", str(rec / "speed.footage"),
                              "--out", str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.wait()
        dt = time.perf_counter() - t0
        cpu = _proc_cpu_seconds(getattr(p, "_handle", None) if os.name == "nt" else 0)
        assert p.returncode == 0, f"engine exit {p.returncode}"
        res["cli"] = (n / dt, 100 * cpu / dt)
        shutil.rmtree(out, ignore_errors=True)

        # 2. in-process API
        out = d / "o_api"
        c0, t0 = _proc_cpu_seconds(), time.perf_counter()
        st = opngx.extract(binp, str(out))
        dt = time.perf_counter() - t0
        res["api"] = (n / dt, 100 * (_proc_cpu_seconds() - c0) / dt)
        assert st.frames_written == n, st
        print(f"api backend={st.backend}")
        shutil.rmtree(out, ignore_errors=True)

        # 3. the studio window, exactly as a user clicks Extract
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        from opngx.ui.qt_app import MainWindow

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        win = MainWindow()
        win.show()
        app.processEvents()
        win.bin_edit.setText(binp)
        win._probe()
        out = d / "o_studio"
        win.out_edit.setText(str(out))
        app.processEvents()
        jobs = win.jobs_slider.value()
        c0, t0 = _proc_cpu_seconds(), time.perf_counter()
        win._start()
        while True:
            app.processEvents()
            time.sleep(0.005)
            if not win._running and time.perf_counter() - t0 > 0.3:
                break
            if time.perf_counter() - t0 > 900:
                raise RuntimeError("studio extraction did not finish in 15 min")
        dt = time.perf_counter() - t0
        res["studio"] = (n / dt, 100 * (_proc_cpu_seconds() - c0) / dt)
        files = sum(len(fs) for _, _, fs in os.walk(out))
        assert files >= n, f"studio wrote {files} files"
        print(f"studio jobs slider={jobs}")
        win.close()
        shutil.rmtree(d, ignore_errors=True)

        for k, (fps, cpu) in res.items():
            print(f"  {k:7} {fps:8.0f} frames/s   CPU {cpu:5.0f}% of {100 * cores}%")
        ref = res["cli"][0]
        bad = [k for k in ("api", "studio") if res[k][0] < 0.6 * ref]
        if bad:
            print(f"SELFTEST-SPEED FAIL: {bad} under 60% of the CLI's throughput")
            return 1
        print(f"SELFTEST-SPEED PASS (studio {res['studio'][0]:.0f} fps = "
              f"{100 * res['studio'][0] / ref:.0f}% of the bundled CLI)")
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        print("SELFTEST-SPEED FAIL")
        return 1
    finally:
        logf.flush()


if __name__ == "__main__":
    if "--selftest-speed" in sys.argv:
        raise SystemExit(_selftest_speed())
    if "--selftest-analysis" in sys.argv:
        raise SystemExit(_selftest_analysis())
    if "--debug-ffmpeg" in sys.argv:
        raise SystemExit(_debug_ffmpeg())
    if "--selftest-video" in sys.argv:
        raise SystemExit(_selftest_video())
    if "--selftest-batch" in sys.argv:
        raise SystemExit(_selftest_batch())
    if "--selftest-ui" in sys.argv:
        raise SystemExit(_selftest_ui())
    if "--selftest-engine" in sys.argv:
        raise SystemExit(_selftest_engine())
    from opngx.ui import main  # noqa: E402

    raise SystemExit(main())
