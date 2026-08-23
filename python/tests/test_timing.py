"""Timestamp analysis + sidecar enrichment gates."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

import opngx
from opngx.timing import analyze_timestamps

REPO = Path(__file__).resolve().parents[2]

SAMPLE_BIN = Path(
    os.environ.get(
        "OPNGX_SAMPLE", "/home/shuvam/codes/ayush_opt/sbs/bin/brow_1.2/brow_1.2.bin"
    )
)


def test_fixture_uniform_clock(fixture_dir):
    """gen_fixture writes ts = 10_000_000 + i*2000 → perfect 500 fps."""
    m = opngx.probe(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    rep = analyze_timestamps(m.bin_path, m)
    assert rep["frames"] == 200
    assert rep["monotonic"] is True
    assert rep["gaps_gt_1p5x_median"] == 0
    assert rep["delta_min"] == rep["delta_max"] == 2000
    assert abs(rep["effective_fps"] - 500.0) < 1e-6
    assert rep["tick_period_s"] == pytest.approx(1e-6)


def test_subrange_start_offset(fixture_dir):
    m = opngx.probe(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    rep = analyze_timestamps(m.bin_path, m, start=100, count=50)
    assert rep["frames"] == 50 and rep["start_index"] == 100
    assert rep["first_tick"] == 10_000_000 + 100 * 2000


def test_probe_surfaces_sidecar_extras(fixture_dir):
    """Every non-core scalar tag lands in FootageMetadata.extra."""
    m = opngx.probe(fixture_dir / "cam_9.9" / "cam_9.9.bin")
    # fixture sidecar is minimal: these are exactly its extra scalars
    assert "BitsPerPixel" in m.extra and "Name" in m.extra
    # core tags stay out of extras (they have dedicated fields)
    assert "ResolutionX" not in m.extra


@pytest.mark.skipif(not SAMPLE_BIN.exists(), reason="real sample data absent")
def test_real_bin_clock_is_clean():
    """brow_1.2: 50k frames must be monotonic, gap-free, exactly 500 fps.

    This pins the discovered timing layer: tick == 1 µs, ±1 tick jitter,
    zero dropped frames across the full recording.
    """
    m = opngx.probe(SAMPLE_BIN)
    assert m.extra.get("FramerateReal") == "500"
    rep = analyze_timestamps(SAMPLE_BIN, m)
    assert rep["frames"] == 50_000
    assert rep["monotonic"] is True
    assert rep["gaps_gt_1p5x_median"] == 0
    assert rep["delta_median"] == 2000
    assert rep["delta_max"] <= 2001
    assert rep["effective_fps"] == pytest.approx(500.0, abs=1e-3)
    assert "Serial" in m.extra and "Model" in m.extra


@pytest.mark.skipif(not SAMPLE_BIN.exists(), reason="real sample data absent")
def test_real_metadata_json_includes_extras(tmp_path):
    import json

    st = opngx.extract(str(SAMPLE_BIN), str(tmp_path), frames=3, export_metadata=True)
    assert st.frames_written == 3
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert meta["camera_name"] and meta["width"] == 256
