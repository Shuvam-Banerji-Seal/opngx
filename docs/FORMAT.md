# The Optronis `.bin` Format — Reverse-Engineering Notes

This document describes the on-disk format produced by **Optronis TimeViewer**
high-speed-camera systems, as reverse-engineered from sample footage
(`brow_*` series) and proven against vendor-exported PNG references.

## Container pair

Every recording consists of two files:

| File | Role |
|---|---|
| `<name>.bin`     | raw frame data (3.84 GB for 50k frames @ 256×300) |
| `<name>.footage` | XML sidecar with geometry, timing and display settings |

## Frame layout

The `.bin` file has **no global header**. It is a flat sequence of frames:

```
offset  size  field
0       8     u64 LE timestamp (camera clock ticks)
8       W*H   pixel data, 1 byte per pixel, row-major, top-left first
--- next frame immediately follows ---
```

Frame stride is therefore `8 + W*H` bytes. For 256×300: `76 808` bytes/frame;
50 000 frames × 76 808 = 3 840 400 000 bytes = exact observed file size.

**Timestamp proof:** frame 0's header decodes to `10 200 535`, which equals
`<TimeMarkerReference>10200535</TimeMarkerReference>` in the sidecar.

Note: the sidecar's `<BitsPerPixel>1</BitsPerPixel>` does *not* mean bit-packed
data — pixels are stored one byte each regardless.

## Display transform (vendor PNG export)

Vendor exports are RGBA PNGs where R=G=B=gray, A=255. The gray channel is a
pure function of the stored byte:

```
out = clamp( round_half_up( (raw + Brightness) × (1 + Contrast/50) ), 0, 255 )
```

with `Brightness`/`Contrast` taken from `<SettingsProcessing>` in the sidecar.
For the verified operating point (B=49, C=18):

* `(34+49)×1.36 = 112.88 → 113`
* `(139+49)×1.36 = 255.68 → clamp 255`  ← vendor export clips highlights here

**Fidelity note:** because the vendor transform saturates at raw ≥ 139, the
reference PNGs destroy sensor information. opngx's `raw` mode writes the
untransformed bytes (identity LUT), preserving everything the camera saw.
Fractional parts of `(v+49)×1.36` are multiples of 0.04, so rounding ties never
occur at this operating point; half-up rounding is used throughout anyway.

## Reference PNG structure

Vendor exports use: color type 6, bit depth 8, all-zero row filters, chunks
`IHDR, sRGB(intent 0), gAMA 45455, pHYs 3779×3779 m⁻¹, IDAT, IEND`. The IDAT
zlib header is `78 5E` (fast-level hint from the vendor's Windows zlib build).
Byte-exact stream reproduction across zlib builds is impossible; **pixel
equality of decoded scanlines** is the correct equivalence criterion, and it is
what opngx proves in verification.

## Naming conventions observed

| Item | Rule | Example |
|---|---|---|
| output dir | camera name, `.` → `_` | `brow_1.2` → `brow_1_2` |
| file names | `{prefix}{frame}{ext}`, the frame number zero-padded to one width for the whole recording (below) | `brow_00000.Png`; `brow_000000.Png` … `brow_123455.Png` |
| extension case | capital P | `.Png` |

> **Frame-number width (v2.1.1).** The width is `max(5, digits of the last
> possible frame index)`, taken from the `.bin` size. It is the same for every
> frame and for every partial or resumed run of that recording. Up to 100,000
> frames (indices 0…99,999) this gives TimeViewer's 5 digits. 100,001 frames to
> 1,000,000 get 6 digits, and so on, with no upper limit. So **sorting by name
> is sorting by frame**, in every tool (`ls`, Explorer, `sorted(glob(...))`,
> ImageJ, MATLAB `dir`).
>
> Before v2.1.1, `%05d` made frame 100,000 `brow_100000.Png`. A plain name sort
> put it between `brow_10000.Png` and `brow_10001.Png`, so a recording longer
> than 100,000 frames was analysed out of order.

opngx defaults reproduce these exactly (`--prefix brow_ --ext .Png`).

## Frame order and the output folder (v2.1.1)

Analysis that reads a folder of frames must see them in recording order and
only from one recording. opngx guarantees three things:

1. **Names sort in frame order**, with the fixed width above.
2. **File dates sort in frame order.** Frames are written in parallel, so their
   natural modification times are out of order. opngx sets frame *i* of a run to
   `start + i` milliseconds. "Sort by date modified" therefore equals frame order
   too.
3. **One folder, one sequence.** The hidden file `.opngx-run` in the output
   folder records which recording (first timestamp, frame count, size) and which
   settings (curve, bit depth, channels, format, quality, crop, naming) made
   the frames there. A later run into the same folder is allowed only if both
   match, as when you re-run or extend the same extraction. Anything else is
   refused, because it would leave frames of two recordings, or two brightness
   curves, side by side under one numbering. The refusal names the folder and
   the source.
   - The **studio** asks whether to use a new folder (`…_2`) or delete the old
     frames. It deletes only the files of the earlier opngx run; other files stay.
   - The **CLI and Python API** refuse. `--allow-mixed` / `allow_mixed=True`
     overrides this when mixing really is intended.

   Frames extracted before v2.1.1 have no `.opngx-run`, so the guard cannot
   know where they came from. Extract them again into an empty folder if a
   folder might hold more than one run.

## Region of interest (v1.7.0)

`--crop X,Y,W,H` restricts extraction to a rectangle of the recorded frame.
It is a **pure pixel selection** — no resampling, no interpolation, no new
information:

```
output pixel (x, y)  ==  LUT( source pixel (X + x, Y + y) )
output geometry      ==  W × H
```

Consequences worth stating explicitly, because they are what make cropping
safe to use on measurement data:

* A cropped frame is **bit-identical** to the corresponding sub-rectangle of
  an uncropped one. T-23 asserts exactly that, against an independently
  computed expectation.
* `--crop 0,0,W,H` is byte-identical to no crop at all (also gated), so a
  crop of the full frame costs nothing and changes nothing.
* `W` or `H` may be `0`, meaning "to the frame edge": `--crop 10,5,0,0` on a
  64×48 frame encodes 54×43. (The v1.7.0 engine expanded `0` to the *full*
  width instead and rejected that example; fixed in v1.8.0, gated by T-25.)
* An MP4 render of an odd-sized crop is padded by one black column/row —
  H.264 4:2:0 cannot encode odd dimensions. Image outputs are never padded.
* A rectangle that does not fit inside the frame is rejected with a
  crop-specific diagnostic, not clamped.
* `metadata.json` records both the source geometry and the result:
  `width`/`height` (source) plus `output_width`/`output_height` and `crop`.

`opngx-engine verifybin` and `opngx.verify_against_bin()` take the same
`--crop` and re-derive the identical window, so verification of a cropped
extraction is meaningful. Verifying a cropped run *without* `--crop` fails
by design — the gate proves that too, so a forgotten flag cannot masquerade
as a pass.

## Batch output identity (v1.7.0)

In the mother-folder architecture the recording **folder** is the identity
of a recording, not its `.bin` filename:

```
Footages/
  camA/recording.bin
  camB/recording.bin     <- same filename, different recording
FramesOut/
  camA/PNG/…             <- v1.7: keyed on the recording folder
  camB/PNG/…
```

Keying on the filename collapsed both into `FramesOut/recording/PNG/` and
each run overwrote the previous one frame for frame. The CLI additionally
refuses to start a batch that would still collide, naming both paths rather
than destroying output.
