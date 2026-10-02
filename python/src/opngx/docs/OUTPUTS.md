# Output formats and video codecs (v2.1)

opngx writes the recording's pixels, mapped through the selected transform
(reference = TimeViewer's curve, raw = sensor values, custom = your curve).
A **lossless** output stores exactly those values; a **lossy** one stores an
approximation. This page lists what every output keeps, measured on real
footage, and which one to pick.

- [Which output should I use?](#which-output-should-i-use)
- [Image formats](#image-formats)
- [Video codecs](#video-codecs)
- [Check it yourself](#check-it-yourself)

---

## Which output should I use?

| you want to… | use | why |
|---|---|---|
| reproduce TimeViewer's export | **PNG** (default) | pixel-identical, the same RGBA container |
| measure / analyse in other software | **PNG grey**, **TIFF**, **PGM** | lossless; PGM and TIFF open everywhere |
| one file for the whole recording (Python, MATLAB) | **NumPy stack** (`.npy`) | lossless, opens 50,000 frames instantly with `np.load(p, mmap_mode="r")` |
| archive a recording as video, losslessly | **FFV1** (`.mkv`) | bit-exact, ~45 % of the size of PNGs |
| slides, sharing, any player | **H.264** (`.mp4`) | plays everywhere; lossy but excellent at CRF 18 |
| the smallest files | **AV1**, **H.265**, **VP9** | lossy; slower to encode |
| video editing (Premiere, Resolve, Final Cut) | **ProRes 422 HQ** (`.mov`) | near-lossless (max error 3 levels) |
| a short clip in a chat or slide | **GIF** | lossless for this 8-bit footage; files grow fast |
| small previews | **JPEG** or **WebP** below 100 | lossy - never for measurements |

## Image formats

Measured on 1,000 full frames (256×300) of `brow_2_0`, reference transform,
16 threads. "Bit-exact" means every decoded file equals the expected pixels;
the decoding is independent (Pillow / a Netpbm reader), not opngx's own.

| format | bits | written by | bit-exact | max error | PSNR | KiB/frame | frames/s |
|---|---:|---|:---:|---:|---:|---:|---:|
| PNG (grey) | 8 | C engine | yes | 0 | ∞ | 35.5 | 3,872 |
| PNG (grey) | 16 | C engine | yes | 0 | ∞ | 44.6 | 8,303 |
| TIFF | 8 | C engine | yes | 0 | ∞ | 75.1 | 18,509 |
| TIFF | 16 | C engine | yes | 0 | ∞ | 150.1 | 33,698 |
| PGM | 8 | C engine | yes | 0 | ∞ | 75.0 | 12,657 |
| PGM | 16 | C engine | yes | 0 | ∞ | 150.0 | 32,743 |
| BMP | 8 | C engine | yes | 0 | ∞ | 76.1 | 54,669 |
| WebP (quality 100) | 8 | Pillow | yes | 0 | ∞ | 37.5 | 569 |
| JPEG 2000 | 8 | Pillow | yes | 0 | ∞ | 40.1 | 498 |
| NumPy stack | 8 | numpy | yes | 0 | ∞ | 75.0 | 6,632 |
| NumPy stack | 16 | numpy | yes | 0 | ∞ | 150.0 | 3,193 |
| JPEG q 95 | 8 | C engine | no | 11 | 42.8 dB | 26.3 | 2,936 |
| JPEG q 90 (default) | 8 | C engine | no | 19 | 39.8 dB | 15.8 | 4,946 |
| JPEG q 75 | 8 | C engine | no | 30 | 37.3 dB | 7.7 | 5,897 |
| WebP q 95 | 8 | Pillow | no | 8 | 45.2 dB | 20.9 | 765 |
| WebP q 75 | 8 | Pillow | no | 31 | 36.7 dB | 3.6 | 1,110 |

Notes:
- **PNG's default container** is TimeViewer's RGBA (four equal channels). The
  *grey* option (`--channels gray`) stores the same pixels as one channel, about
  2.5× faster and a third smaller.
- **16 bit** stores the 8-bit values × 257 (0→0, 255→65535) for pipelines that
  require 16-bit input. It adds no precision, because the sensor is 8-bit.
- **Lossy WebP beats JPEG** at a similar size: 20.9 KiB at 45.2 dB against
  JPEG's 26.3 KiB at 42.8 dB.
- **Without the C engine** (sdist installs), the pure-Python fallback writes the
  same bit-exact files for every lossless format, only slower.

## Video codecs

All videos are made by the **ffmpeg bundled with the studio** (on Windows, the
gyan.dev 7.1 build, so nothing needs installing). Measured on 120 frames of
`brow_1.2`, cropped to an odd 201×177 window, decoded back with ffmpeg.

| codec | container | pixels | max error | PSNR | KiB/frame | encode frames/s |
|---|---|:---:|---:|---:|---:|---:|
| **FFV1** | .mkv | **bit-exact** | 0 | ∞ | 19.8 | 2,045 |
| **GIF** | .gif | **bit-exact** | 0 | ∞ | 14.5 | 1,299 |
| ProRes 422 HQ | .mov | lossy | 3 | 50.0 dB | 28.3 | 1,071 |
| H.264 (CRF 18) | .mp4 | lossy | 20 | 40.7 dB | 0.44 | 1,159 |
| AV1 (CRF 30) | .mkv | lossy | 24 | 41.4 dB | 0.13 | 348 |
| VP9 (CRF 30) | .webm | lossy | 25 | 39.2 dB | 0.10 | 370 |
| H.265 (CRF 22) | .mp4 | lossy | 33 | 39.0 dB | 0.16 | 359 |
| Motion-JPEG (q 2) | .avi | lossy | 12 | 40.9 dB | 7.0 | 2,209 |
| H.264 on the GPU | .mp4 | lossy | - | - | - | NVIDIA / Intel / AMD when present |

- **Lossy codecs and the same image:** inter-frame codecs (H.264/H.265/VP9/AV1)
  compress static scenes to almost nothing, hence < 1 KiB per frame.
- **Odd crop sizes:** 4:2:0 codecs need even sizes, so they get one black
  row/column of padding. FFV1, GIF and MJPEG keep the exact size.
- **GPU H.264:** the encoder is tried for real before it is offered (a listed
  encoder can still lack a GPU or driver).
- **Quality knob:** the default is shown in the studio and with
  `opngx formats`. It is a CRF (lower = better), `q` for MJPEG, or a QP for the
  GPU encoder.

## Check it yourself

- **Studio → System → Format check:** writes the loaded recording in every image
  format, decodes each file independently and reports bit-exactness, error and
  size.
- **Studio → Video → "Check the last video is bit-exact":** decodes an FFV1 / GIF
  video and compares every frame with the extracted pixels.
- **Command line:**
  ```bash
  opngx formats                                  # every format and codec, available or not
  python scripts/format_quality.py REC.bin --frames 1000 --markdown   # the image table above
  ```
