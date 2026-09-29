"""A real text editor for modules and docs (v2.0).

`CodeEditor` — line numbers, syntax highlighting (Python, Markdown, JSON),
current-line / error-line / bracket-match highlight, find & replace (with
case, whole-word and regex), go to line, toggle comment, block indent /
outdent, duplicate line, auto-indent, auto-close brackets, completion
(Python keywords + the opngx.analysis API + words in the file) and zoom.
Colours follow the studio theme.

`EditorTabs` — several files open at once, each tab with its own undo
history and a modified marker.
"""

from __future__ import annotations

import keyword
import os
import re
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

from opngx.ui import themes

API_WORDS = sorted(
    {
        "Module", "Param", "Column", "Context", "analyze", "process", "begin", "finish",
        "ctx", "params", "summary", "state", "inputs", "tables", "table_units", "sample",
        "origin", "crop", "meta", "frame_index", "timestamp_raw", "log", "requires",
        "overlay", "plot", "trajectory", "parallel", "table_plots", "columns", "description",
        "title", "version", "author", "histograms", "mean_std", "extremes", "percentile",
        "fraction_at_or_above", "numpy", "np", "reshape", "astype", "float64", "uint8",
        "nanmean", "nanstd", "percentile", "median", "argmax", "where", "isfinite",
    }
)


# ============================================================ highlighters ==
class _Rules(QtGui.QSyntaxHighlighter):
    def __init__(self, doc, lang: str) -> None:
        super().__init__(doc)
        self.lang = lang
        self.rebuild()

    def rebuild(self) -> None:
        c = themes.syntax()

        def fmt(color, bold=False, italic=False):
            f = QtGui.QTextCharFormat()
            f.setForeground(QtGui.QColor(color))
            if bold:
                f.setFontWeight(QtGui.QFont.Bold)
            f.setFontItalic(italic)
            return f

        self.tri = fmt(c["string"])
        if self.lang == "python":
            kw = "|".join(keyword.kwlist)
            self.rules = [
                (re.compile(r"\b(?:" + kw + r")\b"), fmt(c["keyword"], True), 0),
                (re.compile(r"\b(?:self|ctx|np|cls)\b"), fmt(c["builtin"]), 0),
                (re.compile(r"\b(?:Module|Param|Column|Context|True|False|None)\b"), fmt(c["api"], True), 0),
                (re.compile(r"@\w+"), fmt(c["decorator"]), 0),
                (re.compile(r"\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b"), fmt(c["number"]), 0),
                (re.compile(r"\b(?:def|class)\s+(\w+)"), fmt(c["defname"]), 1),
                (re.compile(r"\"[^\"\n]*\"|'[^'\n]*'"), fmt(c["string"]), 0),
                (re.compile(r"#[^\n]*"), fmt(c["comment"], italic=True), 0),
            ]
        elif self.lang == "markdown":
            self.rules = [
                (re.compile(r"^#{1,6} .*$"), fmt(c["api"], True), 0),
                (re.compile(r"\*\*[^*]+\*\*"), fmt(c["keyword"], True), 0),
                (re.compile(r"(?<!\*)\*[^*\n]+\*(?!\*)|_[^_\n]+_"), fmt(c["decorator"], italic=True), 0),
                (re.compile(r"`[^`\n]+`"), fmt(c["string"]), 0),
                (re.compile(r"\[[^\]]+\]\([^)]+\)"), fmt(c["defname"]), 0),
                (re.compile(r"^\s*(?:[-*+]|\d+\.) "), fmt(c["number"], True), 0),
                (re.compile(r"^\|.*\|$"), fmt(c["builtin"]), 0),
                (re.compile(r"^>.*$"), fmt(c["comment"], italic=True), 0),
            ]
            self.tri = fmt(c["string"])
        elif self.lang == "json":
            self.rules = [
                (re.compile(r"\"(?:[^\"\\\\]|\\\\.)*\"\s*:"), fmt(c["api"]), 0),
                (re.compile(r":\s*(\"(?:[^\"\\\\]|\\\\.)*\")"), fmt(c["string"]), 1),
                (re.compile(r"\b(?:true|false|null)\b"), fmt(c["keyword"], True), 0),
                (re.compile(r"-?\b\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\b"), fmt(c["number"]), 0),
            ]
        else:
            self.rules = []
        self.rehighlight()

    def _fence(self) -> str:
        return '```' if self.lang == "markdown" else None

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for rx, f, grp in self.rules:
            for m in rx.finditer(text):
                s, e = m.span(grp)
                if s >= 0:
                    self.setFormat(s, e - s, f)
        # multi-line strings (python ''' / \"\"\") and fenced code (markdown ```)
        marks = ('"""', "'''") if self.lang == "python" else (("```",) if self.lang == "markdown" else ())
        if not marks:
            return
        self.setCurrentBlockState(0)

        def find(frm):
            c = [i for i in (text.find(m, frm) for m in marks) if i >= 0]
            return min(c) if c else -1

        i = 0
        if self.previousBlockState() == 1:
            end = find(0)
            if end < 0:
                self.setFormat(0, len(text), self.tri)
                self.setCurrentBlockState(1)
                return
            self.setFormat(0, end + 3, self.tri)
            i = end + 3
        while True:
            s = find(i)
            if s < 0:
                return
            e = find(s + 3)
            if e < 0:
                self.setFormat(s, len(text) - s, self.tri)
                self.setCurrentBlockState(1)
                return
            self.setFormat(s, e + 3 - s, self.tri)
            i = e + 3


def language_for(path: Optional[str]) -> str:
    ext = os.path.splitext(path or "")[1].lower()
    return {".py": "python", ".md": "markdown", ".markdown": "markdown", ".json": "json"}.get(ext, "text")


# ================================================================ editor ===
class _Gutter(QtWidgets.QWidget):
    def __init__(self, ed) -> None:
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):  # noqa: N802
        return QtCore.QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, ev):  # noqa: N802
        self.ed.paint_gutter(ev)


class CodeEditor(QtWidgets.QPlainTextEdit):
    """See the module docstring."""

    PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}

    def __init__(self, parent=None, lang: str = "python") -> None:
        super().__init__(parent)
        self.lang = lang
        self._font_pt = max(8.0, QtWidgets.QApplication.font().pointSizeF())
        self._apply_font()
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap if lang != "markdown" else QtWidgets.QPlainTextEdit.WidgetWidth)
        self.gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda *_: self._update_margins())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight)
        self.hl = _Rules(self.document(), lang)
        self.error_line: Optional[int] = None
        self._search_hits: list = []
        self._completer = QtWidgets.QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.activated.connect(self._insert_completion)
        self._update_margins()
        self._highlight()

    # ------------------------------------------------------------- look --
    def _apply_font(self) -> None:
        f = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        f.setPointSizeF(self._font_pt)
        self.setFont(f)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        if hasattr(self, "gutter"):
            self._update_margins()

    def zoom(self, delta: float) -> None:
        self._font_pt = max(6.0, min(40.0, self._font_pt + delta))
        self._apply_font()

    def retheme(self) -> None:
        self.hl.rebuild()
        self._highlight()
        self.gutter.update()

    def set_language(self, lang: str) -> None:
        self.lang = lang
        self.hl.lang = lang
        self.hl.rebuild()

    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * max(3, digits)

    def _update_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        cr = self.contentsRect()
        self.gutter.setGeometry(QtCore.QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, ev) -> None:
        c = themes.syntax()
        p = QtGui.QPainter(self.gutter)
        p.fillRect(ev.rect(), QtGui.QColor(c["gutter_bg"]))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        while block.isValid() and top <= ev.rect().bottom():
            if block.isVisible() and bottom >= ev.rect().top():
                if (num + 1) == self.error_line:
                    p.setPen(themes.qcolor("err"))
                elif num == cur:
                    p.setPen(themes.qcolor("text"))
                else:
                    p.setPen(QtGui.QColor(c["gutter_fg"]))
                p.drawText(0, top, self.gutter.width() - 6, self.fontMetrics().height(), Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1
        p.end()

    def _highlight(self) -> None:
        c = themes.syntax()
        sels = []
        cur = QtWidgets.QTextEdit.ExtraSelection()
        cur.format.setBackground(QtGui.QColor(c["current_line"]))
        cur.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        cur.cursor = self.textCursor()
        cur.cursor.clearSelection()
        sels.append(cur)
        for cs in self._search_hits[:2000]:
            s = QtWidgets.QTextEdit.ExtraSelection()
            s.format.setBackground(QtGui.QColor(c["match_bg"]))
            s.cursor = cs
            sels.append(s)
        if self.error_line:
            blk = self.document().findBlockByNumber(self.error_line - 1)
            if blk.isValid():
                e = QtWidgets.QTextEdit.ExtraSelection()
                e.format.setBackground(QtGui.QColor(c["error_bg"]))
                e.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
                e.cursor = QtGui.QTextCursor(blk)
                sels.append(e)
        sels += self._bracket_match()
        self.setExtraSelections(sels)
        self.gutter.update()

    def _bracket_match(self) -> list:
        doc = self.document()
        pos = self.textCursor().position()
        opens, closes = "([{", ")]}"
        for p0 in (pos, pos - 1):
            ch = doc.characterAt(p0)
            if ch and (ch in opens or ch in closes):
                other = self._find_partner(p0, ch)
                out = []
                for q in (p0, other):
                    if q is None or q < 0:
                        continue
                    s = QtWidgets.QTextEdit.ExtraSelection()
                    s.format.setBackground(themes.qcolor("selection"))
                    cur = QtGui.QTextCursor(doc)
                    cur.setPosition(q)
                    cur.movePosition(QtGui.QTextCursor.NextCharacter, QtGui.QTextCursor.KeepAnchor)
                    s.cursor = cur
                    out.append(s)
                return out
        return []

    def _find_partner(self, pos: int, ch: str) -> Optional[int]:
        doc = self.document()
        pairs = {"(": ")", "[": "]", "{": "}"}
        rev = {v: k for k, v in pairs.items()}
        if ch in pairs:
            want, step, other = pairs[ch], 1, ch
        else:
            want, step, other = rev[ch], -1, ch
        depth = 0
        n = doc.characterCount()
        q = pos
        limit = 200000
        while 0 <= q < n and limit:
            c = doc.characterAt(q)
            if c == other:
                depth += 1
            elif c == want:
                depth -= 1
                if depth == 0:
                    return q
            q += step
            limit -= 1
        return None

    def set_error_line(self, line: Optional[int]) -> None:
        self.error_line = line
        self._highlight()
        if line:
            self.goto_line(line)

    def goto_line(self, line: int) -> None:
        blk = self.document().findBlockByNumber(max(0, line - 1))
        if blk.isValid():
            self.setTextCursor(QtGui.QTextCursor(blk))
            self.centerCursor()

    # ---------------------------------------------------------- search ---
    def find_all(self, pattern: str, case=False, word=False, regex=False) -> int:
        self._search_hits = []
        if pattern:
            flags = QtGui.QTextDocument.FindFlag(0)
            if case:
                flags |= QtGui.QTextDocument.FindCaseSensitively
            if word:
                flags |= QtGui.QTextDocument.FindWholeWords
            what = QtCore.QRegularExpression(pattern) if regex else pattern
            if regex and not what.isValid():
                self._highlight()
                return -1
            if regex and not case:
                what.setPatternOptions(QtCore.QRegularExpression.CaseInsensitiveOption)
            cur = QtGui.QTextCursor(self.document())
            while True:
                cur = self.document().find(what, cur, flags)
                if cur.isNull() or not cur.hasSelection():
                    break
                self._search_hits.append(QtGui.QTextCursor(cur))
                if len(self._search_hits) > 100000:
                    break
        self._highlight()
        return len(self._search_hits)

    def find_next(self, pattern: str, backward=False, case=False, word=False, regex=False) -> bool:
        if not pattern:
            return False
        flags = QtGui.QTextDocument.FindFlag(0)
        if backward:
            flags |= QtGui.QTextDocument.FindBackward
        if case:
            flags |= QtGui.QTextDocument.FindCaseSensitively
        if word:
            flags |= QtGui.QTextDocument.FindWholeWords
        what = QtCore.QRegularExpression(pattern) if regex else pattern
        if regex and not case:
            what.setPatternOptions(QtCore.QRegularExpression.CaseInsensitiveOption)
        cur = self.document().find(what, self.textCursor(), flags)
        if cur.isNull():  # wrap around
            start = QtGui.QTextCursor(self.document())
            if backward:
                start.movePosition(QtGui.QTextCursor.End)
            cur = self.document().find(what, start, flags)
        if cur.isNull():
            return False
        self.setTextCursor(cur)
        return True

    def replace_all(self, pattern: str, repl: str, case=False, word=False, regex=False) -> int:
        n = self.find_all(pattern, case, word, regex)
        if n <= 0:
            return 0
        edit = QtGui.QTextCursor(self.document())
        edit.beginEditBlock()  # ONE undo step
        rx = re.compile(pattern, 0 if case else re.I) if regex else None
        for cur in reversed(self._search_hits):
            text = cur.selectedText()
            cur.insertText(rx.sub(repl, text, count=1) if rx else repl)
        edit.endEditBlock()
        self._search_hits = []
        self._highlight()
        return n

    # ----------------------------------------------------------- editing --
    def _line_range(self) -> tuple[int, int]:
        c = self.textCursor()
        doc = self.document()
        a = doc.findBlock(c.selectionStart()).blockNumber()
        b = doc.findBlock(c.selectionEnd()).blockNumber()
        if c.hasSelection() and doc.findBlock(c.selectionEnd()).position() == c.selectionEnd() and b > a:
            b -= 1
        return a, b

    def _each_line(self, fn) -> None:
        a, b = self._line_range()
        cur = QtGui.QTextCursor(self.document())
        cur.beginEditBlock()
        for n in range(a, b + 1):
            blk = self.document().findBlockByNumber(n)
            fn(QtGui.QTextCursor(blk), blk.text())
        cur.endEditBlock()

    def toggle_comment(self) -> None:
        mark = {"python": "# ", "markdown": "<!-- ", "json": ""}.get(self.lang, "# ")
        if not mark:
            return
        a, b = self._line_range()
        lines = [self.document().findBlockByNumber(n).text() for n in range(a, b + 1)]
        uncomment = all(ln.lstrip().startswith(mark.strip()) or not ln.strip() for ln in lines)

        def fn(cur, text):
            if not text.strip():
                return
            indent = len(text) - len(text.lstrip())
            cur.movePosition(QtGui.QTextCursor.StartOfBlock)
            cur.movePosition(QtGui.QTextCursor.Right, n=indent)
            if uncomment:
                body = text.lstrip()
                cut = len(mark) if body.startswith(mark) else len(mark.strip())
                cur.movePosition(QtGui.QTextCursor.Right, QtGui.QTextCursor.KeepAnchor, cut)
                cur.removeSelectedText()
            else:
                cur.insertText(mark)

        self._each_line(fn)

    def indent_lines(self, outdent=False) -> None:
        def fn(cur, text):
            cur.movePosition(QtGui.QTextCursor.StartOfBlock)
            if outdent:
                n = min(4, len(text) - len(text.lstrip(" ")))
                cur.movePosition(QtGui.QTextCursor.Right, QtGui.QTextCursor.KeepAnchor, n)
                cur.removeSelectedText()
            else:
                cur.insertText("    ")

        self._each_line(fn)

    def duplicate_line(self) -> None:
        c = self.textCursor()
        blk = c.block()
        cur = QtGui.QTextCursor(blk)
        cur.movePosition(QtGui.QTextCursor.EndOfBlock)
        cur.insertText("\n" + blk.text())

    # ------------------------------------------------------- completion --
    def _word_under(self) -> str:
        c = self.textCursor()
        c.select(QtGui.QTextCursor.WordUnderCursor)
        return c.selectedText()

    def complete(self) -> None:
        prefix = self._word_under()
        words = set(API_WORDS)
        if self.lang == "python":
            words |= set(keyword.kwlist)
        words |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", self.toPlainText()))
        words.discard(prefix)
        self._completer.setModel(QtCore.QStringListModel(sorted(words), self._completer))
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            return
        rect = self.cursorRect()
        rect.setWidth(self._completer.popup().sizeHintForColumn(0) + 24)
        self._completer.complete(rect)

    def _insert_completion(self, word: str) -> None:
        c = self.textCursor()
        c.select(QtGui.QTextCursor.WordUnderCursor)
        c.insertText(word)
        self.setTextCursor(c)

    # -------------------------------------------------------------- keys --
    def keyPressEvent(self, ev) -> None:  # noqa: N802
        popup = self._completer.popup()
        if popup.isVisible() and ev.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape, Qt.Key_Tab):
            ev.ignore()
            return
        mod = ev.modifiers()
        ctrl = bool(mod & Qt.ControlModifier)
        if ctrl and ev.key() == Qt.Key_Space:
            self.complete()
            return
        if ctrl and ev.key() == Qt.Key_Slash:
            self.toggle_comment()
            return
        if ctrl and ev.key() == Qt.Key_D:
            self.duplicate_line()
            return
        if ctrl and ev.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom(+1)
            return
        if ctrl and ev.key() == Qt.Key_Minus:
            self.zoom(-1)
            return
        if ev.key() == Qt.Key_Tab and not mod:
            if self.textCursor().hasSelection():
                self.indent_lines()
            else:
                self.insertPlainText("    ")
            return
        if ev.key() == Qt.Key_Backtab:
            self.indent_lines(outdent=True)
            return
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not mod:
            line = self.textCursor().block().text()
            indent = line[: len(line) - len(line.lstrip(" "))]
            if self.lang == "python" and line.rstrip().endswith(":"):
                indent += "    "
            super().keyPressEvent(ev)
            self.insertPlainText(indent)
            return
        ch = ev.text()
        if ch in self.PAIRS and not mod & ~Qt.ShiftModifier and self.lang != "text":
            c = self.textCursor()
            nxt = self.document().characterAt(c.position())
            if ch in ("'", '"') and nxt == ch:  # step over the closing quote
                c.movePosition(QtGui.QTextCursor.Right)
                self.setTextCursor(c)
                return
            if c.hasSelection():
                t = c.selectedText()
                c.insertText(ch + t + self.PAIRS[ch])
                return
            if not nxt or nxt.isspace() or nxt in ")]}":
                c.insertText(ch + self.PAIRS[ch])
                c.movePosition(QtGui.QTextCursor.Left)
                self.setTextCursor(c)
                return
        if ch in ")]}" and self.document().characterAt(self.textCursor().position()) == ch:
            c = self.textCursor()
            c.movePosition(QtGui.QTextCursor.Right)
            self.setTextCursor(c)
            return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        if ev.modifiers() & Qt.ControlModifier:
            self.zoom(1 if ev.angleDelta().y() > 0 else -1)
            return
        super().wheelEvent(ev)


# ============================================================ elide =======
class ElideLabel(QtWidgets.QLabel):
    """Single-line label that elides in the middle instead of being cut off
    (long file paths); the full text is the tooltip."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(40)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.setFullText(text)

    def setFullText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self.setToolTip(self._full)
        self._refit()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def _refit(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(10, self.width() - 4)))

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._refit()


# ============================================================ find bar ====
class FindBar(QtWidgets.QFrame):
    """Ctrl+F / Ctrl+H bar under the editor."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.editor: Optional[CodeEditor] = None
        g = QtWidgets.QGridLayout(self)
        g.setContentsMargins(8, 4, 8, 4)
        self.find_edit = QtWidgets.QLineEdit()
        self.find_edit.setPlaceholderText("find")
        self.repl_edit = QtWidgets.QLineEdit()
        self.repl_edit.setPlaceholderText("replace with")
        self.cb_case = QtWidgets.QCheckBox("Aa")
        self.cb_case.setToolTip("match case")
        self.cb_word = QtWidgets.QCheckBox("word")
        self.cb_regex = QtWidgets.QCheckBox(".*")
        self.cb_regex.setToolTip("regular expression")
        self.count = QtWidgets.QLabel("")
        self.count.setObjectName("hint")
        prev = QtWidgets.QPushButton("↑")
        nxt = QtWidgets.QPushButton("↓")
        rep1 = QtWidgets.QPushButton("Replace")
        repa = QtWidgets.QPushButton("Replace all")
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        g.addWidget(self.find_edit, 0, 0)
        g.addWidget(prev, 0, 1)
        g.addWidget(nxt, 0, 2)
        g.addWidget(self.cb_case, 0, 3)
        g.addWidget(self.cb_word, 0, 4)
        g.addWidget(self.cb_regex, 0, 5)
        g.addWidget(self.count, 0, 6)
        g.addWidget(close, 0, 7)
        g.addWidget(self.repl_edit, 1, 0)
        g.addWidget(rep1, 1, 1, 1, 2)
        g.addWidget(repa, 1, 3, 1, 3)
        g.setColumnStretch(0, 1)
        self.find_edit.textChanged.connect(self.refresh)
        for cb in (self.cb_case, self.cb_word, self.cb_regex):
            cb.toggled.connect(self.refresh)
        self.find_edit.returnPressed.connect(lambda: self.step(False))
        prev.clicked.connect(lambda: self.step(True))
        nxt.clicked.connect(lambda: self.step(False))
        rep1.clicked.connect(self.replace_one)
        repa.clicked.connect(self.replace_all)
        close.clicked.connect(self.hide_bar)
        self.hide()

    def _opts(self):
        return dict(case=self.cb_case.isChecked(), word=self.cb_word.isChecked(), regex=self.cb_regex.isChecked())

    def open_for(self, editor: CodeEditor, replace=False) -> None:
        self.editor = editor
        sel = editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.find_edit.setText(sel)
        self.repl_edit.setVisible(True)
        self.show()
        (self.repl_edit if replace and self.find_edit.text() else self.find_edit).setFocus()
        self.find_edit.selectAll()
        self.refresh()

    def hide_bar(self) -> None:
        if self.editor is not None:
            self.editor.find_all("")
            self.editor.setFocus()
        self.hide()

    def refresh(self) -> None:
        if self.editor is None:
            return
        n = self.editor.find_all(self.find_edit.text(), **self._opts())
        self.count.setText("bad regex" if n < 0 else (f"{n} match{'es' if n != 1 else ''}" if self.find_edit.text() else ""))

    def step(self, back: bool) -> None:
        if self.editor is not None:
            self.editor.find_next(self.find_edit.text(), backward=back, **self._opts())

    def replace_one(self) -> None:
        ed = self.editor
        if ed is None:
            return
        c = ed.textCursor()
        pat = self.find_edit.text()
        o = self._opts()
        sel = c.selectedText()
        match = bool(sel) and (
            re.fullmatch(pat, sel, 0 if o["case"] else re.I) if o["regex"] else (sel == pat if o["case"] else sel.lower() == pat.lower())
        )
        if match:
            c.insertText(re.sub(pat, self.repl_edit.text(), sel, count=1, flags=0 if o["case"] else re.I) if o["regex"] else self.repl_edit.text())
        ed.find_next(pat, **o)
        self.refresh()

    def replace_all(self) -> None:
        if self.editor is not None:
            n = self.editor.replace_all(self.find_edit.text(), self.repl_edit.text(), **self._opts())
            self.count.setText(f"replaced {n}")


# =============================================================== tabs =====
class EditorTabs(QtWidgets.QWidget):
    """Tabbed editors + a shared find bar. One tab per file path."""

    currentChanged = Signal()
    saved = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda *_: self.currentChanged.emit())
        v.addWidget(self.tabs, 1)
        self.find = FindBar(self)
        v.addWidget(self.find)
        self.goto = QtWidgets.QLineEdit()
        self.goto.setPlaceholderText("go to line…")
        self.goto.setVisible(False)
        self.goto.returnPressed.connect(self._goto)
        v.addWidget(self.goto)
        for seq, fn in (
            ("Ctrl+F", lambda: self._with_ed(lambda e: self.find.open_for(e))),
            ("Ctrl+H", lambda: self._with_ed(lambda e: self.find.open_for(e, replace=True))),
            ("F3", lambda: self.find.step(False)),
            ("Shift+F3", lambda: self.find.step(True)),
            ("Ctrl+G", self._show_goto),
            ("Escape", self._escape),
            ("Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex())),
        ):
            sc = QtGui.QShortcut(QtGui.QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ---------------------------------------------------------------------
    def _with_ed(self, fn) -> None:
        ed = self.editor()
        if ed is not None:
            fn(ed)

    def _show_goto(self) -> None:
        self.goto.setVisible(True)
        self.goto.setFocus()
        self.goto.selectAll()

    def _goto(self) -> None:
        try:
            n = int(self.goto.text())
        except ValueError:
            return
        self._with_ed(lambda e: e.goto_line(n))
        self.goto.setVisible(False)
        self._with_ed(lambda e: e.setFocus())

    def _escape(self) -> None:
        if self.goto.isVisible():
            self.goto.setVisible(False)
        elif self.find.isVisible():
            self.find.hide_bar()

    def editor(self) -> Optional[CodeEditor]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, CodeEditor) else None

    def editors(self) -> list[CodeEditor]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def path(self, ed: Optional[CodeEditor] = None) -> Optional[str]:
        ed = ed or self.editor()
        return ed.property("path") if ed is not None else None

    def index_of(self, path: str) -> int:
        a = os.path.abspath(path)
        for i, e in enumerate(self.editors()):
            p = e.property("path")
            if p and os.path.abspath(p) == a:
                return i
        return -1

    def open(self, path: Optional[str], text: Optional[str] = None, read_only=False) -> CodeEditor:
        if path:
            i = self.index_of(path)
            if i >= 0:
                self.tabs.setCurrentIndex(i)
                return self.tabs.widget(i)
        if text is None:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        ed = CodeEditor(self, language_for(path))
        ed.setPlainText(text)
        ed.setProperty("path", path)
        ed.setReadOnly(read_only)
        ed.setProperty("read_only", read_only)
        ed.document().setModified(False)
        ed.document().modificationChanged.connect(lambda *_: self._retitle(ed))
        i = self.tabs.addTab(ed, "")
        self.tabs.setCurrentIndex(i)
        self._retitle(ed)
        return ed

    def _retitle(self, ed: CodeEditor) -> None:
        i = self.tabs.indexOf(ed)
        if i < 0:
            return
        p = ed.property("path")
        name = os.path.basename(p) if p else "untitled"
        mark = " •" if ed.document().isModified() else ""
        lock = " 🔒" if ed.property("read_only") else ""
        self.tabs.setTabText(i, f"{name}{mark}{lock}")
        self.tabs.setTabToolTip(i, p or "")
        self.currentChanged.emit()

    def save(self, ed: Optional[CodeEditor] = None, path: Optional[str] = None) -> Optional[str]:
        ed = ed or self.editor()
        if ed is None or ed.property("read_only"):
            return None
        path = path or ed.property("path")
        if not path:
            return None
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ed.toPlainText())
        ed.setProperty("path", path)
        ed.set_language(language_for(path))
        ed.document().setModified(False)
        self._retitle(ed)
        self.saved.emit(path)
        return path

    def close_tab(self, i: int, force: bool = False) -> bool:
        if i < 0:
            return False
        ed = self.tabs.widget(i)
        if not force and ed.document().isModified() and not ed.property("read_only"):
            r = QtWidgets.QMessageBox.question(
                self, "opngx", f"Save changes to {os.path.basename(ed.property('path') or 'untitled')}?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
            )
            if r == QtWidgets.QMessageBox.Cancel:
                return False
            if r == QtWidgets.QMessageBox.Save and not self.save(ed):
                return False
        self.tabs.removeTab(i)
        ed.deleteLater()
        return True

    def retheme(self) -> None:
        for e in self.editors():
            e.retheme()
