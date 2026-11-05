"""Load the researched equipment and labor rates from the starter library
into your price database (replacing the same codes; crews and anything
you added are kept). Back up first.

    python tools/load_rates.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import heavy                                         # noqa: E402


def main():
    st = heavy._starter()
    heavy.library()                       # creates the tables if new
    for kind in ("equipment", "labor"):
        n = heavy.save_items(kind, st.get(kind) or [],
                             note="researched rates Oct 2026")
        print(f"{kind}: {n} records loaded")
    heavy.set_settings(st.get("settings") or {})
    lib = heavy.library()
    fuel = lib["settings"].get("fuel", 0)
    print(f"\nfuel ${fuel}/gal")
    for c, r in sorted(lib["equipment"].items()):
        e = heavy.equipment_rate(r, fuel)
        print(f"  {c:9} own {e['own']:>7} op {e['op']:>6} fuel {e['fuel']:>6}"
              f"  = {e['total']:>7}/hr")
    for c, r in sorted(lib["labor"].items()):
        b = heavy.burden(r)
        print(f"  {c:5} base {b['base']:>6}  burdened {b['total']:>6}/hr")
    for c, cr in sorted(lib["crews"].items()):
        print(f"  crew {c:6} {heavy.crew_rate(cr, lib)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
