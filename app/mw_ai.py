"""The AI commands of the main window (split out of main_window.py, Nov
25).
"""
import fitz
import os
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog,
    QMessageBox)
from . import annotate, settings


class AiCommandsMixin:
    """MainWindow's ai methods (see main_window.py)."""

    def tag_check(self, pattern=None, show=True):
        """Review > Tags vs Schedule: door / window / fixture tags on the
        plans against their schedule (takeoff list #14)."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                                       QLabel, QLineEdit, QPushButton,
                                       QTableWidget, QTableWidgetItem,
                                       QVBoxLayout)
        from . import tagcheck
        v = self._view
        if v is None:
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle("Tags vs Schedule")
        dlg.resize(760, 480)
        lay = QVBoxLayout(dlg)
        row = QHBoxLayout()
        row.addWidget(QLabel("Tags:"))
        pat = QLineEdit(pattern or settings.get("tagcheck_pattern") or "D-#")
        pat.setToolTip("* any letters, ? one letter, # a number: D-#, 1##, "
                       "W*, P-#")
        go = QPushButton("Check")
        row.addWidget(pat, 1)
        row.addWidget(go)
        lay.addLayout(row)
        note = QLabel("")
        note.setWordWrap(True)
        lay.addWidget(note)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Tag", "Check", "Times drawn",
                                         "Sheets"])
        lay.addWidget(table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        csv_b = bb.addButton("Save CSV…", QDialogButtonBox.ActionRole)
        rfi_b = bb.addButton("Make an RFI", QDialogButtonBox.ActionRole)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        state = {"rep": None}

        def run():
            p = pat.text().strip()
            if not p:
                return None
            settings.set("tagcheck_pattern", p)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                rep = tagcheck.check(v.doc, p)
            finally:
                QApplication.restoreOverrideCursor()
            state["rep"] = rep
            rows = tagcheck.rows(rep)
            table.setRowCount(len(rows))
            for r, vals in enumerate(rows):
                for c, val in enumerate(vals):
                    table.setItem(r, c, QTableWidgetItem(str(val)))
            note.setText(f"{len(rep['both'])} OK, {len(rep['plan_only'])} on "
                         f"the plans only, {len(rep['schedule_only'])} in "
                         "the schedule only.")
            return rep

        def save_csv():
            if not state["rep"]:
                return
            path, _ = QFileDialog.getSaveFileName(
                dlg, "Save CSV", os.path.splitext(self._path or "tags")[0] +
                " tag check.csv", "CSV (*.csv)")
            if path:
                tagcheck.export_csv(state["rep"], path)

        def make_rfi():
            text = tagcheck.rfi_text(state["rep"] or {}) if state["rep"] \
                else ""
            if not text:
                note.setText("Nothing to ask: every tag matches.")
                return
            self.rfi_dock.show()
            self.rfis.new("RFI", {"title": f"Tags {state['rep']['pattern']} "
                                  "vs schedule", "question": text,
                                  "page": v.page})
        go.clicked.connect(run)
        csv_b.clicked.connect(save_csv)
        rfi_b.clicked.connect(make_rfi)
        dlg.run = run
        dlg.table = table
        if pattern:
            run()
        if show:
            dlg.show()
        return dlg

    def ai_models(self, show=True, fetch=None):
        """Review > Local AI Models: what the local AI has installed and
        the model size that fits this PC. Never downloads."""
        from .ai import models_ui
        return models_ui.open_dialog(self, show=show, fetch=fetch)

    def translate_markups(self, language=None, texts_fn=None):
        """Translate markup comments with the local AI model."""
        v = self._view
        if not v:
            return 0
        if language is None:
            language, ok = QInputDialog.getItem(
                self, "Translate Markups", "Translate comments into:",
                ["Spanish", "English", "French", "Portuguese", "German",
                 "Chinese (Simplified)", "Vietnamese", "Korean", "Polish"],
                0, True)
            if not ok or not language.strip():
                return 0
        jobs = []
        for it in annotate.markup_items(v.doc):
            text = (it.get("comment") or "").strip()
            if not text or it["type"] in ("Legend",):
                continue
            if it["subject"] and it.get("mtype"):
                continue                       # measurement labels: numbers
            key = "text" if it["type"] in ("Text Box", "Callout",
                                            "FreeText") else "note"
            jobs.append((it["page"], it["ref"], key, text))
        if not jobs:
            QMessageBox.information(self, "Translate Markups",
                                    "No markup comments to translate.")
            return 0
        from . import bg
        from .ai import review

        def apply(out):
            if getattr(v, "doc", None) is None or v.doc.is_closed:
                return 0                       # the tab closed meanwhile
            marks = [(pg, "set_annot", {**ref, key: new})
                     for (pg, ref, key, old), new in zip(jobs, out)
                     if new != old]
            n = v.apply_marks(marks) if marks else 0
            same = len(jobs) - len(marks)
            msg = f"Translated {n} markup comment(s) into {language}"
            if same:
                # said, not hidden (Chief's round 7, Nov 9: 1 of 3 came
                # back translated and it still read as all done)
                msg = (f"Translated {n} of {len(jobs)} markup comment(s) "
                       f"into {language} - {same} came back unchanged "
                       "(already in that language, or the AI skipped "
                       "them)")
            self._flash(msg)
            return n
        if texts_fn is not None:               # given directly: run here
            try:
                return apply(texts_fn([j[3] for j in jobs]))
            except Exception as ex:            # noqa: BLE001
                QMessageBox.warning(self, "Translate Markups", str(ex))
                return 0
        # the local model can take minutes: off the window's thread, with a
        # box that can be hidden or cancelled (Chief's re-test, Nov 7: the
        # program froze for 6 minutes and Windows said Not Responding)
        from PySide6.QtWidgets import QProgressDialog
        texts = [j[3] for j in jobs]
        busy = QProgressDialog(
            f"Translating {len(texts)} markup comment(s) into {language} "
            "with the local AI - this can take a few minutes. You can keep "
            "working; Cancel throws the result away.", "Cancel", 0, 0, self)
        busy.setWindowTitle("Translate Markups")
        busy.setMinimumDuration(0)
        busy.setAutoClose(False)
        busy.setAutoReset(False)
        busy.setModal(False)
        state = {"cancelled": False, "over": False, "late": False}
        token = review.Cancel()
        # the longest it may wait: the AI part limit for each batch of 25
        limit = self._ai_limit() * max(1, -(-len(texts) // 25))

        def cancel():
            # closing the box when the work is done emits canceled too;
            # only a Cancel while it runs counts (Chief's round 4, Nov 7:
            # every finished translation was thrown away as "cancelled").
            # The request itself is ended too (round 7)
            if not state["over"]:
                state["cancelled"] = True
                token.cancel_soon()
        busy.canceled.connect(cancel)
        busy.show()
        self._translate_busy = busy

        def too_long():
            if not state["over"]:
                state["late"] = True
                cancel()
        watch = QTimer(busy)
        watch.setSingleShot(True)
        watch.timeout.connect(too_long)
        watch.start(int(limit * 1000))

        def finish():
            cancelled = state["cancelled"]
            state["over"] = True
            watch.stop()
            busy.close()
            return cancelled

        def stopped():
            if state["late"]:
                QMessageBox.warning(
                    self, "Translate Markups",
                    "The local AI didn't answer in "
                    f"{self._minutes(limit)}, so the translation was "
                    "stopped. Nothing changed.")
            else:
                self._flash("Translate Markups cancelled - nothing changed")

        def done(out):
            if finish():
                stopped()
                return
            apply(out)

        def failed(msg):
            if finish():
                stopped()
            else:
                QMessageBox.warning(self, "Translate Markups", str(msg))
        bg.run(lambda: review.run_cancellable(
            token, review.translate_texts, texts, language), done, failed,
            self)
        return busy

    def ai_find_rfis(self, spec_path=None, ask=None, wait=False,
                     dialog=None):
        """Find RFIs (v36). Drawings: rule checks over the whole set - pipe
        runs, rims/inverts, slopes, callouts, spec sections, schedules,
        open scope - run in the background and show in one panel as soon
        as they're done; no language model is needed to find anything (the
        panel can optionally reword a question with it). A spec book open
        on its own still goes to _find_rfis_in_specs. `ask`, `wait` and
        `dialog` are for tests."""
        import time
        from .ai import rfi_finder, rfi_rules
        from . import bg
        v = self._view
        if not v:
            return None
        doc = v.doc
        src = doc.name if (doc.name and os.path.isfile(doc.name) and
                           not getattr(doc, "is_dirty", True)) else None
        data = plans_now = None
        if not src:
            try:
                data = doc.tobytes()          # quick; the text pass isn't
            except Exception:
                plans_now = rfi_finder.gather(doc)

        def read_plans():
            # its own copy of the document, so the worker never shares the
            # viewer's (PyMuPDF documents are single-threaded)
            if plans_now is not None:
                return plans_now
            with (fitz.open(src) if src else fitz.open("pdf", data)) as d:
                return rfi_finder.gather(d)

        def scan(spec, plans=None):
            plans = plans if plans is not None else read_plans()
            if rfi_finder.is_spec_book(plans):
                return None, plans, ""
            specs, note = None, ""
            if spec:
                try:
                    with fitz.open(spec) as sd:
                        specs = rfi_finder.gather(sd, "specs")
                except Exception as ex:
                    note = f"Couldn't read the specs: {ex}"
            return rfi_rules.find(plans, specs), plans, note

        if wait:
            items, plans, note = scan(spec_path)
            if items is None:
                return self._find_rfis_in_specs(plans, ask, wait, dialog)
            if dialog is None:
                return items
            dlg = dialog(items, note)
            if not dlg.exec():
                return []
            return self.create_rfis(dlg.selected(), spec_path)
        from .rfi_ui import RfiFindingsPanel
        old = getattr(self, "_rfi_panel", None)
        if old is not None:
            try:
                old.close()
                old.deleteLater()
            except RuntimeError:
                pass

        def goto(f):
            if f.get("doc", "plans") != "plans" or f.get("page") is None:
                return
            pg, _r = rfi_finder.locate(self._view.doc, f)
            if pg is not None:
                self._view.go_to(pg)

        cache = {}

        def run(spec):
            started = time.monotonic()

            def done(res):
                items, plans, note = res
                cache["plans"] = plans
                if items is None:                # a spec book is open
                    panel.close()
                    self._find_rfis_in_specs(plans, ask)
                    return
                panel.set_findings(items, (note + " " if note else "") +
                                   rfi_rules.coverage_text(plans, len(items))
                                   + f" ({time.monotonic() - started:.1f} s)")
            bg.run(lambda: scan(spec, cache.get("plans")), done,
                   lambda err: panel.set_findings([], f"Scan failed: {err}"),
                   panel)
        panel = RfiFindingsPanel(self, on_draft=self.create_rfis,
                                 on_specs=run, on_goto=goto)
        panel.spec_path = spec_path or None
        self._rfi_panel = panel
        panel.show()
        run(spec_path)
        return panel

    def ai_takeoff(self, show=True):
        """AI Takeoff: the whole set taken off in one go."""
        from .aitakeoff_ui import AITakeoffDialog
        if not self._view or self._collab_blocked("AI Takeoff"):
            return None
        dlg = AITakeoffDialog(self)
        if show:
            dlg.show()
            dlg.read()
        self._ai_dlg = dlg
        return dlg

    def ai_summary(self):
        if not self._view:
            return
        from .ai import review
        from . import bg
        text, info = review.doc_text_info(self._view.doc)
        note = review.coverage_note(info)
        in_set = review.set_sheets(self._view.doc)
        # a busy box while the model works (Chief's estimator test, Nov 7:
        # nothing showed for a minute, then the answer popped up)
        from PySide6.QtWidgets import QProgressDialog
        head = ("Asking the local AI for a summary - this can take a "
                "minute.")
        # while it waits nothing has been reviewed yet: "Reading", and the
        # answer keeps "Reviewed" (hands-on pass, Nov 10)
        reading = note.replace("Reviewed", "Reading", 1)
        busy = QProgressDialog(head + "\n" + reading, "Stop", 0, 0, self)
        busy.setWindowTitle("AI Summary")
        busy.setMinimumDuration(0)
        busy.setAutoClose(False)
        busy.setAutoReset(False)
        # Stop really ends the request, and one that never answers is
        # stopped after the AI time limit (Chief's round 7, Nov 9: the
        # button only hid the box and the request could run 15 minutes)
        state = {"over": False, "stopped": False, "late": False}
        token = review.Cancel()
        limit = self._ai_limit()
        started = time.monotonic()

        def stop():
            if not state["over"]:
                state["stopped"] = True
                token.cancel_soon()
        busy.canceled.connect(stop)

        def tick():
            waited = time.monotonic() - started
            if waited > limit and not state["over"]:
                state["late"] = True
                stop()
                return
            busy.setLabelText(f"{head} Waiting {waited:.0f} s.\n{reading}")
        clock = QTimer(busy)
        clock.setInterval(1000)
        clock.timeout.connect(tick)
        clock.start()
        busy.show()
        self._ai_busy = busy
        self._ai_summary_tick = tick                    # for tests

        def finish():
            was = state["stopped"]
            state["over"] = True
            clock.stop()
            try:
                busy.close()
            except RuntimeError:
                pass
            return was

        def stopped():
            if state["late"]:
                QMessageBox.warning(
                    self, "AI Summary",
                    f"The local AI didn't answer in {self._minutes(limit)}"
                    ", so the summary was stopped. Nothing was read.")
            else:
                self._flash("AI Summary stopped")

        def done(text_out):
            if finish():
                stopped()
            else:
                QMessageBox.information(self, "AI Summary", text_out)

        def failed(e):
            if finish():
                stopped()
            else:
                QMessageBox.warning(self, "AI", e)
        bg.run(lambda: review.run_cancellable(
            token, review.summarize_text, text, info["cut"], note, in_set),
            done, failed, self)
        return busy

    def ai_redline(self):
        if not self._view:
            return
        from .ai.dialogs import RedlineDialog
        from .ai import review
        dlg = RedlineDialog(self._view.doc, self)
        if dlg.exec():
            self._view.apply_marks(
                review.redline_marks(self._view.doc, dlg.selected_edits()))

    def ai_spec_check(self):
        if not self._view:
            return
        from .ai.dialogs import SpecCheckDialog
        from .ai import review
        dlg = SpecCheckDialog(self._view.doc, self)
        if dlg.exec() and dlg.findings:
            self._view.apply_marks(
                review.spec_marks(self._view.doc, dlg.findings))

    def ai_schedule(self, store=None, show=True):
        """Review > Build Schedule From Plans: open (or start) the project's
        schedule in the Scheduler and read this drawing set and its spec
        book into a draft schedule."""
        w = self.scheduler(store=store)
        if w is None:
            return None
        return w.build_from_plans(plans=self._path, show=show)
