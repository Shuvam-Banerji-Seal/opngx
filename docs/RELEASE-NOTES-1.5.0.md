# opngx v1.5.0

**Developer:** Shuvam Banerji Seal

## New in v1.5.0

### `verifybin` — verify against the source recording itself
- `opngx-engine verifybin --bin X.bin OUT_DIR` proves an extract is
  pixel-exact **without any vendor reference set**: every output file's
  decoded pixels are compared to the LUT-mapped frame at the absolute
  index encoded in its filename.
- Works for mid-recording subranges (`--start N` extracts), custom/raw
  modes, gray and 16-bit containers.
- Python: `opngx.verify_against_bin(bin_path, out_dir, ...)` (JSON report).
- `--json` machine-readable output on both `verify` and `verifybin`.

### Push-progress callback (ABI 4)
- New optional `opngx_params.progress_fn` / `progress_user`: the engine now
  pushes progress (~100 ms throttle + guaranteed final call) instead of
  forcing bindings to poll. Bindings on other languages get live progress
  for free. ABI version bumped 3 → 4; ctypes mirror updated in lockstep.

### Truthful backend reporting (hardening)
- `opngx_stats.backend_used` now reflects the compressor actually linked
  into the binary — a zlib-only build reports `zlib`, not `libdeflate`.

### Timing analysis — `opngx timestamps`
- Decodes the camera-clock layer hidden in every frame header.
- Reports span, effective fps, delta min/median/max, gap count and where
  the first gaps are — proof of dropped/irregular frames.
- brow_1.2 measured: 50 000 frames, ±1 tick jitter, **500.000 fps
  effective, zero drops**. CSV + JSON output.

### Full sidecar exposure
- `opngx.probe(x).extra` (and metadata.json) now carry every field the
  vendor stored: FramerateReal, camera Serial/Model, TriggerROI window,
  per-channel gains, BayerFormat, acquisition wiring — 41 tags on a real
  recording.

### Studio UX overhaul
- Every action button has an icon (open/info/play/stop/apply/arrows) plus
  richer tooltips — nothing is a mystery button anymore.
- **Live CPU & RAM chips** in the header (Linux /proc and Windows
  GetSystemTimes under the hood) — watch all cores saturate during an run.
- Render-video dialog: duration preview, in-dialog progress bar, status
  line, Stop button — and progress mirrors onto the main window bar while
  rendering; main Cancel stops it too.
- Help menu gained four guides: Timestamps, Sidecar fields, Verification,
  plus the existing Field guide/Tuning. About names the developer.

## Upgrade notes

Rebuild/reinstall engine + Python package together: ABI moved 3 → 4 and the
ctypes handshake refuses mismatches by design.

## Full changelog since v1.4.0
- verifier pairs files BY NAME — mid-bin subrange extracts verify correctly
  against vendor reference sets (previously positional pairing false-failed)
- Qt studio: verify PASS/FAIL dialog restored (signal wiring fixed),
  sidecar-less width/height fields wired end-to-end, worked-examples guide,
  live frame refresh, duplicate log handler removed
- dead per-job scratch allocation removed; installer/rc metadata unified
