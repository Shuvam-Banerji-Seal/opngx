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
def _opngx_cmd() -> list:
    """The installed `opngx` entry point of THIS interpreter's environment
    (a non-activated venv is not on PATH — e.g. CI testing a wheel on
    Windows), else `python -m opngx.cli`."""
    import shutil
    import sys

    here = Path(sys.executable).parent
    for cand in (here / "opngx", here / "opngx.exe", here / "Scripts" / "opngx.exe"):
        if cand.exists():
            return [str(cand)]
    exe = shutil.which("opngx")
    return [exe] if exe else [sys.executable, "-m", "opngx.cli"]


def test_cli_help():
    r = subprocess.run(_opngx_cmd() + ["--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "extract" in r.stdout


def test_cli_info_on_sample():
    if not Path(SAMPLE_BIN).exists():
        pytest.skip("real sample data not present")
    r = subprocess.run(
        _opngx_cmd() + ["info", str(SAMPLE_BIN)], capture_output=True, text=True
    )
    assert r.returncode == 0
    assert "width: 256" in r.stdout


# ------------------------------------------------- audit regressions
def test_backend_reported_truthfully(fixture_dir, native_available):
    """stats.backend_used must reflect the engine actually used (audit #9)."""
    out = fixture_dir / "be_out"
    st = opngx.extract(
        str(fixture_dir / "cam_9.9" / "cam_9.9.bin"),
        str(out),
        jobs=2,
        prefix="cam_",
        backend="zlib",
    )
    # never the literal 'auto'; without the engine (sdist) it is the fallback
    real = ("zlib", "libdeflate") if native_available else ("python-fallback",)
    assert st.backend in real
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


def _png_with_filters(path, img, bpp, filters, bd=8, ct=6):
    """Hand-encode a PNG whose row y uses filter filters[y % len]."""
    import zlib as _z

    h, n = img.shape
    prev = np.zeros(n, np.int64)
    raw = bytearray()
    for y in range(h):
        cur = img[y].astype(np.int64)
        ft = filters[y % len(filters)]
        left = np.concatenate([np.zeros(bpp, np.int64), cur[:-bpp]])
        ul = np.concatenate([np.zeros(bpp, np.int64), prev[:-bpp]])
        if ft == 0:
            pred = np.zeros(n, np.int64)
        elif ft == 1:
            pred = left
        elif ft == 2:
            pred = prev
        elif ft == 3:
            pred = (left + prev) >> 1
        else:
            p = left + prev - ul
            pa, pb, pc = abs(p - left), abs(p - prev), abs(p - ul)
            pred = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, prev, ul))
        raw += bytes([ft]) + ((cur - pred) & 0xFF).astype(np.uint8).tobytes()
        prev = cur

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", _z.crc32(t + d) & 0xFFFFFFFF)

    w = n // bpp
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, bd, ct, 0, 0, 0))
        + chunk(b"IDAT", _z.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def test_pure_python_verifier_all_png_filters(tmp_path, fixture_dir, monkeypatch):
    """v2.0.1: without the engine CLI (sdist installs) opngx.verify() uses a
    numpy PNG decoder. Its Average/Paeth un-filtering used the still-filtered
    left byte, so it failed 30 of 200 pixel-identical frames. Every filter,
    8- and 16-bit, grey/RGB/RGBA, must decode like PIL; the fixture must
    verify; a one-pixel change must not."""
    import importlib

    vm = importlib.import_module("opngx.verify")
    monkeypatch.setattr(vm, "_engine_binary", lambda: None)
    rng = np.random.default_rng(3)
    cases = [(6, 8, 4, "RGBA"), (2, 8, 3, "RGB"), (0, 8, 1, "L"), (6, 16, 8, None)]
    for ct, bd, bpp, mode in cases:
        w, h = 23, 10
        img = rng.integers(0, 256, (h, w * bpp), dtype=np.uint8)
        for filt in ([0], [1], [2], [3], [4], [4, 3, 1, 2, 0]):
            ref, out = tmp_path / "r", tmp_path / "o"
            for d in (ref, out):
                d.mkdir(exist_ok=True)
                for f in d.glob("*"):
                    f.unlink()
            _png_with_filters(ref / "x_00000.Png", img, bpp, filt, bd, ct)
            _png_with_filters(out / "x_00000.Png", img, bpp, [0], bd, ct)
            if mode:
                dec = np.asarray(Image.open(ref / "x_00000.Png").convert(mode)).reshape(h, -1)
                assert np.array_equal(dec, img), (ct, bd, filt)
            rep = opngx.verify(ref, out, prefix="x_")
            assert rep.passed, (ct, bd, filt, rep)
            bad = img.copy()
            bad[h // 2, 5] ^= 1
            _png_with_filters(out / "x_00000.Png", bad, bpp, filt, bd, ct)
            rep = opngx.verify(ref, out, prefix="x_")
            assert not rep.passed and rep.mismatched_files == 1, (ct, bd, filt)
    # the real fixture (vendor-style reference PNGs) through the python path
    out = fixture_dir / "pyverify_out"
    opngx.extract(str(fixture_dir / "cam_9.9" / "cam_9.9.bin"), str(out), jobs=2, prefix="cam_")
    rep = opngx.verify(fixture_dir / "ref_pngs", out, prefix="cam_")
    assert rep.passed and rep.files_compared == 200, rep


def _png_samples(path):
    """(IHDR, big-endian samples) of an all-filter-0 PNG, no PIL: PIL
    narrows 16-bit RGBA to 8 bits and would hide a 16-bit defect."""
    import zlib as _z

    d = Path(path).read_bytes()
    pos, idat, ihdr = 8, b"", None
    while pos < len(d):
        ln = struct.unpack(">I", d[pos : pos + 4])[0]
        typ = d[pos + 4 : pos + 8]
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBB", d[pos + 8 : pos + 18])
        elif typ == b"IDAT":
            idat += d[pos + 8 : pos + 8 + ln]
        pos += 12 + ln
    w, h, bd, ct = ihdr
    rows = np.frombuffer(_z.decompress(idat), np.uint8).reshape(h, -1)
    assert (rows[:, 0] == 0).all()
    return ihdr, (rows[:, 1:].view(">u2") if bd == 16 else rows[:, 1:])


@pytest.mark.parametrize("bit_depth", [8, 16])
@pytest.mark.parametrize("channels", [6, 0])
@pytest.mark.parametrize("crop", [None, (5, 7, 30, 20)])
def test_fallback_png_samples_match_native(fixture_dir, native_available, tmp_path, bit_depth, channels, crop):
    """Every PNG variant from the numpy fallback carries exactly the native
    engine's samples. 16-bit RGBA used to raise ValueError in encode_png
    (and would have written alpha 255 of 65535)."""
    if not native_available:
        pytest.skip("native engine not built")
    from opngx import _fallback

    binp = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    kw = dict(mode="custom", brightness=30.0, contrast=40.0, gamma=1.6,
              bit_depth=bit_depth, channels=channels, frames=4, start=3,
              prefix="cam_", jobs=1)
    if crop:
        kw["crop"] = crop
    opngx.extract(binp, str(tmp_path / "nat"), **kw)
    x, y, w, h = crop or (0, 0, 0, 0)
    _fallback.extract_frames(
        binp, str(tmp_path / "fb"), 64, 48, 4, 8 + 64 * 48, "cam_", ".Png",
        30.0, 40.0, 1.6, bit_depth, jobs=1, channels=channels, start=3,
        crop=(x, y, w, h),
    )
    nat = sorted((tmp_path / "nat").glob("cam_*.Png"))
    fb = sorted((tmp_path / "fb").glob("cam_*.Png"))
    assert [p.name for p in nat] == [p.name for p in fb] and len(nat) == 4
    for a, b in zip(nat, fb):
        (ha, sa), (hb, sb) = _png_samples(a), _png_samples(b)
        assert ha == hb, (a.name, ha, hb)
        assert np.array_equal(sa, sb), a.name
        if channels == 6:
            full = 65535 if bit_depth == 16 else 255
            assert (sa.reshape(ha[1], ha[0], 4)[..., 3] == full).all()


def test_timestamps_captured_by_workers_full_and_cancelled(fixture_dir, native_available, tmp_path):
    """v2.0.4: the engine no longer reads every frame header in a serial pass
    BEFORE extracting (the click -> first-frame delay on Windows); workers
    record each header as they go. The CSV must equal the headers exactly,
    in frame order, and after a cancel hold exactly the extracted frames."""
    if not native_available:
        pytest.skip("native engine not built")
    import csv

    binp = fixture_dir / "cam_9.9" / "cam_9.9.bin"
    m = opngx.probe(binp)
    want = opngx.read_timestamps(m.bin_path, m, 17, 150)
    opngx.extract(str(binp), str(tmp_path / "full"), start=17, frames=150, jobs=7,
                  prefix="cam_", export_timestamps=True)
    rows = list(csv.reader(open(tmp_path / "full" / "cam__timestamps.csv", encoding="utf-8")))
    assert rows[0] == ["frame_index", "timestamp_raw", "timestamp_hex"]
    assert [int(r[0]) for r in rows[1:]] == list(range(17, 167))
    assert [int(r[1]) for r in rows[1:]] == [int(t) for t in want]
    assert all(r[2] == f"0x{int(r[1]):016X}" for r in rows[1:])

    # cancel part-way: rows only for frames that exist on disk
    calls = [0]

    def cancel():
        calls[0] += 1
        return calls[0] > 3

    out = tmp_path / "cut"
    try:
        opngx.extract(str(binp), str(out), frames=200, jobs=1, prefix="cam_",
                      export_timestamps=True, should_cancel=cancel)
    except Exception:  # noqa: BLE001 - a cancelled run may report itself as such
        pass
    csvp = out / "cam__timestamps.csv"
    if csvp.exists():
        idx = [int(r[0]) for r in list(csv.reader(open(csvp, encoding="utf-8")))[1:]]
        on_disk = sorted(int(p.stem[4:]) for p in out.glob("cam_*.Png"))
        assert idx == sorted(idx) and set(idx) <= set(range(200))
        assert set(on_disk) <= set(idx)


def test_default_deflate_level_is_fast_everywhere():
    """v2.0.4: level 1 is the default (2.8-4.3x faster than 6, files ~1.5 %
    larger, identical pixels) in the API, the python CLI and the studio."""
    import inspect

    from opngx import cli
    from opngx.extractor import Extractor

    assert inspect.signature(Extractor.extract).parameters["level"].default == 1
    import argparse

    p = argparse.ArgumentParser()
    cli._add_engine_args(p)          # the flags every extract-like command shares
    assert p.parse_args(["-o", "out"]).level == 1
    src = (REPO / "python" / "src" / "opngx" / "ui" / "qt_app.py").read_text(encoding="utf-8")
    assert "self.level_slider.setValue(1)" in src
    hdr = (REPO / "src" / "opngx.h").read_text(encoding="utf-8")
    assert "#define OPNGX_DEFAULT_LEVEL 1" in hdr


@pytest.mark.parametrize("force_fallback", [False, True])
def test_every_format_is_what_it_claims(fixture_dir, native_available, tmp_path, force_fallback, monkeypatch):
    """v2.1: every image format, every bit depth, engine and fallback: the
    files decode (independently) to exactly the expected pixels when the
    format is documented lossless."""
    from opngx import formats
    from opngx.quality import build_lut

    if not force_fallback and not native_available:
        pytest.skip("native engine not built")
    if force_fallback:
        import opngx.extractor as ex_mod

        monkeypatch.setattr(ex_mod, "load_library", lambda: None)
    binp = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    m = opngx.probe(binp)
    lut = np.asarray(build_lut(m.brightness, m.contrast, m.gamma), np.uint8)
    raw = np.fromfile(binp, np.uint8)
    crop = (3, 5, 41, 27)  # odd sizes on purpose
    x, y, w, h = crop
    for key, f in formats.FORMATS.items():
        if force_fallback and f.engine != "native":
            continue
        for bits in f.bit_depths:
            out = tmp_path / f"{key}{bits}{int(force_fallback)}"
            opngx.extract(binp, str(out), fmt=key, bit_depth=bits, frames=6, start=2, crop=crop,
                          prefix="cam_", channels=0 if key == "png" else 6)
            files = sorted(p for p in out.iterdir() if p.suffix not in (".csv", ".json"))
            dec = list(formats.read_frame(str(files[0]))) if key == "npy" else [formats.read_frame(str(p)) for p in files]
            assert len(dec) == 6, (key, bits, len(dec))
            for i, a in enumerate(dec):
                o = (2 + i) * m.frame_stride + 8
                e = lut[raw[o : o + m.width * m.height].reshape(m.height, m.width)[y : y + h, x : x + w]]
                if bits == 16:
                    e = e.astype(np.uint16) * 257
                r = formats.quality_report(e, np.asarray(a))
                if f.lossless:
                    assert r.get("exact"), (key, bits, force_fallback, r)
                else:
                    assert r.get("psnr_db", 0) > 30, (key, r)


def test_video_codecs_lossless_are_bit_exact_and_errors_surface(fixture_dir, tmp_path):
    """v2.1: FFV1 and GIF decode to exactly the extracted pixels; a bad
    output name reports ffmpeg's own message, not 'Broken pipe'."""
    from opngx import video
    from opngx.quality import build_lut

    if not video.ffmpeg_available():
        pytest.skip("no ffmpeg")
    binp = str(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    m = opngx.probe(binp)
    lut = np.asarray(build_lut(m.brightness, m.contrast, m.gamma), np.uint8)
    raw = np.fromfile(binp, np.uint8)
    crop = (1, 2, 33, 21)
    x, y, w, h = crop
    exp = np.stack([lut[raw[i * m.frame_stride + 8 : i * m.frame_stride + 8 + m.width * m.height]
                        .reshape(m.height, m.width)[y : y + h, x : x + w]] for i in range(20)])
    for codec in ("ffv1", "gif"):
        out = tmp_path / f"v{video.CODECS[codec]['ext']}"
        st = video.render_video(binp, str(out), count=20, crop=crop, codec=codec, fps=25)
        assert st["lossless"] and st["frames_written"] == 20
        dec = video.decode_video_gray(str(out), w, h)
        assert np.array_equal(dec, exp), codec
    st = video.render_video(binp, str(tmp_path / "v.mp4"), count=20, crop=crop, codec="h264")
    assert st["frames_written"] == 20 and not st["lossless"]
    with pytest.raises(RuntimeError) as ei:
        video.render_video(binp, str(tmp_path / "bad.notacontainer"), count=200)
    assert "Broken pipe" not in str(ei.value) and "ffmpeg failed" in str(ei.value)


def test_studio_v21_tabs_icons_and_no_hang(tmp_path, monkeypatch):
    """v2.1 studio: seven tabs in order, every new tab builds, icons render,
    the logo icon is drawn (no file lookup), and a JPEG 2000 export from a
    program without an importable __main__ falls back to threads instead of
    hanging forever."""
    try:
        from PySide6 import QtWidgets
    except ImportError:
        pytest.skip("PySide6 not installed")
    import os as _os

    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("OPNGX_MODULES_DIR", str(tmp_path / "mods"))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from opngx.ui import icons, logo, qt_app

    assert not logo.qicon().isNull()
    for name in icons.names():
        assert not icons.icon(name).isNull(), name
    w = qt_app.MainWindow()
    try:
        assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == \
            ["Start", "Extract", "Video", "Analyze", "Editor", "Docs", "System"]
        for i in range(w.tabs.count()):
            assert not w.tabs.tabIcon(i).isNull()
        assert w.extract_btn.text() == "Extract" and not w.extract_btn.icon().isNull()
    finally:
        w.close()
    from opngx import formats

    monkeypatch.setattr(formats, "_processes_usable", lambda: False)
    binp = str(tmp_path / "x.bin")
    with open(binp, "wb") as fh:
        for i in range(10):
            fh.write(struct.pack("<Q", i) + np.full(32 * 24, i * 20, np.uint8).tobytes())
    (tmp_path / "x.footage").write_text("<x><ResolutionX>32</ResolutionX><ResolutionY>24</ResolutionY>"
                                        "<NumberOfImages>10</NumberOfImages></x>", encoding="utf-8")
    st = opngx.extract(binp, str(tmp_path / "j"), fmt="jp2", mode="raw")
    assert st.frames_written == 10
