"""Torture test: push QuantiSheet past normal use and report what breaks.
Made-up files only, all in a temp folder.

    python tools/torture.py [SECTION,SECTION...|all] [--list]

Each section runs in its own process with a time limit, so a hang or a
hard crash in one is reported and the rest still run. A line per check:
PASS / FAIL / ERROR, then a summary. Exits 0 when nothing failed.
"""
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

SECTION_LIMIT = 280            # seconds per section process
RESULTS = []
SECTIONS = {}


def section(fn):
    SECTIONS[fn.__name__] = fn
    return fn


def check(name, cond, detail=""):
    RESULTS.append(("PASS" if cond else "FAIL", name, detail))
    print(("PASS " if cond else "FAIL ") + name +
          ("" if cond else f": {detail}"), flush=True)
    return cond


def guarded(name):
    """Run a check body; an exception is an ERROR line, not a stop."""
    def deco(fn):
        def run(*a, **k):
            t = time.perf_counter()
            try:
                out = fn(*a, **k)
            except Exception as ex:                       # noqa: BLE001
                tb = traceback.format_exc().strip().splitlines()[-6:]
                RESULTS.append(("ERROR", name, repr(ex)))
                print(f"ERROR {name}: {ex!r}\n    " + "\n    ".join(tb),
                      flush=True)
                return None
            print(f"  ({name}: {time.perf_counter() - t:.1f}s)", flush=True)
            return out
        return run
    return deco


_TMP = None


def tmp():
    global _TMP
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix="qs-torture-")
    return _TMP


# ------------------------------------------------------------------ Qt
_QT = {}


def headless_app():
    """A QApplication whose dialogs answer themselves (from
    click_everything), plus a log catcher."""
    if "app" in _QT:
        return _QT["app"]
    import logging
    from app import settings
    settings.DIR = os.path.join(tmp(), "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = None
    from PySide6.QtWidgets import (QApplication, QColorDialog, QDialog,
                                   QFileDialog, QInputDialog, QMenu,
                                   QMessageBox, QProgressDialog)
    from PySide6.QtGui import QColor
    app = QApplication.instance() or QApplication(sys.argv[:1])
    QDialog.exec = lambda self, *a: 0
    QMenu.exec = lambda self, *a, **k: None
    QProgressDialog.exec = lambda self, *a: 0
    for cls in (QFileDialog, QInputDialog, QColorDialog):
        cls.exec = lambda self, *a: 0
    shown = _QT.setdefault("boxes", [])

    def box_exec(self, *a):
        shown.append(("box", (self.text() or "")[:200]))
        return 0
    QMessageBox.exec = box_exec

    def box(kind):
        def f(*a, **k):
            shown.append((kind, " ".join(str(x) for x in a[1:3])))
            return QMessageBox.No if kind == "question" else 0
        return staticmethod(f)
    for n in ("information", "warning", "critical", "about", "question"):
        setattr(QMessageBox, n, box(n))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    for n in ("getText", "getItem", "getInt", "getDouble"):
        setattr(QInputDialog, n, staticmethod(lambda *a, **k: (None, False)))
    QColorDialog.getColor = staticmethod(lambda *a, **k: QColor())
    errs = _QT.setdefault("errors", [])

    class Catch(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                errs.append(self.format(record)[:300])
    h = Catch()
    h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(h)
    _QT["app"] = app
    return app


def window():
    if "win" in _QT:
        return _QT["win"]
    headless_app()
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    _QT["win"] = w
    _QT["app"].processEvents()
    return w


def pump(n=3):
    for _ in range(n):
        _QT["app"].processEvents()


def close_all(win):
    from app.main_window import DocTab
    for i in reversed(range(win.tabs.count())):
        t = win.tabs.widget(i)
        if isinstance(t, DocTab):
            try:
                t.view.dirty = False
            except Exception:                             # noqa: BLE001
                pass
            win.close_tab(i)
    pump()


# ---------------------------------------------------------- made-up PDFs
def plain_pdf(path, pages=1, w=612, h=792, text="TEST SHEET"):
    import fitz
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=w, height=h)
        p.insert_text((36, 60), f"{text} A-{i + 1:03d}", fontsize=14)
        p.draw_line((36, 80), (min(w, 576), 80))
    d.save(path)
    d.close()
    return path


# ============================================================== sections
@section
def hostile():
    """Damaged, odd and locked files open without a crash or a hang."""
    import fitz
    win = window()
    d = tmp()
    good = plain_pdf(os.path.join(d, "good.pdf"), 3)
    raw = open(good, "rb").read()
    cases = {}

    def put(name, data):
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(data)
        cases[name] = p
    put("empty.pdf", b"")
    put("random.pdf", os.urandom(50_000))
    put("half.pdf", raw[: len(raw) // 2])
    put("header_only.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    put("garbage_tail.pdf", raw + os.urandom(20_000))
    put("no_xref.pdf", raw.replace(b"xref", b"xxxx").replace(
        b"startxref", b"startxxxx"))
    put("png_named_pdf.pdf", b"\x89PNG\r\n\x1a\n" + os.urandom(1000))
    put("text_named_pdf.pdf", b"hello, I am not a PDF\n" * 100)
    # locked with a password to open
    x = fitz.open(good)
    p = os.path.join(d, "user_pw.pdf")
    x.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o-x",
           user_pw="u-x")
    x.close()
    cases["user_pw.pdf"] = p
    # owner-only lock (opens, can't change)
    x = fitz.open(good)
    p = os.path.join(d, "owner_only.pdf")
    x.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o-x",
           user_pw="", permissions=fitz.PDF_PERM_PRINT)
    x.close()
    cases["owner_only.pdf"] = p
    cases["huge_page.pdf"] = plain_pdf(os.path.join(d, "huge_page.pdf"),
                                       1, 14400, 14400)
    cases["tiny_page.pdf"] = plain_pdf(os.path.join(d, "tiny_page.pdf"),
                                       1, 3, 3, text="x")
    x = fitz.open(good)
    for i, r in enumerate((90, 180, 270)):
        x[i].set_rotation(r)
    p = os.path.join(d, "rotated.pdf")
    x.save(p)
    x.close()
    cases["rotated.pdf"] = p
    uni = os.path.join(d, "Plan – Ünïcödé 東京 #1 & (copy).pdf")
    cases["unicode name"] = plain_pdf(uni, 1)
    deep = d
    while len(deep) < 300:
        deep = os.path.join(deep, "a_very_long_folder_name_for_testing")
    try:
        os.makedirs("\\\\?\\" + deep if os.name == "nt" else deep,
                    exist_ok=True)
        lp = os.path.join(deep, "long_path_sheet.pdf")
        plain_pdf(("\\\\?\\" + lp) if os.name == "nt" else lp, 1)
        cases["path over 260"] = lp
    except Exception as ex:                               # noqa: BLE001
        print("  (could not make a long path:", ex, ")")
    # many objects: 1 page, 30,000 tiny vector segments + 3,000 words
    x = fitz.open()
    pg = x.new_page(width=2592, height=1728)
    sh = pg.new_shape()
    rnd = random.Random(1)
    for _ in range(30000):
        a = (rnd.uniform(0, 2592), rnd.uniform(0, 1728))
        sh.draw_line(a, (a[0] + rnd.uniform(-20, 20),
                         a[1] + rnd.uniform(-20, 20)))
    sh.finish(width=0.3)
    sh.commit()
    for i in range(3000):
        pg.insert_text((rnd.uniform(0, 2500), rnd.uniform(10, 1720)),
                       f"W{i}", fontsize=4)
    p = os.path.join(d, "dense.pdf")
    x.save(p)
    x.close()
    cases["dense vector page"] = p

    for name, path in cases.items():
        _open_one(win, name, path)
    close_all(win)


def _open_one(win, name, path):
    errs = _QT["errors"]
    boxes = _QT["boxes"]
    e0, b0 = len(errs), len(boxes)
    t = time.perf_counter()
    try:
        win.open_path(path)
        pump(5)
        v = win._view
        if v is not None and v.doc is not None and v.doc.page_count:
            v.go_to(v.doc.page_count - 1)
            pump(3)
        ok = True
        msg = ""
    except Exception as ex:                               # noqa: BLE001
        ok, msg = False, repr(ex) + " " + traceback.format_exc(
            ).strip().splitlines()[-2]
    dt = time.perf_counter() - t
    from PySide6.QtWidgets import QApplication, QMessageBox
    for w in QApplication.topLevelWidgets():     # boxes shown with show()
        if isinstance(w, QMessageBox) and w.isVisible():
            boxes.append(("box", (w.text() or "")[:200]))
            w.close()
    told = [b for b in boxes[b0:]]
    v = win._view
    opened = v is not None and getattr(v, "doc", None) is not None
    pages = v.doc.page_count if opened else 0
    print(f"    result: {'opened, %d page(s)' % pages if opened else 'no tab'}"
          f", {len(told)} message(s)")
    if ok and not opened and not told and name not in ("user_pw.pdf",):
        check(f"open {name}: says why it didn't open", False,
              "no tab and no message")
    check(f"open {name}: no crash", ok, msg)
    check(f"open {name}: under 30 s", dt < 30, f"{dt:.1f}s")
    if errs[e0:]:
        print("    logged errors:", errs[e0:][:3])
    if told:
        print("    told the user:", told[:2])
    close_all(win)


@section
def bigdoc():
    """A 2,000-sheet set and a sheet with 15,000 takeoff marks."""
    import fitz
    from app import annotate, estimate
    win = window()
    d = tmp()
    p = plain_pdf(os.path.join(d, "big_set.pdf"), 2000, 2592, 1728)
    t = time.perf_counter()
    win.open_path(p)
    pump(5)
    check("2000 sheets open under 20 s", time.perf_counter() - t < 20,
          f"{time.perf_counter() - t:.1f}s")
    v = win._view
    check("2000 sheets: all pages there",
          v is not None and v.doc.page_count == 2000,
          str(v and v.doc.page_count))
    t = time.perf_counter()
    for i in (1999, 0, 1000, 1500, 3):
        v.go_to(i)
        pump(2)
    check("jump around 2000 sheets under 10 s",
          time.perf_counter() - t < 10, f"{time.perf_counter() - t:.1f}s")
    t = time.perf_counter()
    hits = 0
    for i in range(v.doc.page_count):
        hits += len(v.doc[i].search_for("A-1999"))
    check("search 2000 sheets", hits >= 1 and time.perf_counter() - t < 60,
          f"{hits} hits, {time.perf_counter() - t:.1f}s")
    close_all(win)

    # 15,000 marks on one page, then estimate and save/reopen
    doc = fitz.open()
    doc.new_page(width=2592, height=1728)
    rnd = random.Random(2)
    t = time.perf_counter()
    for i in range(15000):
        x, y = rnd.uniform(20, 2500), rnd.uniform(20, 1650)
        if i % 3 == 0:
            op = annotate.new_op("add_count", 0, pt=[x, y], measure={
                "type": "count", "value": 1, "unit": "ea",
                "group": f"Count {i % 40}"})
        elif i % 3 == 1:
            op = annotate.new_op("add_line", 0, pts=[[x, y], [x + 30, y]],
                                 measure={"type": "length", "value": 3.0,
                                          "unit": "ft",
                                          "group": f"Line {i % 40}"})
        else:
            op = annotate.new_op("add_polygon", 0, pts=[
                [x, y], [x + 20, y], [x + 20, y + 20], [x, y + 20]],
                measure={"type": "area", "value": 4.0, "unit": "sq ft",
                         "group": f"Area {i % 40}"})
        annotate.apply_op(doc, op, fresh=True)
        if i % 1000 == 999:
            print(f"  {i + 1} marks: {time.perf_counter() - t:.1f}s",
                  flush=True)
            if time.perf_counter() - t > 150:
                break
    check("15,000 marks added under 120 s", time.perf_counter() - t < 120,
          f"{time.perf_counter() - t:.1f}s")
    for g in range(40):
        estimate.set_price(doc, f"Area {g}", "area", "sq ft",
                           unit_cost=1.125 + g)
    t = time.perf_counter()
    rows = estimate.lines(doc)
    check("estimate of 15,000 marks under 30 s",
          time.perf_counter() - t < 30, f"{time.perf_counter() - t:.1f}s")
    n = sum(r["count"] for r in rows)
    placed = len(list(doc[0].annots()))
    check("estimate counts every mark", n == placed, f"{n} of {placed}")
    tot = [r for r in rows if r["name"].startswith("Area ")]
    want = sum(round(r["adjusted"], 2) * (1.125 + int(r["name"][5:]))
               for r in tot)
    got = sum(r["total"] for r in tot)
    check("area totals match quantity x cost (to 1 cent per line)",
          abs(got - want) <= 0.01 * len(tot) + 1e-6, f"{got} vs {want}")
    out = os.path.join(d, "marks.pdf")
    t = time.perf_counter()
    doc.save(out, garbage=1)
    doc.close()
    win.open_path(out)
    pump(5)
    check("15,000-mark sheet saves and reopens under 60 s",
          time.perf_counter() - t < 60, f"{time.perf_counter() - t:.1f}s")
    v = win._view
    check("all marks still there after reopen",
          v is not None and len(list(v.doc[0].annots())) >= placed,
          str(v and len(list(v.doc[0].annots()))))
    close_all(win)


def _junk(rnd, depth=0):
    pick = rnd.random()
    if depth > 2 or pick < 0.25:
        return rnd.choice([None, True, -1, 0, 1e308, -1e308, float("nan"),
                           float("inf"), 2 ** 70, "", "x" * 5000, "\x00",
                           "Ü東", "<script>", "../../x", 3.5, -0.0, [], {}])
    if pick < 0.5:
        return [_junk(rnd, depth + 1) for _ in range(rnd.randint(0, 6))]
    if pick < 0.7:
        return [[rnd.uniform(-1e6, 1e6), rnd.uniform(-1e6, 1e6)]
                for _ in range(rnd.randint(0, 50))]
    return {rnd.choice(["rect", "pt", "pts", "text", "color", "measure",
                        "value", "group", "ref", "name", "data", "width",
                        "size", "unit", "type", "xref", "id", "fields"]):
            _junk(rnd, depth + 1) for _ in range(rnd.randint(0, 6))}


@section
def fuzzops():
    """20,000 malformed ops (what a bad peer could send): nothing escapes
    apply_op, and the file still saves and reopens."""
    import fitz
    from app import annotate
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    rnd = random.Random(3)
    kinds = sorted(annotate.KINDS) + ["bogus", "", None, 5]
    escaped = []
    good = 0
    t = time.perf_counter()
    for i in range(20000):
        payload = _junk(rnd) if rnd.random() < 0.6 else {
            "rect": [rnd.uniform(-50, 700), rnd.uniform(-50, 900),
                     rnd.uniform(-50, 700), rnd.uniform(-50, 900)],
            "pt": [rnd.uniform(-50, 700), rnd.uniform(-50, 900)],
            "pts": [[rnd.uniform(0, 600), rnd.uniform(0, 800)]
                    for _ in range(rnd.randint(0, 8))],
            "text": rnd.choice(["", "x", "Ü東" * 50, "\x00\x01", "(a)\\"]),
            "measure": _junk(rnd), "color": _junk(rnd)}
        op = {"kind": rnd.choice(kinds),
              "page": rnd.choice([0, 1, 2, -1, 3, None, "0", 1.0, 2 ** 40]),
              "id": rnd.choice([f"f{i}", "", None, "bad id ()", 5]),
              "payload": payload if isinstance(payload, dict) else
              rnd.choice([payload, None])}
        try:
            if annotate.apply_op(doc, op):
                good += 1
        except Exception as ex:                           # noqa: BLE001
            if len(escaped) < 8:
                escaped.append(f"{op['kind']}: {ex!r}"[:200])
            else:
                escaped.append("")
        if time.perf_counter() - t > 200:
            print("  (stopped at", i, "ops: time)")
            break
    check("no exception escapes apply_op", not escaped,
          f"{len(escaped)} escaped, e.g. {escaped[:4]}")
    print(f"  ({good} junk ops changed the document)")
    p = os.path.join(tmp(), "fuzzed.pdf")
    try:
        doc.save(p, garbage=1)
        doc.close()
        r = fitz.open(p)
        n = sum(len(list(r[i].annots())) for i in range(r.page_count))
        for i in range(r.page_count):
            r[i].get_pixmap(dpi=30)
        r.close()
        check("fuzzed file saves, reopens and draws", True)
        print(f"  ({n} markups after reopen)")
    except Exception as ex:                               # noqa: BLE001
        check("fuzzed file saves, reopens and draws", False, repr(ex))
    # set_jobdata from a peer: non-dict JSON, oversize, wrong name
    d2 = fitz.open()
    d2.new_page()
    for data, want in ((json.dumps({"a": 1}), True), ("5", False),
                       ("[]", False), ("null", False), ("{bad", False),
                       ("{" + '"k":"' + "x" * 1_100_000 + '"}', False)):
        ok = annotate.apply_op(d2, annotate.new_op(
            "set_jobdata", 0, file="quantisheet_ada.json", data=data))
        check(f"set_jobdata {data[:12]!r}... accepted={want}", ok == want,
              f"got {ok}")
    ok = annotate.apply_op(d2, annotate.new_op(
        "set_jobdata", 0, file="evil.exe", data="{}"))
    check("set_jobdata refuses a name not on the list", not ok)


@section
def money():
    """Half-up to the cent everywhere: c2 against exact decimal maths on
    300,000 values, and odd inputs."""
    from decimal import Decimal, ROUND_HALF_UP
    from app import dmoney
    rnd = random.Random(4)
    bad = []
    for i in range(300000):
        mag = rnd.choice([1, 10, 1000, 1e5, 1e7, 1e9, 1e11])
        cents_ = rnd.randint(0, int(mag * 100))
        third = rnd.choice([0, 5, 5, 5, rnd.randint(0, 9)])
        s = f"{cents_ // 100}.{cents_ % 100:02d}{third}"
        if rnd.random() < 0.3:
            s = "-" + s
        v = float(s)
        exact = float(Decimal(s).quantize(Decimal("0.01"), ROUND_HALF_UP))
        got = dmoney.c2(v)
        if got != exact and len(bad) < 10:
            bad.append((s, got, exact))
    check("c2 matches exact half-up on 300,000 typed amounts", not bad,
          str(bad[:5]))
    # arithmetic results: a + b, a * pct (what the program actually does)
    bad = []
    for i in range(100000):
        a = rnd.randint(0, 10**9) / 100
        pct = rnd.choice([5, 7.5, 10, 12.5, 15, 33.333, 2.25, 0.5])
        v = a * pct / 100
        exact = float((Decimal(repr(a)) * Decimal(repr(pct)) / 100)
                      .quantize(Decimal("0.01"), ROUND_HALF_UP))
        got = dmoney.c2(v)
        if abs(got - exact) > 0.0051 and len(bad) < 10:
            bad.append((a, pct, got, exact))
        elif got != exact and len(bad) < 10:
            bad.append((a, pct, got, exact))
    check("c2(amount x percent) is the hand-rounded cent", not bad,
          str(bad[:5]))
    odd = {}
    for v in (None, "", "abc", "1,000.125", "$1,000.125", "(1.125)",
              float("nan"), float("inf"), -float("inf"), 1e300, True,
              "1e400", "NaN", " 3.005 ", Decimal("2.675"), 10**20):
        try:
            odd[repr(v)[:20]] = dmoney.c2(v)
        except (ValueError, ArithmeticError) as ex:
            odd[repr(v)[:20]] = f"refused ({type(ex).__name__})"
        except Exception as ex:                           # noqa: BLE001
            odd[repr(v)[:20]] = f"CRASH {ex!r}"
    crashes = {k: x for k, x in odd.items() if str(x).startswith("CRASH")}
    check("c2 on odd input refuses or answers, never crashes",
          not crashes, str(crashes))
    nonfinite = {k: x for k, x in odd.items()
                 if isinstance(x, float) and not math.isfinite(x)
                 and k not in ("nan", "inf", "-inf")}
    check("c2 never turns text into nan/inf", not nonfinite,
          str(nonfinite))
    print("  ", odd)


@section
def numbers():
    """Number fields refuse junk instead of guessing."""
    from app.pm import widgets
    from app import money as m
    rnd = random.Random(5)
    junk = ["nan", "inf", "-inf", "1e400", "1e13", "1.000,50", "1,2,3",
            "--5", "5-", "1..2", "0x10", "١٢٣", "１２３", "1 000", "∞",
            "$", "()", "(", "1e-400", "+-1", ".", ",", "1,,000", "1_000",
            "NaN", "Infinity", "\x00", "9" * 400, "1,000.50.25"]
    for _ in range(3000):
        junk.append("".join(rnd.choice("0123456789.,-+()$e E\t")
                            for _ in range(rnd.randint(1, 12))))
    crashes, nonfinite, big = [], [], []
    for t in junk:
        try:
            v = widgets.read_number(t)
        except Exception as ex:                           # noqa: BLE001
            crashes.append((t, repr(ex)))
            continue
        if v is not None and not math.isfinite(v):
            nonfinite.append((t, v))
        if v is not None and abs(v) > widgets.MAX_NUMBER:
            big.append((t, v))
    check("read_number never crashes", not crashes, str(crashes[:5]))
    check("read_number never returns nan/inf", not nonfinite,
          str(nonfinite[:5]))
    check("read_number caps at a trillion", not big, str(big[:5]))
    for t, want in (("1,250.50", 1250.5), ("(12.5)", -12.5),
                    ("$1,000", 1000.0), ("0.125", 0.125)):
        check(f"read_number {t!r} = {want}", widgets.read_number(t) == want,
              str(widgets.read_number(t)))
    crashes = []
    for t in junk[:400]:
        try:
            m._num(t)
        except (ValueError, m.BillingError):
            pass
        except Exception as ex:                           # noqa: BLE001
            crashes.append((t, repr(ex)))
    check("billing number reader refuses junk cleanly", not crashes,
          str(crashes[:5]))


@section
def billing():
    """A 400-line schedule of values over 12 pay apps: every page adds up
    to the cent, extremes are refused."""
    import fitz
    from app import money as m
    rnd = random.Random(6)
    d = fitz.open()
    d.new_page()
    m.set_info(d, 10, 5, project="Example Tower", owner="Example Owner",
               contractor="Example Builders")
    lines_ = [{"desc": f"Line {i} " + "Ü" * (i % 3),
               "scheduled": rnd.randint(1, 50_000_000) / 100}
              for i in range(400)]
    t = time.perf_counter()
    m.set_sov(d, lines_)
    print(f"  set_sov 400 lines: {time.perf_counter() - t:.2f}s", flush=True)
    items = [r["item"] for r in m.sov(d)]
    done = {it: 0.0 for it in items}
    sched = {r["item"]: r["scheduled"] for r in m.sov(d)}
    bad = []
    paid = []
    last6 = 0.0
    for k in range(12):
        t1 = time.perf_counter()
        no = m.new_pay_app(d, f"2026-{k + 1:02d}-28")
        t_new = time.perf_counter() - t1
        t1 = time.perf_counter()
        for it in rnd.sample(items, 150):
            left = sched[it] - done[it]
            if left <= 0:
                continue
            w = round(rnd.uniform(0, left), 2)
            stored = round(rnd.uniform(0, max(0.0, left - w)) * 0.1, 2)
            m.set_progress(d, no, it, work=w, stored=stored)
            done[it] += w + stored
        t_set = time.perf_counter() - t1
        t1 = time.perf_counter()
        v = m.compute(d, no)
        t_cmp = time.perf_counter() - t1
        tot, rows = v["totals"], v["rows"]
        for key in ("retainage", "this", "stored", "previous", "completed"):
            s = round(sum(r[key] for r in rows), 2)
            if abs(s - round(tot[key], 2)) > 0.001:
                bad.append((k + 1, key, s, tot[key]))
        g = v["g702"]
        if abs(g["5"] - tot["retainage"]) > 0.001 or \
                abs(g["4"] - tot["completed"]) > 0.001 or \
                abs(g["6"] - round(g["4"] - g["5"], 2)) > 0.001:
            bad.append((k + 1, "g702", g["4"], g["5"], g["6"]))
        paid.append(g["8"])
        last6 = g["6"]
        for r in rows:
            for key, val in r.items():
                if isinstance(val, float) and not math.isfinite(val):
                    bad.append((k + 1, "row", key, val))
        if k == 5 and os.environ.get("QS_TORTURE_PROFILE"):
            import cProfile
            import pstats
            raw = m.embfiles.get(d, m.FILE)
            print(f"  billing data: {len(raw) / 1e6:.2f} MB, "
                  f"{d.xref_length()} objects", flush=True)
            pr = cProfile.Profile()
            pr.enable()
            for it in items[:10]:
                m.set_progress(d, no, it, work=0.0)
            pr.disable()
            pstats.Stats(pr).sort_stats("tottime").print_stats(12)
        t1 = time.perf_counter()
        m.certify(d, no)
        print(f"  app {k + 1}: new {t_new:.2f}s, 150 entries {t_set:.2f}s "
              f"({t_set / 150 * 1000:.0f} ms each), compute {t_cmp:.2f}s, "
              f"certify {time.perf_counter() - t1:.2f}s", flush=True)
        if time.perf_counter() - t > 200:
            print("  (stopped: time)", flush=True)
            break
    check("12 pay apps x 400 lines: rows add up to the totals", not bad,
          str(bad[:6]))
    check("payments due over 12 apps add up to the last earned-less-"
          "retainage", abs(round(sum(paid), 2) - last6) < 0.001,
          f"{round(sum(paid), 2)} vs {last6}")
    check("12 pay apps x 400 lines under 120 s",
          time.perf_counter() - t < 120, f"{time.perf_counter() - t:.1f}s")
    out = os.path.join(tmp(), "payapp.pdf")
    t = time.perf_counter()
    m.pay_app_pdf(d, m.pay_apps(d)[-1]["no"], out)
    m.pay_app_xlsx(d, m.pay_apps(d)[-1]["no"], out[:-4] + ".xlsx")
    check("pay app PDF + Excel for 400 lines", os.path.getsize(out) > 1000,
          f"{time.perf_counter() - t:.1f}s")
    # extremes
    d2 = fitz.open()
    d2.new_page()
    m.set_info(d2, 10, 10, project="X", owner="Y", contractor="Z")
    refused = {}
    for val in (float("nan"), float("inf"), -5.0, 1e13, "abc", None,
                10**20):
        try:
            m.set_sov(d2, [{"desc": "A", "scheduled": val}])
            refused[repr(val)] = "accepted " + repr(m.sov(d2)[0][
                "scheduled"])
        except (ValueError, m.BillingError) as ex:
            refused[repr(val)] = "refused"
        except Exception as ex:                           # noqa: BLE001
            refused[repr(val)] = f"CRASH {ex!r}"
    print("   scheduled value:", refused)
    check("schedule refuses nan/inf/huge cleanly", not any(
        str(x).startswith("CRASH") or ("accepted" in x and ("nan" in x or
                                                           "inf" in x))
        for x in refused.values()), str(refused))
    m.set_sov(d2, [{"desc": "A", "scheduled": 100.0}])
    it = m.sov(d2)[0]["item"]
    no = m.new_pay_app(d2, "2026-01-31")
    res = {}
    for w in (150.0, -10.0, float("nan"), 100.004, 1e15):
        try:
            m.set_progress(d2, no, it, work=w)
            v = m.compute(d2, no)
            res[repr(w)] = f"accepted, row work {v['rows'][0]}"[:90]
        except (ValueError, m.BillingError):
            res[repr(w)] = "refused"
        except Exception as ex:                           # noqa: BLE001
            res[repr(w)] = f"CRASH {ex!r}"
    print("   progress:", res)
    check("progress entry never crashes",
          not any(str(x).startswith("CRASH") for x in res.values()),
          str(res))
    check("progress can't be nan", "nan" not in str(res.get("nan", "")) or
          res.get("nan") == "refused", str(res.get("nan")))


@section
def estimate():
    """3,000 takeoff groups priced, a bid on top: lines add to totals,
    export cells can't run formulas."""
    import fitz
    from app import estimate as est, bidbuild, safecell
    import estimate_helpers as eh
    rnd = random.Random(7)
    doc = eh.blank_doc()
    names = []
    t = time.perf_counter()
    for i in range(3000):
        if i % 250 == 0:
            print(f"  {i} groups: {time.perf_counter() - t:.1f}s",
                  flush=True)
            if time.perf_counter() - t > 150:
                break
        g = f"G{i:04d}"
        names.append(g)
        eh.area(doc, g, rnd.randint(1, 40), rnd.randint(1, 40),
                x0=rnd.uniform(0, 1000), y0=rnd.uniform(0, 600))
        est.set_price(doc, g, "area", "sq ft",
                      unit_cost=rnd.choice([1.125, 0.005, 2.675, 1e-4,
                                            33.335, 999999.995]))
    evil = ["=HYPERLINK(\"http://x\",\"y\")", "+1+1", "-2+3", "@SUM(A1)",
            "\t=1", "\r=1", "=cmd|' /C calc'!A0"]
    for e in evil:
        eh.area(doc, e, 1, 1)
        est.set_price(doc, e, "area", "sq ft", unit_cost=1)
    t = time.perf_counter()
    rows = est.lines(doc)
    check("3,000 priced groups estimate under 60 s",
          time.perf_counter() - t < 60, f"{time.perf_counter() - t:.1f}s")
    bad = [r["name"] for r in rows
           if abs(r["total"] - round(r["total"], 2)) > 1e-9
           or not math.isfinite(r["total"])]
    check("every line total is whole cents", not bad, str(bad[:5]))
    p = os.path.join(tmp(), "est.csv")
    est.export_csv(doc, p)
    import csv
    cells = [c for row in csv.reader(open(p, encoding="utf-8-sig"))
             for c in row]
    live = [c for c in cells if c[:1] in ("=", "+", "-", "@", "\t", "\r")
            and not _is_number(c)]
    check("CSV export: no cell starts like a formula", not live,
          str(live[:5]))
    # bid build-up on 5,000 trades
    bl = [{"key": f"k{i}", "trade": f"T{i % 60}",
           "direct": rnd.randint(0, 10**8) / 100,
           "material": rnd.randint(0, 10**7) / 100} for i in range(5000)]
    t = time.perf_counter()
    b = bidbuild.build(bl, {"overhead": 12.5, "profit": 7.5, "bond": 1.0,
                            "tax": 8.25})
    s = round(sum(x["price"] for x in b["lines"]), 2)
    check("bid of 5,000 lines: lines add to the total to the cent",
          abs(s - b["total"]) < 0.001, f"{s} vs {b['total']}")
    check("bid of 5,000 lines under 20 s", time.perf_counter() - t < 20,
          f"{time.perf_counter() - t:.1f}s")
    for data in ({"overhead": float("nan")}, {"overhead": "abc"},
                 {"overhead": 1e300}, {"overhead": -100}):
        try:
            b2 = bidbuild.build(bl[:5], data)
            ok = math.isfinite(b2["total"])
            check(f"bid with {data} gives a finite total or refuses", ok,
                  str(b2["total"]))
        except (ValueError, ArithmeticError):
            check(f"bid with {data} refused", True)
        except Exception as ex:                           # noqa: BLE001
            check(f"bid with {data} doesn't crash", False, repr(ex))
    _ = safecell


def _is_number(c):
    try:
        float(c.replace(",", ""))
        return True
    except ValueError:
        return False


@section
def undo():
    """3,000 single edits, undo every one, redo every one."""
    win = window()
    d = tmp()
    p = plain_pdf(os.path.join(d, "undo.pdf"), 3)
    win.open_path(p)
    pump(3)
    v = win._view
    rnd = random.Random(8)
    t = time.perf_counter()
    N = 3000
    for i in range(N):
        if i % 250 == 0:
            print(f"  {i} edits: {time.perf_counter() - t:.1f}s", flush=True)
            if time.perf_counter() - t > 120:
                N = i
                break
        pg = i % 3
        x, y = rnd.uniform(20, 560), rnd.uniform(20, 740)
        v.apply_marks([(pg, "add_rect", {"rect": [x, y, x + 15, y + 10]})])
    t_add = time.perf_counter() - t

    def count():
        return sum(len(list(v.doc[i].annots())) for i in range(3))
    n_full = count()
    check(f"{N} edits applied", n_full == N, str(n_full))
    t = time.perf_counter()
    k = 0
    while v.history.can_undo() and k < N + 10:
        win.undo()
        k += 1
        if k % 50 == 0:
            print(f"  {k} undos: {time.perf_counter() - t:.1f}s", flush=True)
            if time.perf_counter() - t > 60:
                break
    pump()
    t_undo = time.perf_counter() - t
    left = count()
    print(f"  (add {t_add:.1f}s, {k} undos {t_undo:.1f}s, "
          f"{left} marks left; undo keeps {v.history.limit} steps)")
    check("undo takes back every step it kept", left == N - k,
          f"{left} left after {k} undos")
    t = time.perf_counter()
    r = 0
    while v.history.can_redo() and r < N + 10:
        win.redo()
        r += 1
    pump()
    check("redo brings every undone edit back", count() == n_full,
          f"{count()} vs {n_full}")
    check("undo + redo of 3,000 edits under 120 s",
          t_undo + time.perf_counter() - t < 120,
          f"{t_undo + time.perf_counter() - t:.1f}s")
    close_all(win)


@section
def store():
    """Eight threads write Project Manager records while saves run; the
    file on disk holds every record and is valid."""
    import threading
    from app.pm import store as st
    folder = os.path.join(tmp(), "job")
    os.makedirs(folder, exist_ok=True)
    s = st.ProjectStore(folder)
    errors = []

    def worker(k):
        try:
            for i in range(300):
                s.save_record("rfi", {"subject": f"T{k}-{i}",
                                      "notes": ["a"] * (i % 7),
                                      "body": "Ü東" * (i % 50)})
                s.save()
                if i % 50 == 0:
                    s.flush(force=True)
        except Exception as ex:                           # noqa: BLE001
            errors.append(repr(ex))
    ts = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    t = time.perf_counter()
    for x in ts:
        x.start()
    for x in ts:
        x.join(240)
    s.flush(force=True)
    check("no error from 8 writers", not errors, str(errors[:3]))
    check("2,400 records written under 120 s",
          time.perf_counter() - t < 120, f"{time.perf_counter() - t:.1f}s")
    s2 = st.ProjectStore(folder)
    n = len(s2.list("rfi"))
    check("all 2,400 records on disk after reload", n == 2400, str(n))
    check("file not marked damaged", not s2.damaged, s2.damaged)
    nums = [r.get("number") or r.get("no") for r in s2.list("rfi")]
    nums = [x for x in nums if x not in (None, "")]
    check("record numbers unique", len(nums) == len(set(nums)),
          f"{len(nums)} numbers, {len(set(nums))} unique")
    # damaged file: moved aside, not lost
    with open(s2.path, "w", encoding="utf-8") as f:
        f.write('{"records": {"rfi": ')
    s3 = st.ProjectStore(folder)
    check("damaged project file is set aside and reported",
          bool(s3.damaged) and os.path.exists(s3.damaged), s3.damaged)


# ================================================================ runner
def run_section(name):
    t = time.perf_counter()
    try:
        SECTIONS[name]()
    except Exception as ex:                               # noqa: BLE001
        RESULTS.append(("ERROR", name, repr(ex)))
        print(f"ERROR section {name}: {ex!r}")
        traceback.print_exc()
    n = {k: sum(1 for r in RESULTS if r[0] == k)
         for k in ("PASS", "FAIL", "ERROR")}
    print(f"SECTION {name}: {n['PASS']} passed, {n['FAIL']} failed, "
          f"{n['ERROR']} errors ({time.perf_counter() - t:.0f}s)",
          flush=True)
    return 0 if not (n["FAIL"] or n["ERROR"]) else 1


def main(argv):
    if "--list" in argv:
        for k, f in SECTIONS.items():
            print(f"{k}: {f.__doc__.splitlines()[0]}")
        return 0
    if "--prof" in argv:
        os.environ["QS_TORTURE_PROFILE"] = "1"
        argv = [a for a in argv if a != "--prof"]
    if argv[:1] == ["--one"]:
        return run_section(argv[1])
    want = argv[0].split(",") if argv and argv[0] != "all" else \
        list(SECTIONS)
    failed = []
    for name in want:
        print(f"\n===== {name}", flush=True)
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__),
                                "--one", name], timeout=SECTION_LIMIT)
            if r.returncode:
                failed.append(f"{name} (exit {r.returncode})")
        except subprocess.TimeoutExpired:
            print(f"HANG section {name}: over {SECTION_LIMIT}s")
            failed.append(f"{name} (hang)")
    print("\nTORTURE SUMMARY:", "all passed" if not failed else
          "problems in " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
