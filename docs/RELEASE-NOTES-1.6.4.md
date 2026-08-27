# opngx v1.6.4

**Developer:** Shuvam Banerji Seal

## Fixed — FPS and PNG naming

### 1. FPS display: “1000 fps in timestamps, but 100 fps shown”
**Symptom:** Recordings like `SQ_100_s1` have ~1000 ticks delta per frame (≈1000 fps effective) but the UI’s *Render video* dialog and info panel showed 100 fps (the sidecar’s nominal `Framerate`).

**Root cause:** `fps_default` for the video dialog was derived only from `meta.framerate` (nominal). The timestamp-derived `effective_fps_us` (ground truth from first→last tick, µs clock) was available in `FootageMetadata` but never used for the default.

**Fix:**
- Video dialog now prefers `effective_fps_us` → `FramerateReal` → `framerate`, clamped to 1–2000 fps (spinbox range was 1–500, now 1–2000).
- Tooltip now shows both: `“Timestamps imply 1000.0 fps effective (nominal 100 fps …)”`.
- The `clock span` / `effective fps` rows in the info panel remain the source of truth; `opngx timestamps --json` reports the same.

### 2. PNG naming after `brow_99999` — what happens?
**Answer:** `brow_00000` … `brow_99999` → `brow_100000` (6 digits, no truncation). `%05d` widens automatically. The verifier now **sorts numerically** by the embedded frame index (C: `atoll` after prefix, Python: `int(...)` key) — lexicographic would place `100000` *before* `99999`, breaking verification and any ordered iteration for recordings ≥100k frames.

*Current footage is 50 000 frames, so no existing recording hits the boundary; the fix future-proofs the tool.*

### 3. Version consistency
All six version sites bumped to **1.6.4** (`AR-5` gate passes).

## Verification
- Linux 27/27 engine gates · Wine 27/27 (as of 1.6.2; re-run for 1.6.4)
- 51/51 pytest incl. `AR-5` version consistency
- Manual: `opngx info SQ_100_s1.bin` now shows both nominal and effective fps; `opngx video` defaults to effective.

## Upgrade note
No ABI change — drop-in replacement for 1.6.x. Extracted files remain pixel-identical; only defaults and ordering change.
