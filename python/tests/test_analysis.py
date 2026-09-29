"""Analysis modules (v1.10): accuracy, runner, registry, CLI and studio.

Ground truth comes from synthetic recordings written here: a ring (the
project's footage images a sphere as a bright rim with a dark interior,
brighter on one side) or a Gaussian laser spot, rendered 5x supersampled
at known sub-pixel positions, with noise and dark specks, in a real .bin
(8-byte frame-header clock + pixels) with a .footage sidecar.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import opngx
import opngx.analysis as oa

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- helpers --
def render(kind, cx, cy, H=120, W=140, r=12.0, sigma=2.5, ss=5, seed=0, noise=3.0, bright_bottom=True):
    rng = np.random.default_rng(seed)
    ys = (np.arange(H * ss) + 0.5) / ss - 0.5
    xs = (np.arange(W * ss) + 0.5) / ss - 0.5
    X, Y = np.meshgrid(xs, ys)
    if kind == "spot":
        f = 120 * np.exp(-((X - cx) ** 2 + (Y - cy) ** 2) / (2 * sigma**2))
    else:
        d = np.hypot(X - cx, Y - cy)
        rim = np.exp(-((d - r) ** 2) / (2 * 1.1**2))
        gain = 70 + (40 * np.clip((Y - cy) / r, -1, 1) if bright_bottom else 0)
        f = rim * (gain + 10) - 35 * (d < r - 2)
    img = f.reshape(H, ss, W, ss).mean((1, 3)) + 90
    img += rng.normal(0, noise, img.shape)
    img.flat[rng.integers(0, H * W, 40)] -= 30
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def make_recording(d: Path, name: str, kind: str, n: int = 120, W=140, H=120, t0=5_000_000, dt=2000):
    """Write <d>/<name>/<name>.bin + .footage; return (bin_path, truth (n,2))."""
    rec = d / name
    rec.mkdir(parents=True, exist_ok=True)
    k = np.arange(n)
    # keep the whole ring (r = 12) inside the frame: x 32..98, y 36..84
    truth = np.c_[65 + 30 * np.cos(k / 19.0) + 0.013 * k, 60 + 22 * np.sin(k / 13.0)]
    with open(rec / f"{name}.bin", "wb") as fh:
        for i, (x, y) in enumerate(truth):
            fh.write(struct.pack("<Q", t0 + i * dt))
            fh.write(render(kind, x, y, H=H, W=W, seed=i).tobytes())
    (rec / f"{name}.footage").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<Optronis-TimeViewer-Footage><Footage>
<ResolutionX>{W}</ResolutionX><ResolutionY>{H}</ResolutionY>
<NumberOfImages>{n}</NumberOfImages><Framerate>500</Framerate>
</Footage><SettingsProcessing><Brightness>49</Brightness><Contrast>18</Contrast><Gamma>1</Gamma></SettingsProcessing>
<Camera><Name>{name}</Name></Camera></Optronis-TimeViewer-Footage>
""",
        encoding="utf-8",
    )
    return str(rec / f"{name}.bin"), truth


@pytest.fixture(scope="module")
def recs(tmp_path_factory):
    d = tmp_path_factory.mktemp("an")
    ring = make_recording(d, "ring", "ring")
    spot = make_recording(d, "spot", "spot")
    return d, ring, spot


@pytest.fixture(autouse=True)
def _isolated_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("OPNGX_MODULES_DIR", str(tmp_path / "mods"))
    monkeypatch.delenv("OPNGX_MODULES_PATH", raising=False)


def _err(res, truth):
    x, y = res.columns["x"], res.columns["y"]
    ex, ey = x - truth[: len(x), 0], y - truth[: len(y), 1]
    return float(np.nanmean(ex)), float(np.nanmean(ey)), float(np.sqrt(np.nanmean(ex**2 + ey**2)))


# ------------------------------------------------------------------ AN-1 ---
def test_an1_motion_tracking_accuracy_ring_and_spot(recs):
    """Sub-pixel accuracy against ground truth. The ring is brighter on its
    lower side (as in the real footage): a mask/centroid estimator is
    biased toward it; the ridge-refined circle fit must not be."""
    _d, (ring_bin, ring_t), (spot_bin, spot_t) = recs
    r = oa.analyze(ring_bin, "motion_tracking")["motion_tracking"]
    assert r.summary["method_used"] == "circle", "auto must recognise a ring"
    bx, by, rms = _err(r, ring_t)
    assert rms < 0.10 and abs(bx) < 0.06 and abs(by) < 0.06, (bx, by, rms)
    assert abs(np.nanmean(r.columns["radius"]) - 12.0) < 0.15
    assert r.columns["found"].all()

    s = oa.analyze(spot_bin, "motion_tracking")["motion_tracking"]
    assert s.summary["method_used"] == "centroid", "auto must recognise a solid spot"
    bx, by, rms = _err(s, spot_t)
    assert rms < 0.08 and abs(bx) < 0.03 and abs(by) < 0.03, (bx, by, rms)

    # the intensity centroid on a ring is the biased estimator we avoid
    c = oa.analyze(ring_bin, "motion_tracking", params={"motion_tracking": {"method": "centroid"}})
    assert abs(_err(c["motion_tracking"], ring_t)[1]) > 1.0

    # mask-only circle fit (refine off) is measurably worse than the ridge fit
    m = oa.analyze(ring_bin, "motion_tracking", params={"motion_tracking": {"method": "circle", "refine": False}})
    assert _err(m["motion_tracking"], ring_t)[2] > rms


def test_an2_crop_reports_full_frame_coordinates_and_dark_targets(recs, tmp_path):
    _d, (ring_bin, ring_t), _spot = recs
    full = oa.analyze(ring_bin, "motion_tracking", count=40)["motion_tracking"]
    # ring path x 32..98, y 36..84; the 48 px search window adds 24 px
    crop = (4, 6, 132, 112)
    cr = oa.analyze(ring_bin, "motion_tracking", count=40, crop=crop)["motion_tracking"]
    assert cr.run["crop"] == list(crop)
    # the coarse grid is aligned to the full frame, so a crop that does not
    # clip the search window gives IDENTICAL positions
    assert np.nanmax(np.abs(cr.columns["x"] - full.columns["x"])) < 1e-9
    assert np.nanmax(np.abs(cr.columns["y"] - full.columns["y"])) < 1e-9

    # a dark disc on a bright field: target=dark
    n, W, H = 30, 90, 70
    b = tmp_path / "dark" / "dark.bin"
    b.parent.mkdir()
    truth = np.c_[30 + 0.7 * np.arange(n), 35 + 0.3 * np.arange(n)]
    yy, xx = np.mgrid[0:H, 0:W]
    with open(b, "wb") as fh:
        for i, (x, y) in enumerate(truth):
            img = 200 - 150 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.5**2))
            fh.write(struct.pack("<Q", 1_000_000 + 2000 * i))
            fh.write(np.clip(np.round(img), 0, 255).astype(np.uint8).tobytes())
    (b.parent / "dark.footage").write_text(
        f"<x><ResolutionX>{W}</ResolutionX><ResolutionY>{H}</ResolutionY><NumberOfImages>{n}</NumberOfImages></x>"
    )
    res = oa.analyze(str(b), "motion_tracking", params={"motion_tracking": {"target": "dark"}})["motion_tracking"]
    assert _err(res, truth)[2] < 0.1


# ------------------------------------------------------------------ AN-3 ---
def test_an3_runner_time_axis_range_stride_and_single_pass(recs):
    _d, (ring_bin, _t), _spot = recs
    run = oa.analyze(ring_bin, ["motion_tracking", "luminosity", "contrast"], start=10, count=30, stride=3)
    assert run.ok and set(run.results) == {"motion_tracking", "luminosity", "contrast"}
    for res in run.results.values():
        assert list(res.columns["frame"]) == list(range(10, 100, 3))
        assert res.columns["timestamp_raw"][0] == 5_000_000 + 10 * 2000
        assert np.allclose(res.columns["time_s"], np.arange(30) * 3 * 0.002)
        assert "frame-header clock" in res.run["time_source"]
    # one pass over several modules == each module on its own
    alone = oa.analyze(ring_bin, "luminosity", start=10, count=30, stride=3)["luminosity"]
    for k in alone.columns:
        assert np.array_equal(alone.columns[k], run["luminosity"].columns[k]), k
    # velocities come from the clock: finite differences of x over time_s
    mt = run["motion_tracking"]
    assert np.allclose(mt.columns["vx"], np.gradient(mt.columns["x"], mt.columns["time_s"]))


def test_an4_luminosity_and_contrast_match_numpy(recs):
    _d, (ring_bin, _t), _spot = recs
    m = opngx.probe(ring_bin)
    fr = np.stack([np.frombuffer(opngx.read_frame_gray(ring_bin, m, i, mode="raw"), np.uint8) for i in range(20)])
    run = oa.analyze(ring_bin, ["luminosity", "contrast"], count=20,
                     params={"contrast": {"robust": False}})
    lum, con = run["luminosity"], run["contrast"]
    f = fr.astype(float)
    assert np.allclose(lum.columns["mean"], f.mean(1))
    assert np.allclose(lum.columns["std"], f.std(1))
    assert (lum.columns["min"] == fr.min(1)).all() and (lum.columns["max"] == fr.max(1)).all()
    assert (lum.columns["integrated"] == fr.sum(1)).all()
    hi, lo = f.max(1), f.min(1)
    assert np.allclose(con.columns["michelson"], (hi - lo) / (hi + lo))
    assert np.allclose(con.columns["rms"], f.std(1) / f.mean(1))
    rb = oa.analyze(ring_bin, "contrast", count=20)["contrast"]
    assert np.array_equal(rb.columns["i_high"], np.percentile(f, 99, axis=1, method="inverted_cdf"))


def test_an5_errors_are_isolated_and_params_validated(recs):
    _d, (ring_bin, _t), _spot = recs

    class Broken(oa.Module):
        name = "broken"

        def process(self, frames, ctx):
            raise ZeroDivisionError("boom")

    class BadShape(oa.Module):
        name = "bad_shape"

        def process(self, frames, ctx):
            return {"v": np.zeros((len(frames), 2))}

    run = oa.analyze(ring_bin, [Broken, BadShape, "luminosity"], count=20)
    assert set(run.errors) == {"broken", "bad_shape"}
    assert "boom" in str(run.errors["broken"]) and "ZeroDivisionError" in run.errors["broken"].tb
    assert "shape" in str(run.errors["bad_shape"])
    assert "luminosity" in run.results, "a failing module must not take the others down"

    with pytest.raises(ValueError, match="no parameter"):
        oa.analyze(ring_bin, "motion_tracking", params={"motion_tracking": {"windw": 3}})
    with pytest.raises(ValueError, match="one of"):
        oa.analyze(ring_bin, "motion_tracking", params={"motion_tracking": {"method": "magic"}})
    with pytest.raises(ValueError, match=">="):
        oa.analyze(ring_bin, "motion_tracking", params={"motion_tracking": {"window": 1}})
    # CLI-style strings are coerced
    r = oa.analyze(ring_bin, "motion_tracking", count=5,
                   params={"motion_tracking": {"window": "40", "refine": "false", "threshold": "0,5"}})
    assert r["motion_tracking"].params == {**oa.get_module("motion_tracking").defaults(),
                                           "window": 40, "refine": False, "threshold": 0.5}

    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 2

    c = oa.analyze(ring_bin, "luminosity", batch=10, jobs=1, should_cancel=cancel)
    assert c.cancelled and 0 < c.frames < 120
    assert len(c["luminosity"]) == c.frames, "a cancelled run keeps a clean prefix"


def test_an6_data_files_round_trip(recs, tmp_path):
    _d, (ring_bin, _t), _spot = recs
    res = oa.analyze(ring_bin, "motion_tracking", count=25)["motion_tracking"]
    for ext in ("csv", "json", "npz", "tsv"):
        p = res.save(str(tmp_path / f"t.{ext}"))
        assert os.path.getsize(p) > 0
    import csv

    with open(tmp_path / "t.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.reader(line for line in fh if not line.startswith("#"))]
    assert rows[0][:4] == ["frame", "timestamp_raw", "time_s", "x"] and len(rows) == 26
    assert abs(float(rows[5][3]) - res.columns["x"][4]) < 1e-3
    for ext in ("json", "npz"):
        back = oa.load_result(str(tmp_path / f"t.{ext}"))
        assert back.names == res.names and len(back) == 25
        assert np.allclose(back.columns["x"], res.columns["x"])
        assert back.summary["method_used"] == "circle"
    md = json.loads((tmp_path / "t.json").read_text())
    assert md["format"] == "opngx-analysis/1" and md["module"] == "motion_tracking"


# ------------------------------------------------------------------ AN-7 ---
def test_an7_registry_user_modules_template_and_validation(recs, tmp_path):
    _d, (ring_bin, _t), _spot = recs
    mods = Path(oa.user_modules_dir(create=True))
    assert str(mods).startswith(str(tmp_path))
    (mods / "peak.py").write_text(oa.template("peak_mod", "Peak"))
    (mods / "broken.py").write_text("import numpy as np\ndef oops(:\n")
    clash = oa.template("luminosity", "Imposter")
    (mods / "clash.py").write_text(clash)
    infos = {i.name: i for i in oa.discover()}
    assert infos["peak_mod"].ok and infos["peak_mod"].origin == "user"
    assert not infos["broken"].ok and "SyntaxError" in infos["broken"].error
    usable = [i for i in oa.discover() if i.name == "luminosity" and i.ok]
    assert [i.origin for i in usable] == ["builtin"], "a user file must not replace a built-in"
    assert any(i.origin == "user" and "already loaded" in i.error for i in oa.discover())
    # the template is a working module end to end
    v = oa.validate_file(str(mods / "peak.py"))
    assert v.ok, v.messages
    run = oa.analyze(ring_bin, "peak_mod", count=10)
    assert set(run["peak_mod"].columns) >= {"mean", "bright_px"}
    assert not oa.validate_file(str(mods / "broken.py")).ok
    # every built-in passes its own dry run
    for i in oa.list_modules():
        ok, msgs = oa.dry_run_module(i.cls)
        assert ok, msgs


def test_an8_cli_modules_and_analyze(recs, tmp_path):
    d, (ring_bin, _t), _spot = recs
    env = dict(os.environ, OPNGX_MODULES_DIR=str(tmp_path / "mods"))
    py = [sys.executable, "-m", "opngx.cli"]
    out = subprocess.run(py + ["modules"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "motion_tracking" in out.stdout
    out = subprocess.run(py + ["modules", "template", "my_thing"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and Path(out.stdout.strip()).exists()
    out = subprocess.run(py + ["modules", "validate", out.stdout.strip()], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stdout + out.stderr

    target = tmp_path / "traj.csv"
    out = subprocess.run(py + ["analyze", ring_bin, "-m", "motion_tracking", "-o", str(target),
                               "-p", "method=circle", "--frames", "40"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert target.exists() and "method_used: circle" in out.stdout

    outdir = tmp_path / "batch"
    out = subprocess.run(py + ["analyze", str(d), "--batch", "-m", "motion_tracking", "-m", "luminosity",
                               "-o", str(outdir), "--format", "json", "--stride", "4",
                               "-p", "motion_tracking.window=40"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    for rec in ("ring", "spot"):
        for m in ("motion_tracking", "luminosity"):
            assert (outdir / rec / "ANALYSIS" / f"{m}.json").exists(), (rec, m)
    bad = subprocess.run(py + ["analyze", ring_bin, "-m", "motion_tracking", "-o", str(tmp_path / "x.csv"),
                               "-p", "nope=1"], capture_output=True, text=True, env=env)
    assert bad.returncode != 0 and "no parameter" in bad.stderr


# ------------------------------------------------------------------ AN-9 ---
def test_an9_studio_analyze_and_editor(recs, tmp_path):
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import time as _time

    from PySide6 import QtWidgets

    from opngx.ui import qt_app

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    _d, (ring_bin, ring_t), _spot = recs
    w = qt_app.MainWindow()

    def wait(cond, sec=60):
        t = _time.time()
        while not cond() and _time.time() - t < sec:
            app.processEvents()
            _time.sleep(0.01)

    try:
        w.bin_edit.setText(ring_bin)
        w._probe()
        w.out_edit.setText(str(tmp_path / "out"))
        av = w.analyze_view
        names = [av.mod_list.item(i).data(0x0100) for i in range(av.mod_list.count())]
        assert {"motion_tracking", "brownian_motion", "luminosity", "contrast"} <= set(names)
        av.mod_list.setCurrentRow(names.index("motion_tracking"))
        av.run(only_selected=True)
        wait(lambda: not av._running)
        res = av.result()
        assert res is not None and res.module == "motion_tracking" and len(res) == 120
        assert _err(res, ring_t)[2] < 0.1
        assert (tmp_path / "out" / "ring" / "ANALYSIS" / "motion_tracking.csv").exists()
        av.row_slider.setValue(60)
        assert av.preview.image() is not None and av.preview._point is not None
        assert av.plot.series, "the plot shows the data"

        # untick = switched out of "Run all"
        it = av.mod_list.item(names.index("contrast"))
        from PySide6.QtCore import Qt

        it.setCheckState(Qt.Unchecked)
        assert "contrast" not in av.enabled_names()
        av.run(only_selected=False)
        wait(lambda: not av._running)
        assert (ring_bin, "luminosity") in av.results and (ring_bin, "contrast") not in av.results

        # write a module in the editor, validate, test, use it
        ed = w.module_editor
        path = ed.new_module("frame_energy")
        assert path and os.path.exists(path)
        assert ed.validate()
        run = ed.test_run(50)
        assert run is not None and not run.errors
        ed.save_and_reload()
        names = [av.mod_list.item(i).data(0x0100) for i in range(av.mod_list.count())]
        assert "frame_energy" in names
        av.mod_list.setCurrentRow(names.index("frame_energy"))
        av.run(only_selected=True)
        wait(lambda: not av._running)
        assert av.result().module == "frame_energy"

        # a broken edit is caught and its line is marked; nothing is saved
        ed.editor.setPlainText("from opngx.analysis import Module\nclass X(Module):\n    name = 'x'\n    def process(self, f, ctx)\n        return {}\n")
        assert not ed.validate()
        assert ed.editor.error_line == 4
        assert "frame_energy" in open(path).read()
    finally:
        w.close()
        app.processEvents()


# ----------------------------------------------------------------- AN-10 ---
def test_an10_native_kernel_matches_numpy():
    """v2.0: the C kernel (src/analysis.c) and the numpy reference agree to
    1e-6 px on rings, spots, noise, flat and tiny frames, small windows and
    crop origins — including degenerate windows where ties used to flip on
    FMA / last-bit cos() differences."""
    from opngx.analysis import native
    from opngx.analysis.builtin.motion_tracking import MotionTracking

    if not native.available():
        pytest.skip("native engine not built")
    rng = np.random.default_rng(3)
    cases = {
        "ring": np.stack([render("ring", 40 + 30 * rng.random(), 35 + 40 * rng.random(), seed=i) for i in range(30)]),
        "spot": np.stack([render("spot", 40 + 30 * rng.random(), 35 + 40 * rng.random(), seed=i) for i in range(30)]),
        "noise": rng.integers(0, 256, (20, 50, 70), dtype=np.uint8),
        "flat": np.full((4, 40, 40), 77, np.uint8),
        "tiny": rng.integers(0, 256, (10, 3, 7), dtype=np.uint8),
    }
    m = MotionTracking()
    for name, fr in cases.items():
        for method in ("circle", "centroid", "peak"):
            for over in ({}, {"window": 7, "locate_block": 1}, {"refine": False, "threshold": 0.3}, {"window": 5, "min_pixels": 1}):
                p = MotionTracking.resolve_params({"method": method, **over})
                for origin in ((0, 0), (3, 5)):
                    cx, cy, r, n, good = m._measure(fr, p, method, origin)[:5]
                    nat = native.track(fr, method, p, origin)
                    assert (nat["found"] == good).all(), (name, method, over)
                    assert (nat["area"] == n).all()
                    if good.any():
                        assert np.max(np.abs(nat["x"][good] - cx[good])) < 1e-6, (name, method, over)
                        assert np.max(np.abs(nat["y"][good] - cy[good])) < 1e-6, (name, method, over)
    # histograms
    fr = rng.integers(0, 256, (7, 33, 29), dtype=np.uint8)
    h = native.hist256(fr)
    assert (h == np.stack([np.bincount(f.ravel(), minlength=256) for f in fr])).all()
    # invalid arguments are refused, not a crash
    import ctypes

    lib = native._lib()
    tp = native.TrackParams(0, 0, 0.5, 6, 4, 1, 0, 0)  # window 0
    d = (ctypes.c_double * 1)()
    i8 = (ctypes.c_int8 * 1)()
    buf = (ctypes.c_uint8 * 16)()
    assert lib.opngx_track(buf, 1, 4, 4, ctypes.byref(tp), d, d, d, d, d, i8, d) == -1
    assert lib.opngx_track(None, 1, 4, 4, ctypes.byref(tp), d, d, d, d, d, i8, d) == -1
    assert lib.opngx_hist256(None, 1, 4, None) == -1


def _sim_ou(n, dt, tau, D, rng):
    a = np.exp(-dt / tau)
    s = np.sqrt(D * tau * (1 - a * a))
    x = np.empty(n)
    x[0] = rng.normal(0, np.sqrt(D * tau))
    xi = rng.normal(0, 1, n)
    for i in range(1, n):
        x[i] = a * x[i - 1] + s * xi[i]
    return x


def _brownian_on(x, y, dt, **params):
    from opngx.analysis.builtin.brownian import BrownianMotion

    n = len(x)
    t = np.arange(n) * dt
    tr = {"x": 100 + x, "y": 60 + y, "time_s": t, "found": np.ones(n, np.int8), "radius": np.full(n, 12.0)}
    ctx = oa.Context(meta=None, params=BrownianMotion.resolve_params(params), width=0, height=0,
                     crop=(0, 0, 0, 0), log=lambda s: None)
    ctx.inputs = {"motion_tracking": tr}
    BrownianMotion().finish({"frame": np.arange(n), "time_s": t}, ctx)
    return ctx


def test_an11_brownian_recovers_known_trap_and_diffusion():
    """Simulated trapped bead (sampled Ornstein-Uhlenbeck + localisation
    noise) and free diffusion with known parameters."""
    rng = np.random.default_rng(7)
    dt, n, tau, D, sig = 0.002, 50000, 0.01, 4.0, 0.03
    x = _sim_ou(n, dt, tau, D, rng) + rng.normal(0, sig, n)
    y = _sim_ou(n, dt, tau, D, rng) + rng.normal(0, sig, n)
    ctx = _brownian_on(x, y, dt, pixel_size_um=0.1)
    s = ctx.summary
    fc = 1 / (2 * np.pi * tau)
    for key in ("fc_x_hz", "fc_y_hz", "fc_acf_x_hz", "fc_acf_y_hz"):
        assert abs(s[key] / fc - 1) < 0.08, (key, s[key], fc)
    for key in ("D_acf_x", "D_acf_y", "D_msd_ou_x"):
        assert abs(s[key] / (D * 0.01) - 1) < 0.06, (key, s[key])  # µm² (0.1 µm/px)
    assert abs(s["noise_acf_x"] / (sig * 0.1) - 1) < 0.1
    assert s["alpha"] < 0.8, "a trapped bead is sub-diffusive at these lags"
    kT = 1.380649e-23 * 295.15
    k_true = kT / (D * tau * 0.01 * 1e-12) * 1e6
    assert abs(s["k_x_equipartition_corrected_pN_per_um"] / k_true - 1) < 0.05
    assert abs(s["step_kurtosis_x"]) < 0.1 and not s["warnings"], s["warnings"]
    assert set(ctx.tables) == {"msd", "psd", "steps"}

    D2 = 0.5
    x = np.cumsum(rng.normal(0, np.sqrt(2 * D2 * dt), n))
    y = np.cumsum(rng.normal(0, np.sqrt(2 * D2 * dt), n))
    s = _brownian_on(x, y, dt, detrend="none").summary
    assert abs(s["D_msd"] / D2 - 1) < 0.05 and abs(s["alpha"] - 1) < 0.05

    # a non-thermal trajectory (uniform steps) is flagged, not reported as a trap
    x = np.cumsum(rng.uniform(-0.1, 0.1, n)) * 0.0 + rng.uniform(-0.3, 0.3, n)
    y = rng.uniform(-0.3, 0.3, n)
    s = _brownian_on(x, y, dt).summary
    assert any("not Gaussian" in w for w in s["warnings"]), s["warnings"]


def test_an12_requires_chain_and_extra_tables(recs, tmp_path):
    _d, (ring_bin, _t), _spot = recs
    run = oa.analyze(ring_bin, "brownian_motion", params={"motion_tracking": {"method": "circle"}})
    assert set(run.results) == {"motion_tracking", "brownian_motion"}
    bm = run["brownian_motion"]
    assert bm.run["auto_added"] == ["motion_tracking"]
    assert run["motion_tracking"].params["method"] == "circle"
    assert set(bm.tables) == {"msd", "psd", "steps"}
    p = bm.save(str(tmp_path / "bm.csv"))
    for tn in ("msd", "psd", "steps"):
        assert (tmp_path / f"bm.{tn}.csv").exists()
    for ext in ("json", "npz"):
        back = oa.load_result(bm.save(str(tmp_path / f"bm.{ext}")))
        assert set(back.tables) == {"msd", "psd", "steps"}
        assert np.allclose(back.tables["msd"]["lag_s"], bm.tables["msd"]["lag_s"])
    assert os.path.exists(p)

    class Loop(oa.Module):
        name = "loop_a"
        requires = ("loop_a",)

        def process(self, f, ctx):
            return {}

    with pytest.raises(ValueError, match="circular"):
        oa.analyze(ring_bin, [Loop], count=5)


def test_an13_spectral_lines_are_found_and_excluded():
    """A trapped bead shaken at 40 Hz: the line is reported and left out of
    the Lorentzian fit, so the corner frequency stays right."""
    rng = np.random.default_rng(11)
    dt, n, tau, D = 0.002, 50000, 0.01, 4.0
    t = np.arange(n) * dt
    x = _sim_ou(n, dt, tau, D, rng) + 0.08 * np.sin(2 * np.pi * 40.0 * t)
    y = _sim_ou(n, dt, tau, D, rng)
    s = _brownian_on(x, y, dt).summary
    assert any(abs(f - 40.0) < 0.5 for f in s["psd_peaks_x_hz"]), s["psd_peaks_x_hz"]
    assert not s["psd_peaks_y_hz"]
    assert abs(s["fc_x_hz"] / (1 / (2 * np.pi * tau)) - 1) < 0.1
    assert any("spectral lines" in w for w in s["warnings"])


# ----------------------------------------------------------------- AN-14 ---
def test_an14_crop_editor_tools(tmp_path, monkeypatch):
    """v2.0 crop editor: mapping stays exact when zoomed and panned; aspect
    lock, snapping, undo/redo, nudging, auto-crop around the spot / path,
    frame scrubbing and presets."""
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from PySide6 import QtGui, QtWidgets
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from opngx.ui.batch import CropEditor
    from opngx.ui.frameview import gray_to_qimage

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    frames = [render("spot", 30 + 2 * i, 40, H=80, W=100, seed=i) for i in range(10)]
    ed = CropEditor(None, gray_to_qimage(frames[0]), None, (100, 80),
                    frame_fn=lambda i: gray_to_qimage(frames[i]), n_frames=10,
                    track_fn=lambda: (30.0, 38.0, 48.0, 42.0))
    ed.resize(1000, 750)
    ed.show()
    app.processEvents()
    v = ed.view

    def drag(a, b):
        t, s = v._target()
        pa = QPoint(int(t.x() + (a[0] + 0.5) * s), int(t.y() + (a[1] + 0.5) * s))
        pb = QPoint(int(t.x() + (b[0] + 0.5) * s), int(t.y() + (b[1] + 0.5) * s))
        QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, pa)
        QTest.mouseMove(v, pb)
        QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, pb)

    # zoom + pan, then draw: the selection still lands on the right pixels
    v.set_zoom(3.0)
    v._pan += QtCore_QPointF(-40, 25)
    app.processEvents()
    drag((20, 30), (33, 41))
    assert ed.selection() == (20, 30, 14, 12), ed.selection()
    v.reset_view()

    ed.cmb_aspect.setCurrentText("1:1")
    assert ed.selection()[2] == ed.selection()[3]
    ed.cmb_aspect.setCurrentText("free")
    ed.cmb_snap.setCurrentIndex(3)  # 8 px
    ed._set_sel((5, 5, 37, 21))
    x, y, w, h = ed.selection()
    assert w % 8 == 0 and h % 8 == 0
    ed.cmb_snap.setCurrentIndex(0)

    ed._set_sel((10, 10, 20, 20), push=True)
    ed._set_sel((12, 12, 20, 20), push=True)
    ed.undo()
    assert ed.selection() == (10, 10, 20, 20)
    ed.redo()
    assert ed.selection() == (12, 12, 20, 20)

    ed.view.setFocus()
    QTest.keyClick(ed, Qt.Key_Right, Qt.ShiftModifier)
    assert ed.selection()[0] == 22
    QTest.keyClick(ed, Qt.Key_Down, Qt.AltModifier)
    assert ed.selection()[3] == 21

    ed._set_sel((0, 0, 100, 80))
    ed.sp_margin.setValue(8)
    ed._around_spot()  # spot at (30, 40) in frame 0
    x, y, w, h = ed.selection()
    assert abs(x + w / 2 - 30) <= 3 and abs(y + h / 2 - 40) <= 3, ed.selection()
    ed._around_path()
    assert ed.selection() == (22, 30, 35, 21), ed.selection()

    ed.frame_slider.setValue(9)
    assert ed.frame_lbl.text() == "frame 9"

    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", staticmethod(lambda *a, **k: ("roi1", True)))
    ed._save_preset()
    ed._set_sel((0, 0, 100, 80))
    idx = next(i for i in range(ed.cmb_preset.count()) if ed.cmb_preset.itemData(i) == "roi1")
    ed._apply_preset(idx)
    assert ed.selection() == (22, 30, 35, 21)
    ed.close()


def QtCore_QPointF(x, y):  # noqa: N802 - small helper for the test above
    from PySide6.QtCore import QPointF

    return QPointF(x, y)


# ----------------------------------------------------------------- AN-15 ---
def test_an15_docs_are_in_sync_and_generated_refs_render():
    """The Docs tab ships the package copies; the repo's docs/ must match
    them, and the generated API / module references must build."""
    pkg = REPO / "python" / "src" / "opngx" / "docs"
    for name in ("ANALYSIS.md", "STUDIO.md", "FORMAT.md"):
        assert (pkg / name).read_text(encoding="utf-8") == (REPO / "docs" / name).read_text(encoding="utf-8"), name
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    from opngx.ui import docs_ui

    api = docs_ui.api_reference_md()
    for word in ("Module", "Param", "inputs", "analyze(", "histograms("):
        assert word in api, word
    for info in oa.list_modules():
        md = docs_ui.module_reference_md(info)
        assert info.cls.name in md
        assert "## Parameters" in md or not info.cls.params
    titles = [t for t, _p in docs_ui.bundled_docs()]
    assert any("Analysis modules" in t for t in titles) and any("studio" in t.lower() for t in titles)


# ----------------------------------------------------------------- AN-16 ---
def test_an16_template_is_ascii_and_crash_handlers_log(tmp_path, monkeypatch):
    """Windows found it: the template's em dash was written as cp1252 and
    the module then failed to import. And uncaught errors must reach
    crash.log with a traceback, from the UI thread and from workers."""
    assert all(ord(c) < 128 for c in oa.template("x_mod", "X")), "template must be pure ASCII"
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    import sys as _sys
    import threading

    monkeypatch.setenv("OPNGX_MODULES_DIR", str(tmp_path / "cfg" / "opngx" / "modules"))
    from PySide6 import QtWidgets

    from opngx.ui import qt_app

    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    old_hook, old_thook = _sys.excepthook, threading.excepthook
    try:
        qt_app.install_crash_handlers()
        try:
            raise RuntimeError("ui-thread boom")
        except RuntimeError:
            _sys.excepthook(*_sys.exc_info())
        t = threading.Thread(target=lambda: 1 / 0, name="worker-x")
        t.start()
        t.join()
        log = open(qt_app.crash_log_path(), encoding="utf-8").read()
        assert "ui-thread boom" in log and "Traceback" in log
        assert "worker-x" in log and "ZeroDivisionError" in log
    finally:
        import faulthandler

        faulthandler.disable()
        _sys.excepthook, threading.excepthook = old_hook, old_thook


def test_an17_every_theme_covers_every_role_and_switches_live():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        pytest.skip("PySide6 not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    from opngx.ui import qt_app, themes

    roles = set(themes.ROLE_OF.values())
    for name, th in themes.THEMES.items():
        missing = roles - set(th)
        assert not missing, (name, missing)
    # every colour literal in the stylesheet has a role (else a theme would
    # leave a Midnight colour behind)
    import re

    lits = {m.lower() for m in re.findall(r"#[0-9a-fA-F]{6}\b", qt_app.QSS)}
    assert lits <= set(themes.ROLE_OF), lits - set(themes.ROLE_OF)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    qt_app.apply_theme(app, "Catppuccin Latte")
    qss = app.styleSheet()
    assert themes.THEMES["Catppuccin Latte"]["bg"] in qss and "#050505" not in qss
    themes.apply(app, "Midnight", accent="#ff8800")
    assert "#ff8800" in app.styleSheet()
    themes.apply(app, "Midnight", accent=None)
    assert "#4d8248" in app.styleSheet()
