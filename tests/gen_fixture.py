#!/usr/bin/env python3
"""Generate a synthetic Optronis-style .bin + .footage fixture and the
expected reference PNGs, computed independently of the C engine.

Usage: gen_fixture.py OUTDIR [W H N BRIGHTNESS CONTRAST]
"""

import os
import struct
import sys

import numpy as np
from PIL import Image


def build_lut(brightness: float, contrast: float, gamma: float = 1.0):
    mul = 1.0 + contrast / 50.0
    lut = np.clip(
        np.floor((np.arange(256, dtype=np.float64) + brightness) * mul + 0.5), 0, 255
    )
    if gamma != 1.0 and gamma > 0:
        lut = np.floor(255.0 * np.power(lut / 255.0, 1.0 / gamma) + 0.5)
    return lut.astype(np.uint8)


def main() -> int:
    outdir = sys.argv[1]
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 48
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 200
    brightness = float(sys.argv[5]) if len(sys.argv) > 5 else 49.0
    contrast = float(sys.argv[6]) if len(sys.argv) > 6 else 18.0

    os.makedirs(outdir, exist_ok=True)
    bindir = os.path.join(outdir, "cam_9.9")
    os.makedirs(bindir, exist_ok=True)
    refdir = os.path.join(outdir, "ref_pngs")
    os.makedirs(refdir, exist_ok=True)
    bin_path = os.path.join(bindir, "cam_9.9.bin")
    footage_path = os.path.join(bindir, "cam_9.9.footage")

    rng = np.random.default_rng(42)
    stride = 8 + w * h
    lut = build_lut(brightness, contrast, 1.0)

    with open(bin_path, "wb") as f:
        for i in range(n):
            ts = 10_000_000 + i * 2000  # 500 fps @ 1us ticks
            f.write(struct.pack("<Q", ts))
            gray = rng.integers(0, 256, size=(h, w), dtype=np.uint8)
            f.write(gray.tobytes())
            # independent expectation -> reference PNG
            rgba = np.empty((h, w, 4), dtype=np.uint8)
            rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = lut[gray]
            rgba[..., 3] = 255
            Image.fromarray(rgba).save(
                os.path.join(refdir, f"cam_{i:05d}.Png")
            )

    with open(footage_path, "w") as f:
        f.write(f"""<?xml version="1.0" encoding="utf-8"?>
<Optronis-TimeViewer-Footage>
  <Footage>
    <ResolutionX>{w}</ResolutionX>
    <ResolutionY>{h}</ResolutionY>
    <NumberOfImages>{n}</NumberOfImages>
    <BitsPerPixel>1</BitsPerPixel>
    <Framerate>500</Framerate>
    <Exposure>1998</Exposure>
    <TimeMarkerReference>10000000</TimeMarkerReference>
  </Footage>
  <SettingsProcessing>
    <Brightness>{brightness:.0f}</Brightness>
    <Contrast>{contrast:.0f}</Contrast>
    <Gamma>1</Gamma>
  </SettingsProcessing>
  <Camera>
    <Name>cam_9.9</Name>
  </Camera>
</Optronis-TimeViewer-Footage>
""")

    print(f"fixture: {bin_path} ({n} frames {w}x{h}, B={brightness} C={contrast})")
    print(f"refs:    {os.path.join(outdir, 'ref_pngs')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
