"""Render the site and roof sheets of a few sample sets to PNG for a look.
python tools/genset_preview.py <out_dir>"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
import app  # noqa: E402,F401
import fitz  # noqa: E402
from app import genset_ui  # noqa: E402

SAMPLES = [("house_lot", "3 bed 2 bath house 1600 sf, lot 80 x 120"),
           ("house_tight", "3,000 sf house, lot 80 x 100, setbacks front "
                           "25 side 10 rear 25"),
           ("office", "2,400 sf office, occupancy B, new, 0.5 acre lot"),
           ("retail", "4000 sf retail store, new"),
           ("two_story", "two story 2400 sf house, 4 bed 3 bath, new, lot "
                         "70 x 110"),
           ("garage1", "3 bed 2 bath house 1800 sf with a 2-car garage, "
                       "lot 100 x 130"),
           ("garage2", "two story 2800 sf house, 4 bed 3 bath, 3-car "
                       "garage"),
           ("porch", "3 bed 2 bath house 1800 sf, covered front porch, "
                     "rear deck, 2-car garage, lot 100 x 140"),
           ("narrow", "3 bed 2 bath house 1800 sf, covered porch, lot 45 x "
                      "130, setbacks 20 front, 5 side, 20 rear"),
           ("narrow2", "3 bed 2 bath two story house 2400 sf, lot 50 x 120, "
                       "side setback 5 ft"),
           ("rowhouse", "3 bed 2 bath two story house 2400 sf, lot 40 x "
                        "120, setbacks 20 front, 5 side, 20 rear, porch, "
                        "rear deck")]


def main(out):
    os.makedirs(out, exist_ok=True)
    for key, brief in SAMPLES:
        pdf = os.path.join(out, key + ".pdf")
        genset_ui.generate({"brief": brief}, pdf, use_ai=False)
        doc = fitz.open(pdf)
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=40)
            pix.save(os.path.join(out, f"{key}_{doc[i].get_label()}.png"))
        doc.close()
        print("ok", key)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "genset_preview")
