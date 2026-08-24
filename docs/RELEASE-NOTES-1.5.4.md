# opngx v1.5.4 — Windows deep-hardening

**Developer:** Shuvam Banerji Seal

A dedicated bug hunt across the whole Windows surface. Five real defects
found and fixed, each with a permanent regression gate.

## 1. Non-ASCII paths (the big one)
Every Windows file API in the engine used ANSI-codepage variants
(`CreateFileA`/`fopen`). Windows ANSI is **not UTF-8**, so any path with
non-ASCII characters — `C:\Users\José`, `D:\भीम\recording.bin`,
`ünïcode output` — failed or mangled. The engine now converts UTF-8 →
wide explicitly and uses `CreateFileW`/`FindFirstFileW`/wide `mkdir`
everywhere: mapping, writing, directory creation, enumeration, sidecar
parsing, metadata, verification. A dual decoder (UTF-8 first, system
codepage fallback) handles both Python-originated paths and console
argv; the CLI entry is now `wmain`, so **full-Unicode argv works on real
Windows**.

*Found by hunting, proven under Wine, gated by T-20 (non-ASCII output
dir, Linux + Wine).*

## 2. Directory enumeration aliasing
The new wide enumerator initially lost the first entry and duplicated
the last (pre-read buffer aliasing) — caught by the 200-file gate before
it could ship.

## 3. Installer could destroy a large user PATH
The setup appended itself to `PATH` via a fixed 4 KiB buffer and wrote
the (truncated) value back — users with long PATHs would lose entries.
Now size-queried, protected above 32 KiB, and the uninstaller strips
safely. Uninstall also **tells you when a file was locked** by a running
app instead of claiming removal.

## 4. Console encoding crashes
Redirecting CLI output on Windows (`opngx … > log.txt`) crashed on
`→`/`µ` (locale codepage). Output streams are now UTF-8 with replacement.
`freeze_support` added for frozen fallback pools.

## 5. Unsafe filenames from camera metadata
Camera names from vendor XML can contain `\/:*?"<>|` — the studio now
sanitizes every derived filename (video output, suggested folders, batch
subdirs).

## Verification
- Linux 24/24 engine gates · Wine (real Windows binary) **24/24**
- 48/48 pytest incl. new sanitizer + probe gates
- Packaged selftests (UI / Engine / Video) green on the Windows runner
- Note: the exe is unsigned — Windows SmartScreen may ask for
  "More info → Run anyway" on first launch.
