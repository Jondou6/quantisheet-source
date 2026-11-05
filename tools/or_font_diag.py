"""Owner report: why does a key-plan sheet go in as an image?

Reproduces test_owner_report.py::test_i1_i2_key_plan's sheet (a made-up
792 x 612 sheet, text in an embedded Liberation Sans) with 3 photo pins,
runs the same marking / label-lifting / flattening path as
owner_report._show_sheet, and prints at each step: the annotations (type,
info, DA, appearance stream fonts), the page's font resources, and
get_page_fonts(full=True) with embedded / used flags. Then the decision
_sheet_mode makes and why, and a whole report build's sheet_modes.

Made-up data only; writes into a temp folder. Run from the repo root:
    python tools/or_font_diag.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402,F401  (sets sys.modules["fitz"] = pymupdf)
import fitz  # noqa: E402

from app import annotate, settings  # noqa: E402
from app.pm import owner_report as orp  # noqa: E402
from app.pm import owner_report_logs as orl  # noqa: E402


def say(*a):
    print(*a, flush=True)


def head(title):
    say("\n" + "=" * 8 + " " + title + " " + "=" * (60 - len(title)))


def make_sheet(folder):
    path = os.path.join(folder, "C-101 example.pdf")
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    p.draw_rect(fitz.Rect(60, 60, 300, 200), color=(0, 0, 0), width=1)
    p.insert_font(fontname="SheetF", fontfile=os.path.join(
        orl.font_dir(), "LiberationSans-Regular.ttf"))
    p.insert_text((70, 80), "BLDG A - CLUBHOUSE", fontsize=9,
                  fontname="SheetF")
    d.save(path)
    d.close()
    return path


def ops_for(pins):
    return [annotate.new_op("add_count", 0, pt=[float(x), float(y)],
                            n=str(no), color=list(orp.PIN_COLOR),
                            look="takeoff")
            for no, (x, y) in enumerate(pins, 1)]


def key(doc, xref, k):
    try:
        return doc.xref_get_key(xref, k)
    except Exception as e:                         # noqa: BLE001
        return ("error", str(e))


def tf_names(data):
    return sorted(set(re.findall(rb"/([^\s/\[\]<>(){}%]+)\s+[-+\d.]+\s+Tf",
                                 bytes(data or b""))))


def dump_fonts(doc, label):
    say(f"-- get_page_fonts(0, full=True) {label}:")
    try:
        raw = doc.get_page_fonts(0, full=True)
    except Exception as e:                         # noqa: BLE001
        say("   error:", e)
        return
    if not raw:
        say("   (none)")
    for f in raw:
        say("  ", f)
    for xref, ext, typ, base, name, ref, emb, used in orl.font_report(doc, 0):
        say(f"   -> {base!r} res-name {name!r} xref {xref} ext {ext!r} "
            f"type {typ!r} referencer {ref} embedded={emb} used={used}")
    page = doc[0]
    say("-- page Resources/Font:", key(doc, page.xref, "Resources/Font"))
    try:
        c = page.read_contents()
        dos = sorted(set(re.findall(rb"/([^\s/]+)\s+Do", c)))
        say(f"-- page content: {len(c)} bytes, Tf names {tf_names(c)}, "
            f"Do names {dos}")
    except Exception as e:                         # noqa: BLE001
        say("-- page content: error", e)
    refs = sorted({f[6] for f in raw if len(f) > 6 and f[6]})
    for r in refs:
        try:
            st = doc.xref_stream(r) or b""
        except Exception as e:                     # noqa: BLE001
            st = b""
            say(f"   xobject {r}: stream error {e}")
        say(f"   xobject {r}: Resources/Font {key(doc, r, 'Resources/Font')}"
            f", {len(st)} bytes, Tf names {tf_names(st)}")
        say("     stream head:", bytes(st[:300]))


def dump_annots(doc, label):
    page = doc[0]
    say(f"-- annotations {label}:")
    n = 0
    for a in page.annots():
        n += 1
        ap = key(doc, a.xref, "AP/N")
        rect = tuple(round(v, 1) for v in a.rect)
        say(f"   xref {a.xref} type {a.type} rect {rect}")
        say(f"     info {a.info}")
        say(f"     DA {key(doc, a.xref, 'DA')}  PSLabel "
            f"{key(doc, a.xref, 'PSLabel')}  PSColor "
            f"{key(doc, a.xref, 'PSColor')}")
        try:
            say(f"     get_text {a.get_text()!r}")
        except Exception as e:                     # noqa: BLE001
            say("     get_text error", e)
        say(f"     AP/N {ap}")
        if ap[0] == "xref":
            apx = int(ap[1].split()[0])
            st = doc.xref_stream(apx) or b""
            say(f"     AP Resources/Font {key(doc, apx, 'Resources/Font')} "
                f"Tf names {tf_names(st)}")
    if not n:
        say("   (none)")


def marked_copy(sheet, pins, lift):
    src = fitz.open(sheet)
    tmp = fitz.open()
    tmp.insert_pdf(src, from_page=0, to_page=0)
    src.close()
    dump_fonts(tmp, "of the copy before markup")
    own = {a.xref for a in tmp[0].annots()}
    for op in ops_for(pins):
        ok = annotate.apply_op(tmp, op, fresh=True)
        say(f"   apply_op {op['kind']} n={op['payload'].get('n')} -> {ok}")
    dump_annots(tmp, "after markup")
    dump_fonts(tmp, "after markup, before lift / flatten")
    labels = []
    if lift:
        labels = orp._lift_labels(tmp, own)
        say("-- _lift_labels ->", labels)
        dump_annots(tmp, "after lift")
        dump_fonts(tmp, "after lift, before flatten")
    if hasattr(tmp, "bake"):
        tmp.bake(annots=True, widgets=True)
        say("-- baked")
    else:
        say("-- this engine has no Document.bake")
    dump_annots(tmp, "after flatten")
    dump_fonts(tmp, "after flatten")
    return tmp, labels


def main():
    say("PyMuPDF", getattr(fitz, "VersionBind", "?"), "MuPDF",
        getattr(fitz, "VersionFitz", "?"), "python", sys.version.split()[0])
    folder = tempfile.mkdtemp(prefix="or_font_diag_")
    say("work folder", folder)
    sheet = make_sheet(folder)
    pins = [(100 + 60 * i, 150) for i in range(3)]

    head("the report's path (lift labels, flatten)")
    tmp, labels = marked_copy(sheet, pins, lift=True)
    mode, why = orp._sheet_mode(tmp)
    say(f"\n>>> _sheet_mode: {mode} - {why}")
    dump_fonts(tmp, "after _sheet_mode (unused fonts dropped?)")
    tmp.close()

    head("for comparison: no lift (pins left as free text)")
    tmp, _ = marked_copy(sheet, pins, lift=False)
    say(">>> _sheet_mode:", orp._sheet_mode(tmp))
    tmp.close()

    head("whole report build (as test_i1_i2_key_plan)")
    try:
        settings.DIR = os.path.join(folder, "cfg")
        settings.PATH = os.path.join(folder, "cfg", "s.json")
        settings._cache = {"author": "Pat Example"}
        from datetime import date
        from PIL import Image
        from app.pm.store import ProjectStore
        store = ProjectStore(os.path.join(folder, "Job"))
        store.set_setting("number", "26-101")
        rep = orp.new_report(store, date(2026, 10, 20), online=False)
        paths = []
        for i in range(3):
            p = os.path.join(folder, f"ph{i}.jpg")
            Image.effect_noise((400, 300), 40 + i).convert("RGB").save(p)
            paths.append(p)
        orp.add_photos(store, rep, paths)
        for i, ph in enumerate(rep["photos"][:3]):
            ph["pin"] = {"sheet": sheet, "page": 0, "x": 100 + 60 * i,
                         "y": 150}
        rep["options"]["key_plan"] = True
        rep["key_plan"] = {"sheet": sheet, "page": 0,
                           "clip": [0, 0, 600, 400]}
        out = os.path.join(folder, "report.pdf")
        res = orp.build_pdf(store, rep, out)
        say("sheet_modes:", res.get("sheet_modes"))
        say("raster_bytes:", res.get("raster_bytes"))
        say("unembedded_fonts:", res.get("unembedded_fonts"))
        say("warnings:", res.get("warnings"))
        doc = fitz.open(out)
        m = next(m for m in res["page_map"] if m[0] == "key_plan")
        pg = doc[m[1] - 1]
        dots = [d for d in pg.get_drawings() if d.get("fill") and all(
            abs(a - b) <= 0.05 for a, b in zip(d["fill"], orp.PIN_COLOR))]
        say(f"key plan page {m[1]}: images {len(pg.get_images())}, "
            f"pin-colour fills {len(dots)}")
        say("fonts on it:", doc.get_page_fonts(pg.number, full=True))
        doc.close()
    except Exception as e:                         # noqa: BLE001
        import traceback
        traceback.print_exc()
        say("build failed:", e)


if __name__ == "__main__":
    main()
