"""Dump what auto takeoff sees on a page (for tuning): the grey render,
the words and the scale, into trial_output/."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))

import fitz                                    # noqa: E402

from app import autotakeoff                    # noqa: E402

path, pno, ppf = sys.argv[1], int(sys.argv[2]) - 1, float(sys.argv[3])
doc = fitz.open(path)
page = doc[pno]
plan = autotakeoff.Plan(page, {"ppu": ppf, "unit": "ft"}, claimed=False)
zoom = plan.zoom
pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY,
                      annots=False, alpha=False)
os.makedirs("trial_output", exist_ok=True)
pix.save(f"trial_output/at_p{pno + 1}.png")
json.dump({"zoom": zoom, "ppf": plan.ppf, "rotation": page.rotation,
           "rect": list(page.rect), "words": page.get_text("words"),
           "tags": [{"name": t["name"], "sf": t["sf"],
                     "pt": [t["pt"].x, t["pt"].y]}
                    for t in autotakeoff.room_tags(page)]},
          open(f"trial_output/at_p{pno + 1}.json", "w"))
print("ok", pix.width, pix.height, zoom)
