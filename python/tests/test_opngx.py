"""pytest suite for the opngx Python package.

Covers: metadata probing, LUT formula, native+fallback engine parity,
timestamps, PNG structure, CLI surface. Real-data tests skip when the
sample tree is absent (CI-safe).
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(REPO / "tests"))
from gen_fixture import build_lut  # noqa: E402

import opngx  # noqa: E402

SAMPLE_BIN = Path(
    os.environ.get(
        "OPNGX_SAMPLE", "/home/shuvam/codes/ayush_opt/sbs/bin/brow_1.2/brow_1.2.bin"
    )
)
SAMPLE_PNG_DIR = SAMPLE_BIN.parent.parent.parent / "png" / "brow_1_2"


# ----------------------------------------------------------------- fixtures
# fixture_dir / native_available live in conftest.py (shared with the
# audit regression suite)


# ------------------------------------------------------------------- probes
def test_probe_parses_fixture(fixture_dir):
    m = opngx.probe(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    assert (m.width, m.height) == (64, 48)
    assert m.num_images == 200
    assert m.capacity_frames == 200
    assert m.frame_stride == 8 + 64 * 48
    assert m.camera_name == "cam_9.9"
    assert m.brightness == 49 and m.contrast == 18
    assert m.verified_operating_point


def test_probe_missing_bin_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        opngx.probe(tmp_path / "nope.bin")


def test_lut_matches_verified_formula():
    lut = build_lut(49.0, 18.0)
    assert lut[34] == 113 and lut[35] == 114 and lut[36] == 116
    assert lut[138] == 254 and lut[139] == 255  # saturation boundary
    # independent recomputation for the entire domain
    exp = np.clip(np.floor((np.arange(256) + 49) * 1.36 + 0.5), 0, 255)
    assert np.array_equal(lut, exp.astype(np.uint8))


def test_raw_mode_is_identity():
    lut = build_lut(0, 0)
    assert np.array_equal(lut, np.arange(256, dtype=np.uint8))


# ------------------------------------------------------- python extraction
def test_python_extract_reference_pixel_exact(fixture_dir):
    out = fixture_dir / "py_out"
    st = opngx.extract(
        str(fixture_dir / "cam_9.9" / "cam_9.9.bin"), str(out), jobs=4, prefix="cam_"
    )
    assert st.frames_written == 200
    rep = opngx.verify(fixture_dir / "ref_pngs", out, prefix="cam_")
    assert rep.passed, rep.first_error


def test_timestamp_reader(fixture_dir):
    m = opngx.probe(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    ts = opngx.read_timestamps(m.bin_path, m)
    assert len(ts) == 200
    assert ts[0] == 10_000_000 and ts[199] == 10_000_000 + 199 * 2000
    assert np.all(np.diff(ts.astype(np.int64)) == 2000)


def test_png_structure_of_output(fixture_dir):
    out = fixture_dir / "py_out"
    p = sorted(out.glob("*.Png"))[0]
    d = p.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, []
    while pos < len(d):
        ln = struct.unpack(">I", d[pos : pos + 4])[0]
        typ = d[pos + 4 : pos + 8].decode()
        chunks.append(typ)
        pos += 12 + ln
        if typ == "IEND":
            break
    assert chunks == ["IHDR", "sRGB", "gAMA", "pHYs", "IDAT", "IEND"]


# --------------------------------------------------------- native parity
@pytest.mark.skipif(
    not Path(SAMPLE_BIN).exists(), reason="real sample data not present"
)
def test_native_real_data_subset(native_available):
    if not native_available:
        pytest.skip("native engine missing")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        st = opngx.extract(str(SAMPLE_BIN), td, frames=60, jobs=8)
        assert st.frames_written == 60
        rep = opngx.verify(SAMPLE_PNG_DIR, td)
        assert rep.passed, rep.first_error
        assert rep.bytes_compared == 60 * 300 * 256 * 4


def test_fallback_engine_matches_native_formula(fixture_dir):
    """Fallback engine output must equal independently computed pixels."""
    from opngx._fallback import encode_png, _render_frame

    from PIL import Image as _PILImage

    Image = _PILImage  # noqa: F841 — used by later assertions in this module scope
    _, (_ext, blob) = _render_frame(
        (
            str(fixture_dir / "cam_9.9" / "cam_9.9.bin"),
            3,
            0,
            8 + 64 * 48,
            64,
            48,
            49.0,
            18.0,
            1.0,
            8,
            6,
            "png",
            90,
        )
    )
    # decode our own PNG via zlib and compare against expected RGBA matrix
    pos, idat = 8, b""
    while pos < len(blob):
        ln = struct.unpack(">I", blob[pos : pos + 4])[0]
        typ = blob[pos + 4 : pos + 8]
        if typ == b"IDAT":
            idat += blob[pos + 8 : pos + 8 + ln]
        pos += 12 + ln
    raw = zlib.decompress(idat)
    h, w, stride = 48, 64, 64 * 4 + 1
    px = np.frombuffer(bytearray(raw), dtype=np.uint8).reshape(h, stride)
    assert np.all(px[:, 0] == 0)  # filter bytes zero
    rgba = px[:, 1:].reshape(h, w, 4)
    src = open(fixture_dir / "cam_9.9" / "cam_9.9.bin", "rb").read()
    gray = np.frombuffer(
        src[3 * (8 + w * h) + 8 : (3 * (8 + w * h)) + 8 + w * h], dtype=np.uint8
    ).reshape(h, w)
    exp = np.empty((h, w, 4), dtype=np.uint8)
    g = build_lut(49.0, 18.0)[gray]
    exp[..., 0] = exp[..., 1] = exp[..., 2] = g
    exp[..., 3] = 255
    assert np.array_equal(rgba, exp)


# ------------------------------------------------------------- verify tool
def test_verify_detects_corruption(fixture_dir):
    out = fixture_dir / "corrupt_out"
    if out.exists():
        import shutil

        shutil.rmtree(out)
    import shutil

    shutil.copytree(fixture_dir / "py_out", out)
    victim = sorted(out.glob("*.Png"))[5]
    data = bytearray(victim.read_bytes())
    data[-30] ^= 0xFF
    victim.write_bytes(bytes(data))
    rep = opngx.verify(fixture_dir / "ref_pngs", out, prefix="cam_")
    assert not rep.passed


# ------------------------------------------------------------- CLI smoke
def test_cli_help():
    r = subprocess.run(["opngx", "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "extract" in r.stdout


def test_cli_info_on_sample():
    if not Path(SAMPLE_BIN).exists():
        pytest.skip("real sample data not present")
    r = subprocess.run(
        ["opngx", "info", str(SAMPLE_BIN)], capture_output=True, text=True
    )
    assert r.returncode == 0
    assert "width: 256" in r.stdout


# ------------------------------------------------- audit regressions
def test_backend_reported_truthfully(fixture_dir):
    """stats.backend_used must reflect the engine actually used (audit #9)."""
    out = fixture_dir / "be_out"
    st = opngx.extract(
        str(fixture_dir / "cam_9.9" / "cam_9.9.bin"),
        str(out),
        jobs=2,
        prefix="cam_",
        backend="zlib",
    )
    assert st.backend in ("zlib", "libdeflate")  # never the literal 'auto'
    st2 = opngx.extract(
        str(fixture_dir / "cam_9.9" / "cam_9.9.bin"),
        str(out) + "_2",
        jobs=2,
        prefix="cam_",
    )
    assert st2.backend == st.backend  # same binary => same real backend


def test_fallback_start_offset_matches_native(fixture_dir):
    """fallback engine must honor --start like native (audit #5)."""
    from opngx import _fallback

    binp = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    out = fixture_dir / "fb_start"
    _fallback.extract_frames(
        binp,
        str(out),
        64,
        48,
        10,
        8 + 64 * 48,
        "cam_",
        ".Png",
        49.0,
        18.0,
        1.0,
        8,
        jobs=1,
        channels=6,
        start=100,
    )
    # with start=100 files are numbered by ABSOLUTE frame index
    ref = fixture_dir / "ref_pngs" / "cam_00100.Png"
    got = out / "cam_00100.Png"
    a = np.array(Image.open(ref))
    b = np.array(Image.open(got))
    assert np.array_equal(a, b)


def test_native_start_parity(fixture_dir):
    """native --start slice must be byte-identical to full run slice."""
    if not Path(SAMPLE_BIN).exists():
        pytest.skip("real sample data not present")
    if opngx.engine_backend() == "python-fallback":
        pytest.skip("native engine missing")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        s1 = opngx.extract(SAMPLE_BIN, td + "/a", frames=8, jobs=4)
        s2 = opngx.extract(SAMPLE_BIN, td + "/b", start=7, frames=4, jobs=4)
        f_a = Path(td, "a", "brow_00007.Png").read_bytes()
        f_b = Path(td, "b", "brow_00007.Png").read_bytes()
        assert s2.frames_written == 4 and f_a == f_b


def test_zlib_backend_roundtrip(fixture_dir):
    """explicit zlib backend decodes identically via PIL (CRC strict)."""
    from PIL import Image

    out = fixture_dir / "zb_out"
    st = opngx.extract(
        str(fixture_dir / "cam_9.9" / "cam_9.9.bin"),
        str(out),
        jobs=2,
        prefix="cam_",
        backend="zlib",
        frames=20,
    )
    assert st.frames_written == 20
    rep = opngx.verify(fixture_dir / "ref_pngs", out, prefix="cam_")
    assert rep.passed, rep.first_error


def test_sidecarless_bin_with_manual_geometry(fixture_dir):
    """A .bin without .footage works when W×H are supplied (user report)."""
    import shutil

    bin_only = fixture_dir / "nosidecar.bin"
    shutil.copy(fixture_dir / "cam_9.9" / "cam_9.9.bin", bin_only)
    # probe: no geometry
    m = opngx.probe(bin_only)
    assert m.width == 0 and m.height == 0
    # extractor with explicit geometry
    ex = opngx.Extractor(bin_only, width=64, height=48)
    assert ex.meta.capacity_frames == 200
    out = fixture_dir / "noside_out"
    st = ex.extract(str(out), mode="raw", jobs=2, prefix="ns_")
    assert st.frames_written == 200
    rep = opnx_verify_raw(bin_only, out)
    assert rep


def opnx_verify_raw(bin_path, out):
    import numpy as np
    from PIL import Image

    data = Path(bin_path).read_bytes()
    stride = 8 + 64 * 48
    for idx in (0, 137, 199):
        off = idx * stride + 8
        gray = np.frombuffer(data[off : off + 64 * 48], dtype=np.uint8).reshape(48, 64)
        img = np.array(Image.open(out / f"ns_{idx:05d}.Png"))
        if not np.array_equal(img[..., 0], gray):
            return False
    return True


def test_ffmpeg_resolution():
    from opngx.video import resolve_ffmpeg

    p = resolve_ffmpeg()
    if not shutil.which("ffmpeg") and p is None:
        pytest.skip("no ffmpeg anywhere")
    assert p and Path(p).exists()


# ------------------------------------------------- ADD-5: verify --json
def test_verify_json_machine_readable(fixture_dir):
    """Native engine emits parseable JSON; python wrapper consumes it."""
    import json
    import subprocess

    out = fixture_dir / "py_out"
    eng = None
    from opngx.verify import _engine_binary

    eng = _engine_binary()
    if eng is None:
        pytest.skip("native engine binary not built")
    r = subprocess.run(
        [
            eng,
            "verify",
            str(fixture_dir / "ref_pngs"),
            str(out),
            "--prefix",
            "cam_",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    data = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and data["passed"] is True
    assert data["files_compared"] == 200 and data["mismatched_files"] == 0


def test_verify_survives_colon_in_error_text(fixture_dir):
    """first_error containing ':' must not break report parsing (ADD-5)."""
    import shutil

    out = fixture_dir / "colon_out"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(fixture_dir / "py_out", out)
    victim = sorted(out.glob("*.Png"))[3]
    data = bytearray(victim.read_bytes())
    data[-25] ^= 0xFF
    victim.write_bytes(bytes(data))
    rep = opngx.verify(fixture_dir / "ref_pngs", out, prefix="cam_")
    assert not rep.passed and rep.mismatched_files >= 1
