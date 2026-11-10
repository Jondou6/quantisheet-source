"""Local AI Models window (Review menu, Nov 5): what Ollama has installed
on this PC, the disk they use, free disk, and the model size that fits
this PC's memory - from app/ai/models. It never downloads anything; to
add a model it shows the command to type."""
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import models


def _it_host():
    """The policy AI server, or "" - never an exception (Venice, Nov 9 -
    F4: a mistyped policy value escaped the window's error handling)."""
    try:
        return models.it_host()
    except models.NotLocalError:
        return ""


def _host():
    from . import review
    try:
        return models.it_host() or review.HOST
    except models.NotLocalError:
        raise models.OllamaError(
            "The AI server your IT department named isn't a plain http(s) "
            "address - ask them to check the AIHost setting.")


class ModelsDialog(QDialog):
    def __init__(self, parent=None, fetch=None):
        super().__init__(parent)
        self.setWindowTitle("Local AI Models")
        self.resize(720, 420)
        self.fetch = fetch or (lambda: models.inventory(_host()))
        lay = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setAccessibleName("Installed AI models")
        self.table.setHorizontalHeaderLabels(["Model", "Size", "Parameters",
                                              "Quantization", "Family"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.advice = QLabel("")
        self.advice.setWordWrap(True)
        lay.addWidget(self.advice)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.refresh_btn = QPushButton("Refresh")
        bb.addButton(self.refresh_btn, QDialogButtonBox.ActionRole)
        self.refresh_btn.clicked.connect(lambda _c=False: self.refresh())
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        try:
            inv = self.fetch()
        except models.NotLocalError as e:
            self.status.setText(f"{e} This window only reads the model list "
                                "of the AI on this PC.")
            self.advice.setText("")
            return None
        except (models.OllamaError, OSError) as e:
            where = ("on the AI server your IT department set up"
                     if _it_host() else "on this PC")
            self.status.setText(
                f"The AI (Ollama) isn't answering {where}, so the "
                f"installed models can't be listed. ({e}) Start Ollama and "
                "press Refresh. Help > Help Center explains setting it up.")
            self.advice.setText("")
            return None
        self.table.setRowCount(len(inv.models))
        for i, m in enumerate(inv.models):
            for c, v in enumerate((m.name, m.size_label, m.parameter_size,
                                   m.quantization, m.family)):
                self.table.setItem(i, c, QTableWidgetItem(v or ""))
        self.table.resizeColumnsToContents()
        self.status.setText(
            f"{len(inv.models)} model(s) installed, using {inv.used_label}. "
            f"{inv.disk.free_label} free on the drive."
            if inv.models else
            "No AI models are installed yet. "
            f"{inv.disk.free_label} free on the drive.")
        self.advice.setText(
            f"{inv.advice.reason} To add one, open a Command Prompt and "
            "type: ollama pull <model name> (QuantiSheet never downloads "
            "models itself).")
        return inv


def open_dialog(win=None, show=True, fetch=None):
    dlg = ModelsDialog(win, fetch=fetch)
    if win is not None:
        win._ai_models = dlg
    if show:
        dlg.show()
    return dlg
