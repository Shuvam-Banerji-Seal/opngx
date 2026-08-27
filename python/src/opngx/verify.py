"""Pixel-exact directory verification (native engine preferred)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyReport:
    files_ref: int
    files_out: int
    files_compared: int
    bytes_compared: int
    mismatched_files: int
    set_equal: bool
    first_error: str = ""
    passed: bool = False

    def __str__(self) -> str:
        return (
            f"ref={self.files_ref} out={self.files_out} "
            f"compared={self.files_compared} mismatches={self.mismatched_files} "
            f"-> {'PASS' if self.passed else 'FAIL'}"
        )


def _engine_binary() -> str | None:
    """Locate the opngx-engine CLI for native-speed verification.

    Windows-aware: the packaged studio bundles opngx-engine.exe next to
    libopngx.dll (inside _MEIPASS for onefile builds), and the installed
    setup puts it on PATH — so check all of those, with and without .exe.
    """
    import sys

    from ._engine import library_path

    cands: list[Path] = []
    names = ("opngx-engine.exe", "opngx-engine")
    lp = library_path()
    if lp:
        here = Path(lp).parent
        cands += [here / n for n in names]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        cands += [Path(mei) / n for n in names]
    try:
        cands += [Path(sys.executable).resolve().parent / n for n in names]
    except Exception:
        pass
    env = Path(__file__).resolve().parents[3] / "build"
    cands += [env / n for n in names]
    for c in cands:
        if c.exists():
            return str(c)
    return shutil.which("opngx-engine")


def verify_against_bin(
    bin_path: str | Path,
    out_dir: str | Path,
    *,
    footage_path: str | Path | None = None,
    width: int = 0,
    height: int = 0,
    mode: str = "reference",
    brightness: float = 0.0,
    contrast: float = 0.0,
    gamma: float = 1.0,
    bit_depth: int = 8,
    channels: int = 6,
    prefix: str = "brow_",
    ext: str = ".Png",
    frames: int | None = None,
) -> VerifyReport:
    """ADD-7: verify an extract directory straight against its source .bin.

    Each output file's decoded pixels must equal the LUT-mapped frame at
    the absolute index encoded in its filename — no vendor reference set
    required. Reference mode auto-detects the sibling .footage sidecar.
    Requires the native engine binary.
    """
    engine = _engine_binary()
    if not engine:
        raise RuntimeError(
            "verify_against_bin needs the native opngx-engine binary; "
            "build it with: cmake -S . -B build && cmake --build build -j"
        )
    args = [
        engine,
        "verifybin",
        "--bin",
        str(bin_path),
        "--prefix",
        prefix,
        "--ext",
        ext,
        "-m",
        mode,
        "--brightness",
        str(brightness),
        "--contrast",
        str(contrast),
        "--gamma",
        str(gamma),
        "--bit-depth",
        str(bit_depth),
        "--channels",
        "gray" if channels == 0 else "rgba",
    ]
    fp = Path(footage_path) if footage_path else Path(bin_path).with_suffix(".footage")
    if fp.exists():
        args += ["--footage", str(fp)]
    else:
        args += ["--width", str(width), "--height", str(height)]
    if frames is not None:
        args += ["--frames", str(frames)]
    args.append(str(out_dir))
    args += ["--json"]

    proc = subprocess.run(args, capture_output=True, text=True)
    import json

    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RuntimeError(f"verifybin failed: {proc.stderr.strip() or proc.stdout}")
    return VerifyReport(
        files_ref=int(data["files_ref"]),
        files_out=int(data["files_out"]),
        files_compared=int(data["files_compared"]),
        bytes_compared=int(data["bytes_compared"]),
        mismatched_files=int(data["mismatched_files"]),
        set_equal=bool(data["set_equal"]),
        first_error=str(data.get("first_error", "")),
        passed=bool(data["passed"]),
    )


def verify(
    ref_dir: str | Path,
    out_dir: str | Path,
    *,
    prefix: str = "brow_",
    ext: str = ".Png",
    subset: bool = True,
) -> VerifyReport:
    """Compare extracted output against a reference directory.

    Pixel-exact proof via decoded-scanline comparison. Uses the native
    verifier when available; otherwise falls back to a numpy implementation.
    """
    engine = _engine_binary()
    if engine:
        args = [
            engine,
            "verify",
            str(ref_dir),
            str(out_dir),
            "--prefix",
            prefix,
            "--ext",
            ext,
        ]
        if subset:
            args.append("--subset")
        # ADD-5: structured report — no more scraping 'key: value' lines
        args.append("--json")
        proc = subprocess.run(args, capture_output=True, text=True)
        import json

        try:
            data = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            data = None
        if isinstance(data, dict) and "passed" in data:
            return VerifyReport(
                files_ref=int(data["files_ref"]),
                files_out=int(data["files_out"]),
                files_compared=int(data["files_compared"]),
                bytes_compared=int(data["bytes_compared"]),
                mismatched_files=int(data["mismatched_files"]),
                set_equal=bool(data["set_equal"]),
                first_error=str(data.get("first_error", "")),
                passed=bool(data["passed"]),
            )
        # stale engine without --json: fall back to line parsing
        rep = VerifyReport(0, 0, 0, 0, 0, False)
        for line in proc.stdout.splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "ref files":
                rep.files_ref = int(v)
            elif k == "out files":
                rep.files_out = int(v)
            elif k == "compared":
                rep.files_compared = int(v)
            elif k == "bytes equal":
                rep.bytes_compared = int(v)
            elif k == "mismatches":
                rep.mismatched_files = int(v)
            elif k == "first error":
                rep.first_error = v
            elif k == "RESULT":
                rep.passed = v.startswith("PASS")
        return rep

    # ---- python fallback ----
    import zlib
    import struct
    import numpy as np

    def names(d):
        p = Path(d)
        # Numeric sort by embedded frame index — handles 99999->100000
        # rollover where lexicographic would place 100000 before 99999.
        return sorted(
            (x.name for x in p.glob(f"{prefix}*{ext}") if x.stem[len(prefix) :].isdigit()),
            key=lambda n: int(n[len(prefix) : -len(ext)] if ext else n[len(prefix) :]),
        )

    rn, on = names(ref_dir), names(out_dir)
    set_equal = rn == on
    common = min(len(rn), len(on))
    mism = 0
    bytes_ok = 0
    first_err = ""

    def raw_pixels(path):
        d = Path(path).read_bytes()
        pos, idat, ihdr = 8, b"", None
        while pos + 12 <= len(d):
            ln = struct.unpack(">I", d[pos : pos + 4])[0]
            typ = d[pos + 4 : pos + 8]
            if typ == b"IHDR":
                ihdr = struct.unpack(">IIBBBBB", d[pos + 8 : pos + 21])
            elif typ == b"IDAT":
                idat += d[pos + 8 : pos + 8 + ln]
            pos += 12 + ln
            if typ == b"IEND":
                break
        if ihdr is None:
            raise ValueError(f"no IHDR in {path}")
        w, h, bd, ct = ihdr[0], ihdr[1], ihdr[2], ihdr[3]
        bpp = 8 if bd == 16 else 4
        raw = zlib.decompress(idat)
        stride = w * bpp + 1
        px = np.frombuffer(bytearray(raw), dtype=np.uint8).reshape(h, stride)
        # unfilter (supports all PNG filters; ours and vendor's are simple)
        out = np.zeros((h, w * bpp), dtype=np.int32)
        prev = np.zeros(w * bpp, dtype=np.int32)
        fbpp = bpp
        for y in range(h):
            ftype = px[y, 0]
            row = px[y, 1:].astype(np.int32)
            if ftype == 1:
                for i in range(fbpp, w * bpp):
                    row[i] = (row[i] + row[i - fbpp]) & 0xFF
            elif ftype == 2:
                row = (row + prev) & 0xFF
            elif ftype == 3:
                left = np.concatenate([np.zeros(fbpp, dtype=np.int32), row[:-fbpp]])
                row = (row + ((left + prev) >> 1)) & 0xFF
            elif ftype == 4:
                left = np.concatenate([np.zeros(fbpp, dtype=np.int32), row[:-fbpp]])
                cprev = np.concatenate([np.zeros(fbpp, dtype=np.int32), prev[:-fbpp]])
                pp = left.astype(np.int32) + prev - cprev
                pa = np.abs(pp - left)
                pb = np.abs(pp - prev)
                pc = np.abs(pp - cprev)
                pred = np.where(
                    (pa <= pb) & (pa <= pc), left, np.where(pb <= pc, prev, cprev)
                )
                row = (row + pred) & 0xFF
            out[y] = row
            prev = row
        return out

    from .quality import QualityMode  # noqa: F401  (keep import graph stable)

    for name_r in rn[:common]:
        pr = Path(ref_dir) / name_r
        po = Path(out_dir) / name_r
        try:
            a = raw_pixels(pr)
            b = raw_pixels(po)
        except Exception as exc:
            mism += 1
            if not first_err:
                first_err = str(exc)
            continue
        if a.shape != b.shape or not np.array_equal(a, b):
            mism += 1
        else:
            bytes_ok += a.size
    names_ok = set_equal or (subset and len(on) <= len(rn))
    return VerifyReport(
        len(rn),
        len(on),
        common,
        bytes_ok,
        mism,
        set_equal,
        first_err,
        passed=(mism == 0 and common > 0 and names_ok),
    )
