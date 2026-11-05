"""Stress test of what was added on Oct 16 (v27-v35 and the afternoon fixes),
at real-job sizes, timed. Every step runs even if an earlier one fails.

    python tools/stress_new.py PLANS.pdf SPECS.pdf

Works on copies in a temp folder and a throwaway settings folder, so no
real file or price database is touched. Prints one line per step (OK /
SLOW / FAIL) and a summary; exit code 1 if anything failed.
"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
import traceback
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fitz                                                   # noqa: E402

from app import settings                                      # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-stress-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Stress Test"}
os.makedirs(settings.DIR, exist_ok=True)

RESULTS = []


def step(name, fn, slow=None):
    t = time.time()
    try:
        info = fn()
        dt = time.time() - t
        flag = "SLOW" if slow and dt > slow else "OK  "
        RESULTS.append({"step": name, "ok": True, "s": round(dt, 2),
                        "slow": flag == "SLOW", "info": info})
        print(f"{flag} {name:52} {dt:7.2f}s  {info if info else ''}",
              flush=True)
    except Exception as e:
        dt = time.time() - t
        RESULTS.append({"step": name, "ok": False, "s": round(dt, 2),
                        "error": f"{e.__class__.__name__}: {e}",
                        "trace": traceback.format_exc()[-1500:]})
        print(f"FAIL {name:52} {dt:7.2f}s  {e.__class__.__name__}: {e}",
              flush=True)
        print("     " + traceback.format_exc()[-900:].replace("\n", "\n     "),
              flush=True)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main(argv):
    plans_src, specs_src = argv[0].strip('"'), argv[1].strip('"')
    plans = os.path.join(TMP, "plans.pdf")
    specs = os.path.join(TMP, "specs.pdf")
    shutil.copy(plans_src, plans)
    shutil.copy(specs_src, specs)
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    setattr(QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.No))

    # ---------------------------------------------------- scheduler (600)
    def schedule_600():
        from app.pm import scheduler, schedule
        import datetime as dt
        st = scheduler.create_schedule("Stress 600", os.path.join(TMP, "s"),
                                       dt.date(2026, 11, 2))
        prev = None
        for i in range(600):
            rec = {"name": f"Activity {i + 1}",
                   "duration": random.randint(1, 15),
                   "preds": [{"id": prev, "type": "FS", "lag": 0}]
                   if prev else []}
            r = st.save_record("activity", rec)
            prev = r.get("_no") or r.get("_id")
        t = time.time()
        cpm = schedule.compute(st)
        c1 = time.time() - t
        t = time.time()
        schedule.compute(st)
        c2 = time.time() - t
        check(len(cpm["rows"]) == 600, f"{len(cpm['rows'])} rows")
        check(not cpm["problems"], cpm["problems"][:3])
        w = scheduler.Scheduler(st)
        w.resize(1600, 900)
        w.show()
        app.processEvents()
        n = w.table.rowCount()
        w.close()
        return f"compute {c1:.2f}s, again {c2:.2f}s, grid {n} rows, " \
            f"finish {cpm['finish']}"
    step("Scheduler: 600 linked activities", schedule_600, slow=10)

    # ---------------------------------------------- coded assemblies (big)
    def assemblies_big():
        from app import assembly_codes as ac, cost_rollup
        rows = []
        for a in range(500):
            code = f"{a:05d}"
            for t, rate in (("L", "62.5"), ("M", "4.10"), ("E", "95"),
                            ("M", "")):
                rows.append([code, f"Assembly {a}", "LF", f"Trade {a % 12}",
                             f"{code}.01", f"R{t}{a}", t, f"{t} part", "0.5",
                             "HR", rate])
        path = os.path.join(TMP, "lib.csv")
        ac.write_rows(path, rows)
        lib = ac.read(path)
        check(len(lib) == 500, len(lib))
        doc = fitz.open()
        doc.new_page()
        items = []
        for g in range(300):
            for k in range(10):
                items.append({"group": f"Group {g}", "type": "length",
                              "unit": "LF", "value": 10 + k, "page": 0,
                              "rect": [0, 0, 1, 1]})
        for g in range(300):
            ac.bind(doc, f"Group {g}", "length", "LF", f"{g:05d}", 5, lib)
        lines, unbound = ac.priced_lines(doc, lib, items)
        check(len(lines) == 300 and not unbound, (len(lines), len(unbound)))
        r = cost_rollup.summary(lines, [("gc", "8"), ("profit", "10")], 7,
                                "12000")
        check(r["total"] > r["direct"] > 0, "totals")
        check(all(ln["unpriced"] for ln in lines), "blank rates flagged")
        cost_rollup.export(os.path.join(TMP, "sum.xlsx"), r)
        return f"{len(lines)} lines, total {r['total']}, $/SF {r['per_sf']}"
    step("Coded assemblies: 500 x 4 library, 3000 items", assemblies_big,
         slow=15)

    # ---------------------------------------------------- change report
    def change_big():
        from app import annotate, change_report as cr
        old, new = fitz.open(), fitz.open()
        for d in (old, new):
            for _ in range(20):
                d.new_page()
        rnd = random.Random(4)
        oi, ni = [], []
        for i in range(2000):
            it = {"group": f"G{i % 40}", "type": "count", "unit": "",
                  "multiplier": 1, "page": i % 20,
                  "rect": [rnd.randint(0, 500), rnd.randint(0, 700), 0, 0]}
            it["rect"][2], it["rect"][3] = it["rect"][0] + 5, it["rect"][1] + 5
            oi.append(it)
            if i % 10 == 3:
                continue                                   # removed
            n = dict(it, rect=list(it["rect"]))
            if i % 10 == 5:
                n["rect"] = [x + 40 for x in n["rect"]]    # moved
            ni.append(n)
        ni += [dict(oi[0], rect=[1, 1, 6, 6]) for _ in range(50)]  # added
        real = annotate.takeoff_items
        annotate.takeoff_items = lambda d, *a, **k: oi if d is old else ni
        try:
            res = cr.compare(old, new, {}, pair=lambda a, b: [
                (p, p, f"S{p}") for p in range(20)])
        finally:
            annotate.takeoff_items = real
        cr.text(res)
        return {k: len(res[k]) for k in ("unchanged", "moved", "added",
                                         "removed", "orphans")}
    step("Change report: 2,000 items, 20 sheets", change_big, slow=10)

    # ------------------------------------------------- the real window
    from app.main_window import MainWindow
    holder = {}

    def open_plans():
        w = MainWindow()
        w.resize(1600, 950)
        w.show()
        holder["w"] = w
        w.open_path(plans)
        for _ in range(10):
            app.processEvents()
        v = w._view
        check(v is not None, "no view")
        return f"{v.doc.page_count} pages"
    step("Open the plans in the window", open_plans, slow=20)

    def small_screen():
        w = holder["w"]
        from PySide6.QtWidgets import QToolButton
        w.showNormal()
        w.resize(1280, 640)            # 65 in TV at 300%, laptop at 150%
        for _ in range(5):
            app.processEvents()
        h = w.height()
        sb = w.statusBar()
        zoom = [x for x in w._chip_widgets if isinstance(x, QToolButton)]
        right = max(z.mapTo(sb, z.rect().topRight()).x() for z in zoom)
        check(h <= 680, f"window can't shrink below {h}px tall")
        check(sb.isVisible() and right <= sb.width(),
              f"zoom at {right}px of {sb.width()}px")
        return f"window {w.width()}x{h}, min {w.minimumSizeHint().height()}"
    step("Fits a 1280x640 screen (TV / laptop)", small_screen)

    def page_flip():
        w = holder["w"]
        v = w._view
        t = time.time()
        n = min(v.doc.page_count, 40)
        for p in range(n):
            v.go_to(p)
            app.processEvents()
        per = (time.time() - t) / max(1, n)
        check(per < 1.5, f"{per:.2f}s per page")
        return f"{per * 1000:.0f} ms per page over {n} pages"
    step("Flip through 40 sheets", page_flip, slow=60)

    def edit_mode():
        w = holder["w"]
        v = w._view
        v.go_to(0)
        w.set_tool("edit_text")
        app.processEvents()
        ctl = v.editctl
        check(ctl.active and not ctl.done_btn.isHidden(), "no Done button")
        ctl.done_btn.click()
        check(v.tool is None and not ctl.active, "still editing")
        return "Done Editing works"
    step("Edit Text: in and out", edit_mode)

    def ribbons():
        w = holder["w"]
        sm = w.simple_menu
        check(not sm.on, "simple menus on by default")
        for _ in range(10):
            sm.set_on(True)
            app.processEvents()
            sm.set_on(False)
            app.processEvents()
        w.toggle_field_mode()
        app.processEvents()
        w.toggle_field_mode()
        return "full ribbon default, toggled 10x, field mode on/off"
    step("Ribbons and Field Mode", ribbons)

    def external():
        from app import acrobat2, jobdata
        w = holder["w"]
        doc = w._view.doc
        out = os.path.join(TMP, "external.pdf")
        acrobat2.external_issue(doc, out)
        d2 = fitz.open(out)
        left = jobdata.describe(d2)
        d2.close()
        check(not left, f"job data left: {left}")
        return f"{os.path.getsize(out) / 1e6:.1f} MB, no job data"
    step("External Issue on the real set", external, slow=60)

    def undo_memory():
        from app import history
        w = holder["w"]
        doc = w._view.doc
        h = history.History(lambda: doc.tobytes(), max_bytes=300 * 2 ** 20)
        for i in range(12):
            doc[0].set_rotation((i % 4) * 90)
            h.snapshot()
        doc[0].set_rotation(0)
        size = sum(e[3] for e in h.stack)
        check(size <= 300 * 2 ** 20, f"{size / 2 ** 20:.0f} MB kept")
        return f"{len(h.stack)} steps, {size / 2 ** 20:.0f} MB " \
            f"(budget 300 MB, default {history.default_budget() / 2 ** 20:.0f})"
    step("Undo budget with full-set snapshots", undo_memory, slow=120)

    def heavybid_bg():
        from app import bg
        w = holder["w"]
        done = {}
        real = bg.run

        def run(fn, ok, err, owner):
            done["started"] = True

            def ok2(r):
                done["r"] = r
            return real(fn, ok2, lambda e: done.setdefault("err", e), owner)
        bg.run = run
        try:
            t = time.time()
            w.export_heavybid(folder=os.path.join(TMP, "hb"), soil="B")
            if not done.get("started"):
                return "no civil pipe sheets with a scale in this set " \
                    "(nothing to export) - window didn't wait"
            # the window must stay responsive while it works
            worst = 0.0
            while "r" not in done and "err" not in done:
                t0 = time.time()
                app.processEvents()
                worst = max(worst, time.time() - t0)
                time.sleep(0.05)
                check(time.time() - t < 1800, "takeoff over 30 min")
        finally:
            bg.run = real
        check("err" not in done, done.get("err"))
        r = done["r"]
        check(worst < 1.0, f"window froze for {worst:.1f}s")
        return f"{len(r.get('pipes') or [])} pipe groups, " \
            f"{len(r.get('structures') or [])} structures, worst UI " \
            f"stall {worst * 1000:.0f} ms"
    step("HeavyBid takeoff in the background", heavybid_bg, slow=600)

    def close_window():
        w = holder["w"]
        w._view.dirty = False
        w.close()
        app.processEvents()
    step("Close the window", close_window)

    # ------------------------------------------------- RFIs in the specs
    def rfi_specs():
        from app.ai import rfi_finder as rf
        d = fitz.open(specs)
        t = time.time()
        pages = rf.gather(d)
        g = time.time() - t
        check(rf.is_spec_book(pages), "not seen as a spec book")
        found = rf.checks([], pages) + rf.spec_checks(pages)
        read, total = rf.coverage(pages)
        check(read == total, f"AI would read {read}/{total}")
        d.close()
        return f"{total} pages read in {g:.1f}s, {len(found)} rule " \
            f"findings, AI covers {read}/{total}"
    step("Find RFIs: spec book rule checks", rfi_specs, slow=120)

    # ---------------------------------------------------- money and forms
    def bid_forms():
        from app.pm import bidforms
        lines = [bidforms.L(i, f"Line {i}", t, q, "EA")
                 for i, (t, q) in enumerate(
                     [("Unit price", 10), ("Lump sum", None),
                      ("Allowance", 0), ("Allowance", 500),
                      ("Alternate", None)] * 1000)]
        vals = {str(i): f"{(i % 7) * 100:,}" for i in range(len(lines))}
        t = bidforms.totals(lines, vals)
        check(t["base"] > 0, "no total")
        exp = 0.0
        for i, ln in enumerate(lines):
            exp += bidforms.line_total(ln, vals[str(i)])
        check(abs(t["base"] - round(exp, 2)) < 0.01, "totals disagree")
        return f"5,000 lines, base {t['base']:,.2f}"
    step("Bid forms: 5,000 lines", bid_forms, slow=5)

    def lines_table():
        from app.pm.widgets import LinesEdit
        w = LinesEdit([("crew", "Crew", "text"), ("hours", "Hours",
                                                  "number")])
        rows = [{"crew": f"C{i}", "hours": 1000 + i} for i in range(800)]
        w.set_value(rows)
        want = sum(r["hours"] for r in rows)
        check(f"{want:,}" in w.total.text(), (w.total.text(), want))
        return w.total.text()
    step("Table total: 800 rows over 1,000", lines_table, slow=20)

    def relay_fuzz():
        from app.collab import relaycore as rc
        bad = 0
        for peer in ("8.8.8.8", "203.0.113.5", "198.51.100.9", "1.2.3.4"):
            for xff in ("127.0.0.1", "::1", "10.0.0.1, 127.0.0.1",
                        "localhost"):
                if rc.is_loopback(rc.forwarded_ip(peer, xff)):
                    bad += 1
        check(bad == 0, f"{bad} spoofed addresses passed as local")
        return "spoofed X-Forwarded-For never counts as this computer"
    step("Relay: spoofed addresses", relay_fuzz)

    # ---------------------------------------------------------- summary
    fails = [r for r in RESULTS if not r["ok"]]
    slows = [r for r in RESULTS if r.get("slow")]
    print(f"\n{len(RESULTS)} steps: {len(RESULTS) - len(fails)} passed, "
          f"{len(fails)} failed, {len(slows)} slow")
    for r in fails:
        print(f"  FAIL {r['step']}: {r['error']}")
    for r in slows:
        print(f"  SLOW {r['step']}: {r['s']}s")
    with open(os.path.join(ROOT, ".run", "stress_new.json"), "w",
              encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=1, default=str)
    shutil.rmtree(TMP, ignore_errors=True)
    os._exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
