"""Estimate > Find Bid Terms (Nov 19) and Project Analysis (Nov 20)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import bidsubmittal as bs, bidterms


class BidTermsDialog(QDialog):
    """What the bid documents say about bond, hold time, wages, damages,
    pre-bid, goals, retainage, contract time and alternates - each with
    its page (double-click to go there)."""

    def __init__(self, win, found=None):
        super().__init__(win)
        self.win = win
        self.doc = win._view.doc
        self.found = bidterms.find(self.doc) if found is None else found
        self.setWindowTitle("Bid Terms")
        self.resize(820, 420)
        v = QVBoxLayout(self)
        intro = QLabel(
            "Read from this document's text by pattern - check each one "
            "on its page (double-click a row). Nothing is sent anywhere."
            if self.found else
            "No bid terms were found in this document's text. Open the "
            "specifications or instructions to bidders (scanned pages need "
            "Make Searchable first).")
        intro.setWordWrap(True)
        v.addWidget(intro)
        t = self.table = QTableWidget(len(self.found), 4)
        t.setHorizontalHeaderLabels(["Term", "Found", "Page", "Where"])
        for r, f in enumerate(self.found):
            page = "" if f["page"] is None else str(f["page"] + 1)
            for c, val in enumerate((f["label"], f["value"], page,
                                     f["text"])):
                it = QTableWidgetItem(val)
                if f["page"] is None:
                    it.setForeground(Qt.gray)
                t.setItem(r, c, it)
        t.setWordWrap(True)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.cellDoubleClicked.connect(lambda r, _c: self.go(r))
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.use_btn = bb.addButton("Put Hold Days in the Bid Checklist",
                                    QDialogButtonBox.ActionRole)
        self.use_btn.setEnabled(bidterms.hold_days(self.found) is not None)
        self.use_btn.clicked.connect(lambda: self.use_hold())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def go(self, row):
        page = self.found[row]["page"]
        if page is not None:
            self.win._go_page(page)
        return page

    def use_hold(self):
        """The hold days into the Bid Submittal Checklist (Estimate Error
        Check then warns about quotes that run out sooner)."""
        n = bidterms.hold_days(self.found)
        if n is None:
            return None
        st = bs.read(self.doc)
        st["hold_days"] = n
        bs.write(self.doc, st)
        self.win._doc_edited()
        self.use_btn.setText(f"Bid Checklist: holds {n} days")
        return n


class ProjectAnalysisDialog(QDialog):
    """Project Analysis (Nov 20, Jon + Chief's list): Jon's nine answers
    first, then bonds, insurance, questions due, delivery, wage, goals,
    alternates, unit prices, addenda and contacts - each with its spec
    section and page (double-click to go there), "not found" when the
    specs don't say. Kept in the PDF; Run Again after an addendum."""

    def __init__(self, win, rows=None, fresh=False):
        super().__init__(win)
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import (QCheckBox, QDateEdit, QHBoxLayout,
                                       QSpinBox)
        from . import projanalysis as pa
        self.win = win
        self.doc = win._view.doc
        self.from_cache = False
        if rows is None and not fresh:
            rows = pa.cached(self.doc)
            self.from_cache = rows is not None
        if rows is None:
            rows = pa.run(self.doc)
            try:
                pa.save(self.doc, rows)
                win._doc_edited()
            except Exception:                             # noqa: BLE001
                pass
        self.rows = rows
        self.setWindowTitle("Project Analysis")
        self.resize(980, 620)
        v = QVBoxLayout(self)
        found = sum(1 for r in rows if r["page"] is not None or
                    r["key"] in ("addenda", "unit_prices"))
        self.intro = QLabel(
            f"{found} of {len(rows)} answers found in this document's text"
            + (" (kept from the last run - Run Again after adding an "
               "addendum)" if self.from_cache else "") +
            ". Each shows its section and page - double-click to check it. "
            "Nothing is sent anywhere; nothing is guessed.")
        self.intro.setWordWrap(True)
        v.addWidget(self.intro)
        t = self.table = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Question", "Answer", "Section / page",
                                     "Where it says so"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setWordWrap(True)
        t.cellDoubleClicked.connect(lambda r, _c: self.go(r))
        v.addWidget(t, 1)
        h = QHBoxLayout()
        self.use_ntp = QCheckBox("Notice to proceed:")
        self.ntp = QDateEdit(QDate.currentDate())
        self.ntp.setCalendarPopup(True)
        self.ntp.setEnabled(False)
        self.use_ntp.toggled.connect(self.ntp.setEnabled)
        self.use_ntp.toggled.connect(lambda _b: self.fill())
        self.ntp.dateChanged.connect(lambda _d: self.fill())
        h.addWidget(self.use_ntp)
        h.addWidget(self.ntp)
        h.addSpacing(20)
        h.addWidget(QLabel("LD exposure if late by"))
        self.late = QSpinBox()
        self.late.setRange(0, 3650)
        self.late.setValue(30)
        self.late.setSuffix(" days")
        self.late.valueChanged.connect(lambda _v: self.fill())
        h.addWidget(self.late)
        h.addStretch(1)
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.again_btn = bb.addButton("Run Again", QDialogButtonBox.ActionRole)
        self.again_btn.clicked.connect(lambda: self.run_again())
        self.copy_btn = bb.addButton("Copy", QDialogButtonBox.ActionRole)
        self.copy_btn.clicked.connect(lambda: self.copy())
        self.pdf_btn = bb.addButton("Export PDF…", QDialogButtonBox.ActionRole)
        self.pdf_btn.clicked.connect(lambda: self.export_pdf())
        self.hold_btn = bb.addButton("Put Hold Days in the Bid Checklist",
                                     QDialogButtonBox.ActionRole)
        self.hold_btn.clicked.connect(lambda: self.use_hold())
        # Nov 21 (Jon: inside Project Analysis): a scope summary written by
        # the AI on this PC
        self.ai_btn = bb.addButton("Summarize with Local AI",
                                   QDialogButtonBox.ActionRole)
        self.ai_btn.clicked.connect(lambda: self.ai_summary())
        # Nov 23 (Jon: both places): a new Bid Board entry from these
        # answers, for the user to check and save
        self.board_btn = bb.addButton("Send to Bid Board",
                                      QDialogButtonBox.ActionRole)
        self.board_btn.clicked.connect(lambda: self.send_to_board())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.fill()

    # rows shown: the answers, their "also stated", then worked lines
    def lines(self):
        from . import projanalysis as pa
        out = []
        for r in self.rows:
            where = "" if r["page"] is None else (
                (r["section"] + " - " if r.get("section") else "") +
                f"p. {r['page'] + 1}")
            out.append((r["label"], r["value"], where, r.get("text", ""),
                        r["page"], r["page"] is None and
                        r["key"] not in ("addenda", "unit_prices")))
            for val, pg in r.get("also") or []:
                out.append(("      also stated", val,
                            "" if pg is None else f"p. {pg + 1}",
                            "two answers in the documents - the newest "
                            "addendum wins", pg, False))
        if self.use_ntp.isChecked():
            ntp = self.ntp.date().toPython()
            for k, d in pa.completion_dates(self.rows, ntp).items():
                out.append((f"{pa.LABEL[k][3:]} from NTP", d.strftime(
                    "%B %d, %Y").replace(" 0", " "), "", f"notice to proceed "
                    f"{ntp.isoformat()}", None, False))
        ex = pa.ld_exposure(self.rows, self.late.value()) \
            if self.late.value() else None
        if ex is not None:
            out.append(("LD exposure", f"{ex:,} for {self.late.value()} "
                        "days late", "", "the LD rate x the days late",
                        None, False))
        return out

    def fill(self):
        ls = self.lines()
        t = self.table
        t.setRowCount(len(ls))
        for r, (q, a, where, txt, _pg, missing) in enumerate(ls):
            for c, val in enumerate((q, a, where, txt)):
                it = QTableWidgetItem(val)
                if missing:
                    it.setForeground(Qt.gray)
                t.setItem(r, c, it)
        t.resizeRowsToContents()
        from . import bidterms as bt
        self.hold_btn.setEnabled(bt.hold_days(
            [r for r in self.rows if r["page"] is not None]) is not None)
        return ls

    def go(self, row):
        page = self.lines()[row][4]
        if page is not None:
            self.win._go_page(page)
        return page

    def ai_summary(self, ask=None, wait=False):
        """Ask the local AI (Ollama) for a 3-5 sentence scope summary and
        add it as a row, marked as AI-written. `ask` and `wait` are for
        tests (no thread)."""
        from . import bg, projanalysis as pa
        self.ai_btn.setEnabled(False)
        self.intro.setText("Asking the AI on this PC for a scope summary... "
                           "(nothing leaves the PC)")

        def ok(text):
            self.ai_btn.setEnabled(True)
            if not text:
                self.intro.setText("The local AI gave no summary.")
                return None
            self.rows = pa.with_ai_summary(self.rows, text)
            try:
                pa.save(self.doc, self.rows)
                self.win._doc_edited()
            except Exception:                             # noqa: BLE001
                pass
            self.intro.setText("Summary added (local AI) - check it against "
                               "the specs.")
            self.fill()
            return text

        def bad(msg):
            self.ai_btn.setEnabled(True)
            self.intro.setText(f"No AI summary: {msg}")
            return None

        if wait:
            try:
                return ok(pa.ai_summary(self.doc, self.rows, ask))
            except Exception as e:                        # noqa: BLE001
                return bad(str(e))
        bg.run(lambda: pa.ai_summary(self.doc, self.rows, ask), ok, bad,
               self)
        return None

    def run_again(self):
        from . import projanalysis as pa
        self.rows = pa.run(self.doc)
        pa.save(self.doc, self.rows)
        self.win._doc_edited()
        self.from_cache = False
        self.fill()
        return self.rows

    def text(self):
        out = ["Project Analysis"]
        for q, a, where, _t, _p, _m in self.lines():
            out.append(f"{q.strip()}: {a}" + (f" ({where})" if where else ""))
        return "\n".join(out)

    def copy(self):
        t = self.text()
        QGuiApplication.clipboard().setText(t)
        return t

    def export_pdf(self, path=None):
        from PySide6.QtWidgets import QFileDialog
        from . import projanalysis as pa
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Project Analysis", "Project Analysis.pdf",
                "PDF (*.pdf)")
            if not path:
                return None
        ntp = self.ntp.date().toPython() if self.use_ntp.isChecked() \
            else None
        return pa.export_pdf(self.rows, path, ntp=ntp,
                             days_late=self.late.value() or None)

    def use_hold(self):
        from . import bidterms as bt
        n = bt.hold_days([r for r in self.rows if r["page"] is not None])
        if n is None:
            return None
        st = bs.read(self.doc)
        st["hold_days"] = n
        bs.write(self.doc, st)
        self.win._doc_edited()
        self.hold_btn.setText(f"Bid Checklist: holds {n} days")
        return n

    def send_to_board(self, show=True):
        """A new Bid Board entry filled from these answers. Nothing is
        saved until the user checks it and clicks Save."""
        import os
        from . import bidboard as B, bidboard_ui, projanalysis as pa
        source = os.path.basename(getattr(self.doc, "name", "") or "")
        fields = pa.bidboard_fields(self.rows, source)
        opp, found = pa.fill_empty({"status": "Undecided"}, fields)
        dlg = bidboard_ui.OpportunityDialog(
            self, opp, [k for k in found if k not in ("source", "notes")],
            B.load(), where="the specifications")
        if not show:
            return dlg
        if dlg.exec() == QDialog.Accepted and dlg.saved:
            self.board_btn.setText("On the Bid Board")
            from PySide6.QtWidgets import QApplication
            for w in QApplication.topLevelWidgets():   # an open Bid Board
                if isinstance(w, bidboard_ui.BidBoard):
                    w.refresh(dlg.saved["id"])
        return dlg.saved
