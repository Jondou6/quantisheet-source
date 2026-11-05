"""Help > Report an Issue: the window (logic: issue_report.py)."""
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from . import issue_report


def _png(pm):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(ba)


class ReportDialog(QDialog):
    """What happened, the screenshot (keep, retake or leave out), attach
    the drawing or not, then Send opens the email to support."""

    def __init__(self, win, text="", parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("Report an Issue")
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>What happened?</b> What were you doing, "
                             "what did you expect, and what did you see?"))
        self.text = QPlainTextEdit(text)
        self.text.setPlaceholderText("e.g. I opened the plan set and page 4 "
                                     "stayed white...")
        self.text.setMinimumHeight(120)
        lay.addWidget(self.text)
        self.use_shot = QCheckBox("Include this screenshot of the window")
        self.use_shot.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self.use_shot)
        row.addStretch(1)
        retake = QPushButton("Retake Screenshot")
        retake.clicked.connect(lambda: self.retake())
        row.addWidget(retake)
        lay.addLayout(row)
        self.shot_view = QLabel()
        self.shot_view.setAlignment(Qt.AlignCenter)
        self.shot_view.setMinimumHeight(260)
        self.shot_view.setStyleSheet("border:1px solid #c9d1dc")
        lay.addWidget(self.shot_view, 1)
        v = getattr(win, "_view", None)
        self.doc_path = getattr(v, "_path", None) if v else None
        mb = None
        try:
            import os
            if self.doc_path and os.path.isfile(self.doc_path):
                mb = os.path.getsize(self.doc_path) / 1e6
        except OSError:
            mb = None
        self.attach = QCheckBox(
            f"Attach this drawing ({mb:,.1f} MB) - only if you're allowed "
            "to share it" if mb is not None else "Attach this drawing")
        self.attach.setChecked(False)
        self.attach.setEnabled(mb is not None and
                               mb <= issue_report.MAX_ATTACH_MB)
        if mb is not None and mb > issue_report.MAX_ATTACH_MB:
            self.attach.setText(f"This drawing is too big to attach ({mb:,.0f}"
                                " MB) - facts about it are sent instead")
        lay.addWidget(self.attach)
        # Venice #8 (Nov 4): crash reports go along only if you leave this on
        try:
            from . import crashreport
            n_crash = len(crashreport.reports(10))
        except Exception:                                 # noqa: BLE001
            n_crash = 0
        self.crashes = QCheckBox(
            f"Include the recent crash reports ({n_crash})" if n_crash
            else "No crash reports on this PC")
        self.crashes.setChecked(bool(n_crash))
        self.crashes.setEnabled(bool(n_crash))
        self.crashes.setToolTip("What the program was doing when it "
                                "stopped, with names, emails and network "
                                "paths removed.")
        lay.addWidget(self.crashes)
        note = QLabel(f"<small>An email to {issue_report.SUPPORT_EMAIL} "
                      "opens with this attached, plus facts about the "
                      "drawing (pages, sheet sizes, how many markups - not "
                      "its content) and the program's logs, with names, "
                      "emails and network paths removed. Nothing is sent "
                      "until you click Send in the email.</small>")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.send_btn = bb.addButton("Open the Email…",
                                     QDialogButtonBox.AcceptRole)
        bb.accepted.connect(lambda: self.send())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.shot = None
        self._grab()

    def _grab(self):
        try:
            self.shot = self.win.grab()
        except Exception:                                 # noqa: BLE001
            self.shot = None
        if self.shot is not None and not self.shot.isNull():
            self.shot_view.setPixmap(self.shot.scaled(
                640, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.shot_view.setText("(no screenshot)")
            self.use_shot.setChecked(False)

    def retake(self):
        """Hide this window a moment and take the screenshot again."""
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(350, self._retake_done)

    def _retake_done(self):
        self._grab()
        self.show()
        self.raise_()

    def send(self):
        text = self.text.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Report an Issue",
                                    "Please say what happened first.")
            return None
        png = _png(self.shot) if self.use_shot.isChecked() and \
            self.shot is not None else None
        v = getattr(self.win, "_view", None)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            _zip, attach, facts = issue_report.build(
                text, png, doc=getattr(v, "doc", None),
                doc_path=self.doc_path,
                attach_doc=self.attach.isChecked(),
                view_page=getattr(v, "page", None),
                crashes=self.crashes.isChecked())
            how = issue_report.open_email(
                issue_report.message(text, facts, attach))
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Report an Issue",
                                f"The email couldn't be made: {e}")
            return None
        QApplication.restoreOverrideCursor()
        self.accept()
        return how


def open_dialog(win, text="", show=True):
    dlg = ReportDialog(win, text)
    if show:
        dlg.exec()
    return dlg
