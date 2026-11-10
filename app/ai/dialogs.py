from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QSpinBox
)
import os
import time

from PySide6.QtCore import Qt, QTimer
from . import review
from .. import bg


def _wrap_columns(table, stretch, fixed=None):
    """Long text wraps and rows grow to fit; `stretch` takes the spare
    width, `fixed` {column: width} start at that width (drag to change),
    the rest fit their contents."""
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    h.setSectionResizeMode(stretch, QHeaderView.Stretch)
    for c, w in (fixed or {}).items():
        h.setSectionResizeMode(c, QHeaderView.Interactive)
        table.setColumnWidth(c, w)
    table.setWordWrap(True)
    table.verticalHeader().setVisible(False)
    h.sectionResized.connect(lambda *_: table.resizeRowsToContents())


# the longest one part may take before it is skipped (Chief's round 4,
# Nov 7: a 7-page Redline still waited on the model after almost 5 minutes
# with nothing on screen to say how long)
def _part_limit():
    try:                     # a bad value never stops the app starting
        v = float(os.environ.get("QUANTISHEET_AI_PART_LIMIT") or 300)
    except ValueError:
        return 300.0
    return v if v > 0 else 300.0


PART_LIMIT = _part_limit()


def _minutes(seconds):
    """"5 minutes", "1 minute", "45 seconds" - never "0 minutes"."""
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    m = round(seconds / 60)
    return f"{m} minute" + ("" if m == 1 else "s")


def _count(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}."


def _ranges(pages, most=6):
    """[(0, 2), (3, 5), (9, 9)] -> "pages 1-6, 10": page ranges that touch
    are joined, and a long list is cut short with a count (a long document
    listed 60 ranges; Chief's round 7, Nov 9)."""
    out = []
    for a, b in sorted(pages):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    text = [f"{a + 1}" if a == b else f"{a + 1}-{b + 1}" for a, b in out]
    more = len(text) - most
    if more > 0:
        text = text[:most] + [f"and {more} more range" +
                              ("" if more == 1 else "s")]
    return "pages " + ", ".join(text)


class _AIDialog(QDialog):
    """Shared plumbing: pick the pages, run the model in the background a
    part at a time, show progress and what was read (Chief's estimator
    test, Nov 7: only pages 1-9 of 687 were read, said only afterwards).
    Each part shows how long it has been waiting and is skipped after
    PART_LIMIT seconds; Stop finishes the part in progress, and a second
    click (Stop Now) leaves it at once."""

    def _pages_row(self, layout):
        self.parts = review.page_parts(self.doc)       # read on this thread
        n = max(1, len(self.parts))
        row = QHBoxLayout()
        row.addWidget(QLabel("Pages"))
        self.first = QSpinBox()
        self.last = QSpinBox()
        for sb in (self.first, self.last):
            sb.setRange(1, n)
            sb.valueChanged.connect(self._range_changed)
        # the whole document by default (Chief's re-test, Nov 7: pages 1-9
        # of 687 was the default); the label says how many parts that is
        self.first.setValue(1)
        self.last.setValue(n)
        row.addWidget(self.first)
        row.addWidget(QLabel("to"))
        row.addWidget(self.last)
        whole = QPushButton("Whole Document")
        whole.setAutoDefault(False)
        whole.clicked.connect(lambda: (self.first.setValue(1),
                                       self.last.setValue(n)))
        row.addWidget(whole)
        self.range_label = QLabel("")
        self.range_label.setWordWrap(True)
        row.addWidget(self.range_label, 1)
        # stop a long run between parts; what was found so far is kept
        # (Chief's re-test, Nov 7: no way out of a 4-minute run)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setAutoDefault(False)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda *_a: self.stop())
        row.addWidget(self.stop_btn)
        layout.addLayout(row)
        self._range_changed()

    def _range(self):
        a = min(self.first.value(), self.last.value()) - 1
        b = max(self.first.value(), self.last.value()) - 1
        return a, b

    def _range_changed(self, *_):
        """Sets self.coverage, which _next_part and _done_parts report
        (M15: the old one-shot _start/_finish path is gone)."""
        if not hasattr(self, "range_label"):
            return
        a, b = self._range()
        n = len(review.chunks(self.parts, a, b))
        self.coverage = "To review: " + review.range_note(self.parts, a, b, n)
        self.range_label.setText(self.coverage)

    def _run(self, fn):
        a, b = self._range()
        self._queue = review.chunks(self.parts, a, b)
        self._total = len(self._queue)
        self._results, self._failed_parts = [], []
        self._unread, self._failed_why = [], {}
        self._fn = fn
        self._stopped = False
        self._done_n = 0
        self.gen.setEnabled(False)
        self.apply_btn.setEnabled(False)
        if hasattr(self, "stop_btn"):
            self.stop_btn.setEnabled(True)
            self.stop_btn.setText("Stop")
        self._next_part()

    def stop(self):
        """Finish the part in progress, then stop; asked again while that
        part is still running, leave it now (its answer is ignored)."""
        if getattr(self, "_running", False) and \
                getattr(self, "_stopped", False):
            self._abandon("stopped before the model answered")
            return
        if getattr(self, "_queue", None) is not None and \
                (self._queue or getattr(self, "_running", False)):
            # the parts that will never be asked, to say so at the end
            self._unread = getattr(self, "_unread", []) + [
                (a, b) for _t, a, b in self._queue]
            self._queue.clear()
            self._stopped = True
            if hasattr(self, "stop_btn"):
                self.stop_btn.setText("Stop Now")
                self.stop_btn.setToolTip(
                    "Stop waits for the part in progress to finish. Stop "
                    "Now leaves it at once (a part that never answers).")
            self.status.setText(self.status.text().split("\n")[0] +
                                "\nFinishing this part, then stopping. If "
                                "it doesn't finish, press Stop Now to leave "
                                "it.")

    def _abandon(self, why):
        """Give up on the part in progress: its request to the model is
        ended (so the model isn't kept busy with it) and a late answer is
        ignored."""
        c = getattr(self, "_cancel", None)
        if c is not None:
            c.cancel_soon()
        self._token = getattr(self, "_token", 0) + 1
        self._running = False
        a, b = getattr(self, "_part_pages", (0, 0))
        self._fail(a, b, why)
        self._next_part()

    def _fail(self, a, b, why):
        self._failed_parts.append(f"pages {a + 1}-{b + 1}: {why}")
        self._failed_why = getattr(self, "_failed_why", {})
        self._failed_why.setdefault(str(why), []).append((a, b))

    def done(self, r):
        """Closing the window ends a request still waiting on the model."""
        if getattr(self, "_running", False):
            c = getattr(self, "_cancel", None)
            if c is not None:
                c.cancel_soon()
            self._token = getattr(self, "_token", 0) + 1
            self._running = False
            if getattr(self, "_timer", None) is not None:
                self._timer.stop()
        super().done(r)

    def _tick(self):
        if not getattr(self, "_running", False):
            return
        waited = time.monotonic() - self._part_started
        if waited > PART_LIMIT:
            self._abandon(f"no answer in {_minutes(PART_LIMIT)} - skipped")
            return
        first, _sep, rest = self.status.text().partition("\n")
        first = first.split(" - waiting")[0]
        self.status.setText(f"{first} - waiting {waited:.0f} s"
                            + (_sep + rest if rest else ""))

    def _next_part(self):
        if not self._queue:
            self._running = False
            self._done_parts()
            return
        text, a, b = self._queue.pop(0)
        k = self._total - len(self._queue)
        self.status.setText(
            f"Asking the model… part {k} of {self._total} (pages {a + 1}-"
            f"{b + 1})\n{self.coverage}")
        fn = self._fn
        self._token = token = getattr(self, "_token", 0) + 1
        self._running = True
        self._part_pages = (a, b)
        self._part_started = time.monotonic()
        if getattr(self, "_timer", None) is None:
            self._timer = QTimer(self)
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._tick)
        self._timer.start()

        def ok(res):
            if token != self._token:
                return                         # skipped or left: ignored
            self._running = False
            self._results.extend(res or [])
            self._done_n = getattr(self, "_done_n", 0) + 1
            self._next_part()

        def bad(msg):
            if token != self._token:
                return
            self._running = False
            self._fail(a, b, msg)
            self._next_part()
        self._cancel = cancel = review.Cancel()
        bg.run(lambda: review.run_cancellable(cancel, fn, text), ok, bad,
               self)

    def _done_parts(self):
        if getattr(self, "_timer", None) is not None:
            self._timer.stop()
        self.gen.setEnabled(True)
        if hasattr(self, "stop_btn"):
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Stop")
            self.stop_btn.setToolTip("")
        self._show(self._results)
        head, extra = self._outcome(self.status.text())
        self.status.setText(head + "\n" + extra)
        self.apply_btn.setEnabled(self.table.rowCount() > 0)

    def _outcome(self, shown):
        """What was really read (Chief's round 6, Nov 9: after a skipped
        or stopped part it still said "Reviewed: the whole document" and
        "no suggestions" when nothing had been read). Returns the first
        line and the rest."""
        done, total = getattr(self, "_done_n", 0), self._total
        stopped = getattr(self, "_stopped", False)
        unread = getattr(self, "_unread", [])
        if done == total and not self._failed_parts:
            return shown, self.coverage.replace(
                "To review: ", "Reviewed: ", 1).replace(review.SLOW, "")
        if done == 0:
            head = ("Nothing was reviewed - no part of the document was "
                    "read, so there are no results.")
        elif not self._results:
            head = (f"Nothing to report from the {done} of {total} "
                    "part(s) that were reviewed.")
        else:
            head = shown + f" From {done} of {total} part(s) only."
        extra = (f"{'Stopped' if stopped else 'Incomplete'}: {done} of "
                 f"{total} part(s) reviewed. Generate again to run it all.")
        for why, pages in getattr(self, "_failed_why", {}).items():
            extra += f"\nNot reviewed: {_ranges(pages)}: {why}"
        if unread:
            extra += "\nNot reviewed (stopped before them): " + \
                _ranges(unread)
        return head, extra

    def _failed(self, msg):
        self.gen.setEnabled(True)
        self.status.setText(f"Error: {msg}")

    def _buttons(self, layout):
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        btns = QHBoxLayout()
        self.gen = QPushButton("Generate")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(self.gen)
        btns.addStretch()
        btns.addWidget(self.apply_btn)
        btns.addWidget(cancel)
        layout.addLayout(btns)


class RedlineDialog(_AIDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("AI Redline")
        self.resize(1000, 560)
        layout = QVBoxLayout(self)
        self._pages_row(layout)
        layout.addWidget(QLabel("Proposed edits (check the ones to mark up):"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Old", "New", "Reason"])
        _wrap_columns(self.table, stretch=3, fixed={1: 220, 2: 220})
        layout.addWidget(self.table)
        self._buttons(layout)
        self.gen.clicked.connect(
            lambda: self._run(review.redline_from_text))

    def _show(self, edits):
        self.table.setRowCount(0)
        for e in edits:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            # edits that may change scope (NOT, BY OTHERS...) start unticked
            chk.setCheckState(Qt.Unchecked if review.risky(e) else Qt.Checked)
            if review.risky(e):
                chk.setToolTip("May change scope or meaning - check it "
                               "before applying")
            self.table.setItem(row, 0, chk)
            for col, key in ((1, "old"), (2, "new"), (3, "reason")):
                self.table.setItem(row, col, QTableWidgetItem(str(e.get(key, ""))))
        self.table.resizeRowsToContents()
        self.status.setText(_count(len(edits), "proposal") if edits else
                            "The model had no suggestions.")

    def selected_edits(self):
        out = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.Checked:
                out.append({
                    "old": self.table.item(row, 1).text(),
                    "new": self.table.item(row, 2).text(),
                    "reason": self.table.item(row, 3).text()})
        return out


class SpecCheckDialog(_AIDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.findings = []
        self.setWindowTitle("AI Spec-Check")
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        self._pages_row(layout)
        layout.addWidget(QLabel("Findings (Apply adds them as sticky notes):"))

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Finding", "Page"])
        _wrap_columns(self.table, stretch=0)
        layout.addWidget(self.table)
        self._buttons(layout)
        self.gen.clicked.connect(
            lambda: self._run(review.spec_from_text))

    def _show(self, findings):
        self.findings = findings
        self.table.setRowCount(0)
        for f in findings:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(f.get("finding", ""))))
            page = f.get("page", f.get("page_hint", ""))
            self.table.setItem(row, 1, QTableWidgetItem(str(page)))
        self.table.resizeRowsToContents()
        self.status.setText(_count(len(findings), "finding") if findings else
                            "The model found nothing to report.")
