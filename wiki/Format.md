# The Optronis `.bin` format

Full write-up with proofs lives in the repo: [docs/FORMAT.md](https://github.com/Shuvam-Banerji-Seal/opngx/blob/main/docs/FORMAT.md).

## Frame layout (no global header)

```
offset  size  field
0       8     u64 LE timestamp (camera clock ticks)
8       W*H   pixel data, 1 byte/pixel grayscale
--- next frame ---
```

Frame stride = `8 + W*H`. Proof: frame 0's timestamp equals `<TimeMarkerReference>` in the `.footage` XML.

`<BitsPerPixel>1</BitsPerPixel>` does **not** mean bit-packed data.

## Display transform (vendor PNG export)

```
out = clamp( round_half_up( (raw + Brightness) × (1 + Contrast/50) ), 0, 255 )
```

At the verified operating point B=49 / C=18 the multiplier is 1.36× and highlights clip at raw ≥ 139.
opngx's `raw` mode skips the transform entirely, preserving what the vendor export throws away.

## Naming

| Item | Rule | Example |
|---|---|---|
| output dir | camera name, `.` → `_` | `brow_1.2` → `brow_1_2` |
| files | `{prefix}%05d{ext}` | `brow_00000.Png` |
