"""Takeoff accuracy check on the real test jobs (Nov 25 optimization list:
"Takeoff accuracy check on real jobs after every build").

    python tools/accuracy_gate.py            check against the last good run
    python tools/accuracy_gate.py --accept   make this run the new baseline

On this PC's test plan sets in _incoming\\plans (they never leave the PC):
- Auto Takeoff Rooms on the HMB set's A101 against truth.csv's room areas
  (tools/truth_rooms.py), and
- Auto Scale on every sheet of the HMB and Dillon sets.
It compares with .run\\accuracy_baseline.json (kept on this PC only, never
in the repository) and prints REGRESSION for a room that passed and now
fails, or a sheet whose scale was found and now isn't, or changed. Exit 1
on a regression. tools/build_installer.py runs it after every build and
puts the result line in the build log. Quantities only."""
import contextlib
import glob
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PLANS = os.path.join(ROOT, "_incoming", "plans")
BASE = os.path.join(ROOT, ".run", "accuracy_baseline.json")
SCALE_SETS = {"hmb": "harbor_springs_hmb_bid_drawings.pdf",
              "dillon": os.path.join("Dillon", "Bid Drawings.pdf")}


def rooms():
    import truth_rooms
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        r = truth_rooms.run("hmb")
    return r


def scales(name):
    import fitz
    from app import acrobat, aitakeoff as ait, autoscale
    path = os.path.join(PLANS, SCALE_SETS[name])
    doc = fitz.open(path)                 # read-only: nothing is saved
    need = ait.ocr_needed(doc)
    if need:
        acrobat.make_searchable(doc, sorted(need), vertical=True)
    rows = autoscale.detect(doc, use_ocr=True)
    doc.close()
    return {str(r["page"] + 1): [r["status"], r.get("label")] for r in rows}


def measure():
    out = {"rooms": None, "scales": {}, "seconds": {}}
    if os.path.isfile(os.path.join(PLANS, "truth.csv")):
        t = time.time()
        out["rooms"] = rooms()
        out["seconds"]["rooms"] = round(time.time() - t)
    for name, rel in SCALE_SETS.items():
        if os.path.isfile(os.path.join(PLANS, rel)):
            t = time.time()
            out["scales"][name] = scales(name)
            out["seconds"][name] = round(time.time() - t)
    return out


def compare(base, now):
    """[problem lines] - empty when nothing got worse."""
    bad = []
    if base.get("rooms") and now.get("rooms"):
        for no, b in base["rooms"]["rooms"].items():
            n = now["rooms"]["rooms"].get(no)
            if b["ok"] and not (n and n["ok"]):
                bad.append(f"room {no}: was within tolerance "
                           f"({b['err']:+.1f}%), now "
                           + (f"{n['err']:+.1f}%" if n and n["err"] is not
                              None else "not traced"))
    for name, b in (base.get("scales") or {}).items():
        n = (now.get("scales") or {}).get(name)
        if n is None:
            continue
        for page, (st, label) in b.items():
            st2, label2 = n.get(page, ["none", None])
            if st != "none" and (st2 == "none" or label2 != label):
                bad.append(f"{name} sheet {page}: scale was {label} "
                           f"({st}), now {label2} ({st2})")
    return bad


def summary(now):
    parts = []
    if now.get("rooms"):
        parts.append(f"rooms {now['rooms']['ok']}/{now['rooms']['n']}")
    for name, rows in (now.get("scales") or {}).items():
        found = sum(st != "none" for st, _l in rows.values())
        parts.append(f"{name} scales {found}/{len(rows)}")
    return ", ".join(parts) or "no test plan sets on this PC"


def main(argv):
    now = measure()
    line = "accuracy: " + summary(now)
    try:
        with open(BASE) as f:
            base = json.load(f)
    except (OSError, ValueError):
        base = None
    if "--accept" in argv or base is None:
        os.makedirs(os.path.dirname(BASE), exist_ok=True)
        with open(BASE, "w") as f:
            json.dump(now, f, indent=1)
        print(line, "- saved as the baseline")
        return 0
    bad = compare(base, now)
    better = []
    if base.get("rooms") and now.get("rooms") and \
            now["rooms"]["ok"] > base["rooms"]["ok"]:
        better.append(f"rooms {base['rooms']['ok']} -> {now['rooms']['ok']}")
    print(line + (f" - REGRESSION ({len(bad)})" if bad else
                  " - nothing worse than the baseline") +
          (f"; better: {', '.join(better)}" if better else ""))
    for b in bad:
        print("  REGRESSION", b)
    if not bad and better:
        print("  (run with --accept to keep the better result as the "
              "baseline)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
