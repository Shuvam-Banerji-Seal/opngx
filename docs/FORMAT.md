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
| file names | `{prefix}%05d{ext}` (widens to 6 digits after 99999) | `brow_00000.Png` → `brow_100000.Png` |
| extension case | capital P | `.Png` |

> **Rollover note:** `%05d` zero-pads to 5 digits; frame 100 000 becomes `brow_100000.Png` (6 digits, no truncation, no wrap). The verifier sorts **numerically** by the embedded index, so `100000` correctly follows `99999` (lexicographic would misorder). Current footage is 50 000 frames, so no existing recording hits the boundary; the tool is future-proof for ≥100k runs.

opngx defaults reproduce these exactly (`--prefix brow_ --ext .Png`).
