# opngx v1.6.2 — batch selection fixed & documented

**Developer:** Shuvam Banerji Seal

## Fixed (Windows field report)
Clicking **Batch folder** then Browse opened a .bin FILE dialog — the
button ignored the scope. It now adapts:

- **Batch folder selected** → Browse opens a **FOLDER** dialog titled
  "Select the mother folder (contains one folder per recording)".
- **Single bin selected** → Browse opens the .bin file dialog.
- Button label follows the scope: "Choose folder…" ⇄ "Open…"; Read-info
  becomes "Scan folders" in Batch scope.
- **Drag & drop a FOLDER** anywhere → switches to Batch and scans it;
  dropping a .bin switches to Single.

## Documented: the mother-folder architecture
Help → Field guide now spells out the contract, and the Batch tooltip
shows the tree inline:

    mother/
      recording_1/   x.bin  x.footage
      recording_2/   y.bin  y.footage

    → output mother/
      recording_1/  PNG/ JPG/ BMP/ TIF/ MP4/
      recording_2/  …

Scan folders reports the recording count before you commit; extraction
mirrors the tree exactly (v1.6 layout). Tkinter fallback gets the same
scope-aware picker.

## Gates
- AR-15: picker branches on scope; functional offscreen tests drive the
  real dialogs (monkeypatched) — folder dialog opens for Batch, folder
  drop switches scope, single still uses the file dialog.
- AR-4 caught a duplicate _pick_bin introduced during the refactor —
  proof the duplicate-definition gate earns its keep.
- 51/51 pytest · 27/27 engine gates · packaged selftests green.
