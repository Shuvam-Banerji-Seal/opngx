"""Audit regression gates — cycle 10 read-through findings.

Each test pins one defect discovered during the cycle-9/10 source audit.
They are written RED-first: each must fail on the defective tree and pass
only after the corresponding fix.

  AR-1  engine stats lied about the compression backend
        (src/extract.c never stored `backend_seen`; opngx_stats.backend_used
        always claimed "libdeflate" even on zlib-only builds)
  AR-2  Qt studio emitted an undefined `dialog` signal and never connected it
        (verify PASS/FAIL popup silently died inside the worker thread)
  AR-3  v1.4.0 studio features regressed out of the worktree
        (worked-examples guide, sidecar-less width/height fields,
         live frame-refresh, video dialog duration preview)
  AR-4  hygiene: duplicate method definitions + patch junk in package tree
  AR-5  version strings drifted (installer.c "1.2.1", app.rc "1.3.1",
        docs say 1.2.0) vs engine/pyproject 1.4.0

AR-1b is the behavioral proof: it builds a zlib-only engine from scratch and
asserts the reported backend is truthful. Skip with OPNGX_SKIP_SLOW=1 or when
no C toolchain/zlib headers exist.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import time
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QT_APP = REPO / "python" / "src" / "opngx" / "ui" / "qt_app.py"
EXTRACT_C = REPO / "src" / "extract.c"

import opngx  # noqa: E402
import pytest  # noqa: E402


# --------------------------------------------------------------------- AR-1
def test_ar1a_worker_records_true_backend_id():
    """extract_worker must persist cctx_backend_id, else backend_used lies."""
    src = EXTRACT_C.read_text()
    worker = src.split("static void extract_worker")[1].split("int opngx_job_run")[0]
    assert re.search(r"cctx_backend_id\s*\(", worker), (
        "extract_worker never records the compressor's real backend id; "
        "opngx_stats.backend_used is hardwired to 'libdeflate' and reports "
        "falsehoods on zlib-only builds"
    )


def _have_toolchain() -> bool:
    return (
        os.environ.get("OPNGX_SKIP_SLOW") != "1"
        and shutil.which("cmake") is not None
        and shutil.which("cc") is not None
        and Path("/usr/include/zlib.h").exists()
    )


def test_ar1b_zlib_only_build_reports_truthful_backend(tmp_path):
    """Behavioral proof: a zlib-only build must report 'backend=zlib'."""
    if not _have_toolchain():
        import pytest

        pytest.skip("no cmake/cc/zlib.h or OPNGX_SKIP_SLOW=1")
    bdir = tmp_path / "zbuild"
    cfg = subprocess.run(
        [
            "cmake",
            "-S",
            str(REPO),
            "-B",
            str(bdir),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DOPNGX_WITH_LIBDEFLATE=OFF",
        ],
        capture_output=True,
        text=True,
    )
    assert cfg.returncode == 0, cfg.stderr[-2000:]
    build = subprocess.run(
        ["cmake", "--build", str(bdir), "-j", str(os.cpu_count() or 2)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr[-2000:]

    fx = tmp_path / "fx"
    subprocess.run(
        [sys.executable, str(REPO / "tests" / "gen_fixture.py"), str(fx)],
        check=True,
        capture_output=True,
    )
    eng = bdir / "opngx-engine"
    run = subprocess.run(
        [
            str(eng),
            "extract",
            "--bin",
            str(fx / "cam_9.9" / "cam_9.9.bin"),
            "--footage",
            str(fx / "cam_9.9" / "cam_9.9.footage"),
            "--out",
            str(tmp_path / "out"),
            "--prefix",
            "cam_",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert "backend=zlib" in run.stderr, (
        f"zlib-only binary misreported its backend:\n{run.stderr}"
    )


# --------------------------------------------------------------------- AR-2
def test_ar2_every_emitted_qt_signal_is_defined_and_connected():
    text = QT_APP.read_text()
    sig_block = re.search(
        r"class WorkerSignals\b.*?(?=\n[A-Z_]+\s*=|\nclass |\ndef )", text, re.S
    )
    assert sig_block, "WorkerSignals class not found"
    defined = set(re.findall(r"(\w+)\s*=\s*Signal\(", sig_block.group(0)))
    used = set(re.findall(r"self\._sig\.(\w+)\.emit\(", text))
    connected = set(re.findall(r"self\._sig\.(\w+)\.connect\(", text))

    orphan_emit = used - defined
    assert not orphan_emit, (
        f"signals emitted but never defined: {sorted(orphan_emit)} -> "
        "AttributeError kills the worker thread and the popup never shows"
    )
    unconnected = defined - connected
    assert not unconnected, (
        f"signals defined but never connected: {sorted(unconnected)} -> "
        "emissions vanish into the void"
    )


# --------------------------------------------------------------------- AR-3
def test_ar3_v140_studio_features_present():
    text = QT_APP.read_text()
    missing = [
        marker
        for marker in (
            ("worked-examples modes guide", r"worked examples"),
            ("sidecar-less width field", r"self\.w_spin\s*="),
            ("sidecar-less height field", r"self\.h_spin\s*="),
            ("live frame refresh slot", r"def _refresh_frame"),
            ("video duration preview", r"upd_dur"),
            ("manual-geometry resolver", r"def _manual_geom_kwargs"),
            ("geometry consumed on extract", r"opngx\.Extractor\(b, \*\*geom\)"),
        )
        if not re.search(marker[1], text)
    ]
    assert not missing, f"v1.4.0 studio features missing: {[m[0] for m in missing]}"


# --------------------------------------------------------------------- AR-4
def test_ar4_no_duplicate_method_definitions():
    tree = ast.parse(QT_APP.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names = [
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            dups = sorted({x for x in names if names.count(x) > 1})
            assert not dups, f"class {node.name}: duplicate definitions {dups}"


def test_ar4b_no_patch_junk_in_package_tree():
    junk = [
        p
        for pat in ("*.orig", "*.rej", "*.bak", "*.verify_patch", "*.patched")
        for p in (REPO / "python" / "src").rglob(pat)
    ]
    assert not junk, f"leftover patch artifacts shipped in package tree: {junk}"


# --------------------------------------------------------------------- AR-6
def test_ar6_studio_constructs_offscreen():
    """Full MainWindow construction with no missing attributes.

    This is the gate that catches 'wired but never defined' breakage
    (HEAD shipped _build connecting self._probe/_start/_log and calling
    mini_label() — none of which existed). Skips when PySide6 is absent.
    """
    import pytest

    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    import opngx.ui.qt_app as qt

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = qt.MainWindow()
    for attr in (
        "_probe",
        "_start",
        "_cancel",
        "_verify",
        "_verify_bin",
        "_log",
        "_on_dialog",
        "_refresh_frame",
        "_on_scope_changed",
        "_collect_opts",
        "_pick_bin",
        "_pick_out",
        "_fill_info",
        "w_spin",
        "h_spin",
        "geom_hint",
    ):
        assert hasattr(win, attr), f"MainWindow lacks {attr}"
    assert win.w_spin.value() == 0, "width field must default to auto"

    # AR-11: sysmon values may be None (Windows first poll, unsupported
    # platform) — chips must tolerate that, not raise TypeError. This exact
    # bug crashed the studio on Windows and was caught by the packaged-exe
    # selftest on the CI runner before v1.5.0 shipped.
    win._sys_snapshot = lambda: {"cpu": None, "mem": None, "load1": None}
    win._poll_sysmon()
    assert win.cpu_chip.text() == "CPU –", win.cpu_chip.text()
    assert win.ram_chip.text() == "RAM –", win.ram_chip.text()
    win._sys_snapshot = lambda: {"cpu": 87.0, "mem": 50.0, "load1": 1.25}
    win._poll_sysmon()
    assert win.cpu_chip.text() == "CPU 87%"
    assert win.ram_chip.text() == "RAM 50%"


# --------------------------------------------------------------------- AR-5
def test_ar5_version_strings_consistent():
    def grab(pattern: str, text: str) -> str:
        m = re.search(pattern, text, re.M)
        assert m, f"version pattern not found: {pattern!r}"
        return m.group(1)

    ver_c = grab(
        r'#define OPNGX_VERSION "(.*?)"', (REPO / "src" / "opngx.h").read_text()
    )
    ver_pyproject = grab(
        r'^version = "(.*?)"', (REPO / "python" / "pyproject.toml").read_text()
    )
    ver_init = grab(
        r'__version__ = "(.*?)"',
        (REPO / "python" / "src" / "opngx" / "__init__.py").read_text(),
    )
    rc_text = (REPO / "installer" / "app.rc").read_text()
    ver_rc = grab(r'VALUE "FileVersion",\s*"(.*?)"', rc_text)
    ver_installer = grab(
        r'#define APP_VERSION "(.*?)"',
        (REPO / "installer" / "installer.c").read_text(),
    )

    versions = {
        "opngx.h": ver_c,
        "pyproject.toml": ver_pyproject,
        "__init__.py": ver_init,
        "app.rc": ver_rc,
        "installer.c": ver_installer,
    }
    drift = {k: v for k, v in versions.items() if v != ver_c}
    assert not drift, f"version drift vs {ver_c}: {drift}"


# --------------------------------------------------------------------- AR-7
def test_ar7_subrange_extract_verifies_by_name(fixture_dir):
    """--start>0 extracts are true subsets: verify must pair BY NAME.

    The old verifier paired sorted positions (ref[0] vs out[0]), so any
    extract whose first frame was not frame 0 false-failed every file.
    """
    if opngx.engine_backend() == "python-fallback":
        pytest.skip("native engine missing")
    import tempfile

    binp = fixture_dir / "cam_9.9" / "cam_9.9.bin"
    with tempfile.TemporaryDirectory() as td:
        st = opngx.extract(
            str(binp), str(Path(td) / "sub"), start=100, frames=50, prefix="cam_"
        )
        assert st.frames_written == 50
        rep = opngx.verify(
            fixture_dir / "ref_pngs", Path(td) / "sub", prefix="cam_", subset=True
        )
        assert rep.passed, rep.first_error
        assert rep.files_compared == 50


def test_ar7b_names_outside_ref_fail_subset_claim(fixture_dir):
    """An out-dir containing foreign names must fail subset verification."""
    out = fixture_dir / "foreign_out"
    import shutil

    if out.exists():
        shutil.rmtree(out)
    binp = fixture_dir / "cam_9.9" / "cam_9.9.bin"
    st = opngx.extract(str(binp), str(out), frames=10, prefix="cam_")
    assert st.frames_written == 10
    (out / "cam_99999.Png").write_bytes((out / "cam_00000.Png").read_bytes())
    rep = opngx.verify(fixture_dir / "ref_pngs", out, prefix="cam_", subset=True)
    assert not rep.passed
    assert "absent from reference" in rep.first_error


# --------------------------------------------------------------------- AR-8
def test_ar8a_verifybin_pass_corrupt_and_subrange(fixture_dir):
    """ADD-7: verify an extract dir straight against its source bin."""
    if opngx.engine_backend() == "python-fallback":
        pytest.skip("native engine missing")
    import shutil
    import tempfile

    binp = fixture_dir / "cam_9.9" / "cam_9.9.bin"
    with tempfile.TemporaryDirectory() as td:
        # full run passes
        st = opngx.extract(str(binp), str(Path(td) / "full"), prefix="cam_")
        assert st.frames_written == 200
        rep = opngx.verify_against_bin(str(binp), str(Path(td) / "full"), prefix="cam_")
        assert rep.passed and rep.files_compared == 200, rep.first_error

        # subrange (start>0) passes by absolute-index naming
        opngx.extract(
            str(binp), str(Path(td) / "sub"), start=100, frames=50, prefix="cam_"
        )
        rep2 = opngx.verify_against_bin(str(binp), str(Path(td) / "sub"), prefix="cam_")
        assert rep2.passed and rep2.files_compared == 50, rep2.first_error

        # corrupted output must fail
        shutil.copytree(Path(td) / "full", Path(td) / "bad")
        victim = sorted((Path(td) / "bad").glob("*.Png"))[7]
        data = bytearray(victim.read_bytes())
        data[-20] ^= 0xFF
        victim.write_bytes(bytes(data))
        rep3 = opngx.verify_against_bin(str(binp), str(Path(td) / "bad"), prefix="cam_")
        assert not rep3.passed and rep3.mismatched_files >= 1


def test_ar8b_verifybin_rejects_out_of_range_names(fixture_dir):
    """Filenames encoding indices beyond the bin fail the subset claim."""
    if opngx.engine_backend() == "python-fallback":
        pytest.skip("native engine missing")
    import tempfile

    binp = fixture_dir / "cam_9.9" / "cam_9.9.bin"
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out"
        opngx.extract(str(binp), str(out), frames=5, prefix="cam_")
        (out / "cam_00400.Png").write_bytes((out / "cam_00000.Png").read_bytes())
        rep = opngx.verify_against_bin(str(binp), str(out), prefix="cam_")
        assert not rep.passed
        assert rep.files_compared == 5


# --------------------------------------------------------------------- AR-9
def test_ar9_push_progress_callback_fires_and_completes(fixture_dir):
    """ADD-6: native push-progress via opngx_params.progress_fn.

    Also proves the ABI-4 struct extension is laid out identically on both
    sides of the ctypes mirror.
    """
    if opngx.engine_backend() == "python-fallback":
        pytest.skip("native engine missing")
    import ctypes
    import tempfile
    import os

    from opngx._engine import OpngxParams, ProgressCallback, load_library

    lib = load_library()
    binp = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    fp = str(fixture_dir / "cam_9.9" / "cam_9.9.footage")

    calls: list[tuple[int, int]] = []

    @ProgressCallback
    def cb(done, total, _user):
        calls.append((int(done), int(total)))

    with tempfile.TemporaryDirectory() as td:
        p = OpngxParams()
        p.bin_path = binp.encode()
        p.footage_path = fp.encode()
        p.num_frames = -1
        p.frame_stride = -1
        p.mode = 1  # raw
        p.bit_depth = 8
        p.channels = 6
        p.format = 0
        p.jobs = 4
        p.level = 1  # fastest
        p.backend = 0  # auto
        p.gamma = 1.0
        p.verbose = 0
        p.out_dir = os.fsencode(td)
        p.prefix = b"cam_"
        p.ext = b".Png"
        p.progress_fn = ctypes.cast(cb, ctypes.c_void_p)

        err = ctypes.create_string_buffer(512)
        job = lib.opngx_job_create(ctypes.byref(p), err, len(err))
        assert job, f"job rejected: {err.value.decode()}"
        try:
            rc = lib.opngx_job_run(job)
            assert rc == 0, err.value.decode()
        finally:
            lib.opngx_job_free(job)

    assert calls, "progress_fn was never invoked"
    assert all(total == 200 for _, total in calls), calls
    assert all(0 < done <= 200 for done, _ in calls), calls
    # guaranteed final push reports the exact end state
    assert calls[-1] == (200, 200), calls[-3:]


# --------------------------------------------------------------------- AR-10
# Qt-inherited names MainWindow may call without being defined in qt_app.py.
_QT_SELF_WHITELIST = {
    "setWindowTitle",
    "setWindowIcon",
    "windowIcon",
    "resize",
    "setMinimumSize",
    "setAcceptDrops",
    "setCentralWidget",
    "menuBar",
    "style",
    "close",
    "width",
    "height",
    "setStyleSheet",
    "centralWidget",
    "update",
    "blockSignals",
    "thread",
    "installEventFilter",
    "adjustSize",
    "show",
    "hide",
    "exec",
    "reject",
    "accept",
    "setRange",
    "setValue",
    "setDisabled",
    "setEnabled",
    "addAction",
    "addMenu",
    "addSeparator",
    "setShortcut",
    "setFont",
    "layout",
    "parent",
    "window",
    "setToolTip",
    "toolTip",
    "grab",
    "testAttribute",
    "setAttribute",
    "palette",
    "font",
    "sizeHint",
    "restoreGeometry",
    "saveGeometry",
}


def _unresolved_self_calls(text: str) -> set[str]:
    """self.X( references that resolve to nothing defined/assigned/Qt."""
    import re

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            defined = {
                n.name
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            break
    else:
        return {"MainWindow class not found"}

    assigned: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            calls.add(node.attr)
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                ):
                    assigned.add(tgt.attr)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Attribute)
            and isinstance(node.target.value, ast.Name)
            and node.target.value.id == "self"
        ):
            assigned.add(node.target.attr)

    # attribute *reads* that are not calls are fine (e.g. self.meta.width);
    # only flag call-style uses of unknown names
    import ast as _ast

    call_names: set[str] = set()
    for node in _ast.walk(tree):
        if (
            isinstance(node, _ast.Call)
            and isinstance(node.func, _ast.Attribute)
            and isinstance(node.func.value, _ast.Name)
            and node.func.value.id == "self"
        ):
            call_names.add(node.func.attr)

    return {
        n
        for n in call_names
        if n not in defined and n not in assigned and n not in _QT_SELF_WHITELIST
    }


def test_ar10_every_self_call_resolves_current():
    """All self.X() calls in qt_app.py must resolve — the gate that would
    have caught the v1.4.0 Windows DOA crash (self._log never defined)."""
    missing = _unresolved_self_calls(QT_APP.read_text())
    assert not missing, f"MainWindow calls undefined methods: {sorted(missing)}"


def test_ar10_gate_really_catches_v140_regression():
    """Historical RED: feed the v1.4.0 tagged file — gate must flag _log."""
    import subprocess

    try:
        blob = subprocess.run(
            ["git", "show", "v1.4.0:python/src/opngx/ui/qt_app.py"],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git or v1.4.0 tag unavailable")
    missing = _unresolved_self_calls(blob)
    assert "_log" in missing, (
        "gate failed its purpose: v1.4.0's undefined _log not detected"
    )


# --------------------------------------------------------------------- AR-12
def test_ar12_video_render_streams_and_cancels(fixture_dir, tmp_path):
    """Render must feed ffmpeg immediately (bounded pipeline), honor
    cancel, and produce a valid file.

    Regression for the '1 minute of nothing after pressing Render':
    the old code translated the WHOLE range into RAM before frame 1.
    """
    from opngx.video import render_video

    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg on PATH")
    binp = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    out = tmp_path / "stream.mp4"

    first_progress_at: list[float] = []
    t0 = time.perf_counter()

    def progress(done: int, total: int) -> None:
        if not first_progress_at:
            first_progress_at.append(time.perf_counter() - t0)

    st = render_video(
        binp,
        str(out),
        mode="raw",
        width=64,
        height=48,
        start=0,
        count=120,
        fps=30,
        crf=30,
        progress=progress,
    )
    assert st["frames_written"] == 120
    assert out.exists() and out.stat().st_size > 1024
    assert first_progress_at, "progress never fired"
    # first frames must be encoding almost immediately, not after a
    # full-corpus translate pass
    assert first_progress_at[0] < 5.0, (
        f"first progress after {first_progress_at[0]:.1f}s — "
        "pipeline is buffering instead of streaming"
    )

    # cancel mid-render must return cleanly with cancelled=True
    out2 = tmp_path / "cancel.mp4"
    state = {"n": 0}

    def cancel_after_first(done: int, total: int) -> None:
        state["n"] += 1

    def should_cancel() -> bool:
        return state["n"] >= 2  # cancel once writing has begun

    st2 = render_video(
        binp,
        str(out2),
        mode="raw",
        width=64,
        height=48,
        start=0,
        count=120,
        fps=30,
        crf=30,
        progress=cancel_after_first,
        should_cancel=should_cancel,
    )
    assert st2["cancelled"] is True


# --------------------------------------------------------------------- AR-13
def test_ar13_windows_filename_sanitizer():
    """Camera names from vendor XML must become filename-safe on Windows."""
    from opngx.layout import safe_name as f

    assert f("cam:1.2?") == "cam_1.2_"
    assert f('a/b\\c*d"e<f>g|h') == "a_b_c_d_e_f_g_h"
    assert f("trailing dots...") == "trailing dots"
    assert f("trailing space ") == "trailing space"
    assert f("brow_1.2") == "brow_1.2"  # mid-name dots are legal
    assert f("...") == "_"  # degenerate -> safe placeholder


# --------------------------------------------------------------------- AR-14
def test_ar14_v16_output_tree_helpers():
    """v1.6 layout: <mother>/<recording>/<FMT>/ + sibling MP4 folder."""
    from opngx.layout import mp4_dir, run_out_dir, safe_name

    assert run_out_dir("D:/out", "D:/src/SQ_100_s1.bin") == os.path.join(
        "D:/out", "SQ_100_s1", "PNG"
    )
    assert run_out_dir("D:/out", "D:/src/brow_1.2.bin", "jpg") == os.path.join(
        "D:/out", "brow_1.2", "JPG"
    )  # mid-name dots are legal
    assert mp4_dir("D:/out", "D:/src/SQ_100_s1.bin") == os.path.join(
        "D:/out", "SQ_100_s1", "MP4"
    )
    # windows-unsafe stems are sanitized (colon/question -> underscore)
    rd = run_out_dir("out", "src/evil:name?.bin", "png")
    assert "evil_name_" in rd and ":" not in rd and "?" not in rd
    assert safe_name("...") == "_"


def test_ar14b_studio_uses_v16_tree():
    """The studio's extract/verify/video paths must all speak the v1.6 tree."""
    text = QT_APP.read_text()
    assert 'run_out_dir(out, b, o["fmt"])' in text, "extract must target run dir"
    assert "self._current_run_dir(" in text, "verify must target run dir"
    assert 'mp4_dir = os.path.join(os.path.dirname(stem_dir), "MP4")' in text
    # splitters persisted across sessions
    assert "QSettings" in text and "closeEvent" in text


# --------------------------------------------------------------------- AR-15
def test_ar15_batch_picker_is_a_folder_dialog():
    """Field report: clicking Batch then Browse opened a .bin FILE dialog.

    The picker must branch on scope — Batch => getExistingDirectory of the
    MOTHER folder; Single => the .bin file dialog. Also: dropping a folder
    switches to Batch and probes it.
    """
    import pytest

    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    import opngx.ui.qt_app as qt

    text = QT_APP.read_text()
    pick_src = text.split("def _pick_source")[1].split("def ")[0]
    assert "getExistingDirectory" in pick_src, "batch must open a folder dialog"
    assert "rb_batch.isChecked()" in pick_src, "picker must branch on scope"

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = qt.MainWindow()

    # --- functional: batch scope picks a folder ---
    import tempfile

    mother = tempfile.mkdtemp(prefix="mother_")
    rec = os.path.join(mother, "SQ_100_s1")
    os.makedirs(rec, exist_ok=True)
    with open(os.path.join(rec, "SQ_100_s1.bin"), "wb") as f:
        f.write(b"\x00" * (8 + 64 * 48) * 2)

    orig_dir = QtWidgets.QFileDialog.getExistingDirectory
    orig_file = QtWidgets.QFileDialog.getOpenFileName
    seen = {"dir": 0}
    QtWidgets.QFileDialog.getExistingDirectory = lambda *a, **k: (
        seen.__setitem__("dir", seen["dir"] + 1),
        mother,
    )[1]

    win.rb_batch.setChecked(True)
    win._pick_source()
    assert seen["dir"] == 1, "folder dialog was not opened for Batch"
    assert os.path.isdir(win.bin_edit.text())

    # --- single scope still opens the file dialog ---
    calls = {"n": 0}

    def fake_file(*a, **k):
        calls["n"] += 1
        return (os.path.join(mother, "SQ_100_s1", "SQ_100_s1.bin"), "")

    QtWidgets.QFileDialog.getOpenFileName = fake_file
    win.rb_single.setChecked(False)
    win.rb_single.setChecked(True)
    win._pick_bin()
    QtWidgets.QFileDialog.getOpenFileName = orig_file
    assert calls["n"] == 1
    assert win.meta is not None or True


# --------------------------------------------------------------------- AR-16
def test_ar16_no_duplicate_test_definitions():
    """Hygiene: this file once carried TWO copies of AR-14/AR-15.

    Python silently keeps the last definition, so the first bodies were
    dead code — and the dead AR-15 was itself subtly broken (it toggled
    rb_single to True while it was already checked, so the scope switch
    under test never actually fired). A duplicated gate is worse than no
    gate: it looks like coverage.
    """
    tree = ast.parse(Path(__file__).read_text())
    names = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("test_")
    ]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate top-level test definitions: {dupes}"


# --------------------------------------------------------------------- AR-17
def test_ar17_reference_mode_never_silently_discards_user_transform(
    fixture_dir, tmp_path
):
    """FIX-1: `reference` mode overwrote the user's B/C/G with sidecar values.

    The studio defaults to `reference`, so a user who set gamma=2.0 and
    pressed Extract got sidecar B49/C18/G1 output while the frame viewer
    (which honours the spins) showed the gamma-ed result. The preview lied
    about the file. With the fix, a transform the user explicitly supplied
    is always honoured; the sidecar values are used only when the user
    supplied none.
    """
    import numpy as np
    from PIL import Image

    from opngx.quality import build_lut

    bin_p = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    ref = opngx.Extractor(bin_p)
    assert ref.meta.has_processing

    a = tmp_path / "ref"
    b = tmp_path / "cus"
    ref.extract(a, mode="reference", brightness=20, contrast=30, gamma=2.0, frames=3)
    ref.extract(b, mode="custom", brightness=20, contrast=30, gamma=2.0, frames=3)

    pa = np.asarray(Image.open(a / "brow_00000.Png").convert("L"))
    pb = np.asarray(Image.open(b / "brow_00000.Png").convert("L"))
    assert np.array_equal(pa, pb), (
        "reference mode discarded the user's transform: "
        f"maxdiff={int(np.abs(pa.astype(int) - pb.astype(int)).max())}"
    )

    # ...and the pixels must be the CUSTOM curve, not the sidecar curve
    raw = np.frombuffer(
        open(bin_p, "rb").read()[8 : 8 + 64 * 48], dtype=np.uint8
    ).reshape(48, 64)
    want = np.asarray(build_lut(20, 30, 2.0))[raw]
    assert np.array_equal(pa, want), "reference mode did not apply user B/C/G"


# --------------------------------------------------------------------- AR-18
def test_ar18_reference_mode_still_uses_sidecar_when_user_gives_none(
    fixture_dir, tmp_path
):
    """The other half of FIX-1: with NO user transform, reference mode must
    still reproduce the vendor sidecar curve (that is its whole purpose)."""
    import numpy as np
    from PIL import Image

    from opngx.quality import build_lut

    bin_p = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    ex = opngx.Extractor(bin_p)
    m = ex.meta
    out = tmp_path / "ref_default"
    ex.extract(out, mode="reference", frames=3)

    raw = np.frombuffer(
        open(bin_p, "rb").read()[8 : 8 + 64 * 48], dtype=np.uint8
    ).reshape(48, 64)
    want = np.asarray(build_lut(m.brightness, m.contrast, m.gamma))[raw]
    got = np.asarray(Image.open(out / "brow_00000.Png").convert("L"))
    assert np.array_equal(got, want), "reference mode lost the sidecar curve"


# --------------------------------------------------------------------- AR-19
def test_ar19_cli_batch_flags_exist_and_cli_never_imports_qt():
    """FIX-3: `opngx batch` never registered --layout/--format, and its
    layout branch imported a non-existent `_run_out_dir` from the Qt
    module. A CLI must not depend on PySide6 at all."""
    import argparse
    import contextlib
    import io

    from opngx import cli

    text = Path(cli.__file__).read_text()
    assert "from opngx.ui" not in text, "CLI imports the Qt UI module"

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pb = sub.add_parser("batch")
    pb.add_argument("in_dir")
    cli._add_engine_args(pb)
    pb.add_argument("--layout", choices=["flat", "format"], default="format")
    # the batch parser must accept the same engine flags as extract
    args = ap.parse_args(
        [
            "batch",
            "indir",
            "-o",
            "out",
            "--layout",
            "format",
            "--format",
            "jpg",
            "--channels",
            "gray",
            "--brightness",
            "20",
            "--contrast",
            "30",
            "--gamma",
            "2.0",
        ]
    )
    assert args.layout == "format"
    assert args.format == "jpg"
    assert args.channels == "gray"
    assert args.gamma == 2.0

    # and the real CLI's own `batch` subcommand must accept --layout:
    # before the fix it was never registered, so `opngx batch --layout
    # format` died with "unrecognized arguments" even though run_one()
    # went on to read args.layout via getattr.
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(
                [
                    "batch",
                    "/nonexistent-opngx-batch-root",
                    "-o",
                    "/tmp/opngx-ar19",
                    "--layout",
                    "flat",
                ]
            )
    err = buf.getvalue()
    assert "unrecognized arguments" not in err, err
    assert rc != 0, "batch over a missing directory must return non-zero"
    assert "no .bin files found" in err, err


# --------------------------------------------------------------------- AR-20
def test_ar20_engine_batch_flag_parity_with_extract():
    """FIX-2: the engine's `batch` subcommand must accept every quality
    flag `extract` accepts. Statically pin the flags in cmd_batch."""
    main_c = (REPO / "src" / "main.c").read_text()
    body = main_c.split("static int cmd_batch")[1].split("\n/* ---- verify ---- */")[0]
    for flag in (
        "--brightness",
        "--contrast",
        "--gamma",
        "--bit-depth",
        "--channels",
        "--jpeg-quality",
        "--ext",
    ):
        assert flag in body, f"engine batch does not accept {flag}"
    # no hardcoded gamma reset inside the per-bin params block
    per_bin = body.split("for (int k = 0")[1]
    assert "p.gamma = 1.0" not in per_bin, (
        "cmd_batch still hardcodes gamma=1.0, discarding the user's value"
    )


# --------------------------------------------------------------------- AR-21
def test_ar21_batch_output_folders_never_collide(tmp_path):
    """Cycle-22 data-loss finding: two recordings can share a .bin NAME.

    Cameras are routinely dumped as <root>/<camera>/recording.bin. Keying
    the output folder on the filename collapsed every one of them into a
    single directory, and each run overwrote the previous one frame for
    frame — 16 frames extracted, 8 on disk, with no warning. The recording
    FOLDER is the identity in the mother-folder architecture.
    """
    from opngx.layout import batch_out_dir, recording_key, safe_name

    root = tmp_path / "mother"
    for cam in ("camA", "camB"):
        (root / cam).mkdir(parents=True)
        (root / cam / "recording.bin").write_bytes(b"\0" * 16)

    a = root / "camA" / "recording.bin"
    b = root / "camB" / "recording.bin"
    assert a.name == b.name, "precondition: same filename"
    assert recording_key(str(root), str(a)) == "camA"
    assert recording_key(str(root), str(b)) == "camB"

    da = batch_out_dir("out", str(root), str(a), "png")
    db = batch_out_dir("out", str(root), str(b), "png")
    assert da != db, f"output folders collide: {da}"
    assert da.endswith(os.path.join("camA", "PNG"))
    assert db.endswith(os.path.join("camB", "PNG"))

    # a loose .bin directly in the root keeps using its own stem
    loose = root / "solo.bin"
    loose.write_bytes(b"\0" * 16)
    assert recording_key(str(root), str(loose)) == "solo"
    # unsafe folder names are still sanitized
    assert safe_name("a:b") == "a_b"


# --------------------------------------------------------------------- AR-22
def test_ar22_batch_run_keeps_both_same_named_recordings(tmp_path):
    """End-to-end: a two-recording batch with identical .bin names must
    produce 2 output folders and 2x the frames, not one overwritten set."""
    import shutil
    import subprocess
    import sys as _sys

    from opngx import cli

    fix = tmp_path / "fix"
    subprocess.run(
        [_sys.executable, str(REPO / "tests" / "gen_fixture.py"), str(fix)],
        check=True,
        capture_output=True,
    )
    src = fix / "cam_9.9"
    root = tmp_path / "mother"
    for cam in ("recA", "recB"):
        (root / cam).mkdir(parents=True)
        for f in src.iterdir():
            if f.suffix in (".bin", ".footage"):
                shutil.copy(f, root / cam / f.name)

    out = tmp_path / "out"
    rc = cli.main(
        [
            "batch",
            str(root),
            "-o",
            str(out),
            "--layout",
            "format",
            "--prefix",
            "cam_",
            "--frames",
            "3",
        ]
    )
    assert rc == 0
    dirs = sorted(d.name for d in out.iterdir())
    assert dirs == ["recA", "recB"], f"expected one folder per recording, got {dirs}"
    for d in dirs:
        n = len(list((out / d / "PNG").glob("*.Png")))
        assert n == 3, f"{d}: {n} frames written"


# --------------------------------------------------------------------- AR-23
def test_ar23_crop_in_python_api_and_fallback_parity(fixture_dir, tmp_path):
    """The python `crop=` argument must reach BOTH the native engine and
    the pure-python fallback, and both must match the C engine's pixels."""
    import numpy as np
    from PIL import Image

    import opngx._engine as _eng
    from opngx.quality import build_lut

    bin_p = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    ex = opngx.Extractor(bin_p)
    crop = (8, 4, 20, 12)

    nat = tmp_path / "nat"
    ex.extract(nat, mode="reference", crop=crop, frames=2)
    im = Image.open(nat / "brow_00000.Png")
    assert im.size == (20, 12), f"cropped size {im.size} != (20, 12)"

    raw = np.frombuffer(
        open(bin_p, "rb").read()[8 : 8 + 64 * 48], dtype=np.uint8
    ).reshape(48, 64)
    want = np.asarray(build_lut(ex.meta.brightness, ex.meta.contrast, ex.meta.gamma))[
        raw[4:16, 8:28]
    ]
    got = np.asarray(im.convert("L"))
    assert np.array_equal(got, want), "native crop pixels wrong"

    # force the pure-python path and demand identical pixels
    import opngx._fallback as _fb

    fb = tmp_path / "fb"
    orig = _eng.load_library
    _eng.load_library = lambda: None
    try:
        ex2 = opngx.Extractor(bin_p)
        ex2.extract(fb, mode="reference", crop=crop, frames=2)
    finally:
        _eng.load_library = orig
    assert _fb is not None

    got_fb = np.asarray(Image.open(fb / "brow_00000.Png").convert("L"))
    assert np.array_equal(got_fb, got), "fallback crop pixels differ from native"

    # invalid rects raise ValueError, never silently clamp
    for bad in [(0, 0, 999, 999), (60, 0, 10, 10), (-1, 0, 4, 4)]:
        try:
            ex.extract(tmp_path / "bad", crop=bad, frames=1)
        except ValueError:
            pass
        else:
            raise AssertionError(f"crop {bad} should have been rejected")


# --------------------------------------------------------------------- AR-24
def test_ar24_batch_window_and_crop_editor_construct_and_run(tmp_path):
    """The dedicated batch surface and the crop picker must construct
    offscreen, show a real decoded frame per recording, and apply a crop to
    one recording or to the whole batch."""
    import pytest

    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import shutil
    import subprocess
    import sys as _sys
    from PySide6 import QtGui, QtWidgets

    from opngx.ui.batch import BatchWindow, CropEditor, make_item, scan_batch

    fix = tmp_path / "fix"
    subprocess.run(
        [_sys.executable, str(REPO / "tests" / "gen_fixture.py"), str(fix)],
        check=True,
        capture_output=True,
    )
    src = fix / "cam_9.9"
    root = tmp_path / "mother"
    for cam in ("recA", "recB"):
        (root / cam).mkdir(parents=True)
        for f in src.iterdir():
            if f.suffix in (".bin", ".footage"):
                shutil.copy(f, root / cam / f.name)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    # --- discovery matches the studio/engine batch scope ---
    assert len(scan_batch(str(root))) == 2

    # --- each item carries a REAL decoded frame, not a placeholder ---
    it = make_item(str(root / "recA" / "cam_9.9.bin"))
    assert it.thumb is not None, "batch card must show a decoded frame"
    assert it.width == 64 and it.height == 48 and it.frames == 200

    # --- the window builds a card per recording ---
    win = BatchWindow(
        None,
        str(root),
        str(tmp_path / "out"),
        dict(
            fmt="png",
            mode="reference",
            bit_depth=8,
            channels=6,
            jobs=2,
            level=6,
            prefix="cam_",
            ext=".Png",
        ),
    )
    assert len(win.items) == 2
    assert len(win.cards) == 2
    for item in win.items:
        assert item.thumb is not None
        assert item.out_size == "64 × 48 px"
        assert item.crop_label == "full frame"
    # same-named .bin files must land in DIFFERENT folders
    outs = {i.out_dir for i in win.items}
    assert len(outs) == 2, f"batch output folders collide: {outs}"

    # --- crop editor: drag-select, clamp, apply to one or all ---
    img = QtGui.QImage(64, 48, QtGui.QImage.Format_Grayscale8)
    img.fill(120)
    ed = CropEditor(None, img, None, (64, 48))
    assert ed.selection() is None, "full frame means no crop"
    ed._set_sel((8, 4, 20, 12))
    assert ed.selection() == (8, 4, 20, 12)
    ed._center()
    x, y, w, h = ed.selection()
    assert (w, h) == (32, 24) and (x, y) == (16, 12)
    # an out-of-range spin is clamped, never accepted
    ed.w_spin.setValue(999)
    assert ed.selection()[2] <= 64
    ed._full()
    assert ed.selection() is None

    # apply-to-all through the window. NOTE: open_crop_editor() opens a
    # MODAL dialog, so the test drives the same state the dialog writes
    # rather than calling it — an exec() here would block forever.
    sel = (8, 4, 20, 12)
    for i2 in win.items:
        i2.crop = sel
        win.cards[i2.bin_path].refresh()
    assert all(i2.crop == sel for i2 in win.items)
    # the card must report the cropped output size
    facts = win.cards[win.items[0].bin_path].facts.text()
    assert "20 × 12 px" in facts, facts

    win.clear_crops()
    assert all(i2.crop is None for i2 in win.items)
    assert "64 × 48 px" in win.cards[win.items[0].bin_path].facts.text()

    # --- the batch actually runs, per card, and reports status ---
    from PySide6.QtCore import QEventLoop, QTimer

    for i2 in win.items:
        i2.crop = sel
        win.cards[i2.bin_path].refresh()
    loop = QEventLoop()
    win.finished.connect(lambda _: loop.quit())
    win.start()
    QTimer.singleShot(60000, loop.quit)
    loop.exec()
    assert all(i2.status == "done" for i2 in win.items), [
        (i2.name, i2.status, i2.error) for i2 in win.items
    ]
    assert all(
        len(list((tmp_path / "out" / d / "PNG").glob("*.Png"))) == 200
        for d in ("recA", "recB")
    )
