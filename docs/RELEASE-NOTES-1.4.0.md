# opngx v1.4.0

## New in v1.4.0

### Visual redesign
- **opngx studio** rewritten in Qt/PySide6 with real CSS styling (QSS):
  pristine black `#050505` base, white fonts, coffee-green accents.
  Nothing cramped, nothing clipped — splitters let you resize panels.
- Dark theme throughout: cards, inputs, buttons, sliders, scrollbars.

### Frame viewer
- Scrub through any recording with a slider + ◀▶ step buttons.
- Frames render live with your *current* quality settings — move the
  brightness/contrast/gamma sliders and the preview updates instantly.

### Video render
- One dialog turns a `.bin` straight into an H.264 MP4.
- Frames stream into ffmpeg with **no intermediate files**.
- Stats shown live: frames encoded, %, encoder fps, video-so-far duration, ETA.
- Shows the output video length *before* you render (so you can pick the right fps).
- **ffmpeg is now bundled inside the Windows installer** — Render video works
  out of the box, no separate install.

### Help where you need it
- Rich HTML tooltips on every control.
- **Help → Field guide** (F1) documents every option with *worked numeric
  examples* — what raw value 100 becomes under reference/raw/custom modes,
  what gamma does, what contrast does.

### Sidecar-less recordings
- Your `SQ_100_s1.bin` case (no `.footage` sidecar): the studio now shows
  width × height fields (remembered per recording) so raw/custom extraction
  works, with clear error guidance when reference mode needs a sidecar.

### Batch processing
- Selecting a folder immediately scans and lists every recording found.
- Per-bin progress in the status bar + a summary log when done.

### Performance
- Video render bulk pipeline: **805 → 1065 fps** (+32%) for 3000 frames,
  verified frame-exact via ffprobe.

## Install

### Windows (recommended)
Download `opngx-setup-1.4.0.exe` and double-click. It installs:
the C command-line engine, the opngx studio GUI, ffmpeg, and docs —
per-user, no admin rights. Launch **opngx studio** from the Start Menu.

Alternatives:
- `opngx-studio-portable-1.4.0.exe` — GUI without installing.
- `opngx-engine-1.4.0.exe` — raw CLI binary.

### Linux
`opngx-1.4.0-linux-x86_64.tar.gz` — one fully-static executable.
```bash
tar xzf opngx-1.4.0-linux-x86_64.tar.gz
sudo mv opngx-linux /usr/local/bin/opngx-engine
opngx-engine --help
```

## Quality modes (reference mode examples)
With the verified operating point (B49, C18):

| raw byte | reference | raw  | custom B20 C18 | custom γ2.0 |
|----------|-----------|------|----------------|-------------|
| 40       | 121       | 40   | 149            | 6           |
| 100      | 204       | 100  | 255            | 39          |
| 150      | 255       | 150  | 255            | 93          |

Formula: `out = clamp(round((v + Brightness) × (1 + Contrast/50)), 0, 255)`
