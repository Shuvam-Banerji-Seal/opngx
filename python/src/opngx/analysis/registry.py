"""Find, load and validate analysis modules (v1.10).

Built-in modules live in `opngx.analysis.builtin`. User modules are plain
`.py` files in the user modules folder (see `user_modules_dir()`), or in
any folder listed in the `OPNGX_MODULES_PATH` environment variable
(os.pathsep-separated). A file may define several Module subclasses.
A broken user file never breaks the app: it is listed with its error.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .base import Context, Module


@dataclass
class ModuleInfo:
    name: str
    cls: Optional[type]
    origin: str  # "builtin" | "user"
    path: str = ""
    error: str = ""

    @property
    def title(self) -> str:
        return (self.cls.title if self.cls else "") or self.name

    @property
    def ok(self) -> bool:
        return self.cls is not None and not self.error


def user_modules_dir(create: bool = False) -> str:
    """Per-user folder for analysis modules.

    Windows: %APPDATA%\\opngx\\modules · elsewhere:
    $XDG_CONFIG_HOME/opngx/modules (default ~/.config/opngx/modules).
    Override with OPNGX_MODULES_DIR."""
    d = os.environ.get("OPNGX_MODULES_DIR")
    if not d:
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        d = os.path.join(base, "opngx", "modules")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _search_dirs() -> list[str]:
    dirs = [user_modules_dir()]
    extra = os.environ.get("OPNGX_MODULES_PATH", "")
    dirs += [p for p in extra.split(os.pathsep) if p]
    out, seen = [], set()
    for d in dirs:
        a = os.path.abspath(d)
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _classes_in(mod) -> list[type]:
    return [
        v
        for v in vars(mod).values()
        if isinstance(v, type)
        and issubclass(v, Module)
        and v is not Module
        and v.__module__ == mod.__name__
    ]


def load_file(path: str) -> list[ModuleInfo]:
    """Import one user module file (fresh every call, so edits apply)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    tag = hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:8]
    modname = f"opngx_user_modules.{stem}_{tag}"
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot import {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001
        sys.modules.pop(modname, None)
        return [ModuleInfo(stem, None, "user", path, traceback.format_exc(limit=6))]
    classes = _classes_in(mod)
    if not classes:
        return [ModuleInfo(stem, None, "user", path, "no Module subclass defined in this file")]
    infos = []
    for c in classes:
        issues = c.check_class()
        infos.append(ModuleInfo(c.name or stem, c, "user", path, "; ".join(issues)))
    return infos


def discover() -> list[ModuleInfo]:
    """Every module: built-ins first, then user files (sorted by name).
    A user module with a built-in's name is reported, not loaded over it."""
    from .builtin import BUILTIN

    infos: list[ModuleInfo] = []
    names: set[str] = set()
    for b in BUILTIN:
        try:
            mod = importlib.import_module(f"opngx.analysis.builtin.{b}")
            for c in _classes_in(mod):
                infos.append(ModuleInfo(c.name, c, "builtin", getattr(mod, "__file__", "") or ""))
                names.add(c.name)
        except Exception:  # noqa: BLE001
            infos.append(ModuleInfo(b, None, "builtin", "", traceback.format_exc(limit=6)))
    for d in _search_dirs():
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith(("_", ".")):
                continue
            for info in load_file(os.path.join(d, fn)):
                if info.cls is not None and info.name in names:
                    info.error = (
                        f"a module named '{info.name}' is already loaded "
                        f"({'built-in' if info.name in _builtin_names() else 'another file'}); "
                        "rename it"
                    )
                    info.cls = None
                elif info.cls is not None and not info.error:
                    names.add(info.name)
                infos.append(info)
    return infos


def _builtin_names() -> set[str]:
    from .builtin import BUILTIN

    return set(BUILTIN)


def list_modules(include_broken: bool = False) -> list[ModuleInfo]:
    return [i for i in discover() if include_broken or i.ok]


def get_module(name: str) -> type:
    for i in discover():
        if i.name == name:
            if not i.ok:
                raise ValueError(f"module '{name}' cannot be used: {i.error}")
            return i.cls  # type: ignore[return-value]
    avail = ", ".join(i.name for i in discover() if i.ok)
    raise KeyError(f"no analysis module named '{name}' (available: {avail})")


# ---------------------------------------------------------------- samples --
SEED_MARKER = ".opngx-samples"


def examples_dir() -> str:
    """The pristine sample modules + docs shipped inside the package (also
    inside the frozen Windows app, where they are bundled as data files)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")


def seed_examples(
    modules_dir: Optional[str] = None, docs_dir: Optional[str] = None, force: bool = False
) -> list[str]:
    """Copy the sample modules (and README) into the user's modules folder and
    the sample doc into the docs folder. Returns the files written.

    Runs once per folder: a marker file records it, so samples the user
    deleted are not resurrected on the next start. `force=True` (the
    studio's "Restore samples") ignores the marker. An existing file is
    NEVER overwritten - the user's edits always win."""
    import shutil

    src = examples_dir()
    if not os.path.isdir(src):
        return []
    md = modules_dir or user_modules_dir()
    dd = docs_dir or os.path.join(os.path.dirname(md), "docs")
    marker = os.path.join(md, SEED_MARKER)
    if os.path.exists(marker) and not force:
        return []
    plan = [(os.path.join(src, fn), md) for fn in sorted(os.listdir(src))
            if fn.endswith((".py", ".md")) and not fn.startswith("_")]
    sdocs = os.path.join(src, "docs")
    if os.path.isdir(sdocs):
        plan += [(os.path.join(sdocs, fn), dd) for fn in sorted(os.listdir(sdocs)) if fn.endswith(".md")]
    written = []
    for path, dest in plan:
        os.makedirs(dest, exist_ok=True)
        target = os.path.join(dest, os.path.basename(path))
        if os.path.exists(target):
            continue
        shutil.copyfile(path, target)
        written.append(target)
    os.makedirs(md, exist_ok=True)
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write("opngx copied its sample modules here once; delete this file to get them back.\n")
    return written


# --------------------------------------------------------------- validate --
def synthetic_frames(k: int = 32, h: int = 64, w: int = 80, seed: int = 0) -> np.ndarray:
    """Test frames: noisy background with a bright disc drifting right."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    out = np.empty((k, h, w), np.uint8)
    for i in range(k):
        cx, cy = 20 + 0.8 * i, h / 2 + 3 * np.sin(i / 5)
        spot = 150 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 3.0**2))
        out[i] = np.clip(60 + spot + rng.normal(0, 4, (h, w)), 0, 255).astype(np.uint8)
    return out


@dataclass
class Validation:
    ok: bool
    messages: list[str]
    modules: list[str]


def validate_file(path: str, dry_run: bool = True) -> Validation:
    """Load a module file and (optionally) run it on synthetic frames the
    way the runner would: begin → process (2 batches) → finish."""
    msgs: list[str] = []
    infos = load_file(path)
    names = []
    all_ok = True
    for info in infos:
        if info.cls is None:
            return Validation(False, [f"✗ {info.error.strip()}"], [])
        names.append(info.name)
        if info.error:
            all_ok = False
            msgs.append(f"✗ {info.name}: {info.error}")
            continue
        msgs.append(f"✓ {info.name}: class loads ({info.cls.title or 'no title'})")
        if dry_run:
            ok, m = dry_run_module(info.cls)
            all_ok &= ok
            msgs += m
    return Validation(all_ok, msgs, names)


def dry_run_module(cls: type, _depth: int = 0) -> tuple[bool, list[str]]:
    from .result import RESERVED
    from .runner import _check_tables, _coerce_output

    msgs = []
    frames = synthetic_frames()
    k, h, w = frames.shape
    inputs = {}
    for req in getattr(cls, "requires", ()) or ():
        if _depth > 8:
            return False, [f"✗ {cls.name}: requirement chain too deep (circular?)"]
        try:
            rcls = get_module(req)
        except (KeyError, ValueError) as exc:
            return False, [f"✗ {cls.name}: requires '{req}': {exc}"]
        ok, table = _dry_table(rcls, frames, _depth + 1)
        if not ok:
            return False, [f"✗ {cls.name}: required module '{req}' failed its dry run"]
        inputs[req] = table

    class _Meta:
        bin_path, footage_path, camera_name = "<synthetic>", None, "synthetic"
        width, height, capacity_frames, framerate = w, h, k, 500.0
        brightness, contrast, gamma = 49.0, 18.0, 1.0

    try:
        params = cls.resolve_params()
        m = cls()
        ctx = Context(
            meta=_Meta(), params=params, width=w, height=h, crop=(0, 0, w, h),
            _sampler=lambda n: frames[np.linspace(0, k - 1, max(1, min(n, k))).astype(int)],
            log=lambda s: msgs.append(f"  log: {s}"),
        )
        m.begin(ctx)
        parts = []
        for s, e in ((0, k // 2), (k // 2, k)):
            ctx.frame_index = np.arange(s, e)
            ctx.timestamp_raw = (1_000_000 + 2000 * np.arange(s, e)).astype(np.uint64)
            parts.append(_coerce_output(cls.name, m.process(frames[s:e], ctx), e - s))
        keys = list(parts[0])
        if [list(p) for p in parts] != [keys, keys]:
            raise RuntimeError("batches returned different columns")
        table = {"frame": np.arange(k), "timestamp_raw": (1_000_000 + 2000 * np.arange(k)).astype(np.uint64),
                 "time_s": 0.002 * np.arange(k)}
        table.update({key: np.concatenate([p[key] for p in parts]) for key in keys})
        ctx.inputs = inputs
        new = m.finish(table, ctx)
        if new is not None:
            table = dict(new)
        _check_tables(cls.name, ctx.tables)
        for key in table:
            a = np.asarray(table[key])
            if a.shape != (k,):
                raise RuntimeError(f"finish(): column '{key}' has shape {a.shape}, expected ({k},)")
        cols = [c for c in table if c not in RESERVED]
        msgs.append(f"✓ {cls.name}: dry run on {k} synthetic frames → columns {cols}"
                    + (f", tables {sorted(ctx.tables)}" if ctx.tables else ""))
        if _depth:
            msgs.append(("__table__", table))  # type: ignore[arg-type]
        if ctx.summary:
            msgs.append(f"  summary keys: {sorted(ctx.summary)}")
        return True, msgs
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc(limit=8)
        msgs.append(f"✗ {cls.name}: dry run failed: {exc}\n{tb}")
        return False, msgs


# ASCII only: a user's file must survive any editor / code page (v2.0)
TEMPLATE = '''"""{title} - an opngx analysis module.

Save this file in the modules folder (the Editor tab does that for you);
it then appears in the Modules tab next to the built-in ones.

`process()` receives a BATCH of frames as a (k, h, w) uint8 numpy array -
already cropped to the region you chose, raw sensor values unless the run
uses the display curve - and returns one value per frame for every column.
The runner adds `frame`, `timestamp_raw` and `time_s` for you.
"""

import numpy as np

from opngx.analysis import Column, Module, Param


class {cls}(Module):
    name = "{name}"                      # unique id: lowercase, digits, _
    title = "{title}"
    description = "Describe what this module measures."
    version = "1.0"
    params = [
        Param("threshold", int, 128, "pixels above this value are counted", min=0, max=255),
    ]
    columns = [
        Column("mean", "mean pixel value", "DN"),
        Column("bright_px", "pixels above threshold", "px"),
    ]
    plot = ("mean",)                     # plotted against time by default

    def process(self, frames, ctx):
        k = len(frames)
        flat = frames.reshape(k, -1)
        return {{
            "mean": flat.mean(axis=1),
            "bright_px": (flat > ctx.params["threshold"]).sum(axis=1),
        }}

    # Optional hooks:
    # def begin(self, ctx):             # once, before the first batch
    #     bg = np.median(ctx.sample(64), axis=0)   # e.g. a background
    #     ctx.state["background"] = bg
    #
    # def finish(self, table, ctx):     # once, with every column
    #     ctx.summary["mean_of_means"] = float(table["mean"].mean())
    #     return table
'''


def template(name: str = "my_module", title: str = "My module") -> str:
    cls = "".join(part.capitalize() for part in name.split("_")) or "MyModule"
    return TEMPLATE.format(name=name, title=title, cls=cls)


def _dry_table(cls: type, frames, depth: int):
    """Dry-run a required module and return its finished table."""
    ok, msgs = dry_run_module(cls, depth)
    for m in msgs:
        if isinstance(m, tuple) and m[0] == "__table__":
            return ok, m[1]
    return False, None
