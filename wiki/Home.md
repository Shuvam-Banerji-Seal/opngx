# opngx

**Ultra-fast, pixel-exact extraction of Optronis TimeViewer `.bin` footage to PNG — all CPU cores by default, CLI + GUI + Python library.**

```
3.84 GB .bin ──▶ 50 000 PNGs in ~50 s   (verified pixel-exact vs vendor exports)
```

* Repo: https://github.com/Shuvam-Banerji-Seal/opngx
* Releases: https://github.com/Shuvam-Banerji-Seal/opngx/releases
* License: MIT

## Pages

* [[Format]] — reverse-engineered `.bin` layout and the proven display transform
* [[Benchmarks]] — measured throughput tables and tuning rules of thumb
* [[FAQ]] — fidelity, byte-exactness, GPU, sidecar-less recordings

## Quick start

```bash
opngx extract recording.bin -o frames/            # vendor-identical PNGs
opngx verifybin --bin recording.bin frames/       # prove vs source, no refs needed
opngx video recording.bin -o clip.mp4             # straight to H.264
opngx-ui                                          # studio GUI
```
