# FAQ

**Is output really identical to the vendor exporter?**
Yes — pixel-for-pixel, proven by decoding both PNG streams and comparing every scanline (`opngx verify`). Byte-identical *files* are impossible across zlib builds; pixel equality is the correct criterion.

**Why does `raw` mode look different from the vendor player?**
The vendor transform clips highlights: any raw byte ≥ 139 becomes 255 at B49/C18. Raw mode shows the true sensor data.

**My recording has no `.footage` sidecar.**
Enter width × height in the studio (or `--width/--height` on the CLI) and use `raw` or `custom` mode. Reference mode needs the sidecar to know the vendor curve.

**Can I check an extract without the vendor reference PNGs?**
Yes: `opngx-engine verifybin --bin X.bin OUT_DIR` re-derives expected pixels from the recording itself.

**Does it use my GPU?**
GPUs are detected and reported, but compression — the bottleneck — has no mature ROCm library, so all CPU cores with runtime SIMD dispatch is measurably fastest here. See [[Benchmarks]].

**16-bit output — more quality?**
No extra detail: source is 8-bit. Values are stored ×257 in a 16-bit container for pipelines that require it (PNG only).

**Windows says the exe "crashes" instantly when double-clicked?**
That's the CLI engine launched bare. Use **opngx studio** from the Start Menu, or run `opngx-engine --help` in a terminal.
