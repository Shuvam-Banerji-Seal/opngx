"""opngx command-line interface."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import opngx

# default extension per container, matching the C engine and the studio
_DEFAULT_EXT = {"png": ".Png", "jpg": ".jpg", "bmp": ".bmp", "tif": ".tif"}


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
    p.add_argument(
        "--sidecar-transform",
        action="store_true",
        help="in reference mode take B/C/G from the .footage instead of the "
        "values above (cycle 22)",
    )
    p.add_argument("--bit-depth", type=int, default=8, choices=(8, 16))
    p.add_argument(
        "--channels",
        choices=["rgba", "gray"],
        default="rgba",
        help="rgba (vendor-like) or gray (faster, ~2.5x, identical pixels)",
    )
    p.add_argument(
        "-F",
        "--format",
        choices=["png", "jpg", "bmp", "tif"],
        default="png",
        help="output container (default: png)",
    )
    p.add_argument("-q", "--jpeg-quality", type=int, default=90)
    p.add_argument(
        "--crop",
        default=None,
        metavar="X,Y,W,H",
        help="region of interest; W/H of 0 mean 'to the frame edge'",
    )
    p.add_argument("--prefix", default="brow_", help="filename prefix")
    p.add_argument(
        "--ext", default=None, help="output extension (default: follows --format)"
    )
    p.add_argument(
        "-j", "--jobs", type=int, default=0, help="worker threads (0 = all cores)"
    )
    p.add_argument("-l", "--level", type=int, default=1, help="deflate level 1-12 (1 = fastest, files ~1.5%% larger than 6)")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--frames", type=int, default=None)
    p.add_argument(
        "--timestamps", action="store_true", help="export per-frame timestamp CSV"
    )
    p.add_argument("--metadata", action="store_true", help="export metadata.json")


def main(argv: list[str] | None = None) -> int:
    # Windows: real consoles are UTF-8 (PEP 528) but REDIRECTED output
    # uses the locale codepage -> UnicodeEncodeError on →/µ. Never crash
    # on printing progress.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    if os.name == "nt":  # frozen fallback pools spawn-reimport __main__
        import multiprocessing

        multiprocessing.freeze_support()

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
    pb.add_argument(
        "--layout",
        choices=["flat", "format"],
        default="format",
        help="format = <out>/<recording>/<FMT>/ tree (default), flat = legacy "
        "<out>/<recording>/",
    )

    pv = sub.add_parser("verify", help="pixel-exact verify out vs reference dir")
    pv.add_argument("ref_dir")
    pv.add_argument("out_dir")
    pv.add_argument("--prefix", default="brow_")
    pv.add_argument("--ext", default=".Png")
    pv.add_argument(
        "--subset",
        action="store_true",
        default=True,
        help="out may be a subset of ref (default on)",
    )
    pv.add_argument(
        "--full-set",
        dest="subset",
        action="store_false",
        help="require identical name sets",
    )

    pv2 = sub.add_parser("video", help="render an MP4 straight from a .bin")
    pv2.add_argument("bin")
    pv2.add_argument("-o", "--out", required=True)
    pv2.add_argument("--fps", type=int, default=30)
    pv2.add_argument("--crf", type=int, default=18)
    pv2.add_argument("--start", type=int, default=0)
    pv2.add_argument("--frames", type=int, default=None)
    pv2.add_argument("--footage", default=None)
    pv2.add_argument(
        "-m", "--mode", choices=["reference", "raw", "custom"], default="reference"
    )
    # cycle 23: `video` could not take a curve or a crop at all, and
    # --footage was parsed and then ignored
    pv2.add_argument("--brightness", type=float, default=None)
    pv2.add_argument("--contrast", type=float, default=None)
    pv2.add_argument("--gamma", type=float, default=None)
    pv2.add_argument("--crop", default=None, metavar="X,Y,W,H")

    # v1.10: analysis modules (motion tracking, luminosity, contrast, yours)
    pa = sub.add_parser(
        "analyze",
        help="run analysis modules (e.g. motion tracking) and write data files",
    )
    pa.add_argument("source", help="a .bin, or a batch mother folder with --batch")
    pa.add_argument(
        "-m", "--module", action="append", required=True, dest="modules",
        help="module name (repeatable); see `opngx modules`",
    )
    pa.add_argument(
        "-o", "--out", required=True,
        help="output file (.csv/.json/.npz/.tsv) for ONE module on ONE recording, "
        "otherwise a folder: <out>/<recording>/ANALYSIS/<module>.<fmt>",
    )
    pa.add_argument("--format", choices=["csv", "json", "npz", "tsv"], default="csv")
    pa.add_argument(
        "-p", "--param", action="append", default=[], metavar="[MODULE.]KEY=VALUE",
        help="module parameter; the module prefix may be omitted with one module",
    )
    pa.add_argument("--footage", default=None)
    pa.add_argument("--start", type=int, default=0)
    pa.add_argument("--frames", type=int, default=None)
    pa.add_argument("--stride", type=int, default=1, help="analyse every Nth frame")
    pa.add_argument("--crop", default=None, metavar="X,Y,W,H")
    pa.add_argument(
        "--source", dest="pixels", choices=["raw", "display"], default="raw",
        help="raw sensor bytes (default) or the display curve (-M/B/C/G)",
    )
    pa.add_argument("-M", "--mode", choices=["reference", "raw", "custom"], default="reference")
    pa.add_argument("--brightness", type=float, default=None)
    pa.add_argument("--contrast", type=float, default=None)
    pa.add_argument("--gamma", type=float, default=None)
    pa.add_argument("--batch", action="store_true", help="SOURCE is a mother folder")
    pa.add_argument("-j", "--jobs", type=int, default=0)
    pa.add_argument("--json-summary", action="store_true", help="print summaries as JSON")

    pm = sub.add_parser("modules", help="list / inspect / create / validate analysis modules")
    pm.add_argument(
        "action", nargs="?", default="list",
        choices=["list", "show", "template", "validate", "dir"],
    )
    pm.add_argument("target", nargs="?", help="module name (show), file (validate), or new name (template)")
    pm.add_argument("-o", "--out", default=None, help="template: write here (default: modules folder)")
    pm.add_argument("--json", action="store_true")

    pi = sub.add_parser("info", help="show metadata + machine capabilities")
    pi.add_argument("bin", nargs="?")

    pt = sub.add_parser(
        "timestamps",
        help="analyse per-frame camera-clock headers (gaps, drops, real fps)",
    )
    pt.add_argument("bin")
    pt.add_argument("--footage", default=None)
    pt.add_argument("--start", type=int, default=0)
    pt.add_argument("--frames", type=int, default=None)
    pt.add_argument("--csv", default=None, help="write per-frame deltas CSV")
    pt.add_argument("--json", action="store_true")

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
            extras = getattr(m, "extra", {}) or {}
            for k in (
                "FramerateReal",
                "Serial",
                "Model",
                "Speed",
                "TriggerROIRight",
                "TriggerROIBottom",
                "TriggeredBySoftware",
            ):
                if k in extras:
                    print(f"{k}: {extras[k]}")
            if m.frames_match is not None:
                print(
                    f"frames xml vs file: {m.num_images} vs "
                    f"{m.capacity_frames} "
                    f"({'match' if m.frames_match else 'MISMATCH'})"
                )
            if m.span_s:
                print(
                    f"clock span: {m.span_s:,.3f} s "
                    f"(us ticks) -> effective {m.effective_fps_us:,.2f} fps"
                )
            if extras:
                others = [
                    k
                    for k in extras
                    if k
                    not in (
                        "FramerateReal",
                        "Serial",
                        "Model",
                        "Speed",
                        "TriggerROIRight",
                        "TriggerROIBottom",
                        "TriggeredBySoftware",
                    )
                ]
                if others:
                    print(
                        f"extra_tags: {len(others)} more "
                        f"(metadata.json / probe().extra)"
                    )
        return 0

    if args.cmd == "timestamps":
        from opngx.timing import analyze_timestamps

        m = opngx.probe(args.bin, args.footage)
        rep = analyze_timestamps(args.bin, m, start=args.start, count=args.frames)
        if args.csv:
            import csv as _csv

            from opngx.footage import read_timestamps

            n = (
                args.frames
                if args.frames is not None
                else max(0, m.capacity_frames - args.start)
            )
            ts = read_timestamps(args.bin, m, start=args.start, count=n)
            with open(args.csv, "w", newline="", encoding="utf-8") as fh:
                w = _csv.writer(fh)
                w.writerow(["frame_index", "timestamp_raw", "delta_ticks"])
                prev = None
                for i, t in enumerate(ts):
                    d = "" if prev is None else int(t) - prev
                    w.writerow([args.start + i, int(t), d])
                    prev = int(t)
            print(f"opngx: deltas written to {args.csv}")
        if args.json:
            import json

            print(json.dumps(rep, indent=2))
        else:
            tick = rep.get("tick_period_s")
            unit = f" (~{tick * 1e6:.3f} µs/tick)" if tick else ""
            print(
                f"frames analysed : {rep['frames']:,} "
                f"(from index {rep['start_index']:,})"
            )
            print(
                f"tick range      : {rep['first_tick']:,} … {rep['last_tick']:,}{unit}"
            )
            span = rep.get("span_s")
            print(
                f"span            : {span:.3f}s"
                if span
                else f"span            : {rep['span_ticks']:,.0f} ticks"
            )
            eff = rep.get("effective_fps")
            print(
                f"effective fps   : {eff:.3f}"
                if eff
                else "effective fps   : n/a (no nominal framerate)"
            )
            print(
                f"delta min/med/max: {rep['delta_min']} / "
                f"{rep['delta_median']:.0f} / {rep['delta_max']} ticks"
            )
            print(f"gaps >1.5×median: {rep['gaps_gt_1p5x_median']}")
            print(
                f"non-monotonic   : {rep['non_monotonic']} "
                f"({'monotonic ✓' if rep['monotonic'] else 'CLOCK WENT BACKWARDS'})"
            )
            if rep["gap_examples"]:
                print("first gaps:")
                for g in rep["gap_examples"][:10]:
                    print(f"  after frame {g['frame']:,}: {g['delta_ticks']} ticks")
        return 0

    def _parse_crop(spec):
        if not spec:
            return None
        parts = spec.replace(" ", "").split(",")
        if len(parts) != 4:
            raise SystemExit(f"opngx: --crop needs X,Y,W,H (got {spec!r})")
        try:
            x, y, w, h = (int(v) for v in parts)
        except ValueError:
            raise SystemExit(f"opngx: --crop needs integers (got {spec!r})")
        return (x, y, w, h)

    if args.cmd == "modules":
        return _cmd_modules(args)
    if args.cmd == "analyze":
        return _cmd_analyze(args)

    if args.cmd == "video":
        st = opngx.render_video(
            args.bin,
            args.out,
            mode=args.mode,
            brightness=args.brightness,
            contrast=args.contrast,
            gamma=args.gamma,
            crop=_parse_crop(args.crop),
            footage=args.footage,
            start=args.start,
            count=args.frames,
            fps=args.fps,
            crf=args.crf,
        )
        print(
            f"opngx: wrote {st['frames_written']:,} frames → {st['output']} "
            f"in {st['seconds']:.1f}s"
        )
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

        fmt = getattr(args, "format", "png")
        ext = args.ext if args.ext else _DEFAULT_EXT[fmt]
        st = ex.extract(
            out,
            mode=args.mode,
            fmt=fmt,
            brightness=args.brightness,
            contrast=args.contrast,
            gamma=args.gamma,
            bit_depth=args.bit_depth,
            channels=0 if args.channels == "gray" else 6,
            jpeg_quality=args.jpeg_quality,
            crop=_parse_crop(getattr(args, "crop", None)),
            jobs=args.jobs,
            level=args.level,
            prefix=args.prefix,
            ext=ext,
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
        # batch — walk the tree the same way the studio does: one level of
        # nesting (vendor <root>/<recording>/<name>.bin) plus any loose .bin
        from opngx.layout import batch_out_dir, recording_key, safe_name

        bins = sorted(Path(args.in_dir).glob("*/*.bin")) + sorted(
            Path(args.in_dir).glob("*.bin")
        )
        if not bins:
            print(f"opngx: no .bin files found under {args.in_dir}", file=sys.stderr)
            return 1
        # never let two recordings land in one output folder (cycle 22)
        seen: dict[str, str] = {}
        for b in bins:
            key = recording_key(str(args.in_dir), str(b))
            if key in seen and seen[key] != str(b):
                print(
                    f"opngx: error: '{key}' would receive both {seen[key]} and "
                    f"{b}; rename the recording folders so they stay distinct",
                    file=sys.stderr,
                )
                return 1
            seen[key] = str(b)
        rc = 0
        for b in bins:
            if args.layout == "format":
                outdir = batch_out_dir(
                    str(args.out), str(args.in_dir), str(b), args.format
                )
            else:
                outdir = str(Path(args.out) / recording_key(str(args.in_dir), str(b)))
            print(f"opngx: batch {b} -> {outdir}")
            rc |= run_one(str(b), str(outdir))
        return rc
    except Exception as exc:
        print(f"opngx: error: {exc}", file=sys.stderr)
        return 1


# ------------------------------------------------------------ analysis (v1.10)
def _cmd_modules(args) -> int:
    import json

    import opngx.analysis as oa

    if args.action == "dir":
        print(oa.user_modules_dir(create=True))
        return 0
    if args.action == "template":
        name = (args.target or "my_module").strip()
        path = args.out or os.path.join(oa.user_modules_dir(create=True), f"{name}.py")
        if os.path.exists(path):
            print(f"opngx: {path} exists; not overwriting", file=sys.stderr)
            return 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(oa.template(name, name.replace("_", " ").capitalize()))
        print(path)
        return 0
    if args.action == "validate":
        if not args.target:
            print("opngx: modules validate FILE.py", file=sys.stderr)
            return 2
        v = oa.validate_file(args.target)
        print("\n".join(v.messages))
        return 0 if v.ok else 1
    infos = oa.discover()
    if args.action == "show":
        for i in infos:
            if i.name == args.target:
                if not i.ok:
                    print(f"{i.name}: BROKEN ({i.path})\n{i.error}")
                    return 1
                c = i.cls
                print(f"{c.name}  v{c.version}  [{i.origin}]  {i.path}")
                print(f"  {c.title}\n  {c.description}")
                print("  parameters:")
                for p_ in c.params:
                    extra = f" one of {list(p_.choices)}" if p_.choices else ""
                    print(f"    {p_.key} ({p_.type.__name__}, default {p_.default!r}){extra} — {p_.help}")
                print("  columns: frame, timestamp_raw, time_s, " + ", ".join(
                    f"{c_.key}[{c_.unit}]" if c_.unit else c_.key for c_ in c.columns))
                return 0
        print(f"opngx: no module '{args.target}'", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([
            {"name": i.name, "origin": i.origin, "path": i.path, "ok": i.ok,
             "title": i.title, "error": i.error} for i in infos], indent=1))
        return 0
    print(f"analysis modules (user folder: {oa.user_modules_dir()})")
    for i in infos:
        state = "" if i.ok else f"  BROKEN: {i.error.strip().splitlines()[-1][:90]}"
        print(f"  {i.name:22s} {i.origin:8s} {i.title}{state}")
    return 0


def _parse_params(items, modules):
    out: dict = {m: {} for m in modules}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"opngx: --param needs KEY=VALUE (got {it!r})")
        key, val = it.split("=", 1)
        if "." in key:
            mod, key = key.split(".", 1)
        elif len(modules) == 1:
            mod = modules[0]
        else:
            raise SystemExit(f"opngx: with several modules write MODULE.{key}={val}")
        if mod not in out:
            raise SystemExit(f"opngx: --param for '{mod}', which is not being run")
        out[mod][key] = val
    return {m: p for m, p in out.items() if p}


def _cmd_analyze(args) -> int:
    import json

    import opngx.analysis as oa
    from opngx.layout import recording_key, safe_name

    def crop_of(spec):
        if not spec:
            return None
        parts = spec.replace(" ", "").split(",")
        if len(parts) != 4:
            raise SystemExit(f"opngx: --crop needs X,Y,W,H (got {spec!r})")
        return tuple(int(v) for v in parts)

    params = _parse_params(args.param, args.modules)
    if args.batch:
        root = Path(args.source)
        bins = sorted(root.glob("*/*.bin")) + sorted(root.glob("*.bin"))
        if not bins:
            print(f"opngx: no .bin files found under {root}", file=sys.stderr)
            return 1
    else:
        bins = [Path(args.source)]
    single_file = (not args.batch and len(args.modules) == 1
                   and os.path.splitext(args.out)[1].lower() in (".csv", ".json", ".npz", ".tsv"))
    rc = 0
    for b in bins:
        def prog(d, t_):
            sys.stderr.write(f"\ropngx: {b.name}: {d:,}/{t_:,} frames ({100 * d / max(t_, 1):5.1f}%)")
            if d >= t_:
                sys.stderr.write("\n")

        try:
            run = oa.analyze(
                str(b), args.modules, params=params, footage=args.footage if not args.batch else None,
                start=args.start, count=args.frames, stride=args.stride, crop=crop_of(args.crop),
                source=args.pixels,
                transform=dict(mode=args.mode, brightness=args.brightness,
                               contrast=args.contrast, gamma=args.gamma),
                jobs=args.jobs, progress=prog, log=lambda s: print(f"opngx: {s}", file=sys.stderr),
            )
        except (ValueError, KeyError) as exc:
            print(f"opngx: {b}: {exc}", file=sys.stderr)
            rc = 1
            continue
        for name, err in run.errors.items():
            print(f"opngx: {b.name}: {err}\n{err.tb}", file=sys.stderr)
            rc = 1
        for name, res in run.results.items():
            if single_file:
                path = args.out
            else:
                key = recording_key(str(args.source), str(b)) if args.batch else safe_name(b.stem)
                path = os.path.join(args.out, key, "ANALYSIS", f"{name}.{args.format}")
            res.save(path)
            print(f"opngx: {res.describe()} -> {path}  ({run.frames / max(run.seconds, 1e-9):,.0f} frames/s)")
            if args.json_summary:
                print(json.dumps({"recording": str(b), "module": name, "summary": res.metadata()["summary"]}))
            else:
                for k, v in res.summary.items():
                    if isinstance(v, float):
                        v = f"{v:.6g}"
                    print(f"    {k}: {v}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
