import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz
from app import formlib
out = os.path.join(ROOT, ".run", "forms_check"); os.makedirs(out, exist_ok=True)
want = ["AIA G701 Change Order", "AIA G702-G703 Pay Application", "AIA A132-2009 Exhibit A, Determination of the Cost of the Work", "Invitation to Bid (CCC)"]
for e in formlib.entries():
    if e["name"] not in want:
        continue
    for clear in (False, True):
        d = formlib.open_copy(e, clear=clear)
        left = sum(1 for pg in d for w in pg.widgets() or [] if w.field_value not in (None, "", "Off", False) and not str(w.field_name).startswith("DOD_"))
        print(e["name"], "clear" if clear else "as saved", "-> filled fields:", left)
        d[0].get_pixmap(dpi=60).save(os.path.join(out, f"{e['name'][:20]}_{'clear' if clear else 'saved'}.png"))
