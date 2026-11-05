"""Trial (read-only on the source files): the Master Schedule run against a
real job's schedule printouts. A scratch project is made in a temp folder
from the first printout (its activities, all owned by one made-up sub);
each later printout is then received as that sub's update, the way a
monthly cycle would run. Prints what happened at each step. The source
PDFs are only read (copied into the temp folder first); nothing is
written anywhere else, and the temp folder is deleted at the end.

    python tools/trial_master_real.py "<folder with the PDFs>" """
import datetime as dt
import glob
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings  # noqa: E402

SUB = "Trial Sub"
tmp = tempfile.mkdtemp(prefix="ms_trial_")
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Trial"}

from app.pm.store import ProjectStore  # noqa: E402
from app.pm.master import apply, match, model  # noqa: E402
from app.pm.master.formats import pdfsched  # noqa: E402


def main():
    folder = " ".join(sys.argv[1:])
    pdfs = []
    for f in glob.glob(os.path.join(folder, "**", "*.pdf"), recursive=True):
        if "markup" in os.path.basename(f).lower():
            continue                      # a marked-up copy of another one
        p = pdfsched.read_pages(pdfsched._words(f))
        if p["layout"] == "p6" and p["data_date"]:
            pdfs.append((p["data_date"], f, p))
    pdfs.sort(key=lambda x: (x[0], os.path.basename(x[1])))
    print("printouts in date order:")
    for d, f, p in pdfs:
        print(f"  {d}  {os.path.basename(f)[:70]}  "
              f"({len(pdfsched.activities(p))} activities)")
    base_date, base_file, base = pdfs[0]
    s = ProjectStore(os.path.join(tmp, "NMB trial"))
    s.set_setting("data_date", base_date.isoformat())
    s.save_record("member", {"name": "Trial Person", "company": SUB,
                             "email": "trial@example.invalid",
                             "role": "Subcontractor"})
    ids = {}
    for r in pdfsched.activities(base):
        rec = {"name": r["name"], "duration": r["orig"] or 0,
               "start": r["start"].isoformat(), "owner_co": SUB}
        if r["start_a"]:
            rec["actual_start"] = r["start"].isoformat()
            if r["orig"] and r["rem"] is not None:
                rec["percent"] = round((r["orig"] - r["rem"]) /
                                       r["orig"] * 100)
        a = s.save_record("activity", rec)
        ids[f"p6:{r['id']}"] = a["_id"]
    s.flush()
    mine = set(model.slice_ids(s, SUB))   # milestones stay the GC's
    gc = {k: v for k, v in ids.items() if v not in mine}
    ids = {k: v for k, v in ids.items() if v in mine}
    match.save(s, SUB, ids)                # Jon's one-time "Map rows"
    print(f"   {len(gc)} milestone(s) stay the GC's (not in the sub's slice)")
    model.set_config(s, cycle={"nth": "last"})
    print(f"\nscratch master from {os.path.basename(base_file)[:60]}: "
          f"{len(ids)} activities, all mapped to {SUB}")
    seen = {base_file}
    for d, f, p in pdfs[1:]:
        if f in seen:
            continue
        seen.add(f)
        q = os.path.join(tmp, os.path.basename(f))
        shutil.copy2(f, q)
        now = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(9))
        s.set_setting("data_date", d.isoformat())
        sub = apply.receive(s, q, SUB, channel="manual", now=now)
        rows = sub.get("rows") or []
        ch = sub.get("changes") or []
        imp = sub.get("impact") or {}
        print(f"\n== {d}  {os.path.basename(f)[:60]}")
        print(f"   status: {sub.get('status')}   rows matched: {len(rows)}"
              f"   unmatched: {len(sub.get('unmatched') or [])}"
              f"   not reported: {len(sub.get('not_reported') or [])}"
              f"   changes: {len(ch)}")
        for e in (sub.get("reasons") or [])[:6]:
            print("   REASON:", e.get("where"), "-", e.get("text"))
        for w in (sub.get("warnings") or [])[:6]:
            print("   warning:", w.get("where"), "-", str(w.get("text"))[:150])
        for u in (sub.get("unmatched") or [])[:5]:
            print("   unmatched:", u.get("ref"), u.get("name"))
        for k in ("project_finish", "substantial", "later"):
            if k in imp:
                v = imp[k]
                print(f"   impact {k}:", v if not isinstance(v, list)
                      else f"{len(v)} item(s) {v[:2]}")
        for y in (sub.get("why") or [])[:4]:
            print("   to review because:", str(y)[:150])
        if sub.get("status") == "Pending review":
            try:
                done = apply.approve(s, sub["_id"], by="Trial", now=now)
                if done.get("status") == "Pending review":
                    done = apply.approve(s, sub["_id"], by="Trial", now=now)
                print("   approved ->", done.get("status"))
            except Exception as ex:                       # noqa: BLE001
                print("   approve refused:", ex)
    print("\nimpact keys seen:", sorted(imp) if pdfs[1:] else "-")


try:
    main()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
