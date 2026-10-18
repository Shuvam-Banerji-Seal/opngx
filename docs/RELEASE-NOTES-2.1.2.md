# opngx v2.1.2: the studio for Linux, in one file

**Released:** 2026-10-18 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

Extraction, pixels and file naming are the same as in v2.1.1. This release adds
the studio for Linux.

## Linux studio: one file, nothing to install

`opngx-studio-linux-x86_64-v2.1.2` is the complete studio in one executable,
like the portable Windows studio. It contains:
- the C engine (`libopngx.so`, all cores);
- the `opngx-engine` command-line tool, used by *Verify*;
- Qt;
- ffmpeg, with every video codec.

```bash
chmod +x opngx-studio-linux-x86_64-v2.1.2
./opngx-studio-linux-x86_64-v2.1.2
```

- **Runs on** any x86-64 distro with glibc 2.35 or newer (Ubuntu 22.04+,
  Debian 12+, Fedora, Arch, …), natively on **Wayland** and on X11.
- **App menu:** `--install-desktop` adds an application-menu entry with the opngx
  icon. It writes to `~/.local/share` only and needs no root.
  `--uninstall-desktop` removes the entry again.
- **Tested like the Windows exe.** Every release builds it on Ubuntu 22.04 and
  runs these self-tests inside the finished binary:
  - the main window;
  - native extraction checked by the bundled engine;
  - the analysis modules and motion tracking;
  - the batch window;
  - every video codec through the bundled ffmpeg, with FFV1 and GIF decoded
    back bit-exact;
  - a speed test that compares in-app extraction with the bundled engine.

  The desktop entry is also checked with `desktop-file-validate`.
- **Locally on Arch** (16 cores, Hyprland/Wayland), all six self-tests pass. The
  studio extracts at 107 % of the bundled command-line engine's speed and opens
  as a native Wayland window.

The command-line-only Linux downloads (static engine tarball and `.deb`) and the
Python wheels are unchanged.

## Build

- `opngx.spec` builds the studio on Windows and Linux. `OPNGX_NATIVE_DIR`
  points it at the engine build folder.
- The release workflow can be started by hand (`workflow_dispatch`). It then
  builds and tests everything without publishing.

## Assets

| File | What |
|---|---|
| `opngx-studio-linux-x86_64-v2.1.2` | **new:** Linux studio, single file (engine, Qt, ffmpeg) |
| `opngx-setup-v2.1.2.exe` | Windows installer: studio, engine, ffmpeg, docs, sample modules; uninstaller |
| `opngx-studio-portable-v2.1.2.exe` | Windows studio, single file, no install |
| `opngx-engine-v2.1.2.exe` | Windows CLI engine only |
| `opngx-2.1.2-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl` | Python package + C engine, Linux x86_64 |
| `opngx-2.1.2-py3-none-win_amd64.whl` | Python package + C engine, Windows amd64 |
| `opngx-2.1.2.tar.gz` | Python sdist (numpy fallback) |
| `opngx-2.1.2-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_2.1.2_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
