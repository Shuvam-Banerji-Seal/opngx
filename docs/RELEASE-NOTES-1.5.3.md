# opngx v1.5.3 — Windows field-report hotfixes

**Developer:** Shuvam Banerji Seal

## Fixed (from real Windows field reports, 11th/12th-gen laptops included)

### 1. "native run failed: unknown" — real error was being swallowed
The Python layer read the engine's *creation* error buffer after a *run*
failure, so the actual cause (truncated file, disk-full, permission…) was
replaced by the word "unknown". It now surfaces the engine's own message
plus the exit code. The engine's abort message also decodes the failure
mask in plain language (write failure / disk full / OOM / …) and names the
output directory.

### 2. Video rendering: "The system cannot find the file specified"
`render_video` launched the literal PATH name `ffmpeg` even though the
installer bundles one — it only used the resolver for the pre-check.
It now renders with the **resolved** ffmpeg (bundled `_MEIPASS` copy →
app dir → PATH). The studio exe also **bundles ffmpeg and
opngx-engine.exe inside itself**, so portable installs are self-contained.

### 3. "verify_against_bin needs the native binary"
The locator only looked for `opngx-engine` (no `.exe`) in fixed spots.
It now checks the DLL directory, the PyInstaller bundle, the app dir,
the repo build dir, and PATH — with and without `.exe`.

### 4. 720p / 4K scaling
The whole extraction-settings column now **scrolls** instead of clipping,
and the window minimum dropped from 980×680 to 760×520 — usable on 720p
laptops; Qt6 handles 4K DPI scaling.

## New packaged selftests (run on a real Windows runner every CI/release)
- `--selftest-engine`: synthesize recording → native extract → bundled
  engine CLI `verifybin` — the exact SQ_100_s1 chain that failed in the field.
- `--selftest-video`: renders through the **bundled** ffmpeg inside the exe.
- Spaces-in-output-path gates (T-18) run on Linux **and** under Wine
  against the Windows binary: 21/21.

## Verification this release
- Linux: 21/21 engine gates · 47/47 pytest
- Wine (Windows exe): 21/21 engine gates incl. spaces-path + verifybin
- Windows runner: packaged studio passes UI + Engine + Video selftests
