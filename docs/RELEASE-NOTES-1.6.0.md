# opngx v1.6.0

**Developer:** Shuvam Banerji Seal

## 1. Structured output tree — one mother folder, everything in its place

Pick a mother output folder once. Every recording now lands in its own
subfolder with one folder per format:

```
OUT_MOTHER/
  SQ_100_s1/
    PNG/   SQ_100_00000.Png ...
    JPG/   ...            (when JPG is the selected format)
    BMP/   TIF/           (likewise)
    MP4/   SQ_100_s1.mp4  (Render-video joins its sibling folder)
```

- Studio: single-bin **and** Batch-folder runs both follow the tree; the
  Verify buttons automatically target the current recording's folder
  (with a graceful fallback to pre-1.6 flat folders).
- CLI: `batch --layout format --format jpg` (flat remains the default for
  scripts; `--format` works on extract too).

## 2. Fully resizable, remembered layout

The window is now true split-pane chunks — **drag any divider**:

- left column: settings (scrolls when tight) ⇕ output pane
- main: left ⇔ right panels
- right: info ⇕ frame-viewer ⇕ log

Geometry and all splitter proportions persist across sessions
(QSettings) — arrange it once on your 720p laptop or 4K monitor and it
comes back exactly that way.

## Verification
- 27/27 engine gates on Linux **and** under Wine with the real Windows
  binary (new T-21: layout=format tree + JPG decode + flat back-compat)
- 50/50 pytest (new AR-14 tree-helper + studio-tree gates)
- Packaged selftests (UI/Engine/Video) green on the Windows runner
