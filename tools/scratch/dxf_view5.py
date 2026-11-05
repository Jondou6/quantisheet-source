import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import fitz
OUT = os.path.join(ROOT, ".run", "dxf_trial")
for name in ("gdsestimating__api-cw750-details_sheets.pdf", "gdsestimating__api-cw750-details.pdf"):
    d = fitz.open(os.path.join(OUT, name))
    print(name, "drawings before", len(d[0].get_drawings()))
    for ui in d.layer_ui_configs():
        if not ui["on"]:
            d.set_layer_ui_config(ui["number"], 0)
    print("ui", [(u["text"], u["on"]) for u in d.layer_ui_configs()])
    print("drawings after", len(d[0].get_drawings()))
    for i, pg in enumerate(d):
        if i < 4:
            pg.get_pixmap(dpi=55).save(os.path.join(OUT, f"V5_{name[:-4]}_{i + 1}.png"))
