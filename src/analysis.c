/*
 * analysis.c — native kernels for the analysis modules (v2.0).
 *
 * Mirrors python/src/opngx/analysis/builtin/motion_tracking.py and
 * opngx/analysis/stats.py operation for operation, so both paths give the
 * same numbers (gated by a parity test). Each call is single-threaded and
 * re-entrant: the Python runner already spreads batches over a thread pool,
 * and ctypes releases the GIL for the duration of the call.
 *
 * Memory rules: every buffer is sized from the arguments, allocated once
 * per call, checked, and freed on every path. Inputs are never written.
 */
#include "opngx.h"

#include <float.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ------------------------------------------------------------ histogram -- */
int opngx_hist256(const uint8_t *frames, int64_t k, int64_t npx, int64_t *out) {
    if (!frames || !out || k < 0 || npx < 0) return -1;
    for (int64_t f = 0; f < k; f++) {
        int64_t *h = out + f * 256;
        memset(h, 0, 256 * sizeof(int64_t));
        const uint8_t *p = frames + f * npx;
        /* 4 partial histograms break the store-to-load dependency on runs
         * of equal pixels (flat backgrounds are common) */
        uint32_t t[4][256];
        memset(t, 0, sizeof t);
        int64_t i = 0;
        for (; i + 4 <= npx; i += 4) {
            t[0][p[i]]++; t[1][p[i + 1]]++; t[2][p[i + 2]]++; t[3][p[i + 3]]++;
        }
        for (; i < npx; i++) t[0][p[i]]++;
        for (int v = 0; v < 256; v++) h[v] = (int64_t)t[0][v] + t[1][v] + t[2][v] + t[3][v];
    }
    return 0;
}

/* ---------------------------------------------------------- small maths -- */
/* Solve A x = b (3x3) by Gaussian elimination with partial pivoting.
 * Returns 0 on success, -1 when |det| < 1e-9 (same guard as the numpy path). */
static int solve3(double A[3][3], double b[3], double x[3]) {
    double M[3][4];
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) M[i][j] = A[i][j];
        M[i][3] = b[i];
    }
    double det = 1.0;
    for (int c = 0; c < 3; c++) {
        int piv = c;
        for (int r = c + 1; r < 3; r++)
            if (fabs(M[r][c]) > fabs(M[piv][c])) piv = r;
        if (piv != c) {
            for (int j = 0; j < 4; j++) { double t = M[c][j]; M[c][j] = M[piv][j]; M[piv][j] = t; }
            det = -det;
        }
        double d = M[c][c];
        det *= d;
        if (d == 0.0) return -1;
        for (int r = c + 1; r < 3; r++) {
            double f = M[r][c] / d;
            for (int j = c; j < 4; j++) M[r][j] -= f * M[c][j];
        }
    }
    if (!isfinite(det) || fabs(det) < 1e-9) return -1;
    for (int i = 2; i >= 0; i--) {
        double s = M[i][3];
        for (int j = i + 1; j < 3; j++) s -= M[i][j] * x[j];
        x[i] = s / M[i][i];
    }
    return 0;
}

static int cmp_d(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

/* window median for uint8-valued windows via a 256-bin histogram: exact and
 * O(n) (the window holds integer pixel values) */
static double median_u8win(const float *v, int64_t n) {
    int64_t h[256] = {0};
    for (int64_t i = 0; i < n; i++) h[(int)v[i]]++;
    int64_t lo_rank = (n - 1) / 2, hi_rank = n / 2, c = 0;
    int lo = -1, hi = -1;
    for (int b = 0; b < 256; b++) {
        c += h[b];
        if (lo < 0 && c > lo_rank) lo = b;
        if (hi < 0 && c > hi_rank) { hi = b; break; }
    }
    return ((double)lo + (double)hi) / 2.0;
}

/* ------------------------------------------------------------- locate ---- */
static void locate(const uint8_t *fr, int H, int W, int blk, int ox0, int oy0,
                   int *out_cy, int *out_cx) {
    if (blk < 1) blk = 1;
    if (blk > H) blk = H;
    if (blk > W) blk = W;
    int oy = ((-oy0) % blk + blk) % blk;
    int ox = ((-ox0) % blk + blk) % blk;
    if (!((oy || ox) && H - oy >= blk && W - ox >= blk)) oy = ox = 0;
    int Hs = H - oy, Ws = W - ox;
    int step = blk >= 4 ? 2 : 1;
    int b = blk / step;
    int sh = (Hs + step - 1) / step, sw = (Ws + step - 1) / step; /* ::step sizes */
    int h2 = sh / b * b, w2 = sw / b * b;
    int nby = h2 / b, nbx = w2 / b;
    int64_t best = -1;
    int bby = 0, bbx = 0;
    for (int by = 0; by < nby; by++) {
        for (int bx = 0; bx < nbx; bx++) {
            int64_t s = 0;
            for (int yy = 0; yy < b; yy++) {
                const uint8_t *row = fr + (size_t)(oy + (by * b + yy) * step) * W + ox;
                for (int xx = 0; xx < b; xx++) s += row[(bx * b + xx) * step];
            }
            if (s > best) { best = s; bby = by; bbx = bx; }
        }
    }
    *out_cy = bby * blk + blk / 2 + oy;
    *out_cx = bbx * blk + blk / 2 + ox;
}

/* bilinear sample of a (wh, ww) float window, clamped like the numpy path */
static double bilin(const float *img, int wh, int ww, double x, double y) {
    /* callers guarantee wh, ww >= 2 (see ridge_refine), so x0 + 1 and
     * y0 + 1 are always inside the window */
    double xm = (double)ww - 1.001, ym = (double)wh - 1.001;
    if (x < 0) x = 0;
    if (x > xm) x = xm;
    if (y < 0) y = 0;
    if (y > ym) y = ym;
    int x0 = (int)floor(x), y0 = (int)floor(y);
    double fx = x - x0, fy = y - y0;
    const float *r0 = img + (size_t)y0 * ww, *r1 = r0 + ww;
    double a = r0[x0], bb = r0[x0 + 1], c = r1[x0], d = r1[x0 + 1];
    return (a * (1 - fx) + bb * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
}

#define RIDGE_M 48
#define RIDGE_R 17 /* arange(-4, 4 + 1e-9, 0.5) */

/* two ridge-refinement iterations; updates cx, cy, r (window coords) and
 * writes the weighted ridge residual to *rms. */
static void ridge_refine(const float *sub, int wh, int ww, double *cx, double *cy,
                         double *r, double *rms) {
    /* per call, not a shared static table: a lazily filled static is a
     * data race when batches run on several threads */
    double ca[RIDGE_M], sa[RIDGE_M];
    const double step = (2.0 * M_PI) / RIDGE_M; /* np.linspace: i * step */
    for (int m = 0; m < RIDGE_M; m++) {
        double a = (double)m * step;
        ca[m] = cos(a);
        sa[m] = sin(a);
    }
    if (wh < 2 || ww < 2) return; /* defensive: callers already check */
    double prof[RIDGE_R], sm[RIDGE_R], srt[RIDGE_R];
    double px[RIDGE_M], py[RIDGE_M], w[RIDGE_M];
    for (int it = 0; it < 2; it++) {
        for (int m = 0; m < RIDGE_M; m++) {
            for (int j = 0; j < RIDGE_R; j++) {
                double rr = *r + (-4.0 + 0.5 * j);
                prof[j] = bilin(sub, wh, ww, *cx + ca[m] * rr, *cy + sa[m] * rr);
            }
            sm[0] = prof[0];
            sm[RIDGE_R - 1] = prof[RIDGE_R - 1];
            for (int j = 1; j < RIDGE_R - 1; j++) sm[j] = (prof[j - 1] + 2 * prof[j] + prof[j + 1]) / 4;
            /* first sample within 1e-9 of the maximum: flat (clamped)
             * profiles tie, and a last-bit difference in cos() must not
             * decide which sample wins (same rule in the numpy path) */
            double mx = sm[0];
            for (int j = 1; j < RIDGE_R; j++) if (sm[j] > mx) mx = sm[j];
            int jm = 0;
            while (jm < RIDGE_R - 1 && sm[jm] < mx - 1e-9) jm++;
            int jc = jm < 1 ? 1 : (jm > RIDGE_R - 2 ? RIDGE_R - 2 : jm);
            double l = sm[jc - 1], c0 = sm[jc], rt = sm[jc + 1];
            double den = l - 2 * c0 + rt, off = 0.0;
            if (fabs(den) > 1e-9) off = 0.5 * (l - rt) / den;
            if (off < -0.5) off = -0.5;
            if (off > 0.5) off = 0.5;
            double rad = (*r + (-4.0 + 0.5 * jc)) + off * 0.5;
            memcpy(srt, sm, sizeof sm);
            qsort(srt, RIDGE_R, sizeof(double), cmp_d);
            double prom = c0 - srt[RIDGE_R / 2];
            w[m] = ((jm == 0 || jm == RIDGE_R - 1) ? 0.0 : 1.0) * (prom > 0 ? prom : 0.0);
            px[m] = *cx + ca[m] * rad;
            py[m] = *cy + sa[m] * rad;
        }
        double S[9] = {0};  /* xx xy x yy y 1 xz yz z */
        for (int m = 0; m < RIDGE_M; m++) {
            double X = px[m], Y = py[m], Z = X * X + Y * Y, W8 = w[m];
            S[0] += W8 * X * X; S[1] += W8 * X * Y; S[2] += W8 * X;
            S[3] += W8 * Y * Y; S[4] += W8 * Y; S[5] += W8;
            S[6] += W8 * X * Z; S[7] += W8 * Y * Z; S[8] += W8 * Z;
        }
        double A[3][3] = {{S[0], S[1], S[2]}, {S[1], S[3], S[4]}, {S[2], S[4], S[5]}};
        double bv[3] = {-S[6], -S[7], -S[8]}, sol[3];
        if (solve3(A, bv, sol) == 0) {
            double ncx = -sol[0] / 2, ncy = -sol[1] / 2;
            double q = ncx * ncx + ncy * ncy - sol[2];
            *cx = ncx;
            *cy = ncy;
            *r = sqrt(q > 0 ? q : 0);
        }
        double num = 0, ws = 0;
        for (int m = 0; m < RIDGE_M; m++) {
            double d = hypot(px[m] - *cx, py[m] - *cy) - *r;
            num += w[m] * d * d;
            ws += w[m];
        }
        *rms = ws > 0 ? sqrt(num / ws) : NAN;
    }
}

/* ---------------------------------------------------------------- track -- */
int opngx_track(const uint8_t *frames, int64_t k, int H, int W,
                const opngx_track_params *p,
                double *ox, double *oy, double *orad, double *opeak,
                double *oarea, int8_t *ofound, double *orms) {
    if (!frames || !p || !ox || !oy || !orad || !opeak || !oarea || !ofound || !orms)
        return -1;
    if (k < 0 || H < 1 || W < 1 || p->window < 1) return -1;
    int wh = p->window < H ? p->window : H;
    int ww = p->window < W ? p->window : W;
    int64_t wn = (int64_t)wh * ww;
    float *sub = (float *)malloc((size_t)wn * sizeof(float));
    if (!sub) return -2;
    const double nanv = NAN;
    for (int64_t f = 0; f < k; f++) {
        const uint8_t *fr = frames + (size_t)f * H * W;
        int cy0, cx0;
        locate(fr, H, W, p->locate_block, p->origin_x, p->origin_y, &cy0, &cx0);
        int y0 = cy0 - wh / 2, x0 = cx0 - ww / 2;
        if (y0 < 0) y0 = 0;
        if (y0 > H - wh) y0 = H - wh;
        if (x0 < 0) x0 = 0;
        if (x0 > W - ww) x0 = W - ww;
        float fpeak = 0;
        for (int yy = 0; yy < wh; yy++) {
            const uint8_t *row = fr + (size_t)(y0 + yy) * W + x0;
            float *dst = sub + (size_t)yy * ww;
            for (int xx = 0; xx < ww; xx++) {
                dst[xx] = (float)row[xx];
                if (dst[xx] > fpeak) fpeak = dst[xx];
            }
        }
        double peak = fpeak;
        double base = median_u8win(sub, wn);
        double thr = base + p->threshold * (peak - base);
        int64_t n = 0;
        for (int64_t i = 0; i < wn; i++) n += sub[i] > thr;
        double cx = nanv, cy = nanv, r = nanv, rms = nanv;
        int good = 0;
        if (p->method == 0) { /* circle */
            double S[9] = {0};
            for (int yy = 0; yy < wh; yy++) {
                const float *row = sub + (size_t)yy * ww;
                double Y = yy;
                for (int xx = 0; xx < ww; xx++) {
                    if (!(row[xx] > thr)) continue;
                    double X = xx, Z = X * X + Y * Y;
                    S[0] += X * X; S[1] += X * Y; S[2] += X;
                    S[3] += Y * Y; S[4] += Y; S[5] += 1;
                    S[6] += X * Z; S[7] += Y * Z; S[8] += Z;
                }
            }
            double A[3][3] = {{S[0], S[1], S[2]}, {S[1], S[3], S[4]}, {S[2], S[4], S[5]}};
            double bv[3] = {-S[6], -S[7], -S[8]}, sol[3] = {0, 0, 0};
            int ok = n >= 3 && solve3(A, bv, sol) == 0;
            if (!ok) { sol[0] = sol[1] = sol[2] = 0; }
            cx = -sol[0] / 2;
            cy = -sol[1] / 2;
            double q = cx * cx + cy * cy - sol[2];
            r = sqrt(q > 0 ? q : 0);
            double num = 0;
            for (int yy = 0; yy < wh; yy++) {
                const float *row = sub + (size_t)yy * ww;
                for (int xx = 0; xx < ww; xx++) {
                    if (!(row[xx] > thr)) continue;
                    double d = sqrt((xx - cx) * (xx - cx) + (yy - cy) * (yy - cy)) - r;
                    num += d * d;
                }
            }
            rms = sqrt(num / (double)(n > 1 ? n : 1));
            good = ok;
            if (p->refine && good && r >= 2.0 && wh >= 2 && ww >= 2)
                ridge_refine(sub, wh, ww, &cx, &cy, &r, &rms);
            if (!good) r = nanv;
        } else if (p->method == 1) { /* centroid */
            double sw = 0, sx = 0, sy = 0;
            for (int yy = 0; yy < wh; yy++) {
                const float *row = sub + (size_t)yy * ww;
                for (int xx = 0; xx < ww; xx++) {
                    double v = row[xx] - thr;
                    if (v <= 0) continue;
                    sw += v; sx += v * xx; sy += v * yy;
                }
            }
            good = sw > 0;
            cx = sx / (good ? sw : 1);
            cy = sy / (good ? sw : 1);
        } else { /* peak + parabolic */
            int64_t im = 0;
            for (int64_t i = 1; i < wn; i++) if (sub[i] > sub[im]) im = i;
            int py_ = (int)(im / ww), px_ = (int)(im % ww);
#define AT(yv, xv) ((double)sub[(size_t)((yv) < 0 ? 0 : ((yv) > wh - 1 ? wh - 1 : (yv))) * ww + \
                             ((xv) < 0 ? 0 : ((xv) > ww - 1 ? ww - 1 : (xv)))])
            double c0 = AT(py_, px_);
            double l = AT(py_, px_ - 1), rt = AT(py_, px_ + 1), u = AT(py_ - 1, px_), d = AT(py_ + 1, px_);
#undef AT
            double denx = l - 2 * c0 + rt, deny = u - 2 * c0 + d, offx = 0, offy = 0;
            if (fabs(denx) > 1e-9 && px_ > 0 && px_ < ww - 1) offx = 0.5 * (l - rt) / denx;
            if (fabs(deny) > 1e-9 && py_ > 0 && py_ < wh - 1) offy = 0.5 * (u - d) / deny;
            offx = offx < -0.5 ? -0.5 : (offx > 0.5 ? 0.5 : offx);
            offy = offy < -0.5 ? -0.5 : (offy > 0.5 ? 0.5 : offy);
            cx = px_ + offx;
            cy = py_ + offy;
            good = 1;
        }
        good = good && n >= p->min_pixels;
        ox[f] = cx + x0;
        oy[f] = cy + y0;
        orad[f] = r;
        opeak[f] = peak;
        oarea[f] = (double)n;
        ofound[f] = (int8_t)(good ? 1 : 0);
        orms[f] = rms;
    }
    free(sub);
    return 0;
}


/* ---------------------------------------------------------------- blobs -- */
/* Two-pass connected-component labelling with union-find (path halving).
 * Mirrors opngx/analysis/builtin/particles.py _blobs_numpy() exactly:
 * labels are provisional per pixel; stats are accumulated per root. */
static int32_t uf_find(int32_t *par, int32_t a) {
    while (par[a] != a) {
        par[a] = par[par[a]];
        a = par[a];
    }
    return a;
}

static void uf_union(int32_t *par, int32_t a, int32_t b) {
    a = uf_find(par, a);
    b = uf_find(par, b);
    if (a < b) par[b] = a;
    else if (b < a) par[a] = b;
}

int opngx_blobs(const uint8_t *frames, int64_t k, int h, int w, int thr, int dark,
                int min_area, int conn8, int32_t *count, double *total_area,
                double *mean_area, double *max_area, double *cx, double *cy) {
    if (!frames || k < 0 || h <= 0 || w <= 0 || !count || !total_area || !mean_area ||
        !max_area || !cx || !cy)
        return -1;
    const size_t npx = (size_t)h * (size_t)w;
    int32_t *lab = (int32_t *)malloc(npx * sizeof(int32_t));
    /* at most one new provisional label per pixel; label 0 = background */
    int32_t *par = (int32_t *)malloc((npx + 1) * sizeof(int32_t));
    int64_t *area = (int64_t *)malloc((npx + 1) * sizeof(int64_t));
    double *sx = (double *)malloc((npx + 1) * sizeof(double));
    double *sy = (double *)malloc((npx + 1) * sizeof(double));
    if (!lab || !par || !area || !sx || !sy) {
        free(lab); free(par); free(area); free(sx); free(sy);
        return -2;
    }
    for (int64_t f = 0; f < k; f++) {
        const uint8_t *fr = frames + (size_t)f * npx;
        int32_t next = 1;
        par[0] = 0;
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                const size_t i = (size_t)y * w + x;
                const int on = dark ? (fr[i] < thr) : (fr[i] > thr);
                if (!on) { lab[i] = 0; continue; }
                /* already-labelled neighbours: W, N (+ NW, NE if 8-conn) */
                int32_t nb[4];
                int nn = 0;
                if (x > 0 && lab[i - 1]) nb[nn++] = lab[i - 1];
                if (y > 0 && lab[i - w]) nb[nn++] = lab[i - w];
                if (conn8 && y > 0) {
                    if (x > 0 && lab[i - w - 1]) nb[nn++] = lab[i - w - 1];
                    if (x + 1 < w && lab[i - w + 1]) nb[nn++] = lab[i - w + 1];
                }
                if (!nn) {
                    par[next] = next;
                    lab[i] = next++;
                } else {
                    int32_t m = nb[0];
                    for (int q = 1; q < nn; q++) if (nb[q] < m) m = nb[q];
                    lab[i] = m;
                    for (int q = 0; q < nn; q++) uf_union(par, m, nb[q]);
                }
            }
        }
        for (int32_t l = 0; l < next; l++) { area[l] = 0; sx[l] = 0.0; sy[l] = 0.0; }
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                const size_t i = (size_t)y * w + x;
                if (!lab[i]) continue;
                const int32_t r = uf_find(par, lab[i]);
                area[r]++;
                sx[r] += x;
                sy[r] += y;
            }
        }
        int32_t n = 0;
        int64_t tot = 0, best = 0;
        int32_t bestl = -1;
        for (int32_t l = 1; l < next; l++) {
            if (par[l] != l || area[l] < (int64_t)(min_area > 0 ? min_area : 1)) continue;
            n++;
            tot += area[l];
            if (area[l] > best) { best = area[l]; bestl = l; }
        }
        count[f] = n;
        total_area[f] = (double)tot;
        mean_area[f] = n ? (double)tot / n : 0.0;
        max_area[f] = (double)best;
        cx[f] = bestl > 0 ? sx[bestl] / (double)area[bestl] : NAN;
        cy[f] = bestl > 0 ? sy[bestl] / (double)area[bestl] : NAN;
    }
    free(lab); free(par); free(area); free(sx); free(sy);
    return 0;
}


/* ---------------------------------------------------------------- focus -- */
int opngx_focus(const uint8_t *frames, int64_t k, int h, int w,
                double *laplacian_var, double *tenengrad, double *norm_variance) {
    if (!frames || k < 0 || h <= 0 || w <= 0 || !laplacian_var || !tenengrad || !norm_variance)
        return -1;
    const size_t npx = (size_t)h * (size_t)w;
    for (int64_t f = 0; f < k; f++) {
        const uint8_t *p = frames + (size_t)f * npx;
        /* pixel mean / variance over the whole frame (exact integer sums) */
        uint64_t s = 0, s2 = 0;
        for (size_t i = 0; i < npx; i++) { s += p[i]; s2 += (uint64_t)p[i] * p[i]; }
        const double mean = (double)s / (double)npx;
        const double var = (double)s2 / (double)npx - mean * mean;
        norm_variance[f] = mean > 0 ? var / (mean > 1e-9 ? mean : 1e-9) : 0.0;
        if (h < 3 || w < 3) { laplacian_var[f] = 0.0; tenengrad[f] = 0.0; continue; }
        int64_t ls = 0;
        double ls2 = 0.0, g2 = 0.0;
        const size_t m = (size_t)(h - 2) * (size_t)(w - 2);
        for (int y = 1; y < h - 1; y++) {
            const uint8_t *r0 = p + (size_t)(y - 1) * w, *r1 = p + (size_t)y * w, *r2 = p + (size_t)(y + 1) * w;
            for (int x = 1; x < w - 1; x++) {
                const int lap = r0[x] + r2[x] + r1[x - 1] + r1[x + 1] - 4 * r1[x];
                ls += lap;
                ls2 += (double)lap * lap;
                const int gx = (r0[x + 1] + 2 * r1[x + 1] + r2[x + 1]) - (r0[x - 1] + 2 * r1[x - 1] + r2[x - 1]);
                const int gy = (r2[x - 1] + 2 * r2[x] + r2[x + 1]) - (r0[x - 1] + 2 * r0[x] + r0[x + 1]);
                g2 += (double)gx * gx + (double)gy * gy;
            }
        }
        const double lm = (double)ls / (double)m;
        laplacian_var[f] = ls2 / (double)m - lm * lm;
        tenengrad[f] = g2 / (double)m;
    }
    return 0;
}
