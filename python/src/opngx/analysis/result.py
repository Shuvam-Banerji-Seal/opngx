"""Analysis results and the data files users download (v1.10)."""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

RESERVED = ("frame", "timestamp_raw", "time_s")


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return f if np.isfinite(f) else None
    if isinstance(v, np.ndarray):
        return [_jsonable(x) for x in v.tolist()]
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


@dataclass
class AnalysisResult:
    """One module's output for one recording: a column table + metadata."""

    module: str
    module_title: str
    module_version: str
    columns: dict[str, np.ndarray]
    units: dict[str, str] = field(default_factory=dict)
    help: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    recording: dict[str, Any] = field(default_factory=dict)
    run: dict[str, Any] = field(default_factory=dict)
    overlay: dict[str, str] = field(default_factory=dict)
    plot: tuple = ()
    trajectory: bool = False

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.columns.get("frame", ()))

    @property
    def names(self) -> list[str]:
        return list(self.columns)

    def column(self, key: str) -> np.ndarray:
        return self.columns[key]

    def row_of_frame(self, frame: int) -> Optional[int]:
        f = self.columns.get("frame")
        if f is None or not len(f):
            return None
        i = int(np.searchsorted(f, frame))
        if i < len(f) and f[i] == frame:
            return i
        return None

    def describe(self) -> str:
        n = len(self)
        span = ""
        if n and "time_s" in self.columns:
            span = f", {float(self.columns['time_s'][-1]):.3f} s"
        return f"{self.module_title}: {n:,} rows{span}"

    # ------------------------------------------------------------------ io
    def metadata(self) -> dict[str, Any]:
        from opngx import __version__

        return _jsonable(
            {
                "format": "opngx-analysis/1",
                "opngx": __version__,
                "module": self.module,
                "module_title": self.module_title,
                "module_version": self.module_version,
                "params": self.params,
                "recording": self.recording,
                "run": self.run,
                "summary": self.summary,
                "columns": [
                    {"key": k, "unit": self.units.get(k, ""), "help": self.help.get(k, "")}
                    for k in self.columns
                ],
                "rows": len(self),
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        )

    def to_csv(self, path: str, *, header_comments: bool = True) -> str:
        """Write the table as CSV. With `header_comments`, a few `# key: v`
        lines describe the run first (pandas: `read_csv(p, comment="#")`)."""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        keys = list(self.columns)
        cols = [self.columns[k] for k in keys]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            if header_comments:
                md = self.metadata()
                fh.write(f"# opngx {md['opngx']} analysis: {self.module} v{self.module_version}\n")
                fh.write(f"# recording: {self.recording.get('bin_path', '')}\n")
                fh.write(f"# params: {json.dumps(md['params'])}\n")
                if self.summary:
                    fh.write(f"# summary: {json.dumps(md['summary'])}\n")
                units = ", ".join(f"{k}[{self.units[k]}]" for k in keys if self.units.get(k))
                if units:
                    fh.write(f"# units: {units}\n")
            w = csv.writer(fh)
            w.writerow(keys)
            fmt = []
            for c in cols:
                if c.dtype.kind in "iub":
                    fmt.append(lambda v: str(int(v)))
                else:
                    fmt.append(lambda v: "" if not np.isfinite(v) else f"{float(v):.6g}")
            for i in range(len(self)):
                w.writerow([f(c[i]) for f, c in zip(fmt, cols)])
        return path

    def to_json(self, path: str) -> str:
        md = self.metadata()
        md["data"] = {k: _jsonable(v) for k, v in self.columns.items()}
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(md, fh, indent=1)
        return path

    def to_npz(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        np.savez_compressed(
            path, **self.columns, _metadata=np.array(json.dumps(self.metadata()))
        )
        return path

    def save(self, path: str) -> str:
        """Write by extension: .csv (default), .json, .npz, .tsv."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            return self.to_json(path)
        if ext == ".npz":
            return self.to_npz(path)
        if ext == ".tsv":
            return self._to_tsv(path)
        return self.to_csv(path)

    def _to_tsv(self, path: str) -> str:
        keys = list(self.columns)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\t".join(keys) + "\n")
            for i in range(len(self)):
                fh.write("\t".join(f"{self.columns[k][i]}" for k in keys) + "\n")
        return path


def load_result(path: str) -> AnalysisResult:
    """Read back a .json or .npz written by AnalysisResult.save()."""
    if path.lower().endswith(".npz"):
        z = np.load(path, allow_pickle=False)
        md = json.loads(str(z["_metadata"]))
        cols = {k: z[k] for k in z.files if k != "_metadata"}
    else:
        with open(path, encoding="utf-8") as fh:
            md = json.load(fh)
        cols = {
            k: np.asarray([np.nan if x is None else x for x in v])
            for k, v in md["data"].items()
        }
    return AnalysisResult(
        module=md["module"],
        module_title=md.get("module_title", md["module"]),
        module_version=md.get("module_version", ""),
        columns=cols,
        units={c["key"]: c.get("unit", "") for c in md.get("columns", [])},
        help={c["key"]: c.get("help", "") for c in md.get("columns", [])},
        params=md.get("params", {}),
        summary=md.get("summary", {}),
        recording=md.get("recording", {}),
        run=md.get("run", {}),
    )
