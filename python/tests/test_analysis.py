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
        assert names[:3] == ["motion_tracking", "luminosity", "contrast"]
        av.mod_list.setCurrentRow(0)
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
        it = av.mod_list.item(2)
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
