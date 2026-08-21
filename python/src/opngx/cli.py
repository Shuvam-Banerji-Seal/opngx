"""opngx command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import opngx


def _add_engine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--footage", help="path to .footage sidecar (default: auto)")
    p.add_argument("-o", "--out", required=True, help="output directory")
    p.add_argument(
        "-m",
        "--mode",
        choices=["reference", "raw", "custom"],
        default="reference",
        help="quality mode (default: reference)",
    )
    p.add_argument("--brightness", type=float, default=None)
    p.add_argument("--contrast", type=float, default=None)
    p.add_argument("--gamma", type=float, default=None)
    p.add_argument("--bit-depth", type=int, default=8, choices=(8, 16))
    p.add_argument("--prefix", default="brow_", help="filename prefix")
    p.add_argument("--ext", default=".Png", help='extension (default ".Png")')
    p.add_argument(
        "-j", "--jobs", type=int, default=0, help="worker threads (0 = all cores)"
    )
    p.add_argument("-l", "--level", type=int, default=6, help="deflate level")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--frames", type=int, default=None)
    p.add_argument(
        "--timestamps", action="store_true", help="export per-frame timestamp CSV"
    )
    p.add_argument("--metadata", action="store_true", help="export metadata.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="opngx",
        description=f"opngx {opngx.__version__} — Optronis .bin → PNG extractor",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    px = sub.add_parser("extract", help="extract PNGs from a .bin")
    px.add_argument("bin", help="input .bin file")
    _add_engine_args(px)

    pb = sub.add_parser("batch", help="extract every .bin under a directory tree")
    pb.add_argument("in_dir")
    _add_engine_args(pb)

    pv = sub.add_parser("verify", help="pixel-exact verify out vs reference dir")
    pv.add_argument("ref_dir")
    pv.add_argument("out_dir")
    pv.add_argument("--prefix", default="brow_")
    pv.add_argument("--ext", default=".Png")
    pv.add_argument("--subset", action="store_true", default=True,
                    help="out may be a subset of ref (default on)")
    pv.add_argument("--full-set", dest="subset", action="store_false",
                    help="require identical name sets")

    pi = sub.add_parser("info", help="show metadata + machine capabilities")
    pi.add_argument("bin", nargs="?")

    args = ap.parse_args(argv)

    if args.cmd == "info":
        print(f"opngx {opngx.__version__} | engine: {opngx.engine_backend()}")
        from opngx._engine import detect_gpus

        gpus = detect_gpus()
        print(f"cpus: {__import__('os').cpu_count()}")
        print("gpus:\n  " + ("\n  ".join(gpus) if gpus else "none detected"))
        if args.bin:
            m = opngx.probe(
                args.bin, args.footage if hasattr(args, "footage") else None
            )
            for k in (
                "camera_name",
                "width",
                "height",
                "num_images",
                "framerate",
                "exposure_us",
                "capacity_frames",
                "frame_stride",
                "verified_operating_point",
            ):
                print(f"{k}: {getattr(m, k)}")
        return 0

    if args.cmd == "verify":
        rep = opngx.verify(args.ref_dir, args.out_dir, prefix=args.prefix, ext=args.ext)
        print(rep)
        return 0 if rep.passed else 1

    def run_one(bin_path: str, out: str):
        ex = opngx.Extractor(bin_path, getattr(args, "footage", None))

        def progress(done, total):
            pct = 100.0 * done / max(total, 1)
            sys.stderr.write(f"\ropngx: {done}/{total} ({pct:5.1f}%)")
            if done >= total:
                sys.stderr.write("\n")

        st = ex.extract(
            out,
            mode=args.mode,
            brightness=args.brightness,
            contrast=args.contrast,
            gamma=args.gamma,
            bit_depth=args.bit_depth,
            jobs=args.jobs,
            level=args.level,
            prefix=args.prefix,
            ext=args.ext,
            start=args.start,
            frames=args.frames,
            export_timestamps=args.timestamps,
            export_metadata=args.metadata,
            progress=progress,
        )
        print(f"opngx: {st}")
        return 0

    try:
        if args.cmd == "extract":
            return run_one(args.bin, args.out)
        # batch
        bins = sorted(Path(args.in_dir).glob("*/*.bin")) + sorted(
            Path(args.in_dir).glob("*.bin")
        )
        rc = 0
        for b in bins:
            stem = b.stem
            outdir = Path(args.out) / stem.replace(".", "_")
            print(f"opngx: batch {b} -> {outdir}")
            rc |= run_one(str(b), str(outdir))
        return rc
    except Exception as exc:
        print(f"opngx: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
