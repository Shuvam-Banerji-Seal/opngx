"""The Docs tab (v2.0): every piece of documentation in one place.

Sources, in order:
* the guides shipped inside the package (opngx/docs/*.md), and the repo's
  docs/ folder when running from a source checkout;
* YOUR documents — any Markdown file in the user docs folder (Editor tab →
  New doc…, or drop files there): docs are modular like modules;
* an API reference generated from the live `opngx.analysis` code, so it
  can never drift from what the code accepts;
* one reference page per analysis module (built-in or yours), generated
  from its declared params / columns / tables plus its docstring, and a
  `<module>.md` file next to a user module if you write one.
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import opngx.analysis as oa
from opngx.ui import themes


def _pkg_docs_dir() -> str:
    import opngx.docs as d

    return os.path.dirname(d.__file__)


def bundled_docs() -> list[tuple[str, str]]:
    """[(title, path)] of shipped Markdown docs, de-duplicated by file name."""
    dirs = [_pkg_docs_dir()]
    here = os.path.dirname(os.path.abspath(__file__))
    repo_docs = os.path.normpath(os.path.join(here, "..", "..", "..", "..", "docs"))
    if os.path.isdir(repo_docs):
        dirs.append(repo_docs)
    if getattr(sys, "_MEIPASS", None):
        dirs.append(os.path.join(sys._MEIPASS, "docs"))
    out, seen = [], set()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".md") or fn in seen:
                continue
            seen.add(fn)
            out.append((_title_of(os.path.join(d, fn), fn), os.path.join(d, fn)))
    return out


def _title_of(path: str, fallback: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return os.path.splitext(fallback)[0].replace("_", " ")


# --------------------------------------------------------------- generated --
def api_reference_md() -> str:
    """Markdown reference of the public module API, from the code itself."""
    from opngx.analysis import base, result, runner, stats

    def sig(fn):
        try:
            return f"{fn.__name__}{inspect.signature(fn)}"
        except (TypeError, ValueError):
            return fn.__name__

    parts = ["# opngx.analysis — API reference", "",
             "*Generated from the installed code; always matches this version.*", "",
             "```python\nimport numpy as np\nimport opngx.analysis as oa\nfrom opngx.analysis import Module, Param, Column\n```", "",
             "## Writing a module", "", inspect.cleandoc(base.__doc__ or ""), "",
             "## `Module` — class attributes", "",
             "| attribute | meaning |", "|---|---|"]
    for key, meaning in (
        ("name", "unique id, `[a-z][a-z0-9_]*`"), ("title / description / version / author", "shown in the studio"),
        ("params", "list of `Param` — become form fields and `-p key=value`"),
        ("columns", "list of `Column` — documentation (+ units) of per-frame outputs"),
        ("parallel", "`True` (default): batches may run concurrently; `False`: strictly in order"),
        ("requires", "names of modules whose finished tables arrive in `ctx.inputs`"),
        ("overlay", "`{'x': col, 'y': col, 'r': col}` drawn on the frame by the studio"),
        ("plot / trajectory", "default plot columns / x–y plot as default"),
        ("table_plots", "`{table: {'x': col, 'y': [cols], 'log': bool}}` for extra tables"),
        ("table_columns", "`{table: [Column, …]}` units/docs for extra tables"),
    ):
        parts.append(f"| `{key}` | {meaning} |")
    parts += ["", "## `Module` — methods", ""]
    for m in (base.Module.begin, base.Module.process, base.Module.finish):
        parts += [f"### `{sig(m)}`", "", inspect.cleandoc(m.__doc__ or ""), ""]
    parts += ["## `Param`", "", "```python", sig(base.Param), "```", "", inspect.cleandoc(base.Param.__doc__ or ""), "",
              "## `Column`", "", "```python", sig(base.Column), "```", "",
              "## `Context` (the `ctx` argument)", "", "| field | |", "|---|---|"]
    for f, doc in (
        ("params", "resolved, validated parameter values"), ("meta", "recording metadata (`opngx.FootageMetadata`)"),
        ("width, height", "analysed (cropped) frame size"), ("crop, origin", "crop rect; `origin` = full-frame offset"),
        ("source", "`'raw'` sensor bytes or `'display'` curve"),
        ("frame_index, timestamp_raw", "absolute indices / camera clock of THIS batch"),
        ("summary", "dict of scalar results (goes into every data file)"), ("state", "free dict for your module"),
        ("inputs", "finished tables of `requires` modules (in `finish`)"),
        ("tables, table_units", "publish extra tables (MSD vs lag, spectra, …)"),
        ("sample(n)", "n frames spread over the range (e.g. for a background)"), ("log(msg)", "write to the run log"),
    ):
        parts.append(f"| `{f}` | {doc} |")
    parts += ["", "## Running", "", "```python", sig(runner.analyze), "```", "", inspect.cleandoc(runner.analyze.__doc__ or ""), "",
              "`AnalysisRun`: `.results[name]` → `AnalysisResult`, `.errors`, `.frames`, `.seconds`, `.cancelled`.", "",
              "## Results & data files", "", inspect.cleandoc(result.AnalysisResult.__doc__ or ""), "",
              "`result.columns` (dict of numpy arrays), `.units`, `.summary`, `.tables`, `.save(path)` "
              "(.csv/.json/.npz/.tsv); `oa.load_result(path)` reads .json/.npz back.", "",
              "## Fast statistics for 8-bit frames (`opngx.analysis.stats`)", "", inspect.cleandoc(stats.__doc__ or ""), ""]
    for fn in (stats.histograms, stats.mean_std, stats.extremes, stats.percentile, stats.fraction_at_or_above):
        parts += [f"* `{sig(fn)}` — {inspect.cleandoc(fn.__doc__ or '').splitlines()[0] if fn.__doc__ else ''}"]
    parts += ["", "## Registry", ""]
    for fn in (oa.list_modules, oa.get_module, oa.load_file, oa.validate_file, oa.template, oa.user_modules_dir):
        d = inspect.cleandoc(fn.__doc__ or "").splitlines()
        parts.append(f"* `{sig(fn)}` — {d[0] if d else ''}")
    parts += ["", "## Native kernels", "",
              "`opngx.analysis.native.available()` tells whether the C engine's analysis kernels "
              "(`opngx_track`, `opngx_hist256`) are loaded; they are used automatically. "
              "`OPNGX_ANALYSIS_BACKEND=python` forces numpy (results are identical to ~1e-7 px)."]
    return "\n".join(parts)


def module_reference_md(info) -> str:
    c = info.cls
    if c is None:
        return f"# {info.name}\n\n**This module failed to load:**\n\n```\n{info.error}\n```\n"
    parts = [f"# {c.title or c.name}", "",
             f"`{c.name}` · v{c.version} · {info.origin}" + (f" · by {c.author}" if c.author else ""), "",
             c.description or "", ""]
    mod = sys.modules.get(c.__module__)
    doc = inspect.cleandoc((mod.__doc__ if mod else "") or "")
    if doc:
        parts += ["## How it works", "", doc, ""]
    if c.requires:
        parts += [f"**Requires:** {', '.join(f'`{r}`' for r in c.requires)} (run automatically in the same pass)", ""]
    if c.params:
        parts += ["## Parameters", "", "| name | type | default | allowed | meaning |", "|---|---|---|---|---|"]
        for p in c.params:
            allowed = ", ".join(map(str, p.choices)) if p.choices else (
                f"{'' if p.min is None else p.min} … {'' if p.max is None else p.max}" if (p.min is not None or p.max is not None) else "")
            parts.append(f"| `{p.key}` | {p.type.__name__} | `{p.default!r}` | {allowed} | {p.help} |")
        parts.append("")
    parts += ["## Output columns", "", "| column | unit | meaning |", "|---|---|---|",
              "| `frame` | | absolute frame index |", "| `timestamp_raw` | tick | camera clock |",
              "| `time_s` | s | seconds since the first analysed frame |"]
    for col in c.columns:
        parts.append(f"| `{col.key}` | {col.unit} | {col.help} |")
    if getattr(c, "table_plots", None):
        parts += ["", "## Extra tables", ""] + [f"* `{t}`" for t in c.table_plots]
    parts += ["", "## Use it", "", "```bash", f"opngx analyze recording.bin -m {c.name} -o {c.name}.csv", "```", "",
              "```python", "import opngx.analysis as oa", f"res = oa.analyze('recording.bin', '{c.name}')['{c.name}']",
              "res.save('result.csv')", "```"]
    if info.path:
        side = os.path.splitext(info.path)[0] + ".md"
        if os.path.isfile(side):
            with open(side, encoding="utf-8") as fh:
                parts += ["", "---", "", fh.read()]
        parts += ["", f"*Source: `{info.path}`*"]
    return "\n".join(parts)


# ---------------------------------------------------------------- the view --
class DocsView(QtWidgets.QWidget):
    def __init__(self, studio, parent=None) -> None:
        super().__init__(parent)
        self.studio = studio
        self._docs: dict[str, tuple[str, Optional[str], str]] = {}  # key -> (title, path, kind)
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QtWidgets.QSplitter(Qt.Horizontal)
        outer.addWidget(split)
        left = QtWidgets.QFrame()
        left.setObjectName("card")
        lv = QtWidgets.QVBoxLayout(left)
        t = QtWidgets.QLabel("DOCUMENTATION")
        t.setObjectName("cardtitle")
        lv.addWidget(t)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("search all docs…")
        self.search.textChanged.connect(self.refresh)
        lv.addWidget(self.search)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda cur, _prev: cur and self._show_item(cur))
        lv.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_new = QtWidgets.QPushButton("New doc…")
        self.btn_new.clicked.connect(self._new_doc)
        self.btn_edit = QtWidgets.QPushButton("Edit")
        self.btn_edit.clicked.connect(self._edit)
        self.btn_reload = QtWidgets.QPushButton("Reload")
        self.btn_reload.clicked.connect(self.refresh)
        for b in (self.btn_new, self.btn_edit, self.btn_reload):
            b.setObjectName("compact")
            row.addWidget(b)
        lv.addLayout(row)
        from opngx.ui import scaling

        scaling.fix(left, "setMinimumWidth", 280)
        split.addWidget(left)
        self.view = QtWidgets.QTextBrowser()
        self.view.setObjectName("docview")
        # prose, not code: the global QTextBrowser rule uses a monospace font
        self.view.setStyleSheet("QTextBrowser#docview { font-family: 'Segoe UI', 'Ubuntu', 'DejaVu Sans', sans-serif; }")
        self.view.setOpenExternalLinks(True)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        self.current: Optional[str] = None
        self.refresh()
        self.show_doc("guide:ANALYSIS.md")

    # ---------------------------------------------------------------------
    def _collect(self) -> list[tuple[str, str, str, Optional[str], str]]:
        """[(group, key, title, path, kind)]"""
        from opngx.ui.analysis_ui import user_docs_dir

        rows = [("Reference", "api", "API reference (generated)", None, "api")]
        notes = []
        for title, path in bundled_docs():
            fn = os.path.basename(path)
            if fn.upper().startswith("RELEASE-NOTES"):
                notes.append((title, path, fn))
            else:
                rows.append(("Guides", f"guide:{fn}", title, path, "md"))

        def ver(fn):
            import re as _re

            m = _re.search(r"(\d+)\.(\d+)\.(\d+)", fn)
            return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)

        for title, path, fn in sorted(notes, key=lambda n: ver(n[2]), reverse=True):
            rows.append(("Release notes", f"guide:{fn}", title, path, "md"))
        ud = user_docs_dir()
        if os.path.isdir(ud):
            for fn in sorted(os.listdir(ud)):
                if fn.lower().endswith((".md", ".markdown", ".txt")):
                    p = os.path.join(ud, fn)
                    rows.append(("My docs", f"user:{fn}", _title_of(p, fn), p, "md"))
        for info in oa.discover():
            rows.append(("Modules", f"mod:{info.name}", info.title + ("" if info.ok else "  ✗"), info.path or None, "module"))
        return rows

    def _text_of(self, key: str) -> str:
        title, path, kind = self._docs[key]
        if kind == "api":
            return api_reference_md()
        if kind == "module":
            info = next((i for i in oa.discover() if f"mod:{i.name}" == key), None)
            return module_reference_md(info) if info else f"# {title}\n\nnot found"
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            return f"# {title}\n\ncannot read `{path}`: {exc}"

    def refresh(self, *_):
        q = self.search.text().strip().lower()
        keep = self.current
        self.tree.clear()
        self._docs.clear()
        groups: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for group, key, title, path, kind in self._collect():
            self._docs[key] = (title, path, kind)
            if q:
                try:
                    hay = (title + "\n" + self._text_of(key)).lower()
                except Exception:  # noqa: BLE001
                    hay = title.lower()
                if q not in hay:
                    continue
            g = groups.get(group)
            if g is None:
                g = QtWidgets.QTreeWidgetItem([group])
                g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                self.tree.addTopLevelItem(g)
                g.setExpanded(True)
                groups[group] = g
            it = QtWidgets.QTreeWidgetItem([title])
            it.setData(0, Qt.UserRole, key)
            g.addChild(it)
        if keep and keep in self._docs:
            self.show_doc(keep)

    def _show_item(self, item) -> None:
        key = item.data(0, Qt.UserRole)
        if key:
            self.show_doc(key)

    def show_doc(self, key: str) -> None:
        if key not in self._docs:
            return
        self.current = key
        md = self._text_of(key)
        self.view.document().setDefaultStyleSheet(
            themes.recolor(
                "body { color: #e8ede8; } a { color: #8fbf7f; } "
                "code, pre { font-family: 'Cascadia Mono', Consolas, 'DejaVu Sans Mono', monospace; color: #7fb069; } "
                "h1, h2, h3 { color: #93c5fd; } th { color: #9ab294; }"
            )
        )
        self.view.setMarkdown(md)
        q = self.search.text().strip()
        if q:
            self.view.find(q)
        _t, path, kind = self._docs[key]
        from opngx.ui.analysis_ui import user_docs_dir

        self.btn_edit.setEnabled(bool(path))
        mine = bool(path) and os.path.dirname(os.path.abspath(path)) in (
            os.path.abspath(user_docs_dir()), os.path.abspath(oa.user_modules_dir()))
        self.btn_edit.setText("Edit" if mine else "Source")

    def _on_link(self, url: QtCore.QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QtGui.QDesktopServices.openUrl(url)
            return
        name = os.path.basename(url.path())
        for key in self._docs:
            if key.endswith(":" + name):
                self.show_doc(key)
                return

    def _edit(self) -> None:
        key = self.current
        if not key:
            return
        _t, path, _k = self._docs[key]
        ed = getattr(self.studio, "module_editor", None)
        if ed is not None and path:
            ed.open_path(path)
            self.studio.tabs.setCurrentWidget(self.studio._tab_host(ed))

    def _new_doc(self) -> None:
        ed = getattr(self.studio, "module_editor", None)
        if ed is None:
            return
        p = ed.new_doc()
        if p:
            self.refresh()
            self.studio.tabs.setCurrentWidget(self.studio._tab_host(ed))
