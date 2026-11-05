"""Diagnostic (Jon, Oct 28: 'when you edit a document it makes a black
box'): open a made-up PDF in a QuantiSheet window with the DARK theme,
start editing a paragraph and report what the editor box looks like.
Settings go to a temp folder; Jon's settings and files aren't touched.
Writes the editor's picture to .run/diag_textedit.png.

    python tools/diag_textedit_dark.py [light]"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp(prefix="qs_te_")

from app import settings                                         # noqa: E402
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Diag", "theme": "dark"}

import fitz                                                       # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

app = QApplication.instance() or QApplication([])
from app import annotate, theme                                   # noqa: E402
mode = sys.argv[1] if len(sys.argv) > 1 else "dark"
print("theme:", theme.apply(app, mode))

d = fitz.open()
p = d.new_page()
p.insert_textbox(fitz.Rect(72, 80, 400, 200),
                 "Example County is requesting sealed bids for the "
                 "construction of an example building. Plans may be viewed "
                 "on the example website.", fontsize=11, fontname="helv")
path = os.path.join(tmp, "doc.pdf")
d.save(path)

from app.main_window import MainWindow                            # noqa: E402
w = MainWindow()
w.resize(1400, 900)
w.show()
w.open_path(path)
app.processEvents()
v = w._view
v.set_tool("edit_text")
ctl = v.editctl
word = [x for x in v.pg.get_text("words") if x[4] == "sealed"][0]
ctl.open(annotate.from_page(v.pg, fitz.Rect(word[:4])).tl + (2, 2))
for _ in range(5):
    app.processEvents()
ed = ctl.editor
vp = ed.viewport()
print("editor style sheet:", ed.styleSheet())
print("palette base/text:", ed.palette().base().color().name(),
      ed.palette().text().color().name())
print("viewport palette base:", vp.palette().base().color().name(),
      "autofill", vp.autoFillBackground())
img = ed.grab().toImage()
print("editor size:", img.width(), "x", img.height())
pts = [(img.width() // 2, img.height() - 4), (6, img.height() // 2),
       (img.width() - 8, 6)]
for x, y in pts:
    print(f"pixel {x},{y}:", img.pixelColor(x, y).name())
dark = sum(1 for x in range(0, img.width(), 4)
           for y in range(0, img.height(), 4)
           if img.pixelColor(x, y).lightness() < 80)
tot = len(range(0, img.width(), 4)) * len(range(0, img.height(), 4))
print(f"dark pixels: {dark}/{tot} ({100 * dark / max(1, tot):.0f}%)")
out = os.path.join(ROOT, ".run", "diag_textedit.png")
img.save(out)
print("picture:", out)
ctl.cancel()
w.close()
