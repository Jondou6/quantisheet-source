"""Help > Practice Job: a 10-minute first job on a made-up plan (Venice
#22/#23, Nov 4). The logic and the sandbox are practice_job.py (PR 9);
this is the small step window that sits beside the plan. Each step says
what to do; "Show Me" does it for you on the practice plan only."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from . import practice_job as pj

# what the user does in the window (the PR's "how" lines name functions)
HOW = {
    "open": "The practice plan is open - a made-up clinic, sheet A-101. "
            "Mark it up as much as you like; it isn't a real job.",
    "scale": "Look at the scale on the status bar. If it's blank, use "
             "Takeoff > Set Scale and pick 1/4\" = 1'-0\".",
    "measure": "Pick Length and click the two outside corners of the south "
               "(bottom) wall. Name it South Exterior Wall. It's 60 ft.",
    "price": "In the Estimate panel, give South Exterior Wall a unit cost "
             "of $18.75. Waste 0, multiplier 1. The line comes to "
             "$1,125.00.",
    "export": "Click Export Estimate (CSV) in the Estimate panel. The file "
              "stays in the practice folder.",
}


class PracticeJobWindow(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Practice Job (about 10 minutes)")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.setModal(False)
        lay = QVBoxLayout(self)
        self.head = QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setMinimumWidth(380)
        lay.addWidget(self.body)
        row = QHBoxLayout()
        self.show_me = QPushButton("Show Me")
        self.show_me.setToolTip("Do this step for you on the practice plan")
        self.show_me.clicked.connect(lambda: self.do_step())
        self.next_btn = QPushButton("Done - Next Step")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(lambda: self.next_step())
        over = QPushButton("Start Over")
        over.clicked.connect(lambda: self.start_over())
        row.addWidget(self.show_me)
        row.addStretch(1)
        row.addWidget(over)
        row.addWidget(self.next_btn)
        lay.addLayout(row)
        self.index = [s["id"] for s in pj.STEPS].index(pj.resume()["id"])
        self.fill()

    @property
    def current(self):
        return pj.STEPS[self.index]

    def _doc(self):
        import os
        v = getattr(self.win, "_view", None)
        path = getattr(self.win, "_path", None)
        if v is None or not path or os.path.normcase(os.path.abspath(path)) \
                != os.path.normcase(os.path.abspath(pj.plan_path())):
            return None
        return v.doc

    def fill(self):
        s = self.current
        n = len(pj.STEPS)
        left = sum(x["minutes"] for x in pj.STEPS[self.index:])
        self.head.setText(f"<b>Step {self.index + 1} of {n}: {s['title']}"
                          f"</b> &nbsp; <small>about {left} min left</small>")
        self.body.setText(s["what"] + "<br><br>" + HOW.get(s["id"], ""))
        self.show_me.setVisible(s["id"] in ("measure", "price", "export"))
        self.next_btn.setText("Finish" if self.index == n - 1
                              else "Done - Next Step")

    def do_step(self):
        """Show Me: the practice plan only, never another file."""
        doc = self._doc()
        if doc is None:
            self.body.setText(self.body.text() + "<br><br><i>Open the "
                              "practice plan first (Start Over).</i>")
            return None
        sid = self.current["id"]
        if sid == "measure":
            pj.place_sample_wall(doc)
        elif sid == "price":
            pj.apply_sample_price(doc)
        elif sid == "export":
            out = pj.export_csv(doc)
            self.win._flash("Practice estimate saved: " + out)
        v = self.win._view
        v.dirty = True
        v.update()
        self.win._refresh_panels()
        return sid

    def next_step(self):
        pj.record_step(self.current["id"])
        if self.index >= len(pj.STEPS) - 1:
            self.body.setText("That's a whole job: plan, scale, takeoff, "
                              "price, export. Next, open one of your own "
                              "plan sets with File > Open.")
            self.next_btn.setEnabled(False)
            self.show_me.hide()
            return None
        self.index += 1
        self.fill()
        return self.current["id"]

    def start_over(self):
        pj.reset_progress()
        info = pj.prepare(refresh=True)
        self.win.open_path(info["plan"])
        self.index = 0
        self.next_btn.setEnabled(True)
        self.fill()


def open_window(win, show=True):
    info = pj.prepare()
    win.open_path(info["plan"])
    dlg = PracticeJobWindow(win)
    if show:
        dlg.show()
    return dlg
