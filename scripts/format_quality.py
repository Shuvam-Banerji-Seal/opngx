#!/usr/bin/env python3
"""Measure what every output format really stores.

    python scripts/format_quality.py RECORDING.bin [--frames 200] [--markdown]

For each format (and bit depth), extract frames from a real recording with
the native engine and, where it differs, with the pure-Python fallback;
decode every written file independently; compare with the expected pixels
(the recording mapped through the reference transform); report exactness,
largest error, PSNR, size per frame and speed. Exit status 1 if a format
documented as lossless is not bit-exact.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import tempfile
import time

import numpy as np

import opngx
from opngx import formats
from opngx.quality import build_lut


def expected_frames(meta, start, n, crop, bits):
    lut = np.asarray(build_lut(meta.brightness, meta.contrast, meta.gamma), np.uint8)
    raw = np.memmap(meta.bin_path, np.uint8, "r")
    st, W, H = meta.frame_stride, meta.width, meta.height
    x, y, w, h = crop
    out = []
    for i in range(start, start + n):
        f = raw[i * st + 8 : i * st + 8 + W * H].reshape(H, W)[y : y + h, x : x + w]
        m = lut[f]
        out.append(m.astype(np.uint16) * 257 if bits == 16 else m)
    return out


def run(meta, fmt, bits, n, crop, force_fallback=False, quality=None):
    d = tempfile.mkdtemp(prefix=f"opngx-q-{fmt}{bits}-")
    kw = dict(fmt=fmt, bit_depth=bits, frames=n, start=100, crop=crop, channels=0 if fmt == "png" else 6)
    if quality is not None:
        kw["webp_quality" if fmt == "webp" else "jpeg_quality"] = quality
    if force_fallback:
        import opngx._engine as eng

        saved = eng._lib, eng._lib_path
        eng._lib, eng._lib_path = None, None
        orig = eng.load_library
        eng.load_library = lambda: None
        import opngx.extractor as ex

        ex.load_library = lambda: None
    try:
        t0 = time.perf_counter()
        st = opngx.Extractor(meta.bin_path).extract(d, **kw)
        dt = time.perf_counter() - t0
    finally:
        if force_fallback:
            eng.load_library = orig
            ex.load_library = orig
            eng._lib, eng._lib_path = saved
    files = sorted(f for f in glob.glob(os.path.join(d, "*")) if not f.endswith((".csv", ".json")))
    exp = expected_frames(meta, 100, n, crop, bits)
    if fmt == "npy":
        stack = formats.read_frame(files[0])
        dec = [np.asarray(stack[k]) for k in range(len(stack))]
    else:
        dec = [formats.read_frame(f) for f in files]
    reps = [formats.quality_report(e, a) for e, a in zip(exp, dec)]
    size = sum(os.path.getsize(f) for f in files) / max(1, n)
    shutil.rmtree(d, ignore_errors=True)
    exact = len(reps) == n and all(r.get("exact") for r in reps)
    psnr = min((r.get("psnr_db", 0) for r in reps), default=0)
    maxerr = max((r.get("max_abs_error", 1e9) for r in reps), default=1e9)
    return dict(fmt=fmt, bits=bits, path=("fallback" if force_fallback else st.backend), exact=exact,
                max_err=maxerr, psnr=psnr, kib=size / 1024, fps=n / dt, n=len(reps))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--crop", default="0,0,0,0")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--no-fallback", action="store_true")
    a = ap.parse_args()
    meta = opngx.probe(a.bin)
    x, y, w, h = (int(v) for v in a.crop.split(","))
    crop = (x, y, w or meta.width - x, h or meta.height - y)
    run(meta, "png", 8, 50, crop)  # warm-up: cache + library load out of the first row
    rows = []
    for key, f in formats.FORMATS.items():
        for bits in f.bit_depths:
            rows.append(run(meta, key, bits, a.frames, crop))
            if f.engine == "native" and not a.no_fallback:
                rows.append(run(meta, key, bits, min(a.frames, 60), crop, force_fallback=True))
    for q in (95, 75):
        rows.append(run(meta, "jpg", 8, a.frames, crop, quality=q) | {"fmt": f"jpg q{q}"})
        rows.append(run(meta, "webp", 8, a.frames, crop, quality=q) | {"fmt": f"webp q{q}"})
    bad = [r for r in rows if formats.get(r["fmt"].split()[0]).lossless and " q" not in r["fmt"] and not r["exact"]]
    if a.markdown:
        print("| format | bits | path | bit-exact | max error | PSNR | KiB/frame | frames/s |")
        print("|---|---:|---|:---:|---:|---:|---:|---:|")
    for r in rows:
        ps = "∞" if r["psnr"] == float("inf") else f"{r['psnr']:.1f} dB"
        if a.markdown:
            print(f"| {r['fmt']} | {r['bits']} | {r['path']} | {'yes' if r['exact'] else 'no'} | "
                  f"{r['max_err']:.0f} | {ps} | {r['kib']:.1f} | {r['fps']:.0f} |")
        else:
            print(f"{r['fmt']:10} {r['bits']:>2}-bit {r['path']:16} exact={r['exact']!s:5} "
                  f"maxerr={r['max_err']:<6.0f} psnr={ps:>9} {r['kib']:7.1f} KiB/frame {r['fps']:8.0f} fps")
    if bad:
        print("NOT EXACT (documented lossless):", [(r["fmt"], r["bits"], r["path"]) for r in bad], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
