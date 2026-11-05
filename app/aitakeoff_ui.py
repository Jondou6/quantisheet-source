"""AI Takeoff dialog (AI > AI Takeoff): read the set, review what will be
taken off on each sheet, run it, read the summary, check the results."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog,
                               QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox,
                               QPlainTextEdit, QProgressDialog, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import aitakeoff as ait


PENCIL = [6, 4]          # dash pattern of an AI proposal not yet checked


def _pencil(marks):
    """AI measurements drawn as pencil proposals: lines and outlines
    dashed, count dots with a dashed ring, and a small "AI" badge, until a
    person accepts them (Check Takeoff / the review queue makes an accepted
    one solid and takes the badge off). Setting 'ai_pencil' turns the
    dashes off, 'ai_badge' the badge."""
    from . import settings
    dashed = settings.get("ai_pencil", True)
    badge = settings.get("ai_badge", True)
    if not dashed and not badge:
        return list(marks)
    out = []
    for p, kind, pl in marks:
        if kind in ("add_line", "add_polyline", "add_polygon",
                    "add_count") and isinstance(pl, dict):
            if dashed and "dashes" not in pl:
                pl = dict(pl, dashes=list(PENCIL))
            if badge and "badge" not in pl and isinstance(
                    pl.get("measure"), dict):
                pl = dict(pl, badge=True)
        out.append((p, kind, pl))
    return out


class AITakeoffDialog(QDialog):
    COLS = ["Take off", "Sheet", "Title", "Discipline", "Scale", "What"]

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.rows = []
        self.result = None
        self.setWindowTitle("AI Takeoff - Whole Set")
        self.resize(980, 680)
        v = QVBoxLayout(self)
        intro = QLabel(
            "<b>Take off the whole set in one go.</b> QuantiSheet reads every "
            "sheet - its number, title, discipline and scale - and runs the "
            "right takeoff on each: rooms on floor plans; pipe by size and "
            "depth, manholes and structures on civil sheets; pipe runs and "
            "legend fixtures on MEP sheets. Details, sections and schedules "
            "are skipped. Untick any sheet you don't want. Everything lands "
            "as normal measurements (one Undo) for you to check.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        row = QHBoxLayout()
        self.read_btn = QPushButton("1. Read the Set")
        self.read_btn.setObjectName("primary")
        self.read_btn.clicked.connect(self.read)
        self.run_btn = QPushButton("2. Run AI Takeoff")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(lambda _c=False: self.run())
        self.check_btn = QPushButton("3. Check Takeoff")
        self.check_btn.setEnabled(False)
        self.check_btn.clicked.connect(self.check)
        self.ai_btn = QPushButton("Write Scope Summary (local AI)")
        self.ai_btn.setEnabled(False)
        self.ai_btn.clicked.connect(self.scope)
        self.book_btn = QPushButton("4. Estimate Workbook (Excel)")
        self.book_btn.setEnabled(False)
        self.book_btn.setToolTip(
            "An estimate workbook by CSI division - SUMMARY, BASE BID and "
            "UNITS & WASTAGE - with the quantities filled in and the rate "
            "columns left for you.")
        self.book_btn.clicked.connect(lambda _c=False: self.workbook())
        self.spec_btn = QPushButton("Read Spec Book…")
        self.spec_btn.setEnabled(False)
        self.spec_btn.setToolTip(
            "Read the project manual (PDF): pipe and duct materials the "
            "drawings don't name, and pipe / duct insulation from its "
            "schedules - each line says which section it came from.")
        self.spec_btn.clicked.connect(lambda _c=False: self.read_spec())
        self.review_btn = QPushButton("Review Queue")
        self.review_btn.setEnabled(False)
        self.review_btn.setToolTip(
            "Everything the AI found that isn't accepted yet - doors, "
            "windows, rooms, areas, schedule rows, a doubtful scale - least "
            "sure first, on its sheet: Accept, Deny or Undo. Items in "
            "review are in no total until you accept them.")
        self.review_btn.clicked.connect(lambda _c=False: self.review())
        for b in (self.read_btn, self.run_btn, self.check_btn,
                  self.review_btn, self.ai_btn, self.spec_btn,
                  self.book_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        v.addWidget(self.table, 3)
        ev = QHBoxLayout()
        self.scale_crop = QLabel()
        self.scale_crop.setToolTip("The printed scale on the sheet")
        self.scale_why = QLabel("Pick a sheet to see where its scale was "
                                "read and how sure it is.")
        self.scale_why.setObjectName("muted")
        self.scale_why.setWordWrap(True)
        ev.addWidget(self.scale_crop)
        ev.addWidget(self.scale_why, 1)
        v.addLayout(ev)
        self.table.currentCellChanged.connect(
            lambda r, *_a: self.show_scale(r))
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("The summary appears here.")
        v.addWidget(self.summary, 2)
        self.status = QLabel()
        self.status.setObjectName("muted")
        v.addWidget(self.status)

    @property
    def view(self):
        return self.win._view

    def read(self):
        if not self.view:
            return []
        doc = self.view.doc
        dlg = QProgressDialog("Reading sheets…", "Cancel", 0,
                              doc.page_count, self)
        dlg.setWindowTitle("AI Takeoff")
        dlg.setMinimumDuration(300)

        def step(i, n):
            dlg.setValue(i)
            dlg.setLabelText(f"Reading sheet {i + 1} of {n}…")
            QApplication.processEvents()
            return not dlg.wasCanceled()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.rows = ait.plan_set(doc, step)
        finally:
            QApplication.restoreOverrideCursor()
            dlg.close()
        self._fill()
        n = sum(1 for r in self.rows if r["engines"])
        need = sum(1 for r in self.rows if r["wanted"] and not r["engines"])
        self.status.setText(
            f"{len(self.rows)} sheet(s): {n} to take off"
            + (f", {need} need a scale first (Takeoff > Auto Scale or Set "
               "Scale)" if need else "") + ".")
        self.run_btn.setEnabled(n > 0)
        return self.rows

    def _fill(self):
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            what = ", ".join(ait.ENGINE_NAMES[e] for e in r["engines"]) \
                or r["note"]
            sc = r["scale"][0] if r["scale"] else \
                ("⚠ odd scale" if r["scale_from"] == "odd" else "—")
            if r["scale_from"] == "read":
                sc += " (read)"
            conf = r.get("scale_conf")
            if isinstance(conf, (int, float)) and (r["scale"] or
                                                   r.get("source") == "scan"):
                sc += f" · {conf:.0f}/100" + (" ⚠ check" if
                                              r.get("scale_review") else "")
            vals = ["", r["number"], r["title"], r["discipline"], sc, what]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 0:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if r["engines"] else
                                     Qt.Unchecked)
                    if not r["engines"]:
                        it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
                if c == 4 and r.get("scale_why"):
                    it.setToolTip("Scale confidence:\n- " +
                                  "\n- ".join(r["scale_why"]))
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)

    def show_scale(self, i):
        """The sheet's scale evidence: the printed words it was read from
        (a crop of the sheet), the score and the reasons (v3)."""
        from PySide6.QtGui import QPixmap
        self.scale_crop.clear()
        if not 0 <= i < len(self.rows):
            return None
        r = self.rows[i]
        conf = r.get("scale_conf")
        head = (f"Scale {r['scale'][0]}" if r.get("scale") else
                "No scale read") + (f" - confidence {conf:.0f}/100"
                                    if isinstance(conf, (int, float))
                                    else "")
        if r.get("scale_review"):
            head += " - goes to the review queue: its lengths and areas " \
                    "wait until you confirm it"
        self.scale_why.setText(head + "".join(
            f"\n- {w}" for w in r.get("scale_why") or ()))
        rect = r.get("scale_rect")
        if rect and self.view:
            import fitz
            from . import scale_evidence
            try:
                png = scale_evidence.crop_png(self.view.doc[r["page"]],
                                              fitz.Rect(rect))
                pm = QPixmap()
                pm.loadFromData(png, "PNG")
                if pm.width() > 360:
                    pm = pm.scaledToWidth(360)
                self.scale_crop.setPixmap(pm)
            except Exception:                            # noqa: BLE001
                pass
        return r

    def chosen_rows(self):
        out = []
        for i, r in enumerate(self.rows):
            it = self.table.item(i, 0)
            on = it is not None and it.checkState() == Qt.Checked
            out.append(dict(r, engines=r["engines"] if on else []))
        return out

    def _work_copy(self):
        """A separate copy of the drawing for the background thread (the
        window keeps drawing the open one): the file on disk, or the open
        document's bytes when it has unsaved changes."""
        import fitz
        doc = self.view.doc
        name = getattr(doc, "name", "") or ""
        import os
        if name and os.path.isfile(name) and not doc.is_dirty:
            work = fitz.open(name)
        else:
            work = fitz.open("pdf", doc.tobytes())
        ait.strip_ai_marks(work)        # read the drawing, not our marks
        return work

    def run(self, wait=False, timeout=None):
        """Take off the chosen sheets in the background (Oct 22: on a
        309-sheet plant set the civil pass ran for minutes on the window's
        thread and Windows showed "Not Responding"). The window stays live,
        the progress box shows each sheet and Stop works; the results are
        added to the drawing on this thread at the end, as one Undo.
        `wait` blocks until done (tests)."""
        import threading
        from PySide6.QtCore import QTimer
        from . import bg
        rows = self.chosen_rows()
        if not any(r["engines"] for r in rows):
            self.status.setText("Tick at least one sheet to take off.")
            return None
        try:
            work = self._work_copy()
        except Exception as e:                           # noqa: BLE001
            QMessageBox.warning(self, "AI Takeoff",
                                f"Couldn't read the drawing: {e}")
            return None
        state = {"k": 0, "n": 1, "text": "Starting…", "stop": False,
                 "done": None}
        dlg = QProgressDialog("Starting…", "Stop", 0, 1, self)
        dlg.setWindowTitle("AI Takeoff")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.canceled.connect(lambda: state.__setitem__("stop", True))
        self.run_btn.setEnabled(False)
        self.read_btn.setEnabled(False)
        lock = threading.Lock()

        def step(k, n, text):                 # worker thread: no Qt here
            with lock:
                state.update(k=k, n=max(1, n), text=text)
            return not state["stop"]

        def job():
            try:
                return ait.run(work, rows, step)
            finally:
                try:
                    work.close()
                except Exception:                        # noqa: BLE001
                    pass

        timer = QTimer(self)

        def poll():
            with lock:
                k, n, text = state["k"], state["n"], state["text"]
            dlg.setMaximum(n)
            dlg.setValue(min(k, n))
            dlg.setLabelText(text + ("\nStopping after this step…"
                                     if state["stop"] else ""))
        timer.timeout.connect(poll)
        timer.start(200)

        def finish(res=None, err=None):
            timer.stop()
            dlg.close()
            self.read_btn.setEnabled(True)
            self.run_btn.setEnabled(True)
            state["done"] = True
            if err is not None:
                import logging
                logging.getLogger(__name__).error("AI takeoff failed: %s",
                                                  err)
                QMessageBox.warning(self, "AI Takeoff",
                                    f"AI Takeoff stopped: {err}\n\nNothing "
                                    "was added. The details are in the log.")
                return None
            return self._apply(rows, res)

        bg.run(job, lambda res: finish(res), lambda e: finish(err=e), self)
        if wait:
            import time
            t0 = time.time()
            # follow the job (a big set takes 15 min or more); a caller that
            # gives a timeout gets an error, never an empty result
            while state["done"] is None:
                if timeout is not None and time.time() - t0 > timeout:
                    raise TimeoutError(
                        f"AI Takeoff still running after {timeout:.0f} s")
                QApplication.processEvents()
                time.sleep(0.02)
        return self.result if wait else None

    def _apply(self, rows, res):
        """GUI thread: add the takeoff to the drawing (one Undo)."""
        from . import assemblies
        marks = [(p, "set_scale", {"ppu": ppu, "unit": unit, "name": label})
                 for p, label, ppu, unit in res["scales"]]
        # a second run doesn't add what the first one already put there
        # (v3): its measurements are split into new matches and those
        # already on the drawing (locked); the person picks from the new
        from . import rerun
        # names you gave AI items before (rename / Move to Item) are used
        # straight away (Nov 1, name_memory)
        from . import name_memory
        try:
            renamed = name_memory.rename_marks(res["marks"])
            name_memory.rename_result(res, renamed)
        except Exception:                                 # noqa: BLE001
            renamed = {}
        res["renamed"] = renamed
        # zones drawn on the sheets: only what's inside "only here", never
        # what's inside "leave out" (Nov 1, zones.py)
        from . import zones
        try:
            res["marks"], zdrop = zones.filter_marks(self.view.doc,
                                                     res["marks"])
            zones.filter_result(self.view.doc, res, zdrop)
        except Exception:                                 # noqa: BLE001
            zdrop = []
        res["zoned_out"] = len(zdrop)
        pencil = _pencil(res["marks"])
        sp = rerun.split(self.view.doc, pencil)
        # an exact repeat the shape match left over (the engine drew the
        # same thing twice) isn't offered as new either
        fresh, dup = ait.skip_repeats(self.view.doc, sp["new"])
        if dup:
            sp["new"] = fresh
        carried = rerun.carry_decisions(self.result, res) \
            if self.result else {"locked": []}
        keep = {id(m) for m in sp["new"]} | {id(m) for m in sp["other"]}
        if sp["previous"] or carried["locked"]:
            from .rerun_ui import RerunDialog
            dlg = RerunDialog(self, sp, carried)
            if not self.confirm_rerun(dlg):
                self.status.setText("Run again cancelled - nothing was "
                                    "added; the drawing is as it was.")
                return None
            keep = {id(m) for m in dlg.chosen()} | \
                {id(m) for m in sp["other"]}
        new, repeats = ait.skip_repeats(
            self.view.doc, [m for m in pencil if id(m) in keep])
        repeats += len(sp["previous"]) + dup
        self.last_split = {"new": len(sp["new"]),
                           "previous": len(sp["previous"]),
                           "added": sum(1 for m in new if m in sp["new"]),
                           "locked_decisions": len(carried["locked"])}
        marks += new
        self.status.setText(f"Adding {len(marks):,} measurement(s)…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            n = self.view.apply_marks(marks) if marks else 0
            for a in res["assemblies"].values():
                assemblies.set_job_assembly(self.view.doc, a)
        finally:
            QApplication.restoreOverrideCursor()
        self.result = res
        self.rows = rows
        unit = next((r["scale"][2] for r in rows if r["scale"]), "ft")
        self.summary.setPlainText(ait.summary_text(rows, res, unit))
        stopped = "Stopped before the end." in res.get("problems", [])
        self.status.setText(
            ("Stopped early - " if stopped else "Done - ")
            + f"added {n:,} measurement(s) and scale(s)"
            + (f" ({repeats:,} already on the drawing from an earlier run "
               "left out)" if repeats else "")
            + (f"; {len(renamed)} item name(s) you used before applied"
               if renamed else "")
            + (f"; {len(zdrop):,} left out by your zones" if zdrop else "")
            + ". Ctrl+Z takes them "
            "all off again. Next: 3. Check Takeoff, or see the Quantities "
            "panel.")
        self.check_btn.setEnabled(n > 0)
        self.review_btn.setEnabled(n > 0 or bool(res.get("review")))
        self.ai_btn.setEnabled(True)
        self.book_btn.setEnabled(True)
        self.spec_btn.setEnabled(True)
        if hasattr(self.win, "qty_dock"):
            self.win.qty_dock.show()
        return res

    def confirm_rerun(self, dlg):
        """Show the run-again choice (tests replace this)."""
        return dlg.exec() == QDialog.Accepted

    def check(self):
        self.win.check_takeoff()

    def review(self, show=True):
        """One review queue (v3): the AI's measurements not accepted yet
        and the CHECK items, least sure first (review_ui.ReviewQueueDialog;
        the old CHECK-items-only ReviewDialog is still there for others)."""
        from . import review as rv, settings
        from .review_ui import ReviewQueueDialog as ReviewDialog
        if not self.result:
            return None

        def changed():
            c = rv.counts(self.result)
            self.status.setText(
                f"Review: {c['accepted']} accepted, {c['fixed']} fixed, "
                f"{c['deleted']} deleted, {c['left']} still to check. Make "
                "the Estimate Workbook again to carry them.")
        dlg = ReviewDialog(self.win, self.result,
                           who=settings.author() or "reviewer",
                           on_change=changed)
        if show:
            dlg.show()
        self._review_dlg = dlg
        return dlg

    def scope(self):
        if not self.result:
            return ""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = ait.narrative(self.rows, self.result)
        finally:
            QApplication.restoreOverrideCursor()
        if not text:
            QMessageBox.information(
                self, "AI Takeoff", "The local AI model isn't running. "
                "Install Ollama (Help Center > AI) and run: ollama pull "
                "llama3.2 - the takeoff itself doesn't need it.")
            return ""
        self.summary.appendPlainText("\n--- Scope summary (AI) ---\n" + text)
        return text

    def workbook(self, path=None):
        """Save the takeoff as an estimate workbook (xlsx); returns the
        path, or None when cancelled."""
        import os
        from . import estimate_book
        if not self.result:
            return None
        src = getattr(self.view.doc, "name", "") or ""
        stem = os.path.splitext(os.path.basename(src))[0] or "Takeoff"
        if path is None:
            path, _f = QFileDialog.getSaveFileName(
                self, "Estimate Workbook", f"{stem} - Estimate.xlsx",
                "Excel workbook (*.xlsx)")
            if not path:
                return None
        gsf = next((q["qty"] for q in self.result.get("quantities") or ()
                    if q.get("name") == "Gross floor area"), None)
        lines = estimate_book.collect(self.rows, self.result)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            info = estimate_book.write(path, lines, project=stem, gsf=gsf)
        except OSError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Estimate Workbook",
                                f"Couldn't save the workbook:\n{e}")
            return None
        QApplication.restoreOverrideCursor()
        self.status.setText(
            f"Estimate workbook saved: {info['lines']} line(s) in "
            f"{info['divisions']} division(s), {info['review']} to check "
            f"(shaded). Rates are left blank for you - {path}")
        return path

    def read_spec(self, path=None):
        """Read a spec book PDF into the takeoff (materials, insulation).
        Returns the number of lines added, or None when cancelled."""
        import fitz
        from . import spec_materials
        if not self.result:
            return None
        if path is None:
            path, _f = QFileDialog.getOpenFileName(
                self, "Spec Book", "", "PDF (*.pdf)")
            if not path:
                return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            with fitz.open(path) as sd:
                sp = spec_materials.Spec.from_pdf(sd)
            n = ait.spec_quantities(self.result, sp)
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Spec Book",
                                f"Couldn't read the spec book:\n{e}")
            return None
        QApplication.restoreOverrideCursor()
        mats = len(self.result.get("materials") or {})
        self.status.setText(
            f"Spec book read: {len(sp.sections)} section(s); materials for "
            f"{mats} pipe / duct line(s), {n} insulation line(s) added. "
            "They go into the Estimate Workbook.")
        return n
