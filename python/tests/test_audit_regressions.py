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
