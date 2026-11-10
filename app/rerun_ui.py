"""Running AI Takeoff again (v3): what's new vs what was already there.

The second run's measurements are split (rerun.split): new matches are
listed with a tick box each (ticked; untick any you don't want); what
the drawing already has - accepted, still in review, or measured by hand
- is listed locked: it is never added a second time. Review decisions
from the earlier run that still apply are listed too."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)
from .dmoney import c2 as _c2

STATUS = {"accepted": "accepted", "pending": "AI, not checked",
          "manual": "measured by hand"}


def _line(mark):
    p, kind, pl = mark
    m = pl.get("measure") or {}
    v = m.get("value")
    q = f"{_c2(v):,.2f}".rstrip("0").rstrip(".") if isinstance(
        v, (int, float)) else ""
    return (f"p{p + 1} · {m.get('group') or kind} · {q} "
            f"{m.get('unit') or ''}").strip()


class RerunDialog(QDialog):
    def __init__(self, parent, split, carried=None):
        super().__init__(parent)
        self.split = split
        self.setWindowTitle("AI Takeoff - Run Again")
        self.resize(640, 520)
        v = QVBoxLayout(self)
        new, prev = split["new"], split["previous"]
        locked = (carried or {}).get("locked") or []
        head = QLabel(
            f"<b>{len(new):,} new match(es)</b> to add. "
            f"{len(prev):,} already on the drawing (locked - not added "
            "again, so nothing is counted twice)"
            + (f"; {len(locked):,} review decision(s) from the earlier run "
               "kept" if locked else "") + ".")
        head.setWordWrap(True)
        v.addWidget(head)
        v.addWidget(QLabel("New matches (untick any you don't want):"))
        self.new_list = QListWidget()
        for i, m in enumerate(new):
            it = QListWidgetItem(_line(m))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, i)
            self.new_list.addItem(it)
        v.addWidget(self.new_list, 3)
        b = QHBoxLayout()
        for text, st in (("Tick All", Qt.Checked), ("Untick All",
                                                    Qt.Unchecked)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _c=False, st=st: self._all(st))
            b.addWidget(btn)
        b.addStretch()
        v.addLayout(b)
        v.addWidget(QLabel("Previously detected (locked):"))
        self.prev_list = QListWidget()
        for r in prev:
            it = QListWidgetItem(
                _line(r["mark"]) + f" - {STATUS.get(r['status'], 'there')}"
                + (f" (now '{r['have_group']}')" if r.get("have_group") and
                   r["have_group"] != r.get("group") else ""))
            it.setFlags(Qt.ItemIsEnabled)
            self.prev_list.addItem(it)
        for x in locked:
            it = QListWidgetItem(f"{x.get('sheet') or ''} · "
                                 f"{x.get('name')} - review: "
                                 f"{x.get('decision')}")
            it.setFlags(Qt.ItemIsEnabled)
            self.prev_list.addItem(it)
        v.addWidget(self.prev_list, 2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add Ticked")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _all(self, st):
        for i in range(self.new_list.count()):
            self.new_list.item(i).setCheckState(st)

    def chosen(self):
        out = []
        for i in range(self.new_list.count()):
            it = self.new_list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(self.split["new"][it.data(Qt.UserRole)])
        return out
