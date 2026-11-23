"""Ask the Project window (Nov 23, Jon: on the AI tab, the Review menu and
the Project Analysis tab). Type a question; the best passages from the open
PDF and the job's Project Center records are listed with where each is,
and the AI on this PC writes a short answer from them when it's running."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import askproject as ap


class AskDialog(QDialog):
    def __init__(self, win=None, doc=None, store=None):
        super().__init__(win)
        self.win = win
        self.doc = doc
        self.store = store
        self._chunks = None
        self.result = None
        self.setWindowTitle("Ask the Project")
        self.resize(900, 600)
        v = QVBoxLayout(self)
        have = []
        if doc is not None:
            have.append("the open PDF")
        if store is not None:
            have.append("this job's RFIs, submittals, daily logs, meetings "
                        "and issues")
        self.intro = QLabel(
            "Ask a question in plain words. Answers come only from "
            + (" and ".join(have) or "nothing yet - open the specs or a "
               "drawing of the job first") + ". Nothing leaves this PC.")
        self.intro.setWordWrap(True)
        v.addWidget(self.intro)
        h = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("e.g. What is the warranty on the roofing?")
        self.q.returnPressed.connect(lambda: self.ask())
        h.addWidget(self.q, 1)
        self.ask_btn = QPushButton("Ask")
        self.ask_btn.clicked.connect(lambda: self.ask())
        h.addWidget(self.ask_btn)
        v.addLayout(h)
        self.use_ai = QCheckBox("Write an answer with the AI on this PC "
                                "(when it's running)")
        self.use_ai.setChecked(True)
        v.addWidget(self.use_ai)
        self.answer = QLabel("")
        self.answer.setWordWrap(True)
        self.answer.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.answer)
        t = self.table = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["Where", "What it says"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setWordWrap(True)
        t.cellDoubleClicked.connect(lambda r, _c: self.go(r))
        v.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def chunks(self):
        if self._chunks is None:
            name = os.path.basename(getattr(self.doc, "name", "") or "") \
                if self.doc is not None else ""
            self._chunks = ap.sources(self.doc, self.store, name)
        return self._chunks

    def ask(self, question=None, ask=None, wait=False):
        """Search now; the AI's answer follows when it's done. `ask` and
        `wait` are for tests."""
        from . import bg
        question = (question if question is not None else self.q.text()) \
            .strip()
        if not question:
            return None
        self.q.setText(question)
        found = ap.answer(question, self.chunks(), use_ai=False)
        self._show(found)
        self.result = found
        if not found["hits"] or not self.use_ai.isChecked():
            self.result = found
            return found
        self.answer.setText("<i>Best passages below. Asking the AI on this "
                            "PC for a short answer...</i>")
        self.ask_btn.setEnabled(False)

        def ok(res):
            self.ask_btn.setEnabled(True)
            self.result = res
            if res["error"]:
                self.answer.setText(
                    "<i>The AI on this PC isn't answering "
                    f"({res['error'][:120]}) - the best passages are "
                    "below.</i>")
            elif res["answer"]:
                self.answer.setText(
                    "<b>Answer (AI on this PC - check the sources):</b> "
                    + res["answer"])
            return res

        def bad(msg):
            self.ask_btn.setEnabled(True)
            self.answer.setText(f"<i>No AI answer: {msg}</i>")
            return None

        work = (lambda: ap.answer(question, self.chunks(), ask=ask))
        if wait:
            try:
                return ok(work())
            except Exception as e:                        # noqa: BLE001
                return bad(str(e))
        bg.run(work, ok, bad, self)
        return found

    def _show(self, res):
        hits = res["hits"]
        if not hits:
            self.answer.setText(res["answer"])
        else:
            self.answer.setText(f"{len(hits)} best passage(s) below - "
                                "double-click a page to go there.")
        t = self.table
        t.setRowCount(len(hits))
        for i, h in enumerate(hits):
            t.setItem(i, 0, QTableWidgetItem(f"[{i + 1}] {h['where']}"))
            t.setItem(i, 1, QTableWidgetItem(h["text"]))
        t.resizeRowsToContents()

    def go(self, row):
        res = self.result or {}
        hits = res.get("hits") or []
        if not (0 <= row < len(hits)):
            return None
        kind, ref = hits[row]["ref"]
        if kind == "page" and self.win is not None and \
                hasattr(self.win, "_go_page"):
            self.win._go_page(ref)
            return ref
        return None


def show(win=None, doc=None, store=None):
    dlg = AskDialog(win, doc, store)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.show()
    return dlg
