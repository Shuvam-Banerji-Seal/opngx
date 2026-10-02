"""Drift - how the whole image moves (stage / sample drift).

Each frame is registered to a reference (the average of the first frames)
by phase correlation, refined to 1/10 pixel (adjustable) with the matrix-multiply DFT
upsampling of Guizar-Sicairos et al. (Opt. Lett. 2008). Static structure in the field (debris, edges, the
background) dominates the result, so it measures the drift of the stage
or chamber - which you can subtract from a tracked particle's motion.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis.base import Column, Module, Param


def _tukey(n: int, alpha: float = 0.25) -> np.ndarray:
    w = np.ones(n)
    m = int(alpha * (n - 1) / 2)
    if m > 0:
        r = 0.5 * (1 - np.cos(np.pi * np.arange(m) / m))
        w[:m] = r
        w[-m:] = r[::-1]
    return w


def _window(h: int, w: int) -> np.ndarray:
    # flat-top (Tukey 25 %): tapers the edges so the frame border does not
    # dominate the correlation, without pulling the estimate towards zero
    # shift the way a Hann window does (measured on non-circular drift:
    # 0.05 px rms vs 0.07 with Hann, 0.42 with no window)
    return (_tukey(h)[:, None] * _tukey(w)[None, :]).astype(np.float32)


def _upsampled_dft(data: np.ndarray, size: int, usfac: int, offsets) -> np.ndarray:
    """size x size samples of the inverse DFT of `data` on a grid 1/usfac
    of a pixel apart, starting at `offsets` (Guizar-Sicairos, Thurman &
    Fienup, Opt. Lett. 33, 156 (2008): matrix-multiply DFT)."""
    for n_items, off in reversed(list(zip(data.shape, offsets))):
        kern = (np.arange(size) - off)[:, None] * np.fft.fftfreq(n_items, usfac)
        data = np.tensordot(np.exp(-2j * np.pi * kern), data, axes=(1, -1))
    return data


def phase_shift(F_ref_conj: np.ndarray, frames: np.ndarray, win: np.ndarray, usfac: int = 20) -> tuple:
    """(dx, dy, peak) of each frame relative to the reference spectrum by
    phase correlation, refined to 1/usfac pixel. Positive dx = content
    moved right, positive dy = moved down."""
    k, h, w = frames.shape
    dx = np.empty(k)
    dy = np.empty(k)
    pk = np.empty(k)
    mid = np.array([h // 2, w // 2])
    for i in range(k):
        # one frame at a time: a whole-batch FFT (256 frames, ~160 MB of
        # complex data per thread) made the threads fight over memory
        fi = frames[i].astype(np.float32)
        fi = (fi - fi.mean()) * win
        prod = np.fft.fft2(fi) * F_ref_conj
        prod /= np.maximum(np.abs(prod), 1e-12)
        cc = np.fft.ifft2(prod)
        y, x = np.unravel_index(int(np.argmax(np.abs(cc))), cc.shape)
        sh = np.array([y, x], dtype=np.float64)
        sh[sh > mid] -= np.array([h, w])[sh > mid]
        if usfac > 1:
            sh = np.round(sh * usfac) / usfac
            size = int(np.ceil(usfac * 1.5))
            dshift = float(size // 2)
            up = _upsampled_dft(prod.conj(), size, usfac, dshift - sh * usfac).conj()
            m = np.array(np.unravel_index(int(np.argmax(np.abs(up))), up.shape), dtype=np.float64)
            sh = sh + (m - dshift) / usfac
            pk[i] = float(np.abs(up).max()) / (h * w)
        else:
            pk[i] = float(np.abs(cc).max())
        dy[i], dx[i] = sh
    return dx, dy, pk


class Drift(Module):
    name = "drift"
    title = "Drift (whole-image registration)"
    description = ("Sub-pixel shift of every frame against a reference by phase correlation: stage / "
                   "chamber drift and vibration, independent of a tracked particle.")
    version = "1.0"
    author = "opngx"
    params = [
        Param("reference_frames", int, 16, "average this many first frames as the reference", min=1, max=10000),
        Param("pixel_size_um", float, 0.0, "µm per pixel (0 = report in pixels)", min=0.0),
        Param("precision", int, 10, "sub-pixel refinement: 1/precision of a pixel (1 = whole pixels). "
              "10: ~0.05 px rms; 20: ~0.03 px rms at half the speed", min=1, max=200),
    ]
    columns = [
        Column("dx", "shift of the image to the right", "px"),
        Column("dy", "shift of the image downwards", "px"),
        Column("dx_um", "dx in µm (when pixel_size_um is set)", "µm"),
        Column("dy_um", "dy in µm (when pixel_size_um is set)", "µm"),
        Column("match", "registration quality (correlation peak, 0..1)", ""),
    ]
    plot = ("dx", "dy")
    trajectory = True

    def begin(self, ctx):
        # the FIRST frames of the run (ctx.sample() would spread over the
        # whole run and average the drift itself into the reference)
        ref = ctx.first(int(ctx.params["reference_frames"])).astype(np.float32).mean(0)
        h, w = ref.shape
        win = _window(h, w)
        ref = (ref - ref.mean()) * win
        ctx.state["win"] = win
        ctx.state["Fref"] = np.conj(np.fft.fft2(ref))

    def process(self, frames, ctx):
        dx, dy, pk = phase_shift(ctx.state["Fref"], frames, ctx.state["win"], ctx.params["precision"])
        s = ctx.params["pixel_size_um"]
        nan = np.full(len(frames), np.nan)
        return {"dx": dx, "dy": dy, "dx_um": dx * s if s else nan, "dy_um": dy * s if s else nan, "match": pk}

    def finish(self, table, ctx):
        dx, dy = table["dx"], table["dy"]
        if len(dx) > 1:
            t = table["time_s"]
            span = float(t[-1] - t[0]) or 1.0
            ctx.summary.update(net_dx_px=float(dx[-1] - dx[0]), net_dy_px=float(dy[-1] - dy[0]),
                               drift_px_per_s=float(np.hypot(dx[-1] - dx[0], dy[-1] - dy[0]) / span),
                               jitter_rms_px=float(np.sqrt(np.var(np.diff(dx)) + np.var(np.diff(dy))) / np.sqrt(2)),
                               min_match=float(table["match"].min()))
        return table
