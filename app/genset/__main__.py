"""python -m app.genset --brief "1600 sf 3 bed 2 bath ranch new" [--sketch
f] [--name N] [--firm F] [--no-ai] out.pdf"""
import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.genset")
    ap.add_argument("--brief", default="")
    ap.add_argument("--sketch")
    ap.add_argument("--sketch-page", type=int, default=0)
    ap.add_argument("--name")
    ap.add_argument("--address")
    ap.add_argument("--firm")
    from . import types
    ap.add_argument("--type", choices=types.keys())
    ap.add_argument("--sf", type=float)
    ap.add_argument("--occupancy", choices=types.occupancies())
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    import app  # noqa: F401  (fitz alias)
    from .build import build_set, plan_from_brief
    from .kernel_modulor import KernelMissing
    from .model import PlanError
    form = {"name": a.name, "address": a.address, "building_type": a.type,
            "gross_sf": a.sf, "occupancy": a.occupancy, "firm": a.firm}
    try:
        plan = plan_from_brief(a.brief, form=form, sketch=a.sketch,
                               sketch_page=a.sketch_page,
                               use_ai=not a.no_ai)
        res = build_set(plan, a.out, use_ai=not a.no_ai)
    except (PlanError, KernelMissing) as e:
        print(f"No set made: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
