# Your analysis modules

Every `.py` file in this folder is loaded by opngx as an **analysis module**.
It then appears in the **Analyze** tab next to the built-in ones, and is also
available as `opngx analyze -m <name>` and `opngx.analysis.analyze(...)`.

## Start here

| file | shows |
|---|---|
| `example_bright_area.py` | the basics: params, columns, a frame overlay |
| `example_frame_difference.py` | state carried between batches (`parallel = False`), a summary |
| `example_background.py` | `begin()` with `ctx.sample()`, a parameter with choices |
| `example_track_speed.py` | `requires` (build on `motion_tracking`), extra tables |

Open one in the **Editor** tab, then:

- **Validate** runs it on synthetic frames and points at the failing line;
- **Test** runs it on the loaded recording;
- **Save & use** reloads it everywhere.

**New module** starts from a template. The built-in modules are listed in the
Editor as read-only references; **Duplicate** gives you an editable copy.

## Rules in one breath

`process(frames, ctx)` gets a batch of frames as a `(k, h, w)` uint8 array.
It returns a dict of 1-D arrays, each `k` long. The runner adds `frame`,
`timestamp_raw` and `time_s`. A file that fails to import is listed with
its error and never breaks the app.

The full guide is **Docs -> Analysis modules** in the studio, or
`ANALYSIS.md` in the docs folder next to this one.

These samples are copied here once. Delete or change them as you like;
opngx will not put them back. The pristine copies stay inside the app.
