from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel,
    QFileDialog, QMessageBox
)
from . import macros as macros_mod


class MacroDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setWindowTitle("Macros")
        self.resize(480, 360)
        layout = QVBoxLayout(self)

        self.info = QLabel("Not recording. Start, close this window, mark up "
                           "the page, then come back to stop and save.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.list = QListWidget()
        layout.addWidget(self.list)

        btns = QHBoxLayout()
        self.toggle = QPushButton("Start Recording")
        self.toggle.clicked.connect(self._toggle_rec)
        save = QPushButton("Save Macro…")
        save.clicked.connect(self._save)
        load = QPushButton("Load && Replay…")
        load.clicked.connect(self._load)
        btns.addWidget(self.toggle)
        btns.addWidget(save)
        btns.addWidget(load)
        layout.addLayout(btns)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

        self._show(view.recorder.ops)
        if view.recorder.on:
            self.toggle.setText("Stop Recording")
            self.info.setText(f"Recording — {len(view.recorder.ops)} ops")

    def _show(self, ops):
        self.list.clear()
        for op in ops:
            self.list.addItem(f"{op.get('kind')}  page {op.get('page', 0) + 1}")

    def _toggle_rec(self):
        rec = self.view.recorder
        if rec.on:
            ops = rec.stop()
            self._show(ops)
            self.info.setText(f"Stopped — {len(ops)} ops recorded")
            self.toggle.setText("Start Recording")
        else:
            rec.start()
            self.list.clear()
            self.info.setText("Recording… close this window and mark up "
                              "the page.")
            self.toggle.setText("Stop Recording")

    def _save(self):
        ops = self.view.recorder.ops
        if not ops:
            QMessageBox.information(self, "Macro", "Nothing recorded")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Macro", "",
                                              "Macro (*.json)")
        if path:
            macros_mod.save_macro(path, ops)
            QMessageBox.information(self, "Macro", f"Saved {len(ops)} ops")

    def ask_signer(self, info, answer=None):
        """True to go on. `answer` ("trust", "once", None) for tests."""
        state, who = info.get("signature"), info.get("signer") or "someone"
        if state == "trusted":
            return True
        if state == "signed":
            text = (f"This macro is signed by {who}, who isn't on your "
                    "trusted list. It only adds markups. Play it?")
        else:
            text = ("This macro isn't signed, so you can't tell who made "
                    "it. It only adds markups. Play it?")
        if answer is None:
            box = QMessageBox(QMessageBox.Question, "Macro", text,
                              parent=self)
            tr = box.addButton(f"Trust {who} and Play", QMessageBox.YesRole) \
                if state == "signed" else None
            once = box.addButton("Play Once", QMessageBox.AcceptRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            b = box.clickedButton()
            answer = "trust" if tr is not None and b is tr else \
                "once" if b is once else None
        if answer == "trust" and state == "signed" and info.get("key"):
            macros_mod.trust(info["key"])
        return answer in ("trust", "once")

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Macro", "",
                                              "Macro (*.json)")
        if not path:
            return
        try:
            raw = macros_mod.load_macro(path)
            ops, info = macros_mod.load_macro_info(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Macro", f"Could not load macro:\n{e}")
            return
        # who made it (Venice #2, Nov 4): trusted / signed / unsigned
        if not self.ask_signer(info):
            return
        pre = macros_mod.preflight(raw, self.view.doc)
        ops = [op for op in raw if macros_mod._clean(op) is not None]
        if pre["skipped"]:
            why = "\n".join(f"  step {i + 1}: {w}"
                            for i, w in pre["skipped"][:10])
            if QMessageBox.question(
                    self, "Macro",
                    f"{pre['ok']} of {len(ops)} steps can be played here. "
                    f"Left out:\n{why}\n\nPlay the rest?") != \
                    QMessageBox.Yes:
                return
        n = macros_mod.replay(self.view, ops)
        self._show(ops)
        QMessageBox.information(self, "Macro",
                                f"Replayed {n} of {len(ops)} ops")
