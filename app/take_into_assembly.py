"""Takeoff > Take Off Into Assembly: pick a CSI division, then an assembly
from the job's assembly library, and measure straight into it.

The building takeoff already binds a takeoff group to an assembly by name:
a measurement whose group (subject / count group) is an assembly's name is
priced by that assembly in assemblies.rollup(), which the Assemblies panel,
the proposal, the bid build-up and the SOV read. This command uses that
same binding (no second store): it copies the picked assembly into the
job (assemblies.set_job_assembly, as the Assembly Library's Take Off does)
and starts the tool that matches the assembly's unit - Area for an area
assembly, Polylength for a length one, Count for a count one - on a group
named after the assembly. Every markup traced after that is a priced
estimate line in the Assemblies panel as soon as it is drawn.

The pure part (grouping by division, the tool for a unit) has no Qt and is
tested on its own; the dialog is below it.
"""
import copy
import logging

from . import assemblies, csi

log = logging.getLogger(__name__)

TOOL = {"length": "measure_polylength", "area": "measure_area",
        "count": "count", "volume": "measure_volume"}
UNIT = {"length": "LF", "area": "SF", "count": "EA", "volume": "CY"}
MEASURE_WORD = {"length": "Length", "area": "Area", "count": "Count",
                "volume": "Volume"}
OTHER = "--"                     # assemblies with no CSI code


# ---- pure ------------------------------------------------------------------

def division_of(a):
    """'09' for an assembly coded 09 21 16 (or classified as Finishes),
    OTHER when there is no code and its name doesn't say."""
    code = csi.parse_code(a.get("csi") or "")
    if not code:
        code = csi.classify(f"{a.get('name', '')} {a.get('trade', '')}")
    div = code[:2] if code else ""
    return div if div in csi.DIVISIONS else OTHER


def division_label(div):
    if div == OTHER:
        return "No CSI division"
    t = csi.DIVISIONS.get(div, "")
    return f"{div} {t[:1].upper() + t[1:]}" if t else div


def measure_of(a):
    m = str(a.get("measure") or "").strip().lower()
    return m if m in TOOL else ""


def tool_for(a):
    """The takeoff tool for an assembly's unit, or '' when it has none."""
    return TOOL.get(measure_of(a), "")


def catalog(job=None, lib=None):
    """{name: assembly}: the library with the job's own copies on top (the
    job's prices and properties win, as assemblies.find does). Only
    assemblies that can be measured (length / area / count / volume)."""
    items = {}
    for src in (lib or {}, (job or {}).get("assemblies") or {}):
        for name, a in src.items():
            if isinstance(a, dict) and a.get("name") and tool_for(a):
                items[a["name"]] = a
    return items


def by_division(items):
    """[(division, [assembly, ...]), ...] sorted by division (no-code
    last), assemblies by name inside each."""
    groups = {}
    for a in items.values() if isinstance(items, dict) else items:
        groups.setdefault(division_of(a), []).append(a)
    order = sorted(groups, key=lambda d: (d == OTHER, d))
    return [(d, sorted(groups[d], key=lambda a: a["name"].lower()))
            for d in order]


def describe(a):
    """'Area (SF) - Concrete - 03 30 00' for the list."""
    m = measure_of(a)
    bits = [f"{MEASURE_WORD.get(m, m)} ({UNIT.get(m, '')})"]
    if a.get("trade"):
        bits.append(a["trade"])
    code = csi.parse_code(a.get("csi") or "")
    if code:
        bits.append(code)
    return " - ".join(bits)


def bind(doc, a):
    """Copy the assembly into the job (when it isn't there yet) so the
    group named after it is priced by it. Returns the job's copy."""
    job = assemblies.read_job(doc)
    have = job["assemblies"].get(a["name"])
    if have is None:
        assemblies.set_job_assembly(doc, a)
        have = a
    return copy.deepcopy(have)


# ---- the dialog ------------------------------------------------------------

def _dialog_class():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                                   QLabel, QLineEdit, QListWidget,
                                   QListWidgetItem, QVBoxLayout)

    class TakeIntoAssemblyDialog(QDialog):
        """Division list on the left, its assemblies on the right."""

        def __init__(self, doc, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Take Off Into Assembly")
            self.resize(760, 460)
            self.chosen = None
            job = assemblies.read_job(doc) if doc is not None else {}
            try:
                lib = assemblies.library()
            except Exception:                         # noqa: BLE001
                log.warning("assembly library unreadable", exc_info=True)
                lib = {}
            self.groups = by_division(catalog(job, lib))
            v = QVBoxLayout(self)
            v.addWidget(QLabel(
                "Pick a CSI division, then the assembly to measure into. "
                "The matching tool starts and everything you trace is "
                "priced by the assembly in the Assemblies panel."))
            self.search = QLineEdit()
            self.search.setPlaceholderText("Filter assemblies")
            self.search.textChanged.connect(lambda _t: self._fill())
            v.addWidget(self.search)
            row = QHBoxLayout()
            self.divs = QListWidget()
            self.divs.setMaximumWidth(260)
            for d, items in self.groups:
                it = QListWidgetItem(f"{division_label(d)}  ({len(items)})")
                it.setData(Qt.UserRole, d)
                self.divs.addItem(it)
            self.divs.currentRowChanged.connect(lambda _r: self._fill())
            row.addWidget(self.divs)
            self.list = QListWidget()
            self.list.itemDoubleClicked.connect(lambda _i: self.accept())
            self.list.currentRowChanged.connect(lambda _r: self._sync())
            row.addWidget(self.list, 1)
            v.addLayout(row, 1)
            self.info = QLabel("")
            self.info.setObjectName("muted")
            self.info.setWordWrap(True)
            v.addWidget(self.info)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            self.ok = bb.button(QDialogButtonBox.Ok)
            self.ok.setText("Start Takeoff")
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            v.addWidget(bb)
            if self.groups:
                self.divs.setCurrentRow(0)
            self._fill()

        def division(self):
            it = self.divs.currentItem()
            return it.data(Qt.UserRole) if it is not None else None

        def select_division(self, div):
            for i in range(self.divs.count()):
                if self.divs.item(i).data(Qt.UserRole) == div:
                    self.divs.setCurrentRow(i)
                    return True
            return False

        def select_assembly(self, name):
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole)["name"] == name:
                    self.list.setCurrentRow(i)
                    return True
            return False

        def _fill(self):
            d = self.division()
            items = dict(self.groups).get(d, []) if d is not None else []
            q = self.search.text().strip().lower()
            if q:
                items = [a for a in items
                         if q in a["name"].lower() or
                         q in str(a.get("trade") or "").lower()]
            self.list.clear()
            for a in items:
                it = QListWidgetItem(f"{a['name']}    [{describe(a)}]")
                it.setData(Qt.UserRole, a)
                self.list.addItem(it)
            if self.list.count():
                self.list.setCurrentRow(0)
            self._sync()

        def current(self):
            it = self.list.currentItem()
            return it.data(Qt.UserRole) if it is not None else None

        def _sync(self):
            a = self.current()
            self.ok.setEnabled(a is not None)
            if a is None:
                self.info.setText("No assembly in this division." if
                                  self.groups else
                                  "The assembly library is empty.")
                return
            parts = ", ".join(p.get("name", "") for p in
                              (a.get("parts") or [])[:6])
            self.info.setText(f"<b>{a['name']}</b>: {describe(a)}"
                              + (f"<br>Parts: {parts}" if parts else ""))

        def accept(self):
            self.chosen = self.current()
            if self.chosen is None:
                return
            super().accept()

    return TakeIntoAssemblyDialog


_CLS = []


def TakeIntoAssemblyDialog(doc, parent=None):           # noqa: N802
    """The dialog (its class is made on first use, so the pure part of
    this module never needs Qt)."""
    if not _CLS:
        _CLS.append(_dialog_class())
    return _CLS[0](doc, parent)


def start(mw, a):
    """Bind `a` to its takeoff group and start measuring with it (the
    Assemblies panel's own Take Off path). False with no drawing open."""
    v = getattr(mw, "_view", None)
    if v is None or a is None or not tool_for(a):
        return False
    bind(v.doc, a)
    mw.assemblies.use(a)            # emits take_off -> mw.use_assembly
    try:
        mw._doc_edited()
        mw.assemblies.refresh()
    except Exception:                                     # noqa: BLE001
        log.debug("refresh after binding", exc_info=True)
    return True


def run(mw, show=True):
    """The command. With no drawing open it says so in the status bar
    (no dialog). Returns the dialog (show=False: not opened)."""
    v = getattr(mw, "_view", None)
    if v is None:
        try:
            mw._flash("Open a drawing first, then Take Off Into Assembly.")
        except Exception:                                 # noqa: BLE001
            pass
        return None
    dlg = TakeIntoAssemblyDialog(v.doc, mw)
    mw._take_into_dlg = dlg
    if show and dlg.exec() and dlg.chosen:
        start(mw, dlg.chosen)
    return dlg
