"""The analysis-module API (v1.10).

A module turns a stream of frames into a table: one row per analysed frame,
one column per measured quantity. Writing one takes a class and one method:

    import numpy as np
    from opngx.analysis import Module, Param, Column

    class PeakBrightness(Module):
        name = "peak_brightness"            # unique id, [a-z0-9_]
        title = "Peak brightness"
        description = "Brightest pixel in every frame."
        params = [Param("invert", bool, False, "track the darkest pixel")]
        columns = [Column("peak", "brightest value", "DN")]

        def process(self, frames, ctx):
            # frames: (k, h, w) uint8 — a BATCH of frames, already cropped
            f = 255 - frames if ctx.params["invert"] else frames
            return {"peak": f.reshape(len(f), -1).max(1)}

Every result also carries `frame`, `timestamp_raw` (camera clock ticks from
the frame header) and `time_s` (seconds since the first analysed frame),
added by the runner — modules never have to deal with timing.

Rules the runner relies on:
* `process()` returns a dict of 1-D arrays, each `len(frames)` long;
* it must not depend on other batches unless the class sets
  `parallel = False` (then batches arrive strictly in order, one at a
  time, and instance state may carry over between them);
* `begin(ctx)` runs once before the first batch (e.g. to build a
  background from `ctx.sample(n)`), `finish(table, ctx)` once after the
  last (e.g. derived columns such as velocities) and may return a
  `summary` dict via `ctx.summary`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

import numpy as np

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass
class Param:
    """A user-editable parameter, rendered as a form field in the studio
    and as `--param key=value` on the command line."""

    key: str
    type: type = float  # float | int | bool | str
    default: Any = 0.0
    help: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[Sequence[str]] = None  # makes a str param a drop-down
    label: str = ""

    def coerce(self, value: Any) -> Any:
        """Convert `value` (often a CLI string) to this param's type and
        validate it; raises ValueError with a readable message."""
        if value is None:
            return self.default
        try:
            if self.type is bool:
                if isinstance(value, str):
                    v = value.strip().lower()
                    if v in ("1", "true", "yes", "on"):
                        out: Any = True
                    elif v in ("0", "false", "no", "off"):
                        out = False
                    else:
                        raise ValueError(value)
                else:
                    out = bool(value)
            elif self.type is int:
                f = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
                # "47.9" used to become 47 without a word (v2.1)
                if not math.isfinite(f) or f != int(f):
                    raise ValueError(value)
                out = int(f)
            elif self.type is float:
                out = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
                if not math.isfinite(out):  # NaN passed every range check (v2.1)
                    raise ValueError(value)
            else:
                out = str(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"parameter '{self.key}' expects {self.type.__name__}, got {value!r}"
            ) from None
        if self.choices is not None and out not in self.choices:
            raise ValueError(
                f"parameter '{self.key}' must be one of {list(self.choices)}, got {out!r}"
            )
        if self.min is not None and isinstance(out, (int, float)) and out < self.min:
            raise ValueError(f"parameter '{self.key}' must be >= {self.min}, got {out}")
        if self.max is not None and isinstance(out, (int, float)) and out > self.max:
            raise ValueError(f"parameter '{self.key}' must be <= {self.max}, got {out}")
        return out


@dataclass
class Column:
    """Documentation for one output column (shown in the studio + JSON)."""

    key: str
    help: str = ""
    unit: str = ""


@dataclass
class Context:
    """What a module sees about the run. Created by the runner."""

    meta: Any  # opngx.FootageMetadata of the recording
    params: dict[str, Any]
    width: int  # analysed (cropped) frame size
    height: int
    crop: tuple[int, int, int, int]  # (x, y, w, h) in full-frame pixels
    source: str = "raw"  # "raw" sensor bytes or "display" (B/C/G curve)
    frame_index: Optional[np.ndarray] = None  # absolute indices of THIS batch
    timestamp_raw: Optional[np.ndarray] = None
    summary: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)  # free for modules
    # v2.0: finished tables of the modules this one `requires` (by name),
    # available in finish(); and extra non-per-frame tables a module may
    # publish (e.g. MSD vs lag), exported next to the main table
    inputs: dict[str, dict] = field(default_factory=dict)
    tables: dict[str, dict] = field(default_factory=dict)
    table_units: dict[str, dict] = field(default_factory=dict)  # {table: {col: unit}}
    _sampler: Optional[Callable[[int], np.ndarray]] = None
    _first: Optional[Callable[[int], np.ndarray]] = None
    log: Callable[[str], None] = print

    @property
    def origin(self) -> tuple[int, int]:
        """Full-frame coordinates of the analysed window's top-left pixel;
        add it to window coordinates to report full-frame positions."""
        return self.crop[0], self.crop[1]

    def first(self, n: int = 16) -> np.ndarray:
        """(n, h, w): the FIRST n frames of the analysed range (same crop and
        source as process()) - e.g. a reference image at the start of the
        run (v2.1). sample() spreads over the whole run instead."""
        if self._first is None:
            raise RuntimeError("first() is not available in this context")
        return self._first(int(n))

    def sample(self, n: int = 64) -> np.ndarray:
        """(n, h, w) frames spread evenly over the analysed range (same
        crop/source as process()) — for backgrounds, calibration, etc."""
        if self._sampler is None:
            raise RuntimeError("sampling is not available in this context")
        return self._sampler(int(n))


class Module:
    """Base class for analysis modules. See the module docstring."""

    name: str = ""
    title: str = ""
    description: str = ""
    version: str = "1.0"
    author: str = ""
    params: list[Param] = []
    columns: list[Column] = []
    parallel: bool = True
    # Which result columns the studio should draw on the frame: any subset
    # of {"x": col, "y": col, "r": col}, in FULL-FRAME pixel coordinates.
    overlay: dict[str, str] = {}
    # Default plot: y columns against time_s, and whether an x/y
    # trajectory plot makes sense for this module.
    plot: Sequence[str] = ()
    trajectory: bool = False
    # v2.0: names of modules whose finished table this one needs (runner
    # adds them to the same pass and finishes them first); and per extra
    # table the default plot: {table: {"x": col, "y": [cols], "log": bool}}
    requires: Sequence[str] = ()
    table_plots: dict = {}

    # -- lifecycle ------------------------------------------------------
    def begin(self, ctx: Context) -> None:  # noqa: D401 - optional hook
        """Called once before the first batch."""

    def process(self, frames: np.ndarray, ctx: Context) -> dict[str, np.ndarray]:
        raise NotImplementedError

    def finish(self, table: dict[str, np.ndarray], ctx: Context) -> Optional[dict]:
        """Called once with the full table; may return an updated table."""
        return None

    # -- helpers ----------------------------------------------------------
    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {p.key: p.default for p in cls.params}

    @classmethod
    def resolve_params(cls, given: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Defaults overlaid with `given`, every value coerced and checked.
        Unknown keys are an error (a typo must not silently do nothing)."""
        given = dict(given or {})
        known = {p.key: p for p in cls.params}
        unknown = sorted(set(given) - set(known))
        if unknown:
            raise ValueError(
                f"module '{cls.name}' has no parameter(s) {unknown}; "
                f"known: {sorted(known)}"
            )
        return {k: p.coerce(given.get(k, p.default)) for k, p in known.items()}

    @classmethod
    def check_class(cls) -> list[str]:
        """Static problems with a module class (empty list = fine)."""
        issues = []
        if not isinstance(cls.name, str) or not _NAME.match(cls.name or ""):
            issues.append(
                f"name {cls.name!r} must be lowercase letters/digits/_ and start with a letter"
            )
        if cls.process is Module.process:
            issues.append("process(frames, ctx) is not implemented")
        seen = set()
        for p in cls.params:
            if not isinstance(p, Param):
                issues.append(f"params must be Param(...) objects, got {p!r}")
                continue
            if p.key in seen:
                issues.append(f"duplicate parameter '{p.key}'")
            seen.add(p.key)
            try:
                p.coerce(p.default)
            except ValueError as exc:
                issues.append(f"default of {exc}")
        return issues
