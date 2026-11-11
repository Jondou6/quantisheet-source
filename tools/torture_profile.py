"""Where the time goes in the torture test's slow spots (Nov 10).

    python tools/torture_profile.py billing|estimate|marks

Builds the state the torture test reached, then profiles one more step
and prints the top functions by total time. Made-up data only.
"""
import cProfile
import os
import pstats
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


CALLERS = []


def prof(label, fn, n=1):
    pr = cProfile.Profile()
    t = time.perf_counter()
    pr.enable()
    for _ in range(n):
        fn()
    pr.disable()
    print(f"\n== {label}: {(time.perf_counter() - t) / n * 1000:.0f} ms "
          f"each ({n} runs)")
    st = pstats.Stats(pr).sort_stats("tottime")
    st.print_stats(14)
    for c in CALLERS:
        st.print_callers(c)


def billing():
    import fitz
    from app import money as m
    rnd = random.Random(6)
    d = fitz.open()
    d.new_page()
    m.set_info(d, 10, 5, project="Example", owner="Example",
               contractor="Example")
    m.set_sov(d, [{"desc": f"Line {i}", "scheduled": 100000.0}
                  for i in range(400)])
    items = [r["item"] for r in m.sov(d)]
    for k in range(8):
        no = m.new_pay_app(d, f"2026-{k + 1:02d}-28")
        data = m.read(d)
        a = next(x for x in data["payapps"] if x["no"] == no)
        for it in items[:150]:
            a["lines"][it] = {"work": 1000.0, "stored": 0.0}
        m.write(d, data)
        m.certify(d, no)
    no = m.new_pay_app(d, "2026-09-28")
    raw = len(m.embfiles.get(d, m.FILE))
    print(f"billing data after 8 certified apps: {raw / 1e6:.2f} MB")
    its = iter(items)
    prof("set_progress at app 9", lambda: m.set_progress(
        d, no, next(its), work=10.0), n=20)
    prof("read() alone", lambda: m.read(d), n=20)
    data = m.read(d)
    prof("write() alone", lambda: m.write(d, data), n=20)


def estimate():
    import estimate_helpers as eh
    from app import estimate as est, annotate
    rnd = random.Random(7)
    doc = eh.blank_doc()
    for i in range(1500):
        eh.area(doc, f"G{i:04d}", 3, 3, x0=rnd.uniform(0, 1000),
                y0=rnd.uniform(0, 600))
        est.set_price(doc, f"G{i:04d}", "area", "sq ft", unit_cost=1.5)
    k = iter(range(1500, 3000))
    prof("one more takeoff area (1,500 on the sheet)",
         lambda: eh.area(doc, f"G{next(k):04d}", 3, 3), n=10)
    k2 = iter(range(1500, 3000))
    prof("one more price (1,500 priced)", lambda: est.set_price(
        doc, f"G{next(k2):04d}", "area", "sq ft", unit_cost=2.0), n=10)
    _ = annotate


def marks():
    from torture import window, pump, plain_pdf, tmp, close_all
    win = window()
    p = plain_pdf(os.path.join(tmp(), "m.pdf"), 1)
    win.open_path(p)
    pump(3)
    v = win._view
    rnd = random.Random(8)
    for i in range(500):
        x, y = rnd.uniform(20, 560), rnd.uniform(20, 740)
        v.apply_marks([(0, "add_rect", {"rect": [x, y, x + 15, y + 10]})])
    pump()

    def one():
        x, y = rnd.uniform(20, 560), rnd.uniform(20, 740)
        v.apply_marks([(0, "add_rect", {"rect": [x, y, x + 15, y + 10]})])
        pump(1)
    from app import annotate, history as hm
    import traceback
    h = v.history
    real_bump = annotate.bump_edits
    seen = []

    def spy(doc):
        if len(seen) < 3:
            seen.append("".join(traceback.format_stack(limit=9)[:-1]))
        return real_bump(doc)
    annotate.bump_edits = spy
    one()
    annotate.bump_edits = real_bump
    for k, st in enumerate(seen):
        print(f"--- bump {k + 1} came from:\n{st}")
    hit = h._after
    print("after one edit: stamped count", hit and hit["count"],
          "edit count now", annotate.edit_count(v.doc),
          "doc id same", hit and hit["doc"] == id(v.doc),
          "fingerprint same", hit and hit["fp"].get(0) ==
          hm._fingerprint(v.doc, 0))
    if hit and hit["fp"].get(0) != hm._fingerprint(v.doc, 0):
        print("   stamped fp", str(hit["fp"].get(0))[:80])
        print("   now fp    ", str(hm._fingerprint(v.doc, 0))[:80])
    prof("one rectangle on a sheet with 500 markups", one, n=10)
    close_all(win)


def commands(names):
    """Profile menu commands by name on the click-test job."""
    from torture import window, pump, tmp
    import perf
    from app.ribbon import all_actions, clean
    win = window()
    p = os.path.join(tmp(), "job.pdf")
    perf.make(p, 3)
    win.open_path(p)
    pump(5)
    acts = {clean(a.text()): a for _p, a in all_actions(win.menuBar())}
    for n in names:
        a = acts.get(n)
        if a is None:
            print("no command", n)
            continue

        def run():
            a.trigger()
            pump(3)
        run()                                  # warm up once
        prof(n, run, n=2)


if __name__ == "__main__":
    if len(sys.argv) > 3:
        CALLERS.extend(sys.argv[3].split("|"))
    if sys.argv[1] == "commands":
        commands([x.replace("_", " ") for x in sys.argv[2].split("|")])
    else:
        {"billing": billing, "estimate": estimate, "marks": marks}[
            sys.argv[1]]()
