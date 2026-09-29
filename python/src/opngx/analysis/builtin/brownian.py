"""Brownian motion / optical-trap analysis of a tracked trajectory.

Built for this project's footage: a sphere held (or drifting) in a laser
beam, tracked by `motion_tracking` (which this module requires and runs in
the same pass). From the trajectory it measures:

* **drift**: linear velocity of the centre (removed first with
  `detrend=linear`, so slow stage/thermal drift does not masquerade as
  confinement or diffusion);
* **MSD(τ)**: mean squared displacement at log-spaced lags. A straight fit
  MSD₂D = 4Dτ + 4σ² over the first `fit_points` lags gives the short-time
  diffusion coefficient D and the localisation noise σ; the log-log slope
  gives the anomalous exponent α (≈1 free diffusion, <1 confined/trapped);
* **PSD**: Welch power spectral density of x and y, fitted with the EXACT
  spectrum of a sampled Ornstein-Uhlenbeck process plus a white noise
  floor (a continuous Lorentzian ignores aliasing: +14 % on f_c in a
  500 Hz simulation), giving the corner frequency f_c and D;
* **ACF** estimator: noise only adds to lag 0, so a = c₂/c₁ gives the
  relaxation time, D and the localisation noise without fitting;
* **MSD OU fit**: A(1 − e^(−τ/τc)) + B per axis — the linear fit is only
  meaningful for free diffusion (α ≈ 1);
* **stiffness**: by equipartition κ = k_B·T / var(x), and from the PSD
  κ = 2π·γ·f_c with γ = k_B·T / D. Needs `pixel_size_um`;
* **steps**: the distribution of frame-to-frame displacements and its
  excess kurtosis (0 for Gaussian, thermal motion).

Assumptions, stated so the numbers are read correctly: uniform sampling
(the median frame interval is used; dropped frames count as gaps), no
correction for motion blur or aliasing, and 2-D motion in the image plane.
"""

from __future__ import annotations

import numpy as np

from opngx.analysis.base import Column, Module, Param

KB = 1.380649e-23  # J/K


def _fill_gaps(v: np.ndarray) -> np.ndarray:
    """Linear interpolation over NaNs (for spectra only)."""
    v = v.astype(np.float64).copy()
    bad = ~np.isfinite(v)
    if bad.all() or not bad.any():
        return v
    i = np.arange(len(v))
    v[bad] = np.interp(i[bad], i[~bad], v[~bad])
    return v


def _detrend(t, v, mode):
    ok = np.isfinite(v)
    if mode == "linear" and ok.sum() >= 3:
        a, b = np.polyfit(t[ok], v[ok], 1)
        return v - (a * t + b), a
    return v - (np.nanmean(v) if ok.any() else 0.0), 0.0


def _msd(v: np.ndarray, lags: np.ndarray):
    out = np.full(len(lags), np.nan)
    n = np.zeros(len(lags), dtype=np.int64)
    for i, L in enumerate(lags):
        if L >= len(v):
            continue
        d = v[L:] - v[:-L]
        ok = np.isfinite(d)
        n[i] = int(ok.sum())
        if n[i]:
            out[i] = float(np.mean(d[ok] ** 2))
    return out, n


def _welch(v: np.ndarray, fs: float, segments: int):
    n = len(v)
    seg = max(16, n // max(1, segments))
    seg = min(seg, n)
    if seg < 16:
        return np.zeros(0), np.zeros(0)
    step = seg // 2
    win = np.hanning(seg)
    scale = 1.0 / (fs * (win**2).sum())
    acc, count = None, 0
    for s in range(0, n - seg + 1, step):
        x = v[s : s + seg]
        x = (x - x.mean()) * win
        p = np.abs(np.fft.rfft(x)) ** 2 * scale
        acc = p if acc is None else acc + p
        count += 1
    psd = acc / count
    psd[1:-1] *= 2  # one-sided
    f = np.fft.rfftfreq(seg, 1.0 / fs)
    return f, psd


def _search_tau(model_fn, taus):
    """Coarse log-grid then golden-section refinement of the relaxation time
    for a model that is linear in its other parameters. model_fn(tau) ->
    (sse, extras). Returns tau, extras."""
    sse = np.array([model_fn(tau)[0] for tau in taus])
    if not np.isfinite(sse).any():
        return np.nan, None
    i = int(np.nanargmin(sse))
    lo, hi = np.log(taus[max(i - 1, 0)]), np.log(taus[min(i + 1, len(taus) - 1)])
    g = (np.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - g * (b - a), a + g * (b - a)
    fc_, fd_ = model_fn(np.exp(c))[0], model_fn(np.exp(d))[0]
    for _ in range(40):
        if fc_ < fd_:
            b, d, fd_ = d, c, fc_
            c = b - g * (b - a)
            fc_ = model_fn(np.exp(c))[0]
        else:
            a, c, fc_ = c, d, fd_
            d = a + g * (b - a)
            fd_ = model_fn(np.exp(d))[0]
    tau = float(np.exp((a + b) / 2))
    return tau, model_fn(tau)[1]


def _lin2(g1, g2, y, w):
    """Weighted least squares y ~ A*g1 + B*g2 with A, B >= 0."""
    best = (np.inf, 0.0, 0.0)
    G = np.stack([g1, g2], 1)
    Wh = np.sqrt(w)
    try:
        sol, *_ = np.linalg.lstsq(G * Wh[:, None], y * Wh, rcond=None)
    except np.linalg.LinAlgError:
        sol = np.array([np.nan, np.nan])
    cands = [(max(sol[0], 0.0), max(sol[1], 0.0))] if np.all(np.isfinite(sol)) else []
    for g, j in ((g1, 0), (g2, 1)):  # one-parameter fallbacks on the boundary
        den = np.sum(w * g * g)
        v = max(np.sum(w * g * y) / den, 0.0) if den > 0 else 0.0
        cands.append((v, 0.0) if j == 0 else (0.0, v))
    for A, B in cands:
        sse = float(np.sum(w * (y - A * g1 - B * g2) ** 2))
        if sse < best[0]:
            best = (sse, A, B)
    return best


def _spectral_peaks(f, p, ratio=8.0, halfwin=12, top=6):
    """Narrow peaks: bins exceeding `ratio` × the running median of their
    neighbourhood (a Lorentzian has none; vibration/pickup lines do).
    Returns (mask of peak bins incl. ±1 neighbours, [(freq, ratio)])."""
    n = len(p)
    if n < 2 * halfwin + 3:
        return np.zeros(n, bool), []
    from numpy.lib.stride_tricks import sliding_window_view

    pad = np.pad(p, halfwin, mode="edge")
    med = np.median(sliding_window_view(pad, 2 * halfwin + 1), axis=1)
    r = np.where(med > 0, p / med, 0.0)
    is_peak = (r > ratio) & (np.r_[True, p[1:] >= p[:-1]]) & (np.r_[p[:-1] >= p[1:], True])
    is_peak[0] = False
    idx = np.where(is_peak)[0]
    mask = np.zeros(n, bool)
    for i in idx:
        mask[max(0, i - 1) : i + 2] = True
    order = idx[np.argsort(-r[idx])][:top]
    return mask, [(float(f[i]), float(r[i])) for i in sorted(order)]


def _fit_psd_ou(f, p, dt, fmin, fmax, exclude=None):
    """Exact PSD of a SAMPLED Ornstein-Uhlenbeck process plus a white
    localisation-noise floor: P(f) = A / (1 + a² − 2a cos 2πfΔt) + B,
    a = exp(−Δt/τ). A continuous Lorentzian ignores aliasing and the
    floor; on a simulated trap at 500 Hz it over-estimated f_c by 14 %.
    Returns tau, D (unit²/s), noise sigma (unit), fitted curve."""
    sel = (f >= fmin) & (f <= fmax) & (p > 0)
    if exclude is not None:
        sel &= ~exclude
    if sel.sum() < 6 or dt <= 0:
        return np.nan, np.nan, np.nan, None
    fs_, ps_ = f[sel], p[sel]
    w = 1.0 / ps_**2  # relative error

    def model(tau):
        a = np.exp(-dt / tau)
        g1 = 1.0 / (1 + a * a - 2 * a * np.cos(2 * np.pi * fs_ * dt))
        sse, A, B = _lin2(g1, np.ones_like(fs_), ps_, w)
        return sse, (A, B, a)

    taus = np.logspace(np.log10(dt / 4), np.log10(dt * len(f) * 2), 80)
    tau, ex = _search_tau(model, taus)
    if ex is None or not np.isfinite(tau):
        return np.nan, np.nan, np.nan, None
    A, B, a = ex
    q = A / (2 * dt)  # AR(1) innovation variance
    s2 = q / (1 - a * a) if a < 1 else np.nan
    curve = A / (1 + a * a - 2 * a * np.cos(2 * np.pi * f * dt)) + B
    return tau, s2 / tau, float(np.sqrt(B / (2 * dt))), curve


def _fit_msd_ou(tau_lag, m1, dt):
    """Per-axis MSD of a confined particle: A(1 − exp(−τ/τc)) + B, with
    A = 2·var and B = 2σ² (localisation noise). Returns tau_c, var, sigma."""
    ok = np.isfinite(m1) & (m1 > 0)
    if ok.sum() < 4:
        return np.nan, np.nan, np.nan
    tl, mm = tau_lag[ok], m1[ok]
    w = 1.0 / mm**2

    def model(tc):
        sse, A, B = _lin2(1 - np.exp(-tl / tc), np.ones_like(tl), mm, w)
        return sse, (A, B)

    tc, ex = _search_tau(model, np.logspace(np.log10(dt / 4), np.log10(tl[-1] * 20), 80))
    if ex is None:
        return np.nan, np.nan, np.nan
    A, B = ex
    return tc, A / 2, float(np.sqrt(B / 2))


def _acf_ou(v, dt):
    """Autocorrelation estimator: noise adds to lag 0 only, so for a sampled
    OU process a = c2/c1 exactly, var = c1/a, sigma² = c0 − var."""
    ok = np.isfinite(v)
    if ok.sum() < 16:
        return np.nan, np.nan, np.nan

    def c(k):
        d = v[k:] * v[: len(v) - k] if k else v * v
        d = d[np.isfinite(d)]
        return float(d.mean()) if len(d) else np.nan

    c0, c1, c2 = c(0), c(1), c(2)
    if not (c1 > 0 and c2 > 0 and c2 < c1):
        return np.nan, np.nan, np.nan
    a = c2 / c1
    tau = -dt / np.log(a)
    var = c1 / a
    return tau, var, float(np.sqrt(max(c0 - var, 0.0)))


def _lorentz_fit(f, p, fmin, fmax):
    """Fit P = D / (pi^2 (fc^2 + f^2)) via 1/P = (pi^2/D) fc^2 + (pi^2/D) f^2,
    weighted by P^2 (≈ constant relative error). Returns fc, D or NaNs."""
    sel = (f >= fmin) & (f <= fmax) & (p > 0)
    if sel.sum() < 4:
        return np.nan, np.nan
    x, y, w = f[sel] ** 2, 1.0 / p[sel], p[sel] ** 2
    W = np.sum(w)
    xm, ym = np.sum(w * x) / W, np.sum(w * y) / W
    b = np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2)
    a = ym - b * xm
    if b <= 0 or a <= 0:
        return np.nan, np.nan
    return float(np.sqrt(a / b)), float(np.pi**2 / b)


class BrownianMotion(Module):
    name = "brownian_motion"
    title = "Brownian motion & trap analysis"
    description = (
        "From the tracked trajectory: drift, mean squared displacement (D, α, "
        "localisation noise), power spectrum with corner frequency, trap "
        "stiffness (equipartition and PSD) and the step distribution. Runs "
        "motion tracking in the same pass."
    )
    version = "1.0"
    author = "opngx"
    requires = ("motion_tracking",)
    params = [
        Param("pixel_size_um", float, 0.0, "µm per pixel (0 = report in pixels; stiffness needs it)", min=0.0),
        Param("temperature_K", float, 295.15, "sample temperature for k_B·T", min=1.0),
        Param("detrend", str, "linear", "remove drift before the analysis", choices=("linear", "none")),
        Param("lag_count", int, 40, "number of log-spaced MSD lags", min=3, max=500),
        Param("max_lag_frac", float, 0.1, "longest MSD lag as a fraction of the run", min=0.001, max=0.5),
        Param("fit_points", int, 8, "shortest lags used for the D / α fit", min=2, max=200),
        Param("psd_segments", int, 16, "Welch segments (more = smoother, coarser)", min=1, max=1024),
        Param("psd_fmax_frac", float, 0.25, "fit the PSD up to this fraction of the sampling rate", min=0.01, max=0.5),
        Param("exclude_peaks", bool, True, "leave narrow spectral lines (vibration, pickup) out of the PSD fit"),
        Param("hist_bins", int, 61, "bins of the step histogram", min=5, max=1001),
    ]
    columns = [
        Column("x_detr", "x after drift removal", "px"),
        Column("y_detr", "y after drift removal", "px"),
        Column("dx", "frame-to-frame step in x", "px"),
        Column("dy", "frame-to-frame step in y", "px"),
    ]
    plot = ("x_detr", "y_detr")
    table_plots = {
        "msd": {"x": "lag_s", "y": ["msd_x", "msd_y", "msd_2d"], "log": True},
        "psd": {"x": "freq_hz", "y": ["psd_x", "fit_x", "psd_y", "fit_y"], "log": True},
        "steps": {"x": "step", "y": ["count_x", "gauss_x", "count_y"], "log": False},
    }

    def process(self, frames, ctx):
        return {}  # everything comes from the motion_tracking table in finish()

    def finish(self, table, ctx):
        p = ctx.params
        tr = ctx.inputs["motion_tracking"]
        x = np.where(tr["found"].astype(bool), tr["x"], np.nan).astype(np.float64)
        y = np.where(tr["found"].astype(bool), tr["y"], np.nan).astype(np.float64)
        t = tr["time_s"].astype(np.float64)
        n = len(x)
        s = ctx.summary
        s["frames"] = n
        s["tracked_frames"] = int(np.isfinite(x).sum())
        if s["tracked_frames"] < 16:
            s["error"] = "fewer than 16 tracked frames — nothing to analyse"
            table.update(x_detr=x, y_detr=y, dx=np.full(n, np.nan), dy=np.full(n, np.nan))
            return table
        dt = float(np.median(np.diff(t))) if n > 1 else 0.0
        fs = 1.0 / dt if dt > 0 else 0.0
        um = float(p["pixel_size_um"])
        L = um if um > 0 else 1.0
        unit = "µm" if um > 0 else "px"
        s["length_unit"] = unit
        s["frame_interval_s"] = dt
        s["sampling_hz"] = fs

        xd, vx = _detrend(t, x, p["detrend"])
        yd, vy = _detrend(t, y, p["detrend"])
        s["drift_vx"] = vx * L  # unit/s
        s["drift_vy"] = vy * L
        table["x_detr"], table["y_detr"] = xd, yd
        table["dx"] = np.r_[np.nan, np.diff(x)]
        table["dy"] = np.r_[np.nan, np.diff(y)]
        X, Y = xd * L, yd * L  # physical (or px) units from here on

        var_x, var_y = float(np.nanvar(X)), float(np.nanvar(Y))
        s["std_x"], s["std_y"] = float(np.sqrt(var_x)), float(np.sqrt(var_y))

        # ---- MSD
        max_lag = max(2, int(n * p["max_lag_frac"]))
        lags = np.unique(np.round(np.logspace(0, np.log10(max_lag), p["lag_count"])).astype(np.int64))
        mx, nx = _msd(X, lags)
        my, _ny = _msd(Y, lags)
        m2 = mx + my
        tau = lags * dt
        ctx.tables["msd"] = {"lag_frames": lags, "lag_s": tau, "msd_x": mx, "msd_y": my, "msd_2d": m2, "pairs": nx}
        k = min(int(p["fit_points"]), int(np.isfinite(m2).sum()))
        if k >= 2 and dt > 0:
            sel = np.isfinite(m2)
            tf, mf = tau[sel][:k], m2[sel][:k]
            slope, icpt = np.polyfit(tf, mf, 1)
            s["D_msd"] = float(slope / 4.0)  # unit²/s
            s["loc_noise_sigma"] = float(np.sqrt(icpt / 4.0)) if icpt > 0 else 0.0
            pos = mf > 0
            if pos.sum() >= 2:
                s["alpha"] = float(np.polyfit(np.log(tf[pos]), np.log(mf[pos]), 1)[0])
        s["msd_plateau_2d"] = float(np.nanmean(m2[-max(1, len(m2) // 5):]))

        # ---- PSD + Lorentzian
        # ---- confined-motion (OU) estimators, per axis
        if fs > 0:
            f, px_ = _welch(_fill_gaps(X), fs, p["psd_segments"])
            _f, py_ = _welch(_fill_gaps(Y), fs, p["psd_segments"])
            fits = {}
            for ax, v, pp, m1 in (("x", X, px_, mx), ("y", Y, py_, my)):
                if len(f):
                    pmask, peaks = _spectral_peaks(f, pp)
                    s[f"psd_peaks_{ax}_hz"] = [round(fr, 3) for fr, _r in peaks]
                    tau_p, D_p, sn_p, curve = _fit_psd_ou(
                        f, pp, dt, 2 * (f[1] - f[0]), p["psd_fmax_frac"] * fs,
                        exclude=pmask if p["exclude_peaks"] else None,
                    )
                    fits[ax] = curve if curve is not None else np.full(len(f), np.nan)
                    s[f"fc_{ax}_hz"] = float(1 / (2 * np.pi * tau_p)) if np.isfinite(tau_p) else np.nan
                    s[f"D_psd_{ax}"] = float(D_p)
                    s[f"noise_psd_{ax}"] = sn_p
                tau_a, var_a, sn_a = _acf_ou(v, dt)
                s[f"fc_acf_{ax}_hz"] = float(1 / (2 * np.pi * tau_a)) if np.isfinite(tau_a) else np.nan
                s[f"D_acf_{ax}"] = float(var_a / tau_a) if np.isfinite(tau_a) else np.nan
                s[f"var_signal_{ax}"] = float(var_a)
                s[f"noise_acf_{ax}"] = sn_a
                tc_m, var_m, sn_m = _fit_msd_ou(tau, m1, dt)
                s[f"tau_c_msd_{ax}_s"] = float(tc_m)
                s[f"D_msd_ou_{ax}"] = float(var_m / tc_m) if np.isfinite(tc_m) else np.nan
            if len(f):
                ctx.tables["psd"] = {"freq_hz": f, "psd_x": px_, "psd_y": py_,
                                     "fit_x": fits.get("x"), "fit_y": fits.get("y")}

        # ---- stiffness (SI needs a length calibration)
        T = float(p["temperature_K"])
        if um > 0:
            for ax, var in (("x", var_x), ("y", var_y)):
                if var > 0:
                    s[f"k_{ax}_equipartition_pN_per_um"] = KB * T / (var * 1e-12) * 1e6
                vs = s.get(f"var_signal_{ax}")
                if vs and np.isfinite(vs) and vs > 0:
                    # the localisation noise inflates var(x): the ACF's
                    # noise-free signal variance gives the unbiased value
                    s[f"k_{ax}_equipartition_corrected_pN_per_um"] = KB * T / (vs * 1e-12) * 1e6
                D = s.get(f"D_psd_{ax}")
                fc = s.get(f"fc_{ax}_hz")
                if D and fc and np.isfinite(D) and np.isfinite(fc) and D > 0:
                    gamma = KB * T / (D * 1e-12)  # N·s/m
                    s[f"k_{ax}_psd_pN_per_um"] = 2 * np.pi * gamma * fc * 1e6
                    s[f"drag_{ax}_Ns_per_m"] = gamma

        # ---- steps
        dx, dy = np.diff(X), np.diff(Y)
        dx, dy = dx[np.isfinite(dx)], dy[np.isfinite(dy)]
        if len(dx) > 8:
            lim = float(np.percentile(np.abs(np.r_[dx, dy]), 99.5)) or 1.0
            edges = np.linspace(-lim, lim, p["hist_bins"] + 1)
            cx_, _ = np.histogram(dx, edges)
            cy_, _ = np.histogram(dy, edges)
            mid = (edges[:-1] + edges[1:]) / 2
            w = edges[1] - edges[0]
            sx = float(dx.std())
            g = len(dx) * w / (sx * np.sqrt(2 * np.pi)) * np.exp(-(mid**2) / (2 * sx**2)) if sx > 0 else np.zeros_like(mid)
            ctx.tables["steps"] = {"step": mid, "count_x": cx_, "count_y": cy_, "gauss_x": g}
            for ax, d in (("x", dx), ("y", dy)):
                sd = d.std()
                s[f"step_std_{ax}"] = float(sd)
                s[f"step_kurtosis_{ax}"] = float(np.mean(((d - d.mean()) / sd) ** 4) - 3) if sd > 0 else 0.0

        if "radius" in tr:
            r = np.where(tr["found"].astype(bool), tr["radius"], np.nan)
            if np.isfinite(r).any():
                s["radius_mean_px"] = float(np.nanmean(r))
                s["radius_std_px"] = float(np.nanstd(r))

        # ---- model checks: say so when the numbers above should not be
        # read as "one thermally driven bead in a harmonic trap"
        warn = []
        for ax in ("x", "y"):
            pk = s.get(f"psd_peaks_{ax}_hz") or []
            if pk:
                warn.append(
                    f"{ax}: narrow spectral lines at {', '.join(f'{v:g}' for v in pk)} Hz — periodic "
                    "forcing (vibration, pump, electrical pickup), not thermal motion"
                    + ("; excluded from the PSD fit" if p["exclude_peaks"] else "")
                )
            ku = s.get(f"step_kurtosis_{ax}")
            if ku is not None and abs(ku) > 0.3:
                warn.append(
                    f"{ax}: step distribution is not Gaussian (excess kurtosis {ku:+.2f}); the motion "
                    "is not purely thermal, or the tracker is pixel-locked along this axis"
                )
            fcs = [s.get(k) for k in (f"fc_{ax}_hz", f"fc_acf_{ax}_hz")]
            tcm = s.get(f"tau_c_msd_{ax}_s")
            if tcm and np.isfinite(tcm) and tcm > 0:
                fcs.append(1 / (2 * np.pi * tcm))
            fcs = [v for v in fcs if v is not None and np.isfinite(v) and v > 0]
            if len(fcs) >= 2:
                spread = max(fcs) / min(fcs)
                s[f"fc_agreement_{ax}"] = float(spread)
                if spread > 1.3:
                    warn.append(
                        f"{ax}: PSD, ACF and MSD disagree on the corner frequency "
                        f"({', '.join(f'{v:.3g}' for v in fcs)} Hz): a single trapped-Brownian "
                        "(Ornstein-Uhlenbeck) model does not describe this trajectory well"
                    )
        if s.get("alpha") is not None and s["alpha"] > 0.9 and s.get("fc_agreement_x", 1) > 1.3:
            warn.append("alpha ≈ 1: the motion looks free rather than trapped on these time scales")
        s["warnings"] = warn

        ctx.table_units = {
            "msd": {"lag_s": "s", "msd_x": f"{unit}²", "msd_y": f"{unit}²", "msd_2d": f"{unit}²"},
            "psd": {"freq_hz": "Hz", "psd_x": f"{unit}²/Hz", "psd_y": f"{unit}²/Hz",
                    "fit_x": f"{unit}²/Hz", "fit_y": f"{unit}²/Hz"},
            "steps": {"step": unit},
        }
        s["units_note"] = f"D in {unit}²/s, drift in {unit}/s, std in {unit}"
        return table
