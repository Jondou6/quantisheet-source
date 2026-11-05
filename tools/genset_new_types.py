"""Build sample strip-retail and restaurant sets (made-up briefs) to look at:
python tools/genset_new_types.py OUT_DIR"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app  # noqa: E402,F401

SAMPLES = [
    ("strip_6", "6-tenant strip center, 9,000 sf, end cap on the east, "
     "new", {"name": "Example Plaza"}),
    ("restaurant_dt", "4,000 sf restaurant with drive-thru, 120 seats, new",
     {"name": "Example Grill"}),
]


def main(out):
    from app.genset.build import build_set, plan_from_brief
    os.makedirs(out, exist_ok=True)
    for key, brief, form in SAMPLES:
        plan = plan_from_brief(brief, form=form, use_ai=False)
        pdf = os.path.join(out, key + ".pdf")
        res = build_set(plan, pdf, use_ai=False)
        print(key, plan.get("building_type"), len(plan["rooms"]), "rooms",
              "warnings", res["warnings"])


if __name__ == "__main__":
    main(sys.argv[1])
