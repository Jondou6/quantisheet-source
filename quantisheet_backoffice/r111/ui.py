"""Screens for release 1.1.1.

These pages are not on the navigation yet. Wire each one from
r111.menu.ENTRIES. "Copy Yesterday's Crews" is a button on the crew
board. The checklist editor is the text box on the checklist page,
not a hidden dialog.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QDrag, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from .. import cents, clock
from ..ui.common import fill, heading, table
from . import (apdrop, crewboard, equipment, incident, jha, qatemplates,
               safety, sagejc, waiting, warranty)
from . import schema


class _Page(QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.lay = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)

    def _tell(self, text):
        self.status.setText(str(text))


BY_NUMBER = "Each job in the report (by its job number)"


class ReportPage(_Page):
    """Budget vs committed vs actual from a Job Cost Report: import the
    report PDF, look it over, then Publish so Job Cost uses it."""

    def __init__(self, office, parent=None, pick_file=None, confirm=None):
        super().__init__(office, parent)
        from ..ui.common import job_picker
        self.pick_file = pick_file
        # confirm(text, duplicate) -> True to store (tests pass one)
        self.confirm = confirm
        self.last_import = None
        self.lay.addWidget(heading("Job cost report"))
        self.job = job_picker(office)
        # a report can hold several jobs: by default each goes to the job
        # with its number (added if new), never all onto one picked job
        self.job.insertItem(0, BY_NUMBER, None)
        self.job.setCurrentIndex(0)
        self.lay.addWidget(self.job)
        row = QHBoxLayout()
        imp = QPushButton("Import Job Cost Report…")
        imp.clicked.connect(lambda: self.import_report())
        pub = QPushButton("Publish to Job Cost")
        pub.clicked.connect(lambda: self.publish())
        unp = QPushButton("Unpublish")
        unp.clicked.connect(lambda: self.unpublish())
        for b in (imp, pub, unp):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.grid = table(["Code", "Description", "Total estimate",
                           "Committed", "JTD cost", "Variance", "Overrun"])
        self.lay.addWidget(self.grid)
        self.lay.addWidget(self.status)
        self.job.currentIndexChanged.connect(lambda _i: self._job_changed())
        self.refresh()

    def _job_changed(self):
        # Publish / Unpublish act on the job now picked, not on whatever
        # was imported last (a 3-job report would publish job 1 again)
        self.last_import = None
        self.refresh()

    def _reload_jobs(self, select_id=None):
        """Jobs added by an import show up in the picker; pick select_id."""
        from ..ui.common import job_picker
        fresh = job_picker(self.office)
        self.job.blockSignals(True)
        try:
            self.job.clear()
            self.job.addItem(BY_NUMBER, None)
            for i in range(fresh.count()):
                self.job.addItem(fresh.itemText(i), fresh.itemData(i))
            idx = self.job.findData(select_id) if select_id is not None \
                else 0
            self.job.setCurrentIndex(max(idx, 0))
        finally:
            self.job.blockSignals(False)
        fresh.deleteLater()

    def _job_id(self):
        jid = self.job.currentData()
        return int(jid) if jid is not None else None

    def import_report(self, path=None):
        if path is None:
            if self.pick_file is not None:
                path = self.pick_file()
            else:
                from PySide6.QtWidgets import QFileDialog
                path, _ = QFileDialog.getOpenFileName(
                    self, "Job Cost Report", "", "PDF (*.pdf)")
        if not path:
            return None
        # show what would be stored first (reviews 1 + 2, Nov 4)
        try:
            pv = sagejc.preview(self.office, path, job_id=self._job_id())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        text = sagejc.preview_text(pv)
        if not self._confirm(text, bool(pv["duplicate_of"])):
            self._tell("Not imported.")
            return None
        try:
            iid = sagejc.import_pdf(self.office, path, job_id=self._job_id(),
                                    allow_duplicate=bool(pv["duplicate_of"]))
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        imp = sagejc.get_import(self.office, iid)
        same_file = self.office.db.scalar(
            "SELECT COUNT(*) FROM sage_imports WHERE source_hash = ? AND "
            "deleted = 0 AND id >= ?", (imp.get("source_hash"), iid)) or 1
        self._reload_jobs(imp.get("job_id"))
        self.last_import = iid
        self.refresh(import_id=iid)
        more = (f"  This report had {same_file} jobs; pick each one above "
                "to check and publish it." if same_file > 1 else "")
        self._tell(self.status.text() + "  Check it, then Publish to Job "
                   "Cost." + more)
        return iid

    def _confirm(self, text, duplicate):
        if self.confirm is not None:
            return bool(self.confirm(text, duplicate))
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Icon.Question, "Import Job Cost Report",
                          text + "\n\nStore this import? (Nothing changes in "
                          "Job Cost until you Publish.)", parent=self)
        ok = box.addButton("Import Again Anyway" if duplicate else "Import",
                           QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is ok

    def _current_import(self):
        if self.last_import is not None:
            return self.last_import
        jid = self._job_id()
        if jid is None or not hasattr(sagejc, "latest_import"):
            return None
        return sagejc.latest_import(self.office, jid)

    def publish(self):
        iid = self._current_import()
        if iid is None:
            self._tell("Import a job cost report first.")
            return None
        try:
            sagejc.publish(self.office, iid)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell("Published: Job Cost now uses this report for its codes.")
        return iid

    def unpublish(self):
        iid = self._current_import()
        if iid is None:
            return None
        try:
            sagejc.unpublish(self.office, iid)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell("Unpublished: Job Cost is back to the books figures.")
        return iid

    def refresh(self, import_id=None):
        jid = self._job_id()
        if jid is None and import_id is None:
            self._tell("Pick a job, then Import Job Cost Report.")
            return
        try:
            rows = sagejc.comparison(self.office, job_id=jid,
                                     import_id=import_id)
        except Exception as e:                        # noqa: BLE001
            fill(self.grid, [])
            self._tell(str(e) if import_id else
                       "No job cost report for this job yet.")
            return
        fill(self.grid, [(r["code"], r["description"], r["total_estimate"],
                          r["committed"], r["jtd"], r["variance"],
                          "Overrun" if r["overrun"] else "")
                         for r in rows],
             money_cols=(2, 3, 4, 5))
        n = sum(1 for r in rows if r["overrun"])
        self._tell(f"{len(rows)} cost code(s), {n} overrun(s).")


class WaitingPage(_Page):
    """Invoice PDF text, coding, and one-click approve or reject."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Waiting on me"))
        self.grid = table(["AP no.", "Vendor", "Invoice", "Job", "Total"])
        self.grid.itemSelectionChanged.connect(self._show)
        self.lay.addWidget(self.grid)
        split = QSplitter()
        self.coding = QPlainTextEdit()
        self.coding.setReadOnly(True)
        self.coding.setPlaceholderText("Coding")
        self.pdf = QPlainTextEdit()
        self.pdf.setReadOnly(True)
        self.pdf.setPlaceholderText("Invoice")
        split.addWidget(self.coding)
        split.addWidget(self.pdf)
        self.lay.addWidget(split, 1)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Reason, required to reject")
        self.lay.addWidget(self.reason)
        row = QHBoxLayout()
        approve = QPushButton("Approve")
        approve.clicked.connect(self.approve_selected)
        reject = QPushButton("Reject")
        reject.clicked.connect(self.reject_selected)
        row.addWidget(approve)
        row.addWidget(reject)
        self.lay.addLayout(row)
        self.lay.addWidget(self.status)
        self.ids = []
        self.refresh()

    def refresh(self):
        rows = waiting.mine(self.office)
        self.ids = [r["invoice_id"] for r in rows]
        self.rows = rows
        fill(self.grid, [(r["number"], r["vendor"], r["invoice_no"], r["job"],
                          r["total"]) for r in rows], money_cols=(4,))
        if self.grid.rowCount():
            self.grid.selectRow(0)
        else:
            self.coding.setPlainText("")
            self.pdf.setPlainText("")
        self._tell(f"{len(rows)} waiting on you.")

    def _current(self):
        row = self.grid.currentRow()
        if row < 0 or row >= len(self.ids):
            return None
        return self.rows[row]

    def _show(self):
        cur = self._current()
        if not cur:
            return
        self.coding.setPlainText(cur["coding"])
        self.pdf.setPlainText(cur["pdf_text"] or cur["doc_path"] or
                              "(no invoice PDF)")

    def approve_selected(self):
        cur = self._current()
        if not cur:
            self._tell("Select an invoice.")
            return
        try:
            waiting.approve(self.office, cur["invoice_id"])
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self.refresh()

    def reject_selected(self):
        cur = self._current()
        if not cur:
            self._tell("Select an invoice.")
            return
        try:
            waiting.reject(self.office, cur["invoice_id"], self.reason.text())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self.refresh()


class DropFolderBar(_Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Invoice folder"))
        self.path = QLineEdit()
        self.path.setPlaceholderText("Folder of invoice PDFs")
        use = QPushButton("Use this folder")
        use.clicked.connect(self.use_folder)
        scan = QPushButton("Scan invoice folder")
        scan.clicked.connect(lambda: self.scan_now(False))
        self.lay.addWidget(self.path)
        row = QHBoxLayout()
        row.addWidget(use)
        row.addWidget(scan)
        self.lay.addLayout(row)
        self.lay.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(lambda: self.scan_now(quiet=True))
        self.timer.start()

    def use_folder(self):
        try:
            apdrop.set_folder(self.office, self.path.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self._tell("Folder set.")

    def scan_now(self, quiet=False):
        if quiet and apdrop.folder(self.office) is None:
            return []
        try:
            found = apdrop.scan(self.office)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return []
        if found or not quiet:
            self._tell(f"{len(found)} new file(s).")
        self.refresh_duplicates()
        return found

    # ---- QS-020: files held back as duplicates ---------------------------
    def _dup_widgets(self):
        if getattr(self, "dups", None) is not None:
            return
        self.dups = table(["File", "Why it was held"])
        self.allow = QPushButton("Allow This Duplicate…")
        self.allow.setToolTip("Save the selected invoice even though it "
                              "looks like one already entered. You'll be "
                              "asked why; your name and the reason are kept.")
        self.allow.clicked.connect(lambda: self.allow_selected())
        self.lay.addWidget(QLabel("Held back as possible duplicates:"))
        self.lay.addWidget(self.dups)
        self.recurring = QCheckBox("This vendor often bills the same amount "
                                   "(rent, fuel cards) - don't hold "
                                   "same-amount bills from them again")
        self.lay.addWidget(self.recurring)
        self.lay.addWidget(self.allow)

    def duplicate_rows(self):
        try:
            return self.office.db.rows(
                "SELECT id, source_path, message FROM ap_drop_files WHERE "
                "status = 'duplicate' AND deleted = 0 ORDER BY id")
        except Exception:                             # noqa: BLE001
            return []

    def refresh_duplicates(self):
        rows = self.duplicate_rows()
        if not rows and getattr(self, "dups", None) is None:
            return
        self._dup_widgets()
        import os
        self._dup_ids = [r["id"] for r in rows]
        fill(self.dups, [(os.path.basename(r["source_path"] or ""),
                          r["message"] or "") for r in rows])
        self.allow.setEnabled(bool(rows))

    def allow_selected(self, reason=None):
        ids = getattr(self, "_dup_ids", [])
        row = self.dups.currentRow() if getattr(self, "dups", None) else -1
        if not 0 <= row < len(ids):
            self._tell("Pick a file in the list first.")
            return None
        if reason is None:
            from PySide6.QtWidgets import QInputDialog
            reason, ok = QInputDialog.getText(
                self, "Allow This Duplicate",
                "Why is this not a duplicate? (kept with your name)")
            if not ok:
                return None
        try:
            iid = apdrop.accept_duplicate(self.office, ids[row], reason)
            if getattr(self, "recurring", None) is not None and \
                    self.recurring.isChecked():
                from . import dupblock
                vid = apdrop.loads_captured(self.office.db.get(
                    "ap_drop_files", ids[row])).get("vendor_id")
                if vid:
                    dupblock.set_recurring(self.office, vid, True)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell("Saved; the reason is in the audit log.")
        self.refresh_duplicates()
        return iid


class SecurityPage(_Page):
    """Payroll key (QS-025) and who may approve their own entries
    (QS-024). Settings-level; the buttons say what they do."""

    def __init__(self, office, parent=None, pick_save=None, pick_open=None,
                 ask_password=None):
        super().__init__(office, parent)
        from . import duties, paykeys
        self.paykeys, self.duties = paykeys, duties
        self.pick_save, self.pick_open = pick_save, pick_open
        self.ask_password = ask_password
        self.lay.addWidget(heading("Payroll key and approvals"))
        self.where = QLabel("")
        self.where.setWordWrap(True)
        self.lay.addWidget(self.where)
        row = QHBoxLayout()
        bk = QPushButton("Back Up Payroll Key…")
        bk.setToolTip("Save a password-protected copy of the key. Without "
                      "it, payroll and HR fields can't be opened on another "
                      "PC or after Windows is reset.")
        bk.clicked.connect(lambda: self.backup())
        rs = QPushButton("Restore Payroll Key…")
        rs.clicked.connect(lambda: self.restore())
        rt = QPushButton("Rotate Payroll Key")
        rt.setToolTip("Make a new key and re-lock every payroll and HR "
                      "field with it. Back up the key again afterwards.")
        rt.clicked.connect(lambda: self.rotate())
        rk = QPushButton("Retire Old Keys…")
        rk.setToolTip("After a suspected leak: destroy the keys kept from "
                      "before the last rotation.")
        rk.clicked.connect(lambda: self.retire())
        self.retire_btn = rk
        for b in (bk, rs, rt, rk):
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.selfapp = QPushButton("")
        self.selfapp.setToolTip("Admin only. For a one-person office: let "
                                "the person who entered something approve "
                                "it too. Each use is logged.")
        self.selfapp.clicked.connect(lambda: self.toggle_self_approval())
        self.lay.addWidget(self.selfapp)
        self.lay.addWidget(self.status)
        self.lay.addStretch(1)
        self.refresh()

    def refresh(self):
        last = self.paykeys.last_backup(self.office)
        when = (f"Last key backup: {last['at'][:16].replace('T', ' ')} "
                f"({last['file']})." if last else
                "Last key backup: NEVER - back it up now (Back Up Payroll "
                "Key).")
        olds = self.paykeys.retired_keys(self.office)
        if olds:
            when += (f"\n{len(olds)} older key(s) kept so older backups "
                     "open (Retire Old Keys after a suspected leak).")
        self.where.setText(
            "The payroll key is kept in this Windows user's profile, not "
            "in the company folder. Keep a key backup somewhere safe "
            "(not in the company folder).\n" + when)
        on = self.duties.self_approval_on(self.office)
        self.selfapp.setText("Self-Approval: ON (click to turn off)…" if on
                             else "Self-Approval: off (Admin can turn on)…")

    def _password(self, title, confirm=False):
        if self.ask_password is not None:
            return self.ask_password(title)
        from PySide6.QtWidgets import QInputDialog, QLineEdit as LE
        pw, ok = QInputDialog.getText(self, title, "Key backup password "
                                      "(10+ characters):", LE.EchoMode.Password)
        if not ok:
            return None
        if confirm:
            again, ok = QInputDialog.getText(self, title, "Type it again:",
                                             LE.EchoMode.Password)
            if not ok or again != pw:
                self._tell("The passwords didn't match; nothing was saved.")
                return None
        return pw

    def backup(self):
        path = self.pick_save() if self.pick_save else None
        if path is None and self.pick_save is None:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(
                self, "Back Up Payroll Key", "payroll-key.qskey",
                "Payroll key backup (*.qskey)")
        if not path:
            return None
        pw = self._password("Back Up Payroll Key", confirm=True)
        if not pw:
            return None
        try:
            out = self.paykeys.backup(self.office, path, pw)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell(f"Key backed up to {out}.")
        return out

    def restore(self):
        path = self.pick_open() if self.pick_open else None
        if path is None and self.pick_open is None:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "Restore Payroll Key", "", "Payroll key backup (*.qskey)")
        if not path:
            return False
        pw = self._password("Restore Payroll Key")
        if not pw:
            return False
        try:
            self.paykeys.restore(self.office, path, pw)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return False
        self._tell("Payroll key restored.")
        return True

    def rotate(self, confirmed=None):
        if confirmed is None:
            from PySide6.QtWidgets import QMessageBox
            confirmed = QMessageBox.question(
                self, "Rotate Payroll Key",
                "Make a new payroll key and re-lock every payroll and HR "
                "field with it?\n\nEarlier keys are kept on this PC so old "
                "backups still open. Back up the new key afterwards.") == \
                QMessageBox.StandardButton.Yes
        if not confirmed:
            return None
        try:
            done = self.paykeys.rotate(self.office)
        except Exception as e:                        # noqa: BLE001
            self._tell(f"Not rotated - nothing changed. ({e})")
            return None
        self._tell(f"New key in use: {done['fields']} field(s) and "
                   f"{done['files']} file(s) re-locked. Back up the key now.")
        self.refresh()                  # shows the older key now kept
        return done

    def retire(self, confirmed=None):
        olds = self.paykeys.retired_keys(self.office)
        if not olds:
            self._tell("No old keys are kept on this PC.")
            return 0
        if confirmed is None:
            from PySide6.QtWidgets import QMessageBox
            lst = ", ".join(o["date"].replace("T", " ") for o in olds)
            confirmed = QMessageBox.question(
                self, "Retire Old Keys", self.paykeys.RETIRE_WARNING +
                f"\n\nKeys kept from: {lst}") == \
                QMessageBox.StandardButton.Yes
        if not confirmed:
            return None
        try:
            n = self.paykeys.retire_old_keys(self.office)
        except Exception as e:                        # noqa: BLE001
            self._tell(f"Not retired - nothing changed. ({e})")
            return None
        self._tell(f"{n} old key(s) destroyed.")
        self.refresh()
        return n

    def toggle_self_approval(self, reason=None):
        want = not self.duties.self_approval_on(self.office)
        if reason is None:
            from PySide6.QtWidgets import QInputDialog
            reason, ok = QInputDialog.getText(
                self, "Self-Approval", "Why? (kept in the audit log)")
            if not ok:
                return None
        try:
            self.duties.set_self_approval(self.office, want, reason)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self.refresh()
        return want


class _CrewList(QListWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def startDrag(self, supported):
        item = self.currentItem()
        if item is None:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"crew:{item.data(Qt.ItemDataRole.UserRole)}")
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class _JobList(QListWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        text = event.mimeData().text() if event.mimeData().hasText() else ""
        if str(text).startswith("crew:"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        text = str(event.mimeData().text() or "")
        if not text.startswith("crew:"):
            event.ignore()
            return
        crew_id = int(text.split(":", 1)[1])
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        if item is None and self.count() == 1:
            item = self.item(0)
        elif item is None:
            item = self.currentItem()
        if item is None:
            event.ignore()
            return
        self.page.assign_crew(crew_id, int(item.data(Qt.ItemDataRole.UserRole)))
        event.acceptProposedAction()


class CrewBoardPage(_Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Crew board"))
        self.date = QLineEdit(clock.today().isoformat())
        self.code = QLineEdit()
        self.code.setPlaceholderText("Cost code")
        self.hours = QLineEdit("8")
        self.crews = _CrewList(self)
        self.jobs = _JobList(self)
        lists = QHBoxLayout()
        lists.addWidget(self.crews)
        lists.addWidget(self.jobs)
        self.grid = table(["Crew", "Job", "Cost code", "Hours"])
        self.copy_btn = QPushButton("Copy Yesterday's Crews")
        self.copy_btn.setObjectName("copyYesterday")
        self.copy_btn.clicked.connect(self.copy_crews)
        prefill = QPushButton("Fill daily logs and time cards")
        prefill.clicked.connect(self.fill_day)
        print_btn = QPushButton("Print crew board")
        print_btn.clicked.connect(self.print_board)
        self.lay.addWidget(self.date)
        self.lay.addWidget(self.code)
        self.lay.addWidget(self.hours)
        self.lay.addLayout(lists)
        row = QHBoxLayout()
        row.addWidget(self.copy_btn)
        row.addWidget(prefill)
        row.addWidget(print_btn)
        self.lay.addLayout(row)
        self.lay.addWidget(self.grid)
        self.lay.addWidget(self.status)
        self.reload()

    def reload(self):
        self.crews.clear()
        for c in self.office.db.rows("SELECT id, name FROM crews WHERE "
                                     "deleted = 0 ORDER BY name"):
            item = QListWidgetItem(c["name"])
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self.crews.addItem(item)
        self.jobs.clear()
        for j in self.office.db.rows("SELECT id, number, name FROM jobs WHERE "
                                     "deleted = 0 ORDER BY number"):
            item = QListWidgetItem(f"{j['number']} {j['name']}")
            item.setData(Qt.ItemDataRole.UserRole, j["id"])
            self.jobs.addItem(item)
        self.reload_board()

    def reload_board(self):
        rows = crewboard.board(self.office, self.date.text().strip())
        fill(self.grid, [(r["crew"], f"{r['job_number']} {r['job_name']}",
                          r["cost_code"], cents.hours_text(r["hours"]))
                         for r in rows])

    def assign_crew(self, crew_id, job_id):
        try:
            crewboard.assign(self.office, self.date.text().strip(), crew_id,
                             job_id, self.code.text().strip(),
                             self.hours.text().strip() or "8")
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self.reload_board()
        self._tell("Crew assigned.")

    def copy_crews(self):
        try:
            done = crewboard.copy_yesterday(self.office,
                                            self.date.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self.reload_board()
        self._tell(f"Copied crews from {done['from']}.")

    def fill_day(self):
        try:
            done = crewboard.prefill(self.office, self.date.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self._tell(f"Filled {len(done['jobs'])} job(s), "
                   f"{len(done['time_lines'])} time card line(s).")

    def print_board(self):
        try:
            path = crewboard.print_pdf(self.office, self.date.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self._tell(path)


class QaTemplatePage(_Page):
    """The checklist editor. The list and the text box are on the page."""

    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Checklist templates"))
        self.names = QListWidget()
        self.names.currentTextChanged.connect(self._load)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Checklist name")
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("qaEditor")
        self.editor.setPlaceholderText("One check per line")
        self.save_btn = QPushButton("Save checklist")
        self.save_btn.clicked.connect(self.save)
        remove = QPushButton("Delete checklist")
        remove.clicked.connect(self.remove)
        self.lay.addWidget(self.names)
        self.lay.addWidget(self.name)
        self.lay.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addWidget(self.save_btn)
        row.addWidget(remove)
        self.lay.addLayout(row)
        self.lay.addWidget(self.status)
        self.reload()

    def reload(self):
        self.names.clear()
        for row in qatemplates.templates(self.office):
            self.names.addItem(row["name"])
        if self.names.count():
            self.names.setCurrentRow(0)

    def _load(self, name):
        if not name:
            return
        self.name.setText(name)
        try:
            lines = qatemplates.items(self.office, name)
        except Exception:                             # noqa: BLE001
            return
        self.editor.setPlainText("\n".join(lines))

    def save(self):
        try:
            qatemplates.save(self.office, self.name.text(),
                             self.editor.toPlainText().splitlines())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self.reload()
        self._tell("Checklist saved.")

    def remove(self):
        try:
            qatemplates.delete(self.office, self.name.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self.editor.setPlainText("")
        self.reload()
        self._tell("Checklist removed.")


class SafetyPage(_Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.lay.addWidget(heading("Safety meetings"))
        self.topics = QListWidget()
        for topic in safety.topics(office):
            item = QListWidgetItem(topic["title"])
            item.setData(Qt.ItemDataRole.UserRole, topic["id"])
            self.topics.addItem(item)
        self.date = QLineEdit(clock.today().isoformat())
        self.who = QLineEdit()
        self.who.setPlaceholderText("Attendee name")
        add = QPushButton("Add attendee and sign")
        add.clicked.connect(self.add_signed)
        sheet = QPushButton("Sign-in sheet")
        sheet.clicked.connect(self.sheet)
        self.pad = SignaturePad()
        self.lay.addWidget(self.topics)
        self.lay.addWidget(self.date)
        self.lay.addWidget(self.who)
        self.lay.addWidget(self.pad)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(sheet)
        self.lay.addLayout(row)
        self.lay.addWidget(self.status)
        self.meeting_id = None

    def add_signed(self):
        item = self.topics.currentItem()
        if item is None and self.topics.count():
            item = self.topics.item(0)
        if item is None:
            self._tell("Pick a topic.")
            return
        if not self.pad.strokes:
            # never a stand-in signature: an empty pad isn't signed
            self._tell("Have them sign on the pad first.")
            return
        try:
            if self.meeting_id is None:
                self.meeting_id = safety.add_meeting(
                    self.office, self.date.text().strip(),
                    topic_id=int(item.data(Qt.ItemDataRole.UserRole)))
            strokes = self.pad.strokes
            aid = safety.add_attendee(self.office, self.meeting_id,
                                      self.who.text())
            safety.sign(self.office, aid, strokes)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self._tell(f"Signed onto meeting {self.meeting_id}.")

    def sheet(self):
        if not self.meeting_id:
            self._tell("Add someone first.")
            return
        try:
            path = safety.signin_pdf(self.office, self.meeting_id)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        self._tell(path)


class SignaturePad(QWidget):
    """Mouse signature. Points are integer thousandths of the pad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.strokes = []
        self._current = None
        self.setMinimumHeight(70)

    def mousePressEvent(self, event):
        self._current = [self._point(event)]
        self.strokes.append(self._current)
        self.update()

    def mouseMoveEvent(self, event):
        if self._current is not None:
            self._current.append(self._point(event))
            self.update()

    def mouseReleaseEvent(self, event):
        self._current = None

    def _point(self, event):
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        p = event.position()
        return [int(p.x() / w * 1000), int(p.y() / h * 1000)]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        for stroke in self.strokes:
            for a, b in zip(stroke, stroke[1:]):
                painter.drawLine(int(a[0] / 1000 * w), int(a[1] / 1000 * h),
                                 int(b[0] / 1000 * w), int(b[1] / 1000 * h))
        painter.end()


# ---- helpers for the field pages (incidents, plans, equipment, warranty) --

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"


def _labelled(lay, label, widget):
    """A plain label above its box, so every box says what it is for."""
    lay.addWidget(QLabel(label))
    lay.addWidget(widget)
    return widget


def _box(placeholder="", text=""):
    w = QLineEdit(text)
    if placeholder:
        w.setPlaceholderText(placeholder)
    return w


def _button_row(lay, *buttons):
    row = QHBoxLayout()
    for b in buttons:
        row.addWidget(b)
    row.addStretch(1)
    lay.addLayout(row)


def _button(text, slot):
    b = QPushButton(text)
    b.clicked.connect(lambda: slot())
    return b


def _picked_row(t):
    """The selected row of a read-only table, or None."""
    rows = t.selectionModel().selectedRows() if t.selectionModel() else []
    if rows:
        return rows[0].row()
    r = t.currentRow()
    return r if r >= 0 else None


def _save_path(page, picker, title, suggested, filt="PDF (*.pdf)",
               exts=(".pdf",)):
    """Where to save: the injected picker (tests), else a save dialog.
    '' means the person cancelled. A name with no known extension gets
    the first one."""
    if picker is not None:
        path = picker()
    else:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(page, title, suggested, filt)
    path = str(path or "").strip()
    if path and not path.lower().endswith(tuple(exts)):
        path += exts[0]
    return path


def _image_paths(page, picker):
    """Photos to add: the injected picker (tests), else an open dialog.
    Always a list."""
    if picker is not None:
        got = picker()
    else:
        from PySide6.QtWidgets import QFileDialog
        got, _ = QFileDialog.getOpenFileNames(page, "Add Photo", "",
                                              IMAGE_FILTER)
    if not got:
        return []
    if isinstance(got, (str, bytes)):
        got = [got]
    return [str(p) for p in got if p]


def _check_date(text, what, blank_ok=False):
    t = str(text or "").strip()
    if not t and blank_ok:
        return ""
    try:
        if len(t) == 10:
            return clock.d(t).isoformat()
    except ValueError:
        pass
    raise ValueError(f"Type the {what} as YYYY-MM-DD.")


def _check_hours(text, what, blank_ok=False):
    from decimal import Decimal, InvalidOperation
    t = str(text or "").strip()
    if not t and blank_ok:
        return ""
    try:
        v = Decimal(t)
    except (InvalidOperation, ValueError):
        v = None
    if v is None or not v.is_finite():
        raise ValueError(f"Type the {what} as a number, like 6 or 6.5.")
    return t


def _find_job(office, text):
    """A job by its number (or, as before, its id)."""
    t = str(text or "").strip()
    if not t:
        raise ValueError("Type the job number.")
    row = office.db.one("SELECT id FROM jobs WHERE number = ? AND "
                        "deleted = 0", (t,))
    if row:
        return row["id"]
    if t.isdigit():
        hit = office.db.get("jobs", int(t))
        if hit and not hit.get("deleted"):
            return int(t)
    raise ValueError(f"No job {t}.")


# Incidents hold injury details and statements. The model checks writes
# (time.edit; review needs time.approve or hr.edit) but not reads, so the
# page only shows incidents to roles that can file or review one.
# incidents hold health information: Admin and Payroll/HR only (the roles
# with hr.edit) - reviews 1 + 2, Nov 4
INCIDENT_PERMS = ("hr.edit",)


def incident_roles():
    from .. import security
    return [r for r in security.ROLES
            if any(security.allowed(r, p) for p in INCIDENT_PERMS)]


def _incident_denied_text():
    names = incident_roles()
    if len(names) > 1:
        who = ", ".join(names[:-1]) + " or " + names[-1]
    else:
        who = "".join(names) or "Admin"
    return f"Only {who} can view incidents."


class IncidentPage(_Page):
    def __init__(self, office, parent=None, pick_images=None, pick_save=None):
        super().__init__(office, parent)
        self.pick_images = pick_images
        self.pick_save = pick_save
        self.incident_id = None
        self.ids = []
        self.person_ids = []
        self.lay.addWidget(heading("Incident report"))
        self.body = QWidget()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)

        lay.addWidget(QLabel("Incidents on file"))
        self.list = table(["Number", "Date", "Type", "Where", "Status"])
        self.list.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.list)

        self.kind = QComboBox()
        self.kind.addItems(list(incident.KINDS))
        self.kind.setCurrentText("near miss")
        _labelled(lay, "Type", self.kind)
        self.when = _labelled(lay, "Date",
                              _box("YYYY-MM-DD", clock.today().isoformat()))
        self.time = _labelled(lay, "Time", _box("Time, like 14:10"))
        self.job = _labelled(lay, "Job (optional)", _box("Job number"))
        self.where = _labelled(lay, "Where", _box("Where it happened"))
        self.weather = _labelled(lay, "Weather", _box("Weather at the time"))
        self.what = QPlainTextEdit()
        self.what.setPlaceholderText("What happened")
        _labelled(lay, "What happened", self.what)
        _button_row(lay, _button("Save Incident", self.save))

        lay.addWidget(QLabel("People"))
        self.people_table = table(["Role", "Name", "Company", "Job title",
                                   "Recordable", "Statement"])
        lay.addWidget(self.people_table)
        self.person_name = _labelled(lay, "Name", _box("Person's name"))
        self.person_role = QComboBox()
        self.person_role.addItems(list(incident.ROLES))
        _labelled(lay, "Role", self.person_role)
        self.person_company = _labelled(lay, "Company", _box("Company"))
        self.person_title = _labelled(lay, "Job title", _box("Job title"))
        self.statement = QPlainTextEdit()
        self.statement.setPlaceholderText("Statement in their words")
        _labelled(lay, "Statement", self.statement)
        _button_row(lay, _button("Add Person", self.add_person))

        lay.addWidget(QLabel("Recordable case (pick a person above)"))
        self.classification = QComboBox()
        self.classification.addItems(list(incident.CLASSES))
        _labelled(lay, "Classification", self.classification)
        self.days_away = _labelled(lay, "Days away", _box("0", "0"))
        self.days_restricted = _labelled(lay, "Days restricted",
                                         _box("0", "0"))
        self.privacy = QCheckBox("Privacy case (name left off the log)")
        lay.addWidget(self.privacy)
        _button_row(lay, _button("Mark Recordable", self.mark_recordable))

        lay.addWidget(QLabel("Photos"))
        self.photo_list = QListWidget()
        lay.addWidget(self.photo_list)
        self.caption = _labelled(lay, "Caption", _box("Photo caption"))
        _button_row(lay, _button("Add Photo…", self.add_photos))

        self.review_note = QPlainTextEdit()
        self.review_note.setPlaceholderText("Supervisor review note")
        _labelled(lay, "Supervisor review", self.review_note)
        _button_row(lay, _button("Accept Review", self.accept_review),
                    _button("Return for Changes", self.return_review))

        self.year = _labelled(lay, "Log year",
                              _box("YYYY", str(clock.today().year)))
        _button_row(lay, _button("Incident Packet PDF…", self.packet),
                    _button("Recordable Log…", self.export_log))
        self.lay.addWidget(self.body)
        self.lay.addWidget(self.status)
        self.refresh()

    # -- access ---------------------------------------------------------
    def allowed(self):
        o = self.office
        return bool(o.user) and any(o.can(p) for p in INCIDENT_PERMS)

    def _gate(self):
        if self.allowed():
            self.body.setVisible(True)
            return True
        self.body.setVisible(False)
        fill(self.list, [])
        fill(self.people_table, [])
        self.photo_list.clear()
        self.ids, self.person_ids, self.incident_id = [], [], None
        self._tell(_incident_denied_text())
        return False

    # -- lists ----------------------------------------------------------
    def refresh(self, select_id=None):
        if not self._gate():
            return
        schema.ensure(self.office.db)
        rows = self.office.db.rows(
            "SELECT * FROM incidents WHERE deleted = 0 "
            "ORDER BY occurred_on DESC, id DESC")
        keep = select_id if select_id is not None else self.incident_id
        self.list.blockSignals(True)
        try:
            fill(self.list, [(r["number"], r["occurred_on"], r["kind"],
                              r["location"], r["status"]) for r in rows])
            self.ids = [r["id"] for r in rows]
            if keep in self.ids:
                self.list.selectRow(self.ids.index(keep))
        finally:
            self.list.blockSignals(False)
        self.incident_id = keep if keep in self.ids else None
        self._load_detail()

    def _picked(self):
        r = _picked_row(self.list)
        if r is not None and r < len(self.ids):
            self.incident_id = self.ids[r]
            self._load_detail()

    def _load_detail(self):
        fill(self.people_table, [])
        self.photo_list.clear()
        self.person_ids = []
        if self.incident_id is None:
            return
        try:
            folks = incident.people(self.office, self.incident_id)
            pics = incident.photos(self.office, self.incident_id)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return
        fill(self.people_table, [
            (p["role"], p["name"], p["company"], p["job_title"],
             (p["classification"] or "yes") if p["recordable"] else "",
             (p["statement"] or "")[:80]) for p in folks])
        self.person_ids = [p["id"] for p in folks]
        for ph in pics:
            self.photo_list.addItem(ph["caption"] or
                                    os.path.basename(ph["file_path"]))

    def _need_incident(self):
        if not self._gate():
            return False
        if self.incident_id is None:
            self._tell("Save or pick an incident first.")
            return False
        return True

    # -- actions --------------------------------------------------------
    def save(self):
        if not self._gate():
            return None
        try:
            day = _check_date(self.when.text(), "date")
            jt = self.job.text().strip()
            jid = _find_job(self.office, jt) if jt else None
            iid = incident.add(
                self.office, self.kind.currentText(), day,
                self.what.toPlainText(), job_id=jid,
                occurred_time=self.time.text().strip(),
                weather=self.weather.text().strip(),
                location=self.where.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self.refresh(select_id=iid)
        number = incident.get(self.office, iid)["number"]
        self._tell(f"Saved incident {number}.")
        return iid

    def add_person(self):
        if not self._need_incident():
            return None
        try:
            pid = incident.add_person(
                self.office, self.incident_id, self.person_name.text(),
                role=self.person_role.currentText(),
                statement=self.statement.toPlainText().strip(),
                company=self.person_company.text().strip(),
                job_title=self.person_title.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        name = self.person_name.text().strip()
        for w in (self.person_name, self.person_company, self.person_title):
            w.clear()
        self.statement.clear()
        self._load_detail()
        self._tell(f"Added {name}.")
        return pid

    def mark_recordable(self):
        if not self._need_incident():
            return None
        r = _picked_row(self.people_table)
        if r is None or r >= len(self.person_ids):
            self._tell("Pick the person in the list first.")
            return None
        try:
            away = int(self.days_away.text().strip() or 0)
            restricted = int(self.days_restricted.text().strip() or 0)
        except ValueError:
            self._tell("Type days away and days restricted as whole numbers.")
            return None
        if away < 0 or restricted < 0:
            self._tell("Days can't be less than zero.")
            return None
        pid = self.person_ids[r]
        try:
            incident.mark_recordable(
                self.office, pid, self.classification.currentText(),
                days_away=away, days_restricted=restricted,
                privacy=self.privacy.isChecked())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._load_detail()
        self._tell("Marked recordable: "
                   f"{self.classification.currentText()}.")
        return pid

    def add_photos(self):
        if not self._need_incident():
            return []
        paths = _image_paths(self, self.pick_images)
        if not paths:
            return []
        added = []
        for p in paths:
            if not p.lower().endswith(IMAGE_EXTS):
                self._tell(f"Not a photo: {p}")
                return added
            try:
                # the model copies the photo into the company documents
                added.append(incident.add_photo(
                    self.office, self.incident_id, p,
                    caption=self.caption.text().strip()))
            except Exception as e:                    # noqa: BLE001
                self._tell(e)
                self._load_detail()
                return added
        self.caption.clear()
        self._load_detail()
        self._tell(f"Added {len(added)} photo(s).")
        return added

    def _review(self, accept):
        if not self._need_incident():
            return None
        try:
            incident.review(self.office, self.incident_id,
                            self.review_note.toPlainText(), accept=accept)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        status = incident.get(self.office, self.incident_id)["status"]
        self.review_note.clear()
        self.refresh()
        self._tell(f"Incident {status}.")
        return status

    def accept_review(self):
        return self._review(True)

    def return_review(self):
        return self._review(False)

    def packet(self):
        if not self._need_incident():
            return None
        try:
            row = incident.get(self.office, self.incident_id)
            path = _save_path(self, self.pick_save, "Incident Packet PDF",
                              f"{row['number']}.pdf")
            if not path:
                return None
            path = incident.packet_pdf(self.office, self.incident_id, path)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell(f"Saved {path}")
        return path

    def export_log(self):
        if not self._gate():
            return None
        y = self.year.text().strip()
        if not (len(y) == 4 and y.isdigit()):
            self._tell("Type the year, like 2026.")
            return None
        try:
            path = _save_path(self, self.pick_save, "Recordable Case Log",
                              f"recordable-log-{y}.pdf",
                              "PDF (*.pdf);;CSV (*.csv)", (".pdf", ".csv"))
            if not path:
                return None
            path = incident.export_log(self.office, int(y), path)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell(f"Saved {path}")
        return path


class JhaPage(_Page):
    def __init__(self, office, parent=None, pick_save=None):
        super().__init__(office, parent)
        self.pick_save = pick_save
        self.lay.addWidget(heading("Daily pre-task plan"))
        self.date = QLineEdit(clock.today().isoformat())
        self.job = QLineEdit()
        self.job.setPlaceholderText("Job id")
        self.task = QLineEdit()
        self.hazards = QPlainTextEdit()
        self.controls = QPlainTextEdit()
        self.plan_id = None
        self.job.setPlaceholderText("Job number")
        self.task.setPlaceholderText("Task (what the crew is doing)")
        save = QPushButton("Save Plan")
        save.clicked.connect(lambda: self.save_plan())
        copy = QPushButton("Copy Yesterday's Plan")
        copy.clicked.connect(lambda: self.copy_plan())
        self.lay.addWidget(QLabel("Date"))
        self.lay.addWidget(self.date)
        self.lay.addWidget(QLabel("Job"))
        self.lay.addWidget(self.job)
        self.lay.addWidget(QLabel("Task"))
        self.lay.addWidget(self.task)
        self.lay.addWidget(QLabel("Hazards"))
        self.lay.addWidget(self.hazards)
        self.lay.addWidget(QLabel("Controls"))
        self.lay.addWidget(self.controls)
        row = QHBoxLayout()
        row.addWidget(save)
        row.addWidget(copy)
        row.addStretch(1)
        self.lay.addLayout(row)

        self.signer = _labelled(self.lay, "Crew member",
                                _box("Crew member's name"))
        self.lay.addWidget(QLabel("Signature"))
        self.pad = SignaturePad()
        self.lay.addWidget(self.pad)
        _button_row(self.lay, _button("Sign Plan", self.sign_plan),
                    _button("Clear Signature", self.clear_pad),
                    _button("Plan PDF…", self.plan_pdf))
        self.lay.addWidget(QLabel("Signed"))
        self.signed = QListWidget()
        self.lay.addWidget(self.signed)
        self.lay.addWidget(self.status)

    def _job_id(self):
        """The job typed: its number (or, as before, its id)."""
        t = self.job.text().strip()
        if not t:
            raise jha.JhaError("Type the job number.")
        row = self.office.db.one("SELECT id FROM jobs WHERE number = ? AND "
                                 "deleted = 0", (t,))
        if row:
            return row["id"]
        if t.isdigit() and self.office.db.get("jobs", int(t)):
            return int(t)
        raise jha.JhaError(f"No job {t}.")

    def save_plan(self):
        """Save what's typed: a new plan, or the changes to the one just
        copied from yesterday."""
        try:
            jid = self._job_id()
            if self.plan_id:
                jha.update_plan(self.office, self.plan_id,
                                self.task.text(), self.hazards.toPlainText(),
                                self.controls.toPlainText())
                pid = self.plan_id
            else:
                pid = jha.add_plan(self.office, self.date.text().strip(), jid,
                                   self.task.text(),
                                   self.hazards.toPlainText(),
                                   self.controls.toPlainText())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self.plan_id = pid
        self.refresh_signed()
        self._tell(f"Saved plan {pid}.")
        return pid

    def copy_plan(self):
        try:
            pid = jha.copy_yesterday(self.office, self._job_id(),
                                     self.date.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        plan = jha.get_plan(self.office, pid)
        self.task.setText(plan["task"])
        self.hazards.setPlainText(plan["hazards"] or "")
        self.controls.setPlainText(plan["controls"] or "")
        self.plan_id = pid
        self.refresh_signed()
        self._tell(f"Copied plan {pid}. Change anything, then Save Plan.")
        return pid

    def refresh_signed(self):
        self.signed.clear()
        if not self.plan_id:
            return []
        try:
            rows = jha.signatures(self.office, self.plan_id)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return []
        for r in rows:
            when = str(r.get("signed_at") or "")[:16].replace("T", " ")
            self.signed.addItem(f"{r['name']}  {when}".strip())
        return [r["name"] for r in rows]

    def clear_pad(self):
        self.pad.strokes = []
        self.pad._current = None
        self.pad.update()

    def sign_plan(self):
        if not self.plan_id:
            self._tell("Save the plan first, then have the crew sign it.")
            return None
        if not self.signer.text().strip():
            self._tell("Type the crew member's name.")
            return None
        if not self.pad.strokes:
            # never a stand-in signature: an empty pad isn't signed
            self._tell("Have them sign on the pad first.")
            return None
        try:
            sid = jha.sign(self.office, self.plan_id, self.signer.text(),
                           self.pad.strokes)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        name = self.signer.text().strip()
        self.signer.clear()
        self.clear_pad()
        self.refresh_signed()
        self._tell(f"{name} signed plan {self.plan_id}.")
        return sid

    def plan_pdf(self):
        if not self.plan_id:
            self._tell("Save the plan first.")
            return None
        try:
            plan = jha.get_plan(self.office, self.plan_id)
            path = _save_path(self, self.pick_save, "Plan PDF",
                              f"jha-{plan['plan_date']}.pdf")
            if not path:
                return None
            path = jha.pdf(self.office, self.plan_id, path)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell(f"Saved {path}")
        return path


class EquipmentPage(_Page):
    def __init__(self, office, parent=None):
        super().__init__(office, parent)
        self.unit_ids = []
        self.lay.addWidget(heading("Equipment and vehicles"))
        self.lay.addWidget(QLabel("Units"))
        self.units = table(["Number", "Name", "Kind", "Hours", "Plate",
                            "Serial", "Service at (hrs)", "Service date",
                            "Inspection date"])
        self.lay.addWidget(self.units)

        self.code = _labelled(self.lay, "Unit number", _box("Like EX-1"))
        self.name = _labelled(self.lay, "Name", _box("Like North lift"))
        self.kind = QComboBox()
        self.kind.addItems(list(equipment.KINDS))
        _labelled(self.lay, "Type", self.kind)
        self.plate = _labelled(self.lay, "Plate", _box("License plate"))
        self.serial = _labelled(self.lay, "Serial number", _box("Serial"))
        self.meter = _labelled(self.lay, "Hour meter now", _box("0", "0"))
        self.service_hours = _labelled(self.lay, "Next service at (hours)",
                                       _box("Hours, optional"))
        self.service_on = _labelled(self.lay, "Next service date",
                                    _box("YYYY-MM-DD, optional"))
        self.inspection_on = _labelled(self.lay, "Next inspection date",
                                       _box("YYYY-MM-DD, optional"))
        _button_row(self.lay, _button("Add Unit", self.add_unit))

        self.log_date = _labelled(self.lay, "Log date",
                                  _box("YYYY-MM-DD", clock.today().isoformat()))
        self.log_hours_box = _labelled(self.lay, "Hours used",
                                       _box("Hours, like 6.5"))
        self.log_note = _labelled(self.lay, "Note", _box("Note, optional"))
        _button_row(self.lay,
                    _button("Log Hours", self.log_hours),
                    _button("Update From Time Cards", self.sync_time),
                    _button("Show Reminders", self.refresh))
        self.lay.addWidget(QLabel("Reminders"))
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.lay.addWidget(self.notes)
        self.lay.addWidget(self.status)
        self.reload_units()
        self.refresh()

    def reload_units(self, select_id=None):
        rows = equipment.units(self.office)
        keep = select_id
        if keep is None:
            r = _picked_row(self.units)
            if r is not None and r < len(self.unit_ids):
                keep = self.unit_ids[r]

        def h(v):
            return cents.hours_text(v) if v not in (None, "") else ""
        fill(self.units, [(u["code"], u["name"], u["kind"], h(u["meter"] or 0),
                           u["plate"], u["serial_no"],
                           h(u["next_service_hours"]), u["next_service_on"],
                           u["next_inspection_on"]) for u in rows])
        self.unit_ids = [u["id"] for u in rows]
        if keep in self.unit_ids:
            self.units.selectRow(self.unit_ids.index(keep))
        return rows

    def refresh(self):
        due = equipment.reminders(self.office)
        if not due:
            self.notes.setPlainText("Nothing is due.")
            return due
        self.notes.setPlainText("\n".join(
            f"{d['code']} {d['name']}: {d['detail']}" for d in due))
        return due

    def add_unit(self):
        code = self.code.text().strip()
        try:
            if code and equipment.by_code(self.office, code):
                raise ValueError(f"Unit {code} is already on the register.")
            meter = _check_hours(self.meter.text() or "0", "hour meter")
            service_h = _check_hours(self.service_hours.text(),
                                     "next service hours", blank_ok=True)
            service_on = _check_date(self.service_on.text(),
                                     "next service date", blank_ok=True)
            inspect_on = _check_date(self.inspection_on.text(),
                                     "next inspection date", blank_ok=True)
            uid = equipment.add_unit(
                self.office, code, self.name.text(),
                kind=self.kind.currentText(), plate=self.plate.text().strip(),
                serial_no=self.serial.text().strip(), meter=meter,
                next_service_hours=service_h or None,
                next_service_on=service_on, next_inspection_on=inspect_on)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        for w in (self.code, self.name, self.plate, self.serial,
                  self.service_hours, self.service_on, self.inspection_on):
            w.clear()
        self.meter.setText("0")
        self.reload_units(select_id=uid)
        self.refresh()
        self._tell(f"Added unit {code}.")
        return uid

    def log_hours(self):
        r = _picked_row(self.units)
        if r is None or r >= len(self.unit_ids):
            self._tell("Pick a unit in the list first.")
            return None
        uid = self.unit_ids[r]
        try:
            day = _check_date(self.log_date.text(), "log date")
            hours = _check_hours(self.log_hours_box.text(), "hours")
            lid = equipment.log_hours(self.office, uid, day, hours,
                                      note=self.log_note.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self.log_hours_box.clear()
        self.log_note.clear()
        self.reload_units(select_id=uid)
        self.refresh()
        self._tell(f"Logged {hours} hour(s).")
        return lid

    def sync_time(self):
        try:
            done = equipment.sync_time(self.office)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self.reload_units()
        self.refresh()
        msg = f"Pulled {len(done['added'])} time card line(s)."
        if done["unmatched"]:
            msg += ("  Not on the register: " + ", ".join(done["unmatched"])
                    + ". Add those units, then update again.")
        self._tell(msg)
        return done


class WarrantyPage(_Page):
    def __init__(self, office, parent=None, pick_images=None, pick_save=None):
        super().__init__(office, parent)
        self.pick_images = pick_images
        self.pick_save = pick_save
        self.call_ids = []
        self.lay.addWidget(heading("Warranty and service calls"))
        self.job = _labelled(self.lay, "Job", _box("Job number"))
        _button_row(self.lay, _button("Close Out Job", self.mark_closed),
                    _button("Show Calls", self.refresh_calls),
                    _button("Warranty Report…", self.report))
        self.caller = _labelled(self.lay, "Caller", _box("Who called"))
        self.phone = _labelled(self.lay, "Phone", _box("Caller's phone"))
        self.assigned = _labelled(self.lay, "Assigned to",
                                  _box("Who will handle it"))
        self.issue = QPlainTextEdit()
        self.issue.setPlaceholderText("The issue")
        _labelled(self.lay, "Issue", self.issue)
        _button_row(self.lay, _button("Log Call", self.log_call))

        self.lay.addWidget(QLabel("Calls on this job"))
        self.calls = table(["Number", "Status", "Caller", "Phone",
                            "Assigned to", "Opened", "Closed", "Issue",
                            "Photos"])
        self.lay.addWidget(self.calls)
        self.caption = _labelled(self.lay, "Photo caption",
                                 _box("Caption, optional"))
        self.close_note = _labelled(self.lay, "Close note",
                                    _box("What was done"))
        _button_row(self.lay, _button("Add Photo…", self.add_photos),
                    _button("Close Call", self.close_call))
        self.lay.addWidget(self.status)

    def _job_id(self):
        return _find_job(self.office, self.job.text())

    def _picked_call(self):
        r = _picked_row(self.calls)
        if r is None or r >= len(self.call_ids):
            self._tell("Pick a call in the list first.")
            return None
        return self.call_ids[r]

    def refresh_calls(self, select_id=None):
        try:
            jid = self._job_id()
            rows = warranty.calls(self.office, jid)
        except Exception as e:                        # noqa: BLE001
            fill(self.calls, [])
            self.call_ids = []
            self._tell(e)
            return []

        def n_photos(cid):
            return self.office.db.scalar(
                "SELECT COUNT(*) FROM warranty_photos WHERE call_id = ? AND "
                "deleted = 0", (cid,)) or 0
        fill(self.calls, [(c["number"], c["status"], c["caller"], c["phone"],
                           c["assigned"], c["opened_on"], c["closed_on"],
                           (c["issue"] or "")[:80], n_photos(c["id"]))
                          for c in rows])
        self.call_ids = [c["id"] for c in rows]
        if select_id in self.call_ids:
            self.calls.selectRow(self.call_ids.index(select_id))
        if select_id is None:
            closed = warranty.is_closed(self.office, jid)
            self._tell(f"{len(rows)} call(s)." + (
                "" if closed else "  This job is not closed out yet."))
        return rows

    def mark_closed(self):
        try:
            warranty.close_job(self.office, self._job_id())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell("Job closed out.")
        return True

    def log_call(self):
        try:
            cid = warranty.add_call(self.office, self._job_id(),
                                    self.caller.text(),
                                    self.issue.toPlainText(),
                                    assigned=self.assigned.text().strip(),
                                    phone=self.phone.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        for w in (self.caller, self.phone, self.assigned):
            w.clear()
        self.issue.clear()
        self.refresh_calls(select_id=cid)
        number = self.office.db.get("warranty_calls", cid)["number"]
        self._tell(f"Call {number} logged.")
        return cid

    def add_photos(self):
        cid = self._picked_call()
        if cid is None:
            return []
        paths = _image_paths(self, self.pick_images)
        if not paths:
            return []
        added = []
        for p in paths:
            if not p.lower().endswith(IMAGE_EXTS):
                self._tell(f"Not a photo: {p}")
                break
            try:
                # the model copies the photo into the company documents
                added.append(warranty.add_photo(
                    self.office, cid, p, caption=self.caption.text().strip()))
            except Exception as e:                    # noqa: BLE001
                self._tell(e)
                break
        else:
            self.caption.clear()
            self._tell(f"Added {len(added)} photo(s).")
        self.refresh_calls(select_id=cid)
        return added

    def close_call(self):
        cid = self._picked_call()
        if cid is None:
            return None
        try:
            warranty.close_call(self.office, cid,
                                note=self.close_note.text().strip())
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self.close_note.clear()
        self.refresh_calls(select_id=cid)
        number = self.office.db.get("warranty_calls", cid)["number"]
        self._tell(f"Call {number} closed.")
        return cid

    def report(self):
        try:
            jid = self._job_id()
            number = self.office.db.get("jobs", jid)["number"]
            path = _save_path(self, self.pick_save, "Warranty Report",
                              f"warranty-{number}.pdf")
            if not path:
                return None
            path = warranty.report_pdf(self.office, jid, path)
        except Exception as e:                        # noqa: BLE001
            self._tell(e)
            return None
        self._tell(f"Saved {path}")
        return path
