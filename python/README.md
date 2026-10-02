# opngx

Pixel-exact extraction of **Optronis TimeViewer** high-speed-camera `.bin`
recordings, plus video export and **analysis modules**.

- **Images:** PNG (TimeViewer-identical), TIFF/PGM in 8 or 16 bit, BMP,
  lossless WebP, JPEG 2000, a single-file NumPy stack, JPEG.
- **Video:** H.264/H.265/VP9/AV1/ProRes/MJPEG/GIF, or bit-exact lossless FFV1.
- **Analysis:** sub-pixel motion tracking, Brownian/optical-trap analysis, focus,
  stage drift, particle counting, flicker, luminosity, contrast, ROI statistics,
  and your own modules.

The hot paths are a C engine driven from Python through `ctypes`. There is a Qt
studio (`opngx-ui`).

## Install

The platform wheels on the
[releases page](https://github.com/Shuvam-Banerji-Seal/opngx/releases)
include the compiled engine: manylinux2014 x86_64 (any distro with glibc ≥ 2.17)
and Windows amd64. They work on Python 3.9 and newer.

```bash
pip install opngx-2.1.0-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl          # engine + CLI + library
pip install "opngx-2.1.0-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl[qt]"    # + the studio (PySide6, ffmpeg)
```

Without a platform wheel, installing from the sdist still works: extraction and
analysis fall back to numpy, and give the same pixels and numbers, only slower.
To get native speed from source, build the engine (`cmake -S . -B build && cmake
--build build`) and set `OPNGX_ENGINE=/path/to/libopngx.so`.

## Use

```bash
opngx info recording.bin
opngx extract recording.bin -o frames/                     # vendor-identical PNGs
opngx analyze recording.bin -m motion_tracking -o trajectory.csv
opngx analyze Footages/ --batch -m brownian_motion -p brownian_motion.pixel_size_um=0.1 -o Results/
opngx video recording.bin -o archive.mkv -c ffv1         # lossless, bit-exact video
opngx formats                                              # every format / codec and what it keeps
opngx modules                                              # built-in + your modules
opngx-ui                                                   # the studio
```

```python
import opngx
import opngx.analysis as oa

opngx.extract("recording.bin", "frames/", mode="raw")
run = oa.analyze("recording.bin", ["motion_tracking", "brownian_motion"])
traj = run["motion_tracking"]
traj.columns["x"], traj.columns["y"], traj.columns["time_s"]
traj.save("trajectory.csv")
print(run["brownian_motion"].summary["warnings"])
```

Writing your own analysis module is one class with one method. See the
[analysis guide](https://github.com/Shuvam-Banerji-Seal/opngx/blob/main/docs/ANALYSIS.md).
The studio also has an editor for modules and generated API documentation.

MIT licensed.
