"""opngx analysis modules (v1.10): turn a recording into time-series data.

    import opngx.analysis as oa

    run = oa.analyze("recording.bin", ["motion_tracking", "luminosity"],
                     params={"motion_tracking": {"method": "circle"}},
                     stride=1, crop=(100, 20, 120, 120))
    traj = run["motion_tracking"]
    traj.save("trajectory.csv")          # or .json / .npz
    print(traj.summary)

    for info in oa.list_modules():       # built-in + user modules
        print(info.name, info.origin, info.title)

Write your own: see `opngx.analysis.base` (the API) and
`oa.template()` (a starter file), or use the studio's Editor tab.
"""

from . import native, stats
from .base import Column, Context, Module, Param
from .registry import (
    ModuleInfo,
    discover,
    dry_run_module,
    examples_dir,
    get_module,
    list_modules,
    load_file,
    seed_examples,
    synthetic_frames,
    template,
    user_modules_dir,
    validate_file,
)
from .result import AnalysisResult, load_result
from .runner import AnalysisRun, ModuleError, analyze

__all__ = [
    "Module",
    "Param",
    "Column",
    "Context",
    "analyze",
    "AnalysisRun",
    "AnalysisResult",
    "ModuleError",
    "ModuleInfo",
    "discover",
    "list_modules",
    "get_module",
    "load_file",
    "validate_file",
    "dry_run_module",
    "template",
    "synthetic_frames",
    "user_modules_dir",
    "seed_examples",
    "examples_dir",
    "load_result",
    "native",
    "stats",
]
