"""Run analysis modules over a recording (v1.10).

One pass over the frames feeds every requested module: each batch is read
once from the memory-mapped .bin (cropped, optionally put through the
display curve) and handed to all of them. Parallel-safe modules process
batches on a thread pool (numpy releases the GIL in its kernels);
`parallel = False` modules get the batches strictly in order.
"""

from __future__ import annotations

import os
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, Union

import numpy as np

from .base import Context, Module
from .result import RESERVED, AnalysisResult

ModuleRef = Union[str, type, Module]


class ModuleError(RuntimeError):
    """A module raised, or returned something the runner cannot use."""

    def __init__(self, module: str, message: str, tb: str = "") -> None:
        super().__init__(f"module '{module}': {message}")
        self.module = module
        self.tb = tb


@dataclass
class AnalysisRun:
    """Everything one run produced."""

    results: dict[str, AnalysisResult] = field(default_factory=dict)
    errors: dict[str, ModuleError] = field(default_factory=dict)
    frames: int = 0
    seconds: float = 0.0
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors and not self.cancelled

    def __getitem__(self, name: str) -> AnalysisResult:
        return self.results[name]


def _instantiate(ref: ModuleRef) -> Module:
    if isinstance(ref, Module):
        return ref
    if isinstance(ref, type) and issubclass(ref, Module):
        return ref()
    from .registry import get_module

    return get_module(str(ref))()


def _coerce_output(name: str, out: Any, k: int) -> dict[str, np.ndarray]:
    if not isinstance(out, dict):
        raise ModuleError(name, f"process() must return a dict of arrays, got {type(out).__name__}")
    cols: dict[str, np.ndarray] = {}
    for key, v in out.items():
        if not isinstance(key, str) or not key:
            raise ModuleError(name, f"column names must be non-empty strings, got {key!r}")
        if key in RESERVED:
            raise ModuleError(name, f"column '{key}' is reserved (added by the runner)")
        a = np.asarray(v)
        if a.ndim == 0:
            a = np.full(k, a)
        if a.ndim != 1 or len(a) != k:
            raise ModuleError(
                name,
                f"column '{key}' has shape {a.shape}; expected ({k},) — one value per frame",
            )
        if a.dtype.kind not in "biuf":
            raise ModuleError(name, f"column '{key}' must be numeric, got dtype {a.dtype}")
        cols[key] = a
    return cols


def analyze(
    bin_path: str,
    modules: Sequence[ModuleRef] | ModuleRef,
    *,
    params: Optional[dict[str, dict[str, Any]]] = None,
    footage: Optional[str] = None,
    meta: Any = None,
    start: int = 0,
    count: Optional[int] = None,
    stride: int = 1,
    crop: Optional[tuple[int, int, int, int]] = None,
    source: str = "raw",
    transform: Optional[dict[str, Any]] = None,
    batch: int = 256,
    jobs: int = 0,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
    raise_errors: bool = False,
) -> AnalysisRun:
    """Run `modules` over frames start, start+stride, … of a recording.

    `params` maps module name → {param: value}. `source="raw"` analyses the
    sensor bytes (the right choice for measurement); `"display"` applies
    the quality curve in `transform` (mode/brightness/contrast/gamma, same
    meaning as extraction). `crop` restricts analysis to a region; reported
    positions are always FULL-FRAME pixel coordinates.
    """
    from opngx.extractor import normalize_crop
    from opngx.footage import probe
    from opngx.quality import build_lut
    from opngx.video import resolve_transform

    t0 = time.perf_counter()
    log = log or (lambda _m: None)
    if meta is None:
        meta = probe(bin_path, footage)
    W, H = int(meta.width), int(meta.height)
    if not W or not H or not meta.capacity_frames:
        raise ValueError("unknown geometry or empty recording; a .footage sidecar is required")
    stride = max(1, int(stride))
    start = max(0, int(start))
    if start >= meta.capacity_frames:
        raise ValueError(f"start {start} is past the last frame ({meta.capacity_frames - 1})")
    avail = (meta.capacity_frames - start + stride - 1) // stride
    n = avail if count is None else max(0, min(int(count), avail))
    if n == 0:
        raise ValueError("empty frame range")
    cx, cy, cw, ch = normalize_crop(crop, W, H)
    idx_all = start + stride * np.arange(n, dtype=np.int64)

    insts = [_instantiate(m) for m in (modules if isinstance(modules, (list, tuple)) else [modules])]
    names = [type(m).name or type(m).__name__ for m in insts]
    if len(set(names)) != len(names):
        raise ValueError(f"a module was requested twice: {names}")
    params = params or {}
    unknown = sorted(set(params) - set(names))
    if unknown:
        raise ValueError(f"parameters given for modules that are not being run: {unknown}")

    lut = None
    if source == "display":
        xf = dict(transform or {})
        b, c, g = resolve_transform(
            meta, xf.get("mode", "reference"), xf.get("brightness"), xf.get("contrast"), xf.get("gamma")
        )
        lut = np.asarray(build_lut(b, c, g), dtype=np.uint8)
    elif source != "raw":
        raise ValueError(f"source must be 'raw' or 'display', got {source!r}")

    mm = np.memmap(
        meta.bin_path, dtype=np.uint8, mode="r", shape=(meta.capacity_frames, meta.frame_stride)
    )
    ts_all = np.ascontiguousarray(mm[idx_all, :8]).view("<u8").reshape(-1).astype(np.uint64)

    def frames_for(idx: np.ndarray) -> np.ndarray:
        px = mm[idx, 8 : 8 + W * H].reshape(-1, H, W)
        win = np.ascontiguousarray(px[:, cy : cy + ch, cx : cx + cw])
        return np.take(lut, win) if lut is not None else win

    def sampler(k: int) -> np.ndarray:
        k = max(1, min(int(k), n))
        pick = idx_all[np.linspace(0, n - 1, k).round().astype(np.int64)]
        return frames_for(pick)

    run = AnalysisRun(frames=n)
    ctxs: dict[str, Context] = {}
    live: list[Module] = []
    for m, name in zip(insts, names):
        try:
            p = type(m).resolve_params(params.get(name))
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        ctx = Context(
            meta=meta,
            params=p,
            width=cw,
            height=ch,
            crop=(cx, cy, cw, ch),
            source=source,
            _sampler=sampler,
            log=log,
        )
        try:
            m.begin(ctx)
        except Exception as exc:  # noqa: BLE001
            err = ModuleError(name, f"begin() failed: {exc}", traceback.format_exc())
            if raise_errors:
                raise err from exc
            run.errors[name] = err
            log(str(err))
            continue
        ctxs[name] = ctx
        live.append(m)

    par = [m for m in live if getattr(m, "parallel", True)]
    seq = [m for m in live if not getattr(m, "parallel", True)]
    parts: dict[str, list[dict[str, np.ndarray]]] = {type(m).name: [] for m in live}
    chunks = [(s, min(s + batch, n)) for s in range(0, n, max(1, int(batch)))]
    jobs = jobs or os.cpu_count() or 1

    def call(m: Module, frames: np.ndarray, sl: slice) -> dict[str, np.ndarray]:
        name = type(m).name
        base = ctxs[name]
        # a shallow per-batch view of the context: parallel batches must
        # not see each other's frame_index
        ctx = Context(**{**base.__dict__, "frame_index": idx_all[sl], "timestamp_raw": ts_all[sl]})
        ctx.summary = base.summary
        ctx.state = base.state
        return _coerce_output(name, m.process(frames, ctx), len(frames))

    def work(ci: int):
        s, e = chunks[ci]
        if should_cancel is not None and should_cancel():
            return ci, None, {}
        fr = frames_for(idx_all[s:e])
        out: dict[str, Any] = {}
        for m in par:
            name = type(m).name
            if name in run.errors:
                continue
            try:
                out[name] = call(m, fr, slice(s, e))
            except ModuleError as exc:
                out[name] = exc
            except Exception as exc:  # noqa: BLE001
                out[name] = ModuleError(name, f"process() failed: {exc}", traceback.format_exc())
        return ci, (fr if seq else None), out

    done = 0
    inflight: deque = deque()
    nxt = 0
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        while nxt < len(chunks) and len(inflight) < max(2, jobs * 2):
            inflight.append(ex.submit(work, nxt))
            nxt += 1
        while inflight:
            ci, fr, out = inflight.popleft().result()
            if nxt < len(chunks):
                inflight.append(ex.submit(work, nxt))
                nxt += 1
            if fr is None and out == {} and should_cancel is not None and should_cancel():
                run.cancelled = True
                break
            s, e = chunks[ci]
            for name, res in out.items():
                if isinstance(res, ModuleError):
                    if raise_errors:
                        raise res
                    if name not in run.errors:
                        run.errors[name] = res
                        log(str(res))
                else:
                    parts[name].append(res)
            for m in seq:
                name = type(m).name
                if name in run.errors:
                    continue
                try:
                    parts[name].append(call(m, fr, slice(s, e)))
                except ModuleError as exc:
                    if raise_errors:
                        raise
                    run.errors[name] = exc
                    log(str(exc))
                except Exception as exc:  # noqa: BLE001
                    err = ModuleError(name, f"process() failed: {exc}", traceback.format_exc())
                    if raise_errors:
                        raise err from exc
                    run.errors[name] = err
                    log(str(err))
            done += e - s
            if progress is not None:
                progress(done, n)
            if should_cancel is not None and should_cancel():
                run.cancelled = True
                for f_ in inflight:
                    f_.cancel()
                break

    # batches are consumed strictly in order, so `done` frames form one
    # contiguous prefix even after a cancel
    rows = min(done, n)
    idx = idx_all[:rows]
    ts = ts_all[:rows]
    t_s, time_source = _time_axis(ts, idx, meta)

    for m in live:
        name = type(m).name
        if name in run.errors:
            continue
        cls = type(m)
        got = parts[name]
        keys = list(got[0]) if got else [c.key for c in cls.columns]
        try:
            cols = {k: np.concatenate([g[k] for g in got]) if got else np.zeros(0) for k in keys}
        except KeyError as exc:
            run.errors[name] = ModuleError(name, f"column {exc} missing from some batches")
            continue
        table: dict[str, np.ndarray] = {"frame": idx.copy(), "timestamp_raw": ts.copy(), "time_s": t_s.copy()}
        table.update({k: v[:rows] for k, v in cols.items()})
        ctx = ctxs[name]
        ctx.frame_index, ctx.timestamp_raw = idx, ts
        try:
            new = m.finish(table, ctx)
            if new is not None:
                table = dict(new)
        except Exception as exc:  # noqa: BLE001
            err = ModuleError(name, f"finish() failed: {exc}", traceback.format_exc())
            if raise_errors:
                raise err from exc
            run.errors[name] = err
            log(str(err))
            continue
        units = {"frame": "", "timestamp_raw": "tick", "time_s": "s"}
        helps = {
            "frame": "absolute frame index in the recording",
            "timestamp_raw": "camera clock from the frame header",
            "time_s": f"seconds since the first analysed frame ({time_source})",
        }
        for c in cls.columns:
            units[c.key] = c.unit
            helps[c.key] = c.help
        run.results[name] = AnalysisResult(
            module=name,
            module_title=cls.title or name,
            module_version=str(cls.version),
            columns=table,
            units={k: units.get(k, "") for k in table},
            help={k: helps.get(k, "") for k in table},
            params=dict(ctx.params),
            summary=dict(ctx.summary),
            recording={
                "bin_path": str(meta.bin_path),
                "footage_path": str(meta.footage_path or ""),
                "camera": meta.camera_name,
                "width": W,
                "height": H,
                "frames_in_recording": int(meta.capacity_frames),
                "framerate": float(meta.framerate),
            },
            run={
                "start": start,
                "stride": stride,
                "frames_analysed": rows,
                "crop": [cx, cy, cw, ch],
                "source": source,
                "transform": dict(transform or {}) if source == "display" else None,
                "time_source": time_source,
                "cancelled": run.cancelled,
            },
            overlay=dict(getattr(cls, "overlay", {}) or {}),
            plot=tuple(getattr(cls, "plot", ()) or ()),
            trajectory=bool(getattr(cls, "trajectory", False)),
        )
    run.frames = rows
    run.seconds = time.perf_counter() - t0
    return run


def _time_axis(ts: np.ndarray, idx: np.ndarray, meta) -> tuple[np.ndarray, str]:
    """Seconds since the first analysed frame. The frame-header clock (µs
    ticks at the verified operating point) is used when it is monotonic;
    otherwise the nominal frame rate."""
    if len(ts) >= 2 and ts[0] > 0 and np.all(np.diff(ts.astype(np.int64)) > 0):
        return (ts - ts[0]).astype(np.float64) * 1e-6, "frame-header clock, µs ticks"
    if len(ts) == 1 and ts[0] > 0:
        return np.zeros(1), "frame-header clock, µs ticks"
    fps = float(meta.framerate) if meta.framerate and meta.framerate > 0 else 0.0
    if fps > 0:
        return (idx - idx[0]).astype(np.float64) / fps if len(idx) else np.zeros(0), f"nominal {fps:g} fps"
    return (idx - idx[0]).astype(np.float64) if len(idx) else np.zeros(0), "frame index (no clock)"
