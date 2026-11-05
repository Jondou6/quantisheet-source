"""Build the three Generate Set samples, render every sheet, run the
plan's acceptance checks.

    python tools/genset_samples.py [OUT_DIR]
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app  # noqa: E402,F401
import fitz  # noqa: E402

SAMPLES = [
    ("house_1600", "3 bed 2 bath ranch, about 1600 sf, new",
     {"name": "Smith Residence"}),
    ("office_2400", "2,400 sf office, occupancy B, new",
     {"name": "Riverside Office"}),
    ("retail_4000", "4000 sf retail store, new", {"name": "Main St Retail"}),
]


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, ".run", "genset")
    os.makedirs(out, exist_ok=True)
    from app.genset import DISCLAIMER
    from app.genset.build import SHEETS, build_set, plan_from_brief
    from app import annotate
    for key, brief, form in SAMPLES:
        t = time.perf_counter()
        plan = plan_from_brief(brief, form=form, use_ai=False)
        pdf = os.path.join(out, key + ".pdf")
        res = build_set(plan, pdf, use_ai=False)
        dt = time.perf_counter() - t
        doc = fitz.open(pdf)
        texts = [p.get_text() for p in doc]
        checks = {
            "10 pages": doc.page_count == 10,
            "disclaimer on every page": all(DISCLAIMER in t_ for t_ in
                                            texts),
            "sheet numbers": all(no in texts[i] for i, (no, _) in
                                 enumerate(SHEETS)),
            "no m2 anywhere": not any(("m2" in t_) or ("m²" in t_)
                                      for t_ in texts),
            "metadata": doc.metadata.get("subject") == DISCLAIMER,
            "sidecar kernel modulor": json.load(open(res["sidecar"]))[
                "source"]["kernel"] == "modulor",
        }
        vps = annotate.read_viewports(doc)
        checks["scales on AS-101/A-101/102/201/301"] = all(
            vps.get(i) for i in (2, 3, 4, 5, 6))
        checks["drawings on A-101 > 20"] = len(doc[3].get_drawings()) > 20
        print(f"== {key}: {dt:.2f}s  scales {res['scales']}  "
              f"warnings {res['warnings']}", flush=True)
        for k, v in checks.items():
            print(f"   {'ok ' if v else 'FAIL'} {k}", flush=True)
        from app.genset_ui import check
        print(f"   read back: {check(pdf)}  rooms {len(plan['rooms'])}  "
              f"doors {sum(o['kind'] == 'door' for o in plan['openings'])}",
              flush=True)
        for i, p in enumerate(doc):
            p.get_pixmap(dpi=40).save(os.path.join(out, f"{key}_{i+1}.png"))
        doc.close()


if __name__ == "__main__":
    main(sys.argv[1:])
