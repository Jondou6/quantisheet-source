"""The app log, and a small window that shows the warnings.

The log file is the one app.main._setup_logging opens
(<log folder>/quantisheet.log, unless a FileHandler is already aimed at
that file). Nothing here uploads the log.

Public
------
log_path()
    Path of the app log (the file may not exist yet).
tail(n, level="WARNING")
    The last `n` records at or above `level`, oldest first.
    A record is the leveled line plus the lines under it that have no
    level of their own (a traceback under an ERROR).
LogViewer
    A plain dialog with Copy and Refresh. It shows tail().
"""
import logging
import os
import re

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

# app.main._setup_logging: "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)\s+"
    r"(?P<lvl>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b")
_READ_LIMIT = 2_000_000


def log_path():
    """Where the app log is written.

    A FileHandler already installed for settings.LOG_NAME wins (that is
    the logging setup). Otherwise the path is log_folder() / LOG_NAME,
    the same place app.main._setup_logging uses.
    """
    found = _from_logging()
    if found:
        return found
    from . import settings
    from .main import log_folder
    return os.path.join(log_folder(), settings.LOG_NAME)


def tail(n, level="WARNING"):
    """Last `n` log records at or above `level` (default WARNING).

    Returns a list of lines, oldest first. `n` counts records, not the
    extra traceback lines kept with them. A missing log, or `n` < 1,
    returns []. `level` is a name ("WARNING", "ERROR", ...) or a logging
    number. An unknown name raises ValueError.
    """
    try:
        count = int(n)
    except (TypeError, ValueError):
        raise ValueError("n must be a number of log records") from None
    if count <= 0:
        return []
    minimum = _threshold(level)
    try:
        text = _read(log_path())
    except OSError:
        return []
    records = []
    current = None
    keep = False
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            if current is not None and keep:
                records.append(current)
            current = [line]
            keep = _threshold(match.group("lvl")) >= minimum
        elif current is not None:
            current.append(line)
    if current is not None and keep:
        records.append(current)
    lines = []
    for record in records[-count:]:
        lines.extend(record)
    return lines


class LogViewer(QDialog):
    """The recent warnings, with Copy and Refresh."""

    def __init__(self, parent=None, n=200, level="WARNING"):
        super().__init__(parent)
        self.n = n
        self.level = level
        self.setWindowTitle("Log")
        self.resize(760, 480)
        lay = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.setAutoDefault(False)
        copy.clicked.connect(self.copy_log)
        refresh = QPushButton("Refresh")
        refresh.setAutoDefault(False)
        refresh.clicked.connect(self.refresh)
        row.addWidget(copy)
        row.addWidget(refresh)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        lines = tail(self.n, self.level)
        if lines:
            self.view.setPlainText("\n".join(lines))
        else:
            self.view.setPlainText(
                "(no log lines at " + str(self.level) + " or above)")

    def copy_log(self):
        QGuiApplication.clipboard().setText(self.view.toPlainText())


def _from_logging():
    from . import settings
    want = settings.LOG_NAME
    for logger in (logging.getLogger("quantisheet"), logging.getLogger()):
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", "") or ""
            if base and os.path.basename(base) == want:
                return base
    return ""


def _threshold(level):
    if isinstance(level, int):
        return level
    key = str(level).strip().upper()
    if key == "WARN":
        key = "WARNING"
    if key == "FATAL":
        key = "CRITICAL"
    number = getattr(logging, key, None)
    if not isinstance(number, int):
        raise ValueError(f"unknown log level {level!r}")
    return number


def _read(path):
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - _READ_LIMIT))
        data = fh.read()
    if size > _READ_LIMIT:
        cut = data.find(b"\n")
        if cut >= 0:
            data = data[cut + 1:]
    return data.decode("utf-8", "replace")
