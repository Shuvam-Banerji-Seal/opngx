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
    if isinstance(v, (bool, np.bool_)):  # np.bool_ is not JSON (v2.1)
        return bool(v)
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
    if isinstance(v, np.generic):
        return _jsonable(v.item())
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
    tables: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    table_units: dict[str, dict[str, str]] = field(default_factory=dict)
    table_plots: dict = field(default_factory=dict)

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
                    {"key": k, "unit": self.units.get(k, ""), "help": self.help.get(k, ""),
                     "dtype": str(np.asarray(v).dtype)}
                    for k, v in self.columns.items()
                ],
                # display hints, so a reloaded result plots like the original (v2.1)
                "overlay": dict(self.overlay or {}),
                "plot": list(self.plot or ()),
                "trajectory": bool(self.trajectory),
                "table_plots": self.table_plots or {},
                "rows": len(self),
                "tables": {
                    name: {"rows": len(next(iter(tb.values()), [])),
                           "columns": [{"key": k, "unit": self.table_units.get(name, {}).get(k, ""),
                                        "dtype": str(np.asarray(v).dtype)} for k, v in tb.items()]}
                    for name, tb in self.tables.items()
                },
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        )

    def to_csv(self, path: str, *, header_comments: bool = True, delimiter: str = ",") -> str:
        """Write the table as CSV (or TSV with delimiter="\t"). With
        `header_comments`, a few `# key: v` lines describe the run first
        (pandas: `read_csv(p, comment="#")`); extra tables go next to it as
        <name>.<table>.csv; NaN is an empty cell."""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        keys = list(self.columns)
        cols = [self.columns[k] for k in keys]
        for name, tb in self.tables.items():
            root, ext = os.path.splitext(path)
            _write_table_csv(f"{root}.{name}{ext or '.csv'}", tb, self.table_units.get(name, {}),
                             f"# opngx analysis: {self.module} — table '{name}'\n" if header_comments else "",
                             delimiter=delimiter)
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
            w = csv.writer(fh, delimiter=delimiter)
            w.writerow(keys)
            fmt = []
            for c in cols:
                if c.dtype.kind in "iub":
                    fmt.append(lambda v: str(int(v)))
                else:
                    # 10 significant digits: .6g quantised time_s to 1 ms
                    # beyond 100 s (duplicate times at >= 2 kHz)
                    fmt.append(lambda v: "" if not np.isfinite(v) else f"{float(v):.10g}")
            for i in range(len(self)):
                w.writerow([f(c[i]) for f, c in zip(fmt, cols)])
        return path

    def to_json(self, path: str) -> str:
        md = self.metadata()
        md["data"] = {k: _jsonable(v) for k, v in self.columns.items()}
        md["table_data"] = {n: {k: _jsonable(v) for k, v in tb.items()} for n, tb in self.tables.items()}
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(md, fh, indent=1)
        return path

    def to_npz(self, path: str) -> str:
        """Neutral array keys plus a name map in the metadata (v2.1): a
        column named "file" collided with savez's own argument, and table
        names containing "__" were split wrongly on load."""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        arrays: dict[str, np.ndarray] = {}
        cmap: dict[str, str] = {}
        tmap: dict[str, dict[str, str]] = {}
        for i, (k, v) in enumerate(self.columns.items()):
            cmap[k] = f"c{i}"
            arrays[f"c{i}"] = np.asarray(v)
        for j, (n, tb) in enumerate(self.tables.items()):
            tmap[n] = {}
            for i, (k, v) in enumerate(tb.items()):
                tmap[n][k] = f"t{j}_{i}"
                arrays[f"t{j}_{i}"] = np.asarray(v)
        md = self.metadata()
        md["npz_keys"] = {"columns": cmap, "tables": tmap}
        arrays["_metadata"] = np.array(json.dumps(md))
        with open(path, "wb") as fh:
            np.savez_compressed(fh, **arrays)
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
        # the CSV writer with tabs: same comments, extra tables and empty
        # NaN cells (v2.0 wrote only the main table, NaN as "nan", and
        # failed when the folder did not exist yet)
        return self.to_csv(path, delimiter="\t")


def load_result(path: str) -> AnalysisResult:
    """Read back a .json or .npz written by AnalysisResult.save()."""
    if path.lower().endswith(".npz"):
        z = np.load(path, allow_pickle=False)
        md = json.loads(str(z["_metadata"]))
        keys = md.get("npz_keys")
        tables: dict = {}
        if keys:  # v2.1 layout
            cols = {k: z[a] for k, a in keys["columns"].items()}
            tables = {n: {k: z[a] for k, a in tb.items()} for n, tb in keys["tables"].items()}
        else:  # v2.0 layout: names as keys
            cols = {k: z[k] for k in z.files if k != "_metadata" and not k.startswith("tbl__")}
            for k in z.files:
                if k.startswith("tbl__"):
                    _, n, c = k.split("__", 2)
                    tables.setdefault(n, {})[c] = z[k]
    else:
        with open(path, encoding="utf-8") as fh:
            md = json.load(fh)
        dts = {c["key"]: c.get("dtype") for c in md.get("columns", [])}
        cols = {k: _typed([np.nan if x is None else x for x in v], dts.get(k)) for k, v in md["data"].items()}
        tdts = {n: {c["key"]: c.get("dtype") for c in v.get("columns", [])} for n, v in md.get("tables", {}).items()}
        tables = {
            n: {k: _typed([np.nan if x is None else x for x in v], tdts.get(n, {}).get(k)) for k, v in tb.items()}
            for n, tb in md.get("table_data", {}).items()
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
        tables=tables,
        table_units={n: {c["key"]: c.get("unit", "") for c in v.get("columns", [])}
                     for n, v in md.get("tables", {}).items()},
        overlay=dict(md.get("overlay") or {}),
        plot=tuple(md.get("plot") or ()),
        trajectory=bool(md.get("trajectory", False)),
        table_plots=md.get("table_plots") or {},
    )


def _typed(values, dtype) -> np.ndarray:
    """JSON numbers back to the saved dtype (uint64 timestamps, int8 flags)."""
    a = np.asarray(values)
    if dtype:
        try:
            dt = np.dtype(dtype)
            if dt.kind in "iub" and a.dtype.kind == "f" and not np.isfinite(a).all():
                return a  # NaN cannot be an integer: keep float
            return a.astype(dt)
        except (TypeError, ValueError):
            pass
    return a


def _write_table_csv(path: str, tb: dict, units: dict, head: str, delimiter: str = ",") -> None:
    keys = list(tb)
    n = len(next(iter(tb.values()), []))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(head)
        u = ", ".join(f"{k}[{units[k]}]" for k in keys if units.get(k))
        if u and head:
            fh.write(f"# units: {u}\n")
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(keys)
        for i in range(n):
            row = []
            for k in keys:
                v = tb[k][i]
                if isinstance(v, (float, np.floating)):
                    row.append("" if not np.isfinite(v) else f"{float(v):.10g}")
                else:
                    row.append(str(v))
            w.writerow(row)
