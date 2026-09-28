# opngx v1.9.0 — multi-pane batch preview, 720p-to-4K interface

**Released:** 2026-09-28 · **ABI:** 5 (unchanged) · **License:** MIT
**Developer:** Shuvam Banerji Seal

Two requested features, three bug fixes (one of them the cause of every
failed CI run since v1.6.x), and a fix to the release pipeline that had
overwritten the v1.8.0 notes. Drop-in upgrade: same ABI, CLI and output
tree. Everything in [v1.8.0](RELEASE-NOTES-1.8.0.md) still applies.

---

## Batch window: multiple panes, each collapsible and full-screen

The batch window used to be one scrolling grid of cards. It is now a
multi-pane window:

| Pane | What it shows |
|---|---|
| **Recordings** (centre) | one card per recording: a real frame through the curve it will get, its crop drawn in context, geometry, fps, the B/C/G in force, status and progress. Cards reflow into as many columns as fit (it used to be a fixed 3). Click a card to preview it |
| **Preview** | the selected recording, large and pixel-exact, with its own frame scrubber, previous/next recording, crop overlay or *output only*, pixel readout (position, raw value, output value) and a Crop… button |
| **Compare** | every recording side by side at the same position in its timeline (one slider), crops outlined, so a batch can be sanity-checked before extracting |
| **Progress & log** | overall progress bar, a per-recording table (status, frames, fps, time, output folder; click a row to preview it) and a timestamped log |

Every pane has its own title bar:

* **▾ collapse** to just its title, and expand again;
* **⧉ pop out** into a separate window (for a second monitor), then dock
  it back;
* **⛶ full screen** (`Esc` returns it to where it was);
* **✕ hide**, and bring it back from the **View** menu.

Panes can also be dragged to another side, stacked, or tabbed together.
**F11** makes the whole window full screen and **F10** the Preview pane.
*View → Reset layout* restores the default arrangement. The layout and
window size are remembered between sessions.

## The interface adapts to the monitor: 720p to 4K

The studio used to open at a fixed 1180×800, which is taller than a 720p
screen, so the action bar started off-screen. On a 4K panel at 100% OS
scaling, every 11 px label was drawn at a quarter of its intended size.

* **Automatic scale** from the screen's logical height: 0.9× on 720p and
  768p, 1.0× on 1080p, 1.35× on 1440p, 2.0× on 4K at 100%. A 4K screen at
  200% OS scaling is 1080p logically, so it stays at 1.0× and Qt's own
  HiDPI handling does the rest. The factor scales fonts, every stylesheet
  pixel value, and the fixed widths and heights.
* **Re-scales live** when the window is moved to a different monitor.
* **View → Interface scale** pins 90% to 200% (or back to Auto), saved
  across sessions. **View → Fit window to this screen** recovers a
  window saved on a larger display.
* Windows open sized to their screen (at most 94% of the available
  area). A remembered position from a disconnected monitor is pulled back
  on-screen.
* At 720p the settings column no longer clips *Read info* and the gamma
  box behind a horizontal scrollbar. The splitter can no longer squeeze
  it below the width its rows need.

Checked by rendering the studio and the batch window at 1280×720,
1366×768, 1920×1080, 2560×1440, 3840×2160 at 100% and 3840×2160 at 200%.
Every window fits its screen, and no visible button is cut off.

## Fixes

* **The Qt studio could not start on a Python without `tkinter`.**
  `opngx/ui/__init__.py` imported the Tk edition eagerly, so importing any
  `opngx.ui` module needed `tkinter`. That is missing from uv's standalone
  Pythons and from many Linux installs without `python3-tk`. It was also
  why **every CI run since v1.6.x failed**. The import is now lazy.
* **The promised Tk fallback never ran.** Without PySide6,
  `qt_app.main()` raises `SystemExit`, not `ImportError`, so `opngx-ui`
  exited instead of falling back. It now checks whether Qt is available.
* **Running the test suite overwrote the user's saved studio layout.**
  Qt windows save their geometry when closed, and the suite used the
  real config directory. It now runs against a throwaway one.

## Release pipeline

When the v1.8.0 tag was pushed, the Release workflow replaced the
hand-written release notes with a generic "Automated build" blurb (the v1.8.0
page has since been restored). The workflow now publishes
`docs/RELEASE-NOTES-<version>.md` when it exists, and never rewrites the
notes of an existing release.

## Verification

* pytest **68/68** (new: AR-30 imports without tkinter, AR-31 panes
  collapse, float, full screen, Esc re-dock, hide/restore, column
  reflow, and Compare/Preview use each recording's own `.footage`
  curve, AR-32 scale calibration and screen fitting);
* engine suite **46/46**;
* packaged selftests (ui / engine / batch / video) pass on Linux;
* the Windows assets below come from the Release workflow on GitHub's
  Windows runner. They were downloaded, checked against `SHA256SUMS`,
  and their packaged selftests run under Wine before publication.

## Assets

| File | What |
|---|---|
| `opngx-setup-v1.9.0.exe` | Windows installer: engine + Qt studio + ffmpeg + docs, Start-menu shortcuts, uninstaller |
| `opngx-studio-portable-v1.9.0.exe` | Windows studio, single file, no install |
| `opngx-engine-v1.9.0.exe` | Windows CLI engine only |
| `opngx-1.9.0-linux-x86_64.tar.gz` | static Linux engine + docs |
| `opngx_1.9.0_amd64.deb` | Debian/Ubuntu package of the engine |
| `SHA256SUMS` | checksums for all of the above |
