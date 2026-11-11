"""Read with AI for a sub's proposal: the review window (see
proposal_ai.py). Nothing the model says goes into the quote until it is
ticked here and accepted."""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import bg, proposal_ai, settings

KIND = {"line": "Priced line", "total": "Total", "alternate": "Alternate",
        "exclusion": "Exclusion", "inclusion": "Inclusion",
        "clarification": "Clarification"}


def _limit():
    from .ai import dialogs
    return dialogs.PART_LIMIT


class ProposalAIDialog(QDialog):
    """Ask the local model, show what it found in the quote, and let the
    user tick what to accept. `self.result` is the quote with the
    accepted values (None until Accept)."""

    def __init__(self, p, parent=None, ask=None, start=True):
        super().__init__(parent)
        self.p, self.ask = p, ask
        self.result = None
        self.offers, self.rejected = [], []
        self._running = False
        self._token = 0
        self._cancel = None
        self.setWindowTitle(f"Read with AI - {p.get('bidder') or ''}")
        self.resize(900, 520)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "The AI on this PC reads the quote; nothing leaves the "
            "computer. Only values that are in the quote word for word are "
            "listed, each marked <b>AI, check</b>. Nothing is added until "
            "you tick it and press Accept. Double-click a row to see it in "
            "the quote."))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Accept", "What", "AI, check", "Page"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(
            lambda r, _c: self.show_source(r))
        v.addWidget(self.table, 1)
        self.thrown = QLabel("")
        self.thrown.setWordWrap(True)
        v.addWidget(self.thrown)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.go = bb.addButton("Read Again", QDialogButtonBox.ActionRole)
        self.go.clicked.connect(lambda: self.start())
        self.stop_btn = bb.addButton("Stop", QDialogButtonBox.ActionRole)
        self.stop_btn.clicked.connect(lambda: self.stop())
        self.src_btn = bb.addButton("Show in the Quote",
                                    QDialogButtonBox.ActionRole)
        self.src_btn.clicked.connect(
            lambda: self.show_source(self.table.currentRow()))
        self.ok = bb.addButton("Accept Ticked", QDialogButtonBox.AcceptRole)
        self.ok.clicked.connect(lambda: self.accept_ticked())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._buttons()
        if start:
            self.start()

    def _buttons(self):
        self.go.setEnabled(not self._running)
        self.stop_btn.setEnabled(self._running)
        self.ok.setEnabled(not self._running and bool(self.offers))
        self.src_btn.setEnabled(bool(self.offers))

    # ----------------------------------------------------------- the run
    def start(self):
        if self._running:
            return
        from .ai import review
        self._token += 1
        token = self._token
        self._running = True
        self._started = time.monotonic()
        self._cancel = cancel = review.Cancel()
        self.status.setText("Asking the AI on this PC…")
        self._buttons()
        self._timer.start()
        p, ask = self.p, self.ask

        def ok(res):
            if token == self._token:
                self._finish(res)

        def bad(msg):
            if token == self._token:
                self._finish(None, msg)
        bg.run(lambda: review.run_cancellable(
            cancel, proposal_ai.read, p, ask), ok, bad, self)

    def _tick(self):
        if not self._running:
            return
        waited = time.monotonic() - self._started
        if waited > _limit():
            self.stop(f"No answer in {_limit() / 60:g} minutes - stopped. "
                      "Nothing was added.")
            return
        self.status.setText(f"Asking the AI on this PC… waiting "
                            f"{waited:.0f} s (Stop ends it)")

    def stop(self, why="Stopped. Nothing was added."):
        """End the request now; a late answer is ignored."""
        if not self._running:
            return
        if self._cancel is not None:
            self._cancel.cancel_soon()
        self._token += 1
        self._finish(None, why)

    def _finish(self, res, error=None):
        self._running = False
        self._timer.stop()
        if res is None:
            self.status.setText(error or "The AI didn't answer.")
        else:
            self.offers, self.rejected = res["offers"], res["rejected"]
            self.status.setText(res["note"] + (
                "" if self.offers else " Nothing new to add."))
            self.fill()
        self._buttons()

    def fill(self):
        t = self.table
        t.setRowCount(len(self.offers))
        for r, o in enumerate(self.offers):
            box = QTableWidgetItem("")
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                         Qt.ItemIsSelectable)
            box.setCheckState(Qt.Unchecked)       # nothing pre-accepted
            t.setItem(r, 0, box)
            t.setItem(r, 1, QTableWidgetItem(KIND[o["kind"]]))
            t.setItem(r, 2, QTableWidgetItem("AI, check: " +
                                             proposal_ai.label(o)))
            t.setItem(r, 3, QTableWidgetItem(str(o["src"]["page"] + 1)))
        if self.rejected:
            self.thrown.setText(
                f"Thrown out ({len(self.rejected)}) - not in the quote word "
                "for word: " + "; ".join(
                    f"{what} ({why})" for _k, what, why in
                    self.rejected[:6]) +
                (" …" if len(self.rejected) > 6 else ""))
        else:
            self.thrown.setText("")

    # ------------------------------------------------------------ accept
    def ticked(self):
        return [o for r, o in enumerate(self.offers)
                if self.table.item(r, 0).checkState() == Qt.Checked]

    def tick(self, rows=None):
        for r in range(self.table.rowCount()):
            if rows is None or r in rows:
                self.table.item(r, 0).setCheckState(Qt.Checked)

    def accept_ticked(self):
        got = self.ticked()
        if not got:
            self.status.setText("Tick the rows to accept first (each one "
                                "can be shown in the quote).")
            return None
        self.result = proposal_ai.accept(
            self.p, got, settings.get("author", "") or "")
        self.accept()
        return self.result

    def show_source(self, row, modal=True):
        if not 0 <= row < len(self.offers):
            return None
        from . import source_view
        o = self.offers[row]
        src = o.get("src_amount") or o["src"]
        return source_view.show(self, {"file": self.p.get("path"),
                                       "page": src["page"],
                                       "rect": src["rect"]},
                                proposal_ai.label(o), modal=modal)

    def done(self, r):
        if self._running:
            if self._cancel is not None:
                self._cancel.cancel_soon()
            self._token += 1
            self._running = False
            self._timer.stop()
        super().done(r)


def offer(parent, p, ask=None):
    """Open Read with AI for the parsed quote; returns the quote with the
    accepted values, or None when nothing was accepted."""
    dlg = ProposalAIDialog(p, parent, ask)
    dlg.exec()
    return dlg.result
