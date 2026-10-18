# opngx v2.2.0: analyse a video, or any .bin, straight from the Analyze tab

**Released:** 2026-10-18 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

Extraction and pixels are unchanged.

## Analyze: choose the .bin or the video to analyse

The **Analyze** tab has a new source, **a file**, next to *the loaded recording*
and *every recording in the batch folder*. **Browse…** picks:

- any **`.bin` recording**, without loading it in Extract first;
- a **video**: MP4, MKV, MOV, AVI, WebM, GIF, MPEG, WMV, MXF.

Once you pick a file, the tab describes it:
- for a recording: its size, frame count and rate;
- for a video: its codec, whether its pixels are exact (lossless) or not, its
  size, frame count and the frame rate used for the time axis.

Every module (motion tracking, Brownian/trap, focus, drift, particles, flicker,
luminosity, contrast, ROI statistics, your own) runs on a video unchanged. So do
the trajectory overlay, the plots and the data export.

**On the command line and in Python:**

```bash
opngx analyze clip.mp4 -m luminosity -o lum.csv
opngx analyze phone.mov -m motion_tracking --fps 240 -o traj.csv
```

```python
oa.analyze("clip.mkv", ["motion_tracking"], fps=5000)
```

## What a video can and cannot give

- **Time:** a video only knows its playback rate (e.g. 25 fps), not the camera's
  (e.g. 5000 fps).
  - **Videos opngx exports now carry the camera rate and their true picture
    size** in their metadata, so analysing them gives real seconds.
  - For any other video, enter the camera rate (*time axis: frames per second*,
    `--fps`, `fps=`).
- **Pixels:** only lossless codecs keep exact values.
  - On 5,000 frames of a real recording, an **FFV1** video gives exactly the
    same luminosity results as the `.bin` with the same curve.
  - **H.264** differs by up to 0.10 grey levels in the mean, and the log says so.
  - The time axis agrees with the camera clock to 1 µs.

  Measure on the `.bin` or an FFV1 video.
- **Odd crops:** H.264's padding row/column is removed again for opngx's own
  videos.
- **Colour videos** are analysed as their brightness.

## How it works

The video is decoded once with the bundled ffmpeg. Only the frames being
analysed are kept, in a temporary file that is removed afterwards, so start /
count / every-Nth-frame apply as for a recording and frame numbers are the
video's own. The frame shown for a result row is picked by its exact timestamp.

## Verification

- **pytest** 121/121. New tests:
  - FFV1, GIF and H.264 against the `.bin` (frame numbers, values, time axis,
    tracking accuracy);
  - odd-crop padding;
  - exact preview frames;
  - the Analyze tab end to end with a video.
- **Packaged-app self-test:** the analysis self-test inside the Windows and Linux
  binaries now also analyses an FFV1 video made by the bundled ffmpeg. It must
  equal the `.bin` exactly.
- **Engine suite** 46/46.

## Assets

| File | What |
|---|---|
| `opngx-setup-v2.2.0.exe` | Windows installer: studio, engine, ffmpeg, docs, sample modules; uninstaller |
| `opngx-studio-portable-v2.2.0.exe` | Windows studio, single file, no install |
| `opngx-studio-linux-x86_64-v2.2.0` | Linux studio, single file (engine, Qt, ffmpeg) |
| `opngx-engine-v2.2.0.exe` | Windows CLI engine only |
| `opngx-2.2.0-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.2.0-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.2.0.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.2.0-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.2.0_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
