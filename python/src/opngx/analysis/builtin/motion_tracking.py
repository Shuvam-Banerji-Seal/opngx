"""Motion tracking — trajectory of a bright (or dark) spot or ring.

Per frame, fully vectorised over a batch of frames:

1. **Locate**: sum the frame in `locate_block`² blocks and take the
   brightest block. Block sums ignore single hot pixels and cost one
   reshape; no temporal dependency, so batches run in parallel.
2. **Window**: cut a `window`² region around it; threshold at
   `median + threshold·(peak − median)` of that window, so the level
   adapts to exposure frame by frame.
3. **Refine** to sub-pixel, by `method`:
   * `circle` — algebraic (Kåsa) least-squares circle through the
     above-threshold pixels, then (with `refine`, default) re-fitted to
     the rim's intensity RIDGE along 48 rays. Right for a sphere imaged
     as a bright RING:
     it recovers the true centre and the radius, where an intensity
     centroid is dragged toward the brighter side of the rim (measured on
     this project's footage: ~5 px bias, 2.5× the frame-to-frame jitter).
   * `centroid` — intensity-weighted centroid of (I − threshold)⁺. Right
     for a solid spot (Gaussian-like laser point).
   * `peak` — brightest pixel + 3-point parabolic sub-pixel interpolation.
   * `auto` (default) — decides ONCE from frames sampled over the whole
     range: a ring (dark centre inside the fitted circle) → `circle`,
     otherwise `centroid`. Deciding once keeps the whole trajectory on one
     estimator.

Positions are FULL-FRAME pixel coordinates (x = column, y = row, pixel
centres at integers), whatever crop the run used. `finish()` adds
velocities from the frame-header clock and summary statistics.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis import native
from opngx.analysis.base import Column, Module, Param


def _locate(frames: np.ndarray, blk: int, origin=(0, 0)) -> tuple[np.ndarray, np.ndarray]:
    """Coarse position: the brightest blk x blk block. For blk >= 4 the
    block sums use every 2nd row/column (4x fewer reads; still 4+ pixels
    per block, so a single hot pixel cannot win) — the sub-pixel estimate
    that follows uses every pixel of the window."""
    k, H, W = frames.shape
    blk = max(1, min(int(blk), H, W))
    # align the block grid to FULL-FRAME coordinates, so a crop does not
    # move the search window (and with it the threshold) for a feature
    # that is nowhere near the crop edge
    oy = (-int(origin[1])) % blk
    ox = (-int(origin[0])) % blk
    if (oy or ox) and H - oy >= blk and W - ox >= blk:
        frames = frames[:, oy:, ox:]
    else:
        oy = ox = 0
    step = 2 if blk >= 4 else 1
    b = blk // step
    src = frames[:, ::step, ::step] if step > 1 else frames
    h2, w2 = src.shape[1] // b * b, src.shape[2] // b * b
    s = np.ascontiguousarray(src[:, :h2, :w2]).reshape(k, h2, w2 // b, b).sum(3, dtype=np.uint16)
    s = s.reshape(k, h2 // b, b, w2 // b).sum(2, dtype=np.int32)
    i = s.reshape(k, -1).argmax(1)
    by, bx = np.divmod(i, w2 // b)
    return by * blk + blk // 2 + oy, bx * blk + blk // 2 + ox


def _circle_fit(m: np.ndarray, lx: np.ndarray, ly: np.ndarray):
    """Kåsa fit per frame on a 0/1 mask (k, wh, ww) -> cx, cy, r, n."""
    mx = m.sum(1)  # (k, ww)
    my = m.sum(2)  # (k, wh)
    n = mx.sum(1)
    Sx = mx @ lx
    Sy = my @ ly
    Sxx = mx @ (lx * lx)
    Syy = my @ (ly * ly)
    Sxy = np.einsum("kyx,y,x->k", m, ly, lx)
    Sxz = mx @ (lx**3) + np.einsum("kyx,y,x->k", m, ly * ly, lx)
    Syz = my @ (ly**3) + np.einsum("kyx,y,x->k", m, ly, lx * lx)
    Sz = Sxx + Syy
    A = np.stack(
        [np.stack([Sxx, Sxy, Sx], -1), np.stack([Sxy, Syy, Sy], -1), np.stack([Sx, Sy, n], -1)],
        -2,
    ).astype(np.float64)
    b = -np.stack([Sxz, Syz, Sz], -1).astype(np.float64)
    ok = n >= 3
    A[~ok] = np.eye(3)
    b[~ok] = 0
    # a degenerate (collinear) mask makes A singular: fall back per frame
    det = np.linalg.det(A)
    bad = ~np.isfinite(det) | (np.abs(det) < 1e-9)
    A[bad] = np.eye(3)
    b[bad] = 0
    D, E, F = np.linalg.solve(A, b[..., None])[..., 0].T
    cx, cy = -D / 2, -E / 2
    r = np.sqrt(np.maximum(cx**2 + cy**2 - F, 0))
    good = ok & ~bad
    return cx, cy, r, n, good


def _bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """img (k, h, w) float; x, y (k, ...) -> bilinear samples (clamped)."""
    k, H, W = img.shape
    x = np.clip(x, 0, W - 1.001)
    y = np.clip(y, 0, H - 1.001)
    x0 = np.floor(x).astype(np.intp)
    y0 = np.floor(y).astype(np.intp)
    fx, fy = x - x0, y - y0
    K = np.arange(k).reshape((k,) + (1,) * (x.ndim - 1))
    a, b = img[K, y0, x0], img[K, y0, x0 + 1]
    c, d = img[K, y0 + 1, x0], img[K, y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _kasa_points(px, py, w):
    """Weighted algebraic circle fit to point sets (k, M)."""
    z = px * px + py * py

    def S(a):
        return (w * a).sum(1)

    A = np.stack(
        [
            np.stack([S(px * px), S(px * py), S(px)], -1),
            np.stack([S(px * py), S(py * py), S(py)], -1),
            np.stack([S(px), S(py), S(np.ones_like(px))], -1),
        ],
        -2,
    )
    b = -np.stack([S(px * z), S(py * z), S(z)], -1)
    det = np.linalg.det(A)
    bad = ~np.isfinite(det) | (np.abs(det) < 1e-9)
    A[bad] = np.eye(3)
    b[bad] = 0
    D, E, F = np.linalg.solve(A, b[..., None])[..., 0].T
    cx, cy = -D / 2, -E / 2
    return cx, cy, np.sqrt(np.maximum(cx * cx + cy * cy - F, 0)), ~bad


def _ridge_refine(sub, cx, cy, r, M=48, span=4.0, step=0.5, iters=2):
    """Refit a ring to its RIDGE: along M rays from the current centre, the
    sub-pixel radius of peak intensity (3-tap smoothed profile + parabolic
    peak), then a prominence-weighted circle through those points.

    A fit to the thresholded MASK follows the rim's thickness, so a rim that
    is brighter on one side (as on this project's footage) pulls it that
    way. The ridge position does not depend on brightness. Measured on
    synthetic rings with a brighter lower rim: mask fit bias +0.22 px /
    RMS 0.24 px -> ridge fit bias +0.03 px / RMS 0.04 px.
    Returns cx, cy, r, rms (weighted ridge residual)."""
    ang = np.linspace(0, 2 * np.pi, M, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)
    k = len(sub)
    K = np.arange(k)[:, None]
    Mi = np.arange(M)[None, :]
    rms = np.full(k, np.nan)
    for _ in range(iters):
        rr = r[:, None] + np.arange(-span, span + 1e-9, step)[None, :]
        X = cx[:, None, None] + ca[None, :, None] * rr[:, None, :]
        Y = cy[:, None, None] + sa[None, :, None] * rr[:, None, :]
        prof = _bilinear(sub, X, Y)
        prof = np.concatenate(
            [prof[..., :1], (prof[..., :-2] + 2 * prof[..., 1:-1] + prof[..., 2:]) / 4, prof[..., -1:]], -1
        )
        # first sample within 1e-9 of the maximum (tie-proof; same in C)
        j = (prof >= prof.max(2, keepdims=True) - 1e-9).argmax(2)
        R = prof.shape[2]
        jc = np.clip(j, 1, R - 2)
        lft, c0, rgt = prof[K, Mi, jc - 1], prof[K, Mi, jc], prof[K, Mi, jc + 1]
        den = lft - 2 * c0 + rgt
        with np.errstate(divide="ignore", invalid="ignore"):
            off = np.where(np.abs(den) > 1e-9, 0.5 * (lft - rgt) / den, 0.0).clip(-0.5, 0.5)
        rad = rr[K, jc] + off * step
        w = np.where((j == 0) | (j == R - 1), 0.0, 1.0) * np.clip(c0 - np.median(prof, 2), 0, None)
        px = cx[:, None] + ca[None, :] * rad
        py = cy[:, None] + sa[None, :] * rad
        ncx, ncy, nr, ok = _kasa_points(px, py, w)
        cx, cy, r = np.where(ok, ncx, cx), np.where(ok, ncy, cy), np.where(ok, nr, r)
        ws = w.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            rms = np.sqrt((w * (np.hypot(px - cx[:, None], py - cy[:, None]) - r[:, None]) ** 2).sum(1) / ws)
    return cx, cy, r, rms


class MotionTracking(Module):
    name = "motion_tracking"
    title = "Motion tracking (trajectory)"
    description = (
        "Tracks one bright spot or ring through the recording and writes its "
        "trajectory: sub-pixel x/y per frame, ring radius, brightness, "
        "velocity and a found flag, timed by the camera's frame clock."
    )
    version = "1.0"
    author = "opngx"
    params = [
        Param("method", str, "auto", "sub-pixel estimator", choices=("auto", "circle", "centroid", "peak")),
        Param("target", str, "bright", "track a bright or a dark feature", choices=("bright", "dark")),
        Param("window", int, 48, "search window around the coarse position (px)", min=5, max=2048),
        Param("threshold", float, 0.5, "level between window median (0) and peak (1)", min=0.05, max=0.95),
        Param("min_pixels", int, 6, "fewer pixels above threshold = not found", min=1, max=100000),
        Param("locate_block", int, 4, "coarse-search block size (px); larger ignores small specks", min=1, max=64),
        Param("refine", bool, True, "circle: fit the rim's ridge (unbiased by uneven rim brightness)"),
        Param("pixel_size_um", float, 0.0, "µm per pixel for physical units (0 = off)", min=0.0),
    ]
    columns = [
        Column("x", "spot/ring centre, column (full frame)", "px"),
        Column("y", "spot/ring centre, row (full frame)", "px"),
        Column("radius", "fitted ring radius (circle method)", "px"),
        Column("peak", "brightest value in the search window", "DN"),
        Column("area", "pixels above threshold", "px"),
        Column("found", "1 = tracked in this frame, 0 = lost", ""),
        Column("fit_rms", "RMS distance of the rim (ridge points, or mask pixels) from the circle", "px"),
        Column("vx", "x velocity (central difference on the frame clock)", "px/s"),
        Column("vy", "y velocity", "px/s"),
        Column("speed", "|v|", "px/s"),
        Column("disp", "distance from the first tracked position", "px"),
        Column("x_um", "x in µm (only with pixel_size_um > 0)", "µm"),
        Column("y_um", "y in µm (only with pixel_size_um > 0)", "µm"),
        Column("speed_um_s", "speed in µm/s (only with pixel_size_um > 0)", "µm/s"),
    ]
    overlay = {"x": "x", "y": "y", "r": "radius"}
    plot = ("x", "y")
    trajectory = True

    # ------------------------------------------------------------------
    def begin(self, ctx) -> None:
        self._origin = ctx.origin
        p = ctx.params
        method = p["method"]
        if method == "auto":
            sample = ctx.sample(24)
            if p["target"] == "dark":
                sample = 255 - sample
            method = "circle" if self._looks_like_ring(sample, p) else "centroid"
        ctx.state["method"] = method
        ctx.summary["method_used"] = method
        ctx.state["native"] = native.available()
        ctx.summary["backend"] = "native C" if ctx.state["native"] else "numpy"
        ctx.log(f"motion_tracking: using the '{method}' estimator")

    def _looks_like_ring(self, frames: np.ndarray, p) -> bool:
        cx, cy, r, n, good, _rms, sub, x0, y0 = self._measure(frames, p, "circle", getattr(self, "_origin", (0, 0)))
        votes = 0
        for i in range(len(frames)):
            if not good[i] or r[i] < 2.5:
                continue
            yy, xx = np.mgrid[0 : sub.shape[1], 0 : sub.shape[2]]
            inner = (xx - (cx[i] - x0[i])) ** 2 + (yy - (cy[i] - y0[i])) ** 2 <= (0.45 * r[i]) ** 2
            if inner.sum() < 3:
                continue
            flat = sub[i].reshape(-1)
            base = np.median(flat)
            thr = base + p["threshold"] * (flat.max() - base)
            if sub[i][inner].mean() < thr:
                votes += 1
        return votes > len(frames) // 2

    def _measure(self, frames: np.ndarray, p, method: str, origin=(0, 0)):
        k, H, W = frames.shape
        cy0, cx0 = _locate(frames, p["locate_block"], origin)
        wh, ww = min(p["window"], H), min(p["window"], W)
        y0 = np.clip(cy0 - wh // 2, 0, H - wh)
        x0 = np.clip(cx0 - ww // 2, 0, W - ww)
        yy = y0[:, None] + np.arange(wh)
        xx = x0[:, None] + np.arange(ww)
        sub = frames[np.arange(k)[:, None, None], yy[:, :, None], xx[:, None, :]].astype(np.float32)
        flat = sub.reshape(k, -1)
        # float64 threshold: identical in the numpy and C paths, so a pixel
        # sitting exactly on the threshold compares the same way in both
        peak = flat.max(1).astype(np.float64)
        base = np.median(flat, axis=1).astype(np.float64)
        thr = base + float(p["threshold"]) * (peak - base)
        # float64 moments: cubic coordinate sums reach ~1e7, where float32
        # keeps too few digits for a sub-pixel circle centre
        lx = np.arange(ww, dtype=np.float64)
        ly = np.arange(wh, dtype=np.float64)
        above = sub > thr[:, None, None]
        n = above.sum((1, 2)).astype(np.float64)
        rms = np.full(k, np.nan)
        r = np.full(k, np.nan)
        if method == "circle":
            m = above.astype(np.float64)
            cx, cy, r, _n, good = _circle_fit(m, lx, ly)
            # rim residual: RMS of (distance to centre − r) over the mask
            d = np.sqrt((lx[None, None, :] - cx[:, None, None]) ** 2 + (ly[None, :, None] - cy[:, None, None]) ** 2)
            res = (d - r[:, None, None]) ** 2 * m
            rms = np.sqrt(res.sum((1, 2)) / np.maximum(n, 1))
            if p.get("refine", True) and good.any() and wh >= 2 and ww >= 2:
                g = good & (r >= 2.0)
                if g.any():
                    rcx, rcy, rr, rrms = _ridge_refine(sub[g], cx[g], cy[g], r[g])
                    cx, cy, r, rms = cx.copy(), cy.copy(), r.copy(), rms.copy()
                    cx[g], cy[g], r[g], rms[g] = rcx, rcy, rr, rrms
            r = np.where(good, r, np.nan)
        elif method == "centroid":
            w = np.clip(sub - thr[:, None, None], 0, None)
            sw = w.sum((1, 2))
            good = sw > 0
            cx = (w.sum(1) @ lx) / np.where(good, sw, 1)
            cy = (w.sum(2) @ ly) / np.where(good, sw, 1)
        else:  # peak + parabolic refinement
            i = flat.argmax(1)
            py, px = np.divmod(i, ww)
            K = np.arange(k)

            def at(yv, xv):
                return sub[K, np.clip(yv, 0, wh - 1), np.clip(xv, 0, ww - 1)].astype(np.float64)

            c0 = at(py, px)
            l_, r_ = at(py, px - 1), at(py, px + 1)
            u_, d_ = at(py - 1, px), at(py + 1, px)
            denx = l_ - 2 * c0 + r_
            deny = u_ - 2 * c0 + d_
            with np.errstate(divide="ignore", invalid="ignore"):  # masked by where()
                ox = np.where((np.abs(denx) > 1e-9) & (px > 0) & (px < ww - 1), 0.5 * (l_ - r_) / denx, 0.0)
                oy = np.where((np.abs(deny) > 1e-9) & (py > 0) & (py < wh - 1), 0.5 * (u_ - d_) / deny, 0.0)
            cx = px + np.clip(ox, -0.5, 0.5)
            cy = py + np.clip(oy, -0.5, 0.5)
            good = np.ones(k, bool)
        good = good & (n >= p["min_pixels"])
        return (cx + x0, cy + y0, r, n, good, rms, sub, x0, y0) if method == "circle" else (
            cx + x0, cy + y0, r, n, good, rms, peak, x0, y0
        )

    def process(self, frames, ctx):
        p = ctx.params
        if p["target"] == "dark":
            frames = 255 - frames
        method = ctx.state.get("method", "centroid")
        # native C kernel (src/analysis.c) when the engine provides it; the
        # numpy implementation below is the reference and the fallback
        nat = native.track(frames, method, p, ctx.origin) if ctx.state.get("native", True) else None
        if nat is not None:
            cx, cy, r, n, good, rms, peak = (
                nat["x"], nat["y"], nat["r"], nat["area"], nat["found"], nat["rms"], nat["peak"]
            )
        else:
            out = self._measure(frames, p, method, ctx.origin)
            cx, cy, r, n, good, rms = out[:6]
            if method == "circle":
                sub = out[6]
                peak = sub.reshape(len(sub), -1).max(1)
            else:
                peak = out[6]
        ox, oy = ctx.origin
        if p["target"] == "dark":
            peak = 255 - peak
        nan = np.nan
        return {
            "x": np.where(good, cx + ox, nan),
            "y": np.where(good, cy + oy, nan),
            "radius": np.where(good, r, nan),
            "peak": peak.astype(np.float64),
            "area": n,
            "found": good.astype(np.int8),
            "fit_rms": np.where(good, rms, nan),
        }

    def finish(self, table, ctx):
        x, y, t = table["x"], table["y"], table["time_s"]
        found = table["found"].astype(bool)
        vx = np.full(len(x), np.nan)
        vy = np.full(len(x), np.nan)
        if found.sum() >= 2:
            tf = t[found]
            if np.all(np.diff(tf) > 0):
                vx[found] = np.gradient(x[found], tf)
                vy[found] = np.gradient(y[found], tf)
        table["vx"], table["vy"] = vx, vy
        table["speed"] = np.hypot(vx, vy)
        disp = np.full(len(x), np.nan)
        if found.any():
            i0 = int(np.argmax(found))
            disp[found] = np.hypot(x[found] - x[i0], y[found] - y[i0])
        table["disp"] = disp
        s = ctx.summary
        s["frames"] = int(len(x))
        s["found_frames"] = int(found.sum())
        s["found_pct"] = round(100.0 * found.mean(), 3) if len(x) else 0.0
        if found.any():
            xf, yf = x[found], y[found]
            steps = np.hypot(np.diff(xf), np.diff(yf))
            s.update(
                x_mean=float(xf.mean()), y_mean=float(yf.mean()),
                x_std=float(xf.std()), y_std=float(yf.std()),
                x_range=[float(xf.min()), float(xf.max())],
                y_range=[float(yf.min()), float(yf.max())],
                path_length_px=float(steps.sum()),
                net_displacement_px=float(np.hypot(xf[-1] - xf[0], yf[-1] - yf[0])),
                step_median_px=float(np.median(steps)) if len(steps) else 0.0,
                mean_speed_px_s=float(np.nanmean(table["speed"][found])) if found.sum() > 1 else 0.0,
                duration_s=float(t[found][-1] - t[found][0]),
            )
            rr = table["radius"][found]
            if np.isfinite(rr).any():
                s["radius_mean_px"] = float(np.nanmean(rr))
                s["radius_std_px"] = float(np.nanstd(rr))
        um = float(ctx.params["pixel_size_um"])
        if um > 0:
            table["x_um"] = x * um
            table["y_um"] = y * um
            table["speed_um_s"] = table["speed"] * um
            for key in ("path_length_px", "net_displacement_px", "mean_speed_px_s"):
                if key in s:
                    s[key.replace("_px", "_um")] = s[key] * um
        return table
