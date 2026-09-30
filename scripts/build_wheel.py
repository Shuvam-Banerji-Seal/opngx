#!/usr/bin/env python3
"""Build a platform wheel of the opngx Python package WITH the C engine.

    python scripts/build_wheel.py --lib build/libopngx.so --engine build/opngx-engine \
        --plat-tag manylinux2014_x86_64 --outdir dist/

The library and the CLI are copied into python/src/opngx/_native/, a wheel is
built, retagged py3-none-<plat-tag> (pure Python + a ctypes library, so one
wheel serves every CPython >= 3.9 on that platform), checked, and the
staging folder is emptied again whatever happens.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "python")
NATIVE = os.path.join(PKG, "src", "opngx", "_native")
KEEP = {"README.txt"}


def clean() -> None:
    for f in os.listdir(NATIVE):
        if f not in KEEP:
            p = os.path.join(NATIVE, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True, help="libopngx.so / libopngx.dll")
    ap.add_argument("--engine", required=True, help="opngx-engine / opngx-engine.exe")
    ap.add_argument("--plat-tag", required=True, help="e.g. manylinux2014_x86_64, win_amd64")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--extra", action="append", default=[], help="more files for _native/ (e.g. DLLs)")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    clean()
    try:
        for src in [a.lib, a.engine, *a.extra]:
            dst = os.path.join(NATIVE, os.path.basename(src))
            shutil.copy2(src, dst)
            if not dst.endswith((".dll", ".txt")):
                os.chmod(dst, os.stat(dst).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        # setuptools reuses python/build/lib: a stale _native/ from another
        # platform's build would ride along into this wheel
        shutil.rmtree(os.path.join(PKG, "build"), ignore_errors=True)
        tmp = tempfile.mkdtemp(prefix="opngx-wheel-")
        try:  # the standard front-end; uv-made venvs have no pip
            import build  # noqa: F401

            cmd = [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", tmp, PKG]
        except ImportError:
            cmd = [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", tmp, PKG]
        subprocess.run(cmd, check=True)
        (whl,) = glob.glob(os.path.join(tmp, "opngx-*.whl"))
        subprocess.run([sys.executable, "-m", "wheel", "tags", "--remove", "--python-tag", "py3",
                        "--abi-tag", "none", "--platform-tag", a.plat_tag, whl], check=True)
        (whl,) = glob.glob(os.path.join(tmp, "opngx-*.whl"))
        with zipfile.ZipFile(whl) as z:
            names = z.namelist()
            want = [f"opngx/_native/{os.path.basename(p)}" for p in (a.lib, a.engine)]
            missing = [w for w in want if w not in names]
            if missing:
                raise SystemExit(f"wheel is missing {missing}")
            staged = {f"opngx/_native/{os.path.basename(p)}" for p in (a.lib, a.engine, *a.extra)}
            staged.add("opngx/_native/README.txt")
            stray = [n for n in names if n.startswith("opngx/_native/") and n not in staged]
            if stray:
                raise SystemExit(f"wheel has unexpected native files {stray}")
            for w in want:
                if not w.endswith(".dll") and not w.endswith(".exe"):
                    mode = (z.getinfo(w).external_attr >> 16) & 0o777
                    if not mode & 0o100:
                        raise SystemExit(f"{w} lost its executable bit ({oct(mode)})")
            if not any(n.endswith("opngx/docs/ANALYSIS.md") for n in names):
                raise SystemExit("wheel is missing the bundled docs")
        out = shutil.move(whl, os.path.join(a.outdir, os.path.basename(whl)))
        print(out)
        return 0
    finally:
        clean()


if __name__ == "__main__":
    raise SystemExit(main())
