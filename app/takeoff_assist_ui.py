"""Window-level commands for three takeoff helpers (Takeoff menu):

- Trace Outline: the follow-drawn-lines switch (the tool itself is in
  viewer.py / trace_outline.py);
- Walls by Role: wall_roles.py, with a review table to reassign roles
  before anything is added, and "Change Wall Role of Selection" after;
- Count Several Symbols: count_several.py.

Each returns quietly when no document is open (the click-everything
sweep runs every command).
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QInputDialog, QLabel,
                               QMessageBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import settings, takeoff

log = logging.getLogger(__name__)


# ---- Trace Outline ---------------------------------------------------------------
def set_trace_follow(on):
    settings.set("trace_follow", bool(on))


def trace_follow():
    return settings.get("trace_follow", True) is not False


# ---- Walls by Role -----------------------------------------------------------------
class WallRolesDialog(QDialog):
    """Every wall piece with its role; change a role in its row before
    the walls are added."""

    def __init__(self, pieces, unit, parent=None, note=""):
        super().__init__(parent)
        from . import wall_roles
        self.pieces = [dict(p) for p in pieces]
        self.unit = unit
        self.note = note
        self.setWindowTitle("Walls by Role")
        lay = QVBoxLayout(self)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.table = QTableWidget(len(self.pieces), 3)
        self.table.setHorizontalHeaderLabels(["Role", "Length",
                                              "Thickness"])
        self.table.verticalHeader().setVisible(False)
        self.combos = []
        for i, p in enumerate(self.pieces):
            cb = QComboBox()
            cb.addItems(list(wall_roles.ROLES))
            cb.setCurrentText(p["role"])
            cb.currentTextChanged.connect(
                lambda text, i=i: self.set_role(i, text))
            self.table.setCellWidget(i, 0, cb)
            self.combos.append(cb)
            for col, text in ((1, takeoff.fmt(p["length"], unit)),
                              (2, f"{p['thickness']:.1f}\"")):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(i, col, it)
        self.table.setColumnWidth(0, 130)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add Walls")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(460, 520)
        self._totals()

    def set_role(self, i, role):
        self.pieces[i]["role"] = role
        if self.combos[i].currentText() != role:
            self.combos[i].setCurrentText(role)
        self._totals()

    def _totals(self):
        from . import wall_roles
        sm = wall_roles.summary(self.pieces)
        lines = [f"{wall_roles.group_name(r)}: "
                 f"{takeoff.fmt(v, self.unit)}" for r, v in sm.items()]
        self.info.setText(
            "Each role becomes its own group in Quantities (bind an "
            "assembly to it like any group). Change a wall's role here, or "
            "later with Takeoff > Change Wall Role of Selection.\n\n" +
            "\n".join(lines) + (f"\n\n{self.note}" if self.note else ""))


def walls_by_role(win, review=True):
    """Find this sheet's walls, sort them by role, review, add. Returns
    the role totals, or None."""
    from . import wall_roles
    v = win._view
    if not v:
        return None
    sc = v.scale()
    if not sc:
        QMessageBox.information(
            win, "Walls by Role", "Set the scale for this page first "
            "(Takeoff > Set Scale or Auto Scale).")
        return None
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        pieces, _labels = wall_roles.find(v.pg, sc["ppu"], sc["unit"])
    except Exception as e:
        QApplication.restoreOverrideCursor()
        log.info("walls by role: %s", e)
        QMessageBox.information(win, "Walls by Role", str(e) or
                                "Couldn't read the walls on this page.")
        return None
    QApplication.restoreOverrideCursor()
    if not pieces:
        QMessageBox.information(win, "Walls by Role", "No walls found on "
                                "this page's linework.")
        return None
    note = ""
    try:
        from . import annotate
        if any(it["page"] == v.page and it["type"] == "length" and
               str(it["group"]).startswith("Wall ")
               for it in annotate.takeoff_items(v.doc)):
            note = ("This sheet already has Auto Walls groups (\"Wall 5in\" "
                    "...). Delete them if these replace them, so the walls "
                    "aren't counted twice.")
    except Exception:
        pass
    if review:
        dlg = WallRolesDialog(pieces, sc["unit"], win, note)
        win._wall_roles_dlg = dlg
        if not dlg.exec():
            return None
        pieces = dlg.pieces
    v.apply_marks(wall_roles.marks(v.page, pieces, sc))
    try:
        win._show_takeoff_panel()
    except Exception:
        pass
    sm = wall_roles.summary(pieces)
    try:
        win._flash("Walls by role: " + "; ".join(
            f"{r} {takeoff.fmt(n, sc['unit'])}" for r, n in sm.items()))
    except Exception:
        pass
    return sm


def change_wall_role(win, role=None):
    """Move the selected wall markup to another role's group (and give it
    that role's color). Returns 1 if changed."""
    from . import wall_roles
    v = win._view
    if not v:
        return 0
    props = v.selected_props() if v.selected else None
    if not props or not props.get("takeoff"):
        try:
            win._flash("Select a wall markup first (Select tool), then "
                       "choose its role.")
        except Exception:
            pass
        return 0
    if role is None:
        cur = wall_roles.role_of_group(props.get("subject") or "") or \
            "Interior"
        role, ok = QInputDialog.getItem(
            win, "Change Wall Role", "Role:", list(wall_roles.ROLES),
            list(wall_roles.ROLES).index(cur), False)
        if not ok or not role:
            return 0
    if role not in wall_roles.ROLES:
        return 0
    return v.change_selected(
        subject=wall_roles.group_name(role),
        color=list(wall_roles.ROLE_COLORS[role]))


# ---- Count Several Symbols -----------------------------------------------------------
def count_several(win, show=True):
    """Open the samples panel (not modal: box samples on the drawing)."""
    from . import count_several as cs
    v = win._view
    if not v:
        return None
    old = getattr(win, "_count_several_dlg", None)
    if old is not None:
        try:
            old.close()
        except RuntimeError:
            pass
    dlg = cs.SamplesDialog(v, win)
    win._count_several_dlg = dlg
    if show:
        dlg.show()
        dlg.arm()
    return dlg
