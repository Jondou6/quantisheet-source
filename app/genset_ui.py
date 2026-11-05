"""File > Generate Set... : a brief (plus a few fields and an optional
sketch) in, a ten-sheet starter set out. Every sheet says FOR REVIEW -
NOT FOR SEALING; the dialog says so too, in red, before anything is built."""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

AUTO = "Auto (from the brief)"


def _types():
    """[(label, key)], {key: [occupancies]} and the largest gross SF, from
    the type registry (app/genset/types): house, small commercial,
    warehouse..."""
    from .genset import types
    reg = [types.get(k) for k in types.keys()]
    return ([(AUTO, None)] + [(t.label, t.key) for t in reg],
            {None: [AUTO], **{t.key: [AUTO] + list(t.occupancies)
                              for t in reg}},
            max(t.sf_range[1] for t in reg))


TYPES, OCCS, MAX_SF = _types()


class GenerateSetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Set")
        self.setObjectName("GenerateSetDialog")
        self.request = None
        lay = QVBoxLayout(self)
        from .genset import DISCLAIMER
        banner = QLabel(DISCLAIMER + "\nA computer-generated starting point: "
                        "a house or small commercial building up to 8,000 "
                        "SF, a restaurant (2,000 - 12,000 SF), a strip "
                        "retail center (4,000 - 60,000 SF), or a warehouse "
                        f"up to {MAX_SF:,.0f} SF. A "
                        "licensed design professional must verify "
                        "everything.")
        banner.setObjectName("GenSetBanner")
        banner.setWordWrap(True)
        banner.setStyleSheet("QLabel#GenSetBanner{background:#fdeaea;"
                             "color:#b00020;border:1px solid #b00020;"
                             "padding:8px;font-weight:bold;}")
        lay.addWidget(banner)
        form = QFormLayout()
        self.brief = QPlainTextEdit()
        self.brief.setPlaceholderText(
            "e.g. 3 bed 2 bath ranch, about 1,600 sf, new")
        self.brief.setFixedHeight(80)
        form.addRow("Brief", self.brief)
        self.kind = QComboBox()
        for label, key in TYPES:
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Building type", self.kind)
        self.work = QComboBox()
        self.work.addItem(AUTO, None)
        self.work.addItem("New", "new")
        self.work.addItem("Existing", "existing")
        form.addRow("Work", self.work)
        self.sf = QSpinBox()
        self.sf.setRange(0, int(MAX_SF))
        self.sf.setSingleStep(100)
        self.sf.setSpecialValueText("from the brief")
        self.sf.setSuffix(" SF")
        form.addRow("Gross area", self.sf)
        self.stories = QComboBox()
        self.stories.addItem(AUTO, None)
        self.stories.addItem("1 story", 1)
        self.stories.addItem("2 stories (house: bedrooms upstairs)", 2)
        form.addRow("Stories", self.stories)
        self.occ = QComboBox()
        form.addRow("Occupancy (label)", self.occ)
        self.name = QLineEdit()
        form.addRow("Project name", self.name)
        self.address = QLineEdit()
        self.address.setPlaceholderText("ADDRESS TBD")
        form.addRow("Address", self.address)
        self.firm = QLineEdit("[FIRM NAME]")
        form.addRow("Firm", self.firm)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        self.sketch = QLineEdit()
        self.sketch.setPlaceholderText("optional PDF or image")
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._pick_sketch)
        self.sketch_page = QSpinBox()
        self.sketch_page.setRange(1, 9999)
        self.sketch_page.setPrefix("page ")
        h.addWidget(self.sketch, 1)
        h.addWidget(pick)
        h.addWidget(self.sketch_page)
        form.addRow("Sketch", row)
        self.dxf = QCheckBox("Also save the floor plan for CAD (.dxf, "
                             "in feet)")
        self.dxf.setChecked(True)
        form.addRow("", self.dxf)
        lay.addLayout(form)
        self.ai = QLabel("Checking the local AI…")
        self.ai.setObjectName("GenSetAI")
        lay.addWidget(self.ai)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = self.buttons.addButton("Generate…",
                                         QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._kind_changed()
        self.resize(560, self.sizeHint().height())
        QTimer.singleShot(0, self._check_ai)

    def _check_ai(self):
        from . import bg
        from .genset import brief

        def done(up):
            self.ai.setText("Local AI: running - it reads the brief and "
                            "writes the project notes." if up else
                            "Local AI: not running - the brief is read by "
                            "text rules and the notes come from the "
                            "template.")
        bg.run(brief.ai_up, done, lambda _m: done(False), self)

    def _kind_changed(self, *_):
        self.occ.clear()
        self.occ.addItems(OCCS[self.kind.currentData()])

    def _pick_sketch(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Sketch", "", "Sketch (*.pdf *.png *.jpg *.jpeg)")
        if p:
            self.sketch.setText(p)

    def values(self):
        # only an explicit pick overrides the brief (Grok S1: the
        # defaults used to turn every retail brief into a house)
        form = {"building_type": self.kind.currentData(),
                "work": self.work.currentData(),
                "occupancy": None if self.occ.currentText() == AUTO
                else self.occ.currentText(),
                "name": self.name.text().strip(),
                "address": self.address.text().strip(),
                "firm": self.firm.text().strip() or "[FIRM NAME]",
                "stories": self.stories.currentData()}
        if self.sf.value() >= 400:
            form["gross_sf"] = float(self.sf.value())
        return {"brief": self.brief.toPlainText().strip(), "form": form,
                "sketch": self.sketch.text().strip() or None,
                "sketch_page": self.sketch_page.value() - 1,
                "dxf": self.dxf.isChecked()}

    def _accept(self):
        v = self.values()
        if 0 < self.sf.value() < 400:            # Venice N7: not silently
            self.ai.setText("Gross area starts at 400 SF (or leave it at "
                            "\"from the brief\").")
            return
        if not v["brief"] and "gross_sf" not in v["form"]:
            self.ai.setText("Type a brief or set the gross area "
                            "(400 - 8,000 SF; restaurants to 12,000, strip "
                            "centers to 60,000, warehouses to "
                            f"{MAX_SF:,.0f} SF).")
            return
        self.request = v
        self.accept()


def default_name(request):
    name = (request.get("form") or {}).get("name") or "Project"
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    return safe.strip().replace(" ", "_") + "_GenSet_v1.pdf"


def generate(request, out_path, use_ai=True):
    """Brief -> plan -> PDF (runs off the GUI thread)."""
    from .genset.build import build_set, plan_from_brief
    plan = plan_from_brief(request.get("brief") or "",
                           form=request.get("form"),
                           sketch=request.get("sketch"),
                           sketch_page=request.get("sketch_page") or 0,
                           use_ai=use_ai)
    return build_set(plan, out_path, use_ai=use_ai,
                     dxf=bool(request.get("dxf")))


def check(out_path):
    """Read the set back with the app's own takeoff readers (Step 8):
    room area tags on A-101 and the door count against the schedule."""
    import fitz
    from . import autotakeoff
    res = {}
    doc = fitz.open(out_path)
    fp = next((i for i in range(doc.page_count)
               if doc[i].get_label() == "A-101"), 2)
    try:
        try:
            res["room_tags"] = len(autotakeoff.room_tags(doc[fp]))
        except Exception as e:                            # noqa: BLE001
            res["room_tags"] = f"error: {e}"
        try:
            from . import annotate, autowalls
            vps = annotate.read_viewports(doc, fp)
            ppu = vps[0]["ppu"] if vps else 0
            res["doors"] = len(autowalls.doors(doc[fp], ppu)) if ppu \
                else "no scale"
        except Exception as e:                            # noqa: BLE001
            res["doors"] = f"error: {e}"
    finally:
        doc.close()
    return res


__all__ = ["GenerateSetDialog", "generate", "default_name", "check", "Qt"]
