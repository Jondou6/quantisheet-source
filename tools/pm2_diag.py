"""PyMuPDF 1.28 vs 2.x: reproduce the three failing paths step by step.

    python tools/pm2_diag.py            (from the repo root)
    python tools/pm2_diag.py > pm2_diag_<version>.txt 2>&1

Everything happens in a temporary folder with made-up data (Shelter Cove /
Example Builders...); your settings, forms and jobs are not touched.
Sections:
  F  Form Library fill  (tests/test_formlib.py: ProjectName came back '')
  T  Takeoff items save (tests/test_takeoff_items.py: items lost on save,
     "object is not a stream")
  Q  the same two through the real window (only when PySide6 is there)
Raw PyMuPDF calls come first (what the library itself does), then the
app's own functions (which now have fallbacks - their log lines say when
one was used). Run it under both versions and compare the output.
"""
import contextlib
import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app  # noqa: E402,F401  (maps "fitz" to pymupdf quietly)
import fitz  # noqa: E402

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="    [log %(levelname)s %(name)s] %(message)s")

TMP = tempfile.mkdtemp(prefix="pm2_diag_")
TAKEOFF = "quantisheet_takeoffitems.json"
MONEY = "quantisheet_money.json"


def out(*a):
    print(*a, flush=True)


@contextlib.contextmanager
def step(title):
    out(f"\n--- {title}")
    try:
        yield
    except Exception:                                # noqa: BLE001
        out("    !! EXCEPTION")
        out("    " + traceback.format_exc().replace("\n", "\n    "))


def short(s, n=300):
    s = repr(s) if not isinstance(s, str) else s
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[:n] + f"... ({len(s)} chars)"


def tryit(label, fn):
    try:
        v = fn()
        out(f"    {label}: {short(v)}")
        return v
    except Exception as ex:                          # noqa: BLE001
        out(f"    {label}: !! {type(ex).__module__}.{type(ex).__name__}: "
            f"{ex}")
        out("      " + traceback.format_exc().strip().replace(
            "\n", "\n      "))
        return None


def versions():
    out("=" * 70)
    out("PyMuPDF diagnostics (QuantiSheet)")
    out(f"python {sys.version.split()[0]} on {platform.platform()}")
    for attr in ("__version__", "VersionBind", "VersionFitz", "VersionDate",
                 "pymupdf_version", "mupdf_version"):
        if hasattr(fitz, attr):
            out(f"fitz.{attr} = {getattr(fitz, attr)!r}")
    out(f"module: {getattr(fitz, '__file__', '?')}")
    for c in ("PDF_WIDGET_TYPE_TEXT", "PDF_WIDGET_TYPE_COMBOBOX",
              "PDF_WIDGET_TYPE_CHECKBOX", "PDF_ENCRYPT_KEEP"):
        v = getattr(fitz, c, "<missing>")
        out(f"fitz.{c} = {v!r} ({type(v).__name__})")
    for name in ("xref_is_stream", "xref_stream", "xref_stream_raw",
                 "update_stream", "embfile_add", "embfile_get",
                 "embfile_upd", "embfile_info", "need_appearances",
                 "can_save_incrementally", "is_dirty"):
        out(f"Document.{name}: {'yes' if hasattr(fitz.Document, name) else 'NO'}")
    out(f"temp folder: {TMP}")
    out("=" * 70)


def isolate_settings():
    from app import settings
    settings.DIR = os.path.join(TMP, "cfg")
    settings.PATH = os.path.join(settings.DIR, "settings.json")
    settings._cache = None
    os.makedirs(settings.DIR, exist_ok=True)
    try:
        from app import toolchest
        toolchest.PATH = os.path.join(settings.DIR, "tc.json")
    except Exception:                                # noqa: BLE001
        pass


# ---- dumps -----------------------------------------------------------------

def dump_obj(doc, x, indent="      "):
    try:
        st = doc.xref_is_stream(x)
    except Exception as ex:                          # noqa: BLE001
        st = f"!! {ex}"
    out(f"{indent}xref {x}: is_stream={st}")
    try:
        out(f"{indent}  object: {short(doc.xref_object(x, compressed=True), 400)}")
    except Exception as ex:                          # noqa: BLE001
        out(f"{indent}  object: !! {type(ex).__name__}: {ex}")
    for fn in ("xref_stream_raw", "xref_stream"):
        try:
            data = getattr(doc, fn)(x)
            out(f"{indent}  {fn}: " + ("None" if data is None else
                                       f"{len(data)} bytes {short(bytes(data[:60]))}"))
        except Exception as ex:                      # noqa: BLE001
            out(f"{indent}  {fn}: !! {type(ex).__module__}.{type(ex).__name__}: {ex}")


def dump_embedded(doc, label):
    from app import embfiles
    out(f"  [embedded files: {label}]")
    tryit("doc.name", lambda: doc.name)
    tryit("xref_length", doc.xref_length)
    tryit("is_dirty", lambda: getattr(doc, "is_dirty", "<n/a>"))
    tryit("can_save_incrementally", doc.can_save_incrementally)
    names = tryit("embfile_names()", doc.embfile_names) or []
    tryit("embfile_count()", doc.embfile_count)
    cat = doc.pdf_catalog()
    tryit("catalog /Names", lambda: doc.xref_get_key(cat, "Names"))
    tryit("catalog /Names/EmbeddedFiles",
          lambda: doc.xref_get_key(cat, "Names/EmbeddedFiles"))
    loc = tryit("embfiles._names_array", lambda: embfiles._names_array(doc))
    entries = []
    if loc:
        t, text = doc.xref_get_key(*loc)
        out(f"    names array ({t}): {short(text, 600)}")
        entries = tryit("entries", lambda: embfiles._entries(text)) or []
    for n, v in entries:
        out(f"    entry {n!r} -> {short(v, 200)}")
        import re
        m = re.match(r"(\d+)\s+\d+\s+R", v)
        if m:
            dump_obj(doc, int(m.group(1)))
        for x in embfiles._stream_candidates(doc, v):
            dump_obj(doc, x)
    for n in names:
        out(f"    file {n!r}:")
        tryit("  embfile_info", lambda n=n: {k: w for k, w in
                                            doc.embfile_info(n).items()
                                            if k in ("name", "filename",
                                                     "size", "length",
                                                     "xref", "_ef_xref",
                                                     "desc")})
        tryit("  embfile_get (raw PyMuPDF)",
              lambda n=n: len(doc.embfile_get(n)))
        tryit("  embfiles.get (app, with fallback)",
              lambda n=n: short(embfiles.get(doc, n), 120))


def _raw_v(doc, x):
    return {k: doc.xref_get_key(x, k) for k in ("T", "V", "FT", "Ff",
                                                "Parent", "AS")}


def dump_widgets(doc, label):
    out(f"  [widgets: {label}]")
    try:
        cat = doc.pdf_catalog()
        out(f"    AcroForm: {doc.xref_get_key(cat, 'AcroForm')}")
        t, v = doc.xref_get_key(cat, "AcroForm")
        if t == "xref":
            out(f"    NeedAppearances: "
                f"{doc.xref_get_key(int(v.split()[0]), 'NeedAppearances')}")
    except Exception as ex:                          # noqa: BLE001
        out(f"    AcroForm: !! {ex}")
    for pg in doc:
        try:
            ws = list(pg.widgets() or [])
        except Exception:                            # noqa: BLE001
            out("    widgets(): !! " + traceback.format_exc())
            continue
        for w in ws:
            try:
                out(f"    p{pg.number} xref={w.xref} name={w.field_name!r} "
                    f"type={w.field_type!r}({type(w.field_type).__name__}) "
                    f"type_str={getattr(w, 'field_type_string', '?')!r} "
                    f"value={w.field_value!r}")
                out(f"      raw: {_raw_v(doc, w.xref)}")
                t, p = doc.xref_get_key(w.xref, "Parent")
                if t == "xref":
                    out(f"      parent raw: {_raw_v(doc, int(p.split()[0]))}")
            except Exception:                        # noqa: BLE001
                out("    !! " + traceback.format_exc())


def widget_by_name(doc, name):
    for pg in doc:
        for w in pg.widgets() or []:
            if w.field_name == name:
                return pg, w
    return None, None


def reopen(doc):
    return fitz.open("pdf", doc.tobytes())


# ---- F: form fill ------------------------------------------------------------

def make_form(path, filled=True):
    """The test's change order form: 6 text fields + 1 checkbox."""
    d = fitz.open()
    p = d.new_page()
    p.insert_text((50, 60), "CHANGE ORDER", fontsize=16)
    y = 100
    for name, val in (("ProjectName", "Old Job" if filled else ""),
                      ("OwnerName", ""), ("ContractorName", ""),
                      ("ContractorAddress", ""), ("Date", ""),
                      ("Text20", "keep me" if filled else "")):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(150, y, 450, y + 18)
        w.field_value = val
        p.add_widget(w)
        y += 30
    c = fitz.Widget()
    c.field_name = "Owner"
    c.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    c.rect = fitz.Rect(150, y, 165, y + 15)
    c.field_value = filled
    p.add_widget(c)
    d.save(path)
    d.close()
    return path


def raw_set(doc, name, value):
    pg, w = widget_by_name(doc, name)
    if w is None:
        out(f"    no widget {name!r}")
        return
    out(f"    before: value={w.field_value!r} raw={_raw_v(doc, w.xref)}")
    w.field_value = value
    r = tryit("w.update() returned", w.update)
    out(f"    same Widget object: field_value={w.field_value!r}")
    out(f"    raw after update: {_raw_v(doc, w.xref)}")
    tryit("pg.load_widget(xref).field_value",
          lambda: pg.load_widget(w.xref).field_value)
    tryit("fresh pg.widgets() value",
          lambda: widget_by_name(doc, name)[1].field_value)
    tryit("is_dirty", lambda: getattr(doc, "is_dirty", "<n/a>"))
    return r


def section_forms():
    out("\n" + "#" * 70 + "\n# F  Form Library fill\n" + "#" * 70)
    from app import formlib, money, proposal
    isolate_settings()
    src = os.path.join(TMP, "G701 Change Order.pdf")
    with step("F1 make the test form, save, reopen from disk"):
        make_form(src)
        with fitz.open(src) as d:
            dump_widgets(d, "saved form")
    with step("F2 raw: fresh in-memory copy (no clearing), set ProjectName"):
        d = fitz.open("pdf", open(src, "rb").read())
        raw_set(d, "ProjectName", "Raw Uncleared")
        dump_widgets(reopen(d), "after tobytes + reopen")
    with step("F3 raw: copy, clear like formlib.clear_fields, then set"):
        d = fitz.open("pdf", open(src, "rb").read())
        n = tryit("formlib.clear_fields", lambda: formlib.clear_fields(d))
        dump_widgets(d, f"after clear_fields ({n})")
        raw_set(d, "ProjectName", "Shelter Cove (raw)")
        raw_set(d, "OwnerName", "City of MB (raw)")
        dump_widgets(d, "after raw set, same doc")
        dump_widgets(reopen(d), "after raw set, tobytes + reopen")
    with step("F4 raw: brand-new form never saved, set value"):
        d = fitz.open()
        p = d.new_page()
        w = fitz.Widget()
        w.field_name = "ProjectName"
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(100, 100, 300, 120)
        w.field_value = ""
        p.add_widget(w)
        raw_set(d, "ProjectName", "Fresh Value")
    with step("F5 job data for the fill: money.set_info on a new doc"):
        isolate_settings()
        proposal.save_company({"name": "Example Builders",
                               "address": "100 Sample Rd\nAnytown, SC 29000"})
        tryit("proposal.company()", proposal.company)
        job = fitz.open()
        job.new_page()
        money.set_info(job, project="Shelter Cove", owner="City of MB")
        dump_embedded(job, "job doc after money.set_info")
        tryit("raw embfile_get money",
              lambda: json.loads(job.embfile_get(MONEY))["info"])
        tryit("money.read(job)['info']", lambda: money.read(job)["info"])
        tryit("formlib.job_values(job)", lambda: formlib.job_values(job))
    with step("F6 app: open_copy(clear=True) + fill_from_job"):
        e = formlib.add(src, "AIA Contract Administration", "AIA G701 Test")
        out(f"    entry: fields={e['fields']} filled={e['filled']}")
        doc = formlib.open_copy(e, clear=True)
        dump_widgets(doc, "after open_copy(clear=True)")
        done = tryit("fill_from_job", lambda: formlib.fill_from_job(doc, job))
        out(f"    filled {len(done or {})} field(s)")
        dump_widgets(doc, "after fill_from_job, same doc")
        vals = {w.field_name: w.field_value for w in doc[0].widgets()}
        out(f"    TEST CHECK ProjectName == 'Shelter Cove': "
            f"{vals.get('ProjectName') == 'Shelter Cove'} "
            f"({vals.get('ProjectName')!r})")
        dump_widgets(reopen(doc), "after fill, tobytes + reopen")
        doc2 = formlib.open_copy(e)
        formlib.fill_from_job(doc2, job)
        v2 = {w.field_name: w.field_value for w in doc2[0].widgets()}
        out(f"    no-clear copy keeps 'Old Job': {v2.get('ProjectName')!r}")


# ---- T: takeoff items ------------------------------------------------------

def sample(path):
    import make_sample
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        make_sample.make(path)
    return path


def items_json(*names):
    return json.dumps({"items": [{"name": n, "type": t, "color": None}
                                 for n, t in names]}, indent=1).encode()


def _stream_of(doc, name):
    from app import embfiles
    loc = embfiles._names_array(doc)
    if not loc:
        return None
    ents = embfiles._entries(doc.xref_get_key(*loc)[1])
    i = embfiles._index(doc, ents, name)
    return None if i is None else embfiles._stream_xref(doc, ents[i][1])


def check_file(path, label):
    out(f"  [reopened from disk: {label}]")
    with fitz.open(path) as d:
        dump_embedded(d, label)
        tryit("raw embfile_get(takeoff) decoded",
              lambda: json.loads(d.embfile_get(TAKEOFF)))
        from app import takeoff_items
        tryit("takeoff_items.read (app)", lambda: takeoff_items.read(d))


def raw_variant(tag, update, save_mode, two_saves=False):
    path = sample(os.path.join(TMP, f"plan_{tag}.pdf"))
    doc = fitz.open(path)
    out(f"    opened {os.path.basename(path)}: "
        f"can_save_incrementally={doc.can_save_incrementally()}")
    tryit("embfile_add returned",
          lambda: doc.embfile_add(TAKEOFF, items_json(("Doors", "count")),
                                  filename=TAKEOFF, desc="test"))
    if two_saves:
        doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        out("    (saved incrementally once after embfile_add)")
    x = _stream_of(doc, TAKEOFF)
    out(f"    stream xref of {TAKEOFF}: {x}")
    if x:
        dump_obj(doc, x)
    if update and x:
        data = items_json(("Doors", "count"), ("Carpet", "area"))
        tryit("update_stream(x, data) returned",
              lambda: doc.update_stream(x, data))
        dump_obj(doc, x)
        tryit("live embfile_get after update",
              lambda: json.loads(doc.embfile_get(TAKEOFF)))
    if save_mode == "incremental":
        tryit("save(incremental=True)",
              lambda: doc.save(path, incremental=True,
                               encryption=fitz.PDF_ENCRYPT_KEEP))
        out("    live doc after incremental save:")
        if x:
            dump_obj(doc, x)
        tryit("live embfile_get after save",
              lambda: json.loads(doc.embfile_get(TAKEOFF)))
        doc.close()
    else:
        tmp = path + ".tmp"
        tryit("save(tmp, garbage=1, deflate=True)",
              lambda: doc.save(tmp, garbage=1, deflate=True))
        doc.close()
        os.replace(tmp, path)
    check_file(path, f"{tag}")


def section_takeoff():
    out("\n" + "#" * 70 + "\n# T  Takeoff items survive a save\n" + "#" * 70)
    isolate_settings()
    for tag, update, mode, two in (
            ("A_add_incremental", False, "incremental", False),
            ("B_add_update_incremental", True, "incremental", False),
            ("C_add_update_fullsave", True, "full", False),
            ("D_add_save_update_save", True, "incremental", True)):
        with step(f"T raw variant {tag}"):
            raw_variant(tag, update, mode, two)
    with step("T app: takeoff_items.add x2 on a file-backed doc, "
              "incremental save + check (MainWindow._write logic)"):
        from app import embfiles, takeoff_items
        path = sample(os.path.join(TMP, "plan_app.pdf"))
        doc = fitz.open(path)
        takeoff_items.add(doc, "Doors", "count")
        takeoff_items.add(doc, "Carpet", "area")
        dump_embedded(doc, "live, after two takeoff_items.add")
        tryit("live takeoff_items.read", lambda: takeoff_items.read(doc))
        snap = embfiles.snapshot(doc)
        out(f"    snapshot: {sorted(snap)}")
        doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        bad = tryit("saved_mismatches after incremental save",
                    lambda: embfiles.saved_mismatches(path, snap))
        if bad:
            out("    -> the app would now re-put and save the whole file")
            for n in bad:
                embfiles.put(doc, n, snap[n])
            tmp = path + ".tmp"
            doc.save(tmp, garbage=1, deflate=True)
            doc.close()
            os.replace(tmp, path)
            tryit("saved_mismatches after full save",
                  lambda: embfiles.saved_mismatches(path, snap))
        else:
            doc.close()
        check_file(path, "app path")


# ---- Q: through the real window ---------------------------------------------

def section_qt():
    out("\n" + "#" * 70 + "\n# Q  Through MainWindow (offscreen)\n" + "#" * 70)
    try:
        from PySide6.QtWidgets import (QApplication, QFileDialog,
                                       QInputDialog, QMessageBox)
    except Exception as ex:                          # noqa: BLE001
        out(f"    PySide6 not available ({ex}); skipped")
        return
    isolate_settings()
    qapp = QApplication.instance() or QApplication([])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    for n in ("information", "warning", "about", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Hello", True))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    from app.main_window import MainWindow
    from app import formlib, money, takeoff_items

    def new_win():
        path = sample(os.path.join(TMP, f"qt_{len(os.listdir(TMP))}.pdf"))
        w = MainWindow()
        w.resize(1200, 900)
        assert w.open_path(path), "open_path failed"
        qapp.processEvents()
        return w

    with step("Q1 takeoff: new_item x2, save_file, reopen"):
        w = new_win()
        t = w.takeoff_tree
        t.set_doc(w._view.doc)
        t.new_item("Doors", "count", activate=False)
        t.new_item("Carpet", "area", activate=False)
        dump_embedded(w._view.doc, "live before save")
        ok = tryit("save_file()", w.save_file)
        out(f"    saved to {w._path} ok={ok}")
        with fitz.open(w._path) as d:
            dump_embedded(d, "reopened")
            names = {(i["name"], i["type"]) for i in takeoff_items.items(d)}
        out(f"    TEST CHECK items saved: "
            f"{ {('Doors', 'count'), ('Carpet', 'area')} <= names} {names}")
        w._view.dirty = False
    with step("Q2 form: new_from_form with job info"):
        src = make_form(os.path.join(TMP, "co.pdf"))
        e = formlib.add(src, "AIA", "AIA G701 Qt")
        w = new_win()
        money.set_info(w._view.doc, project="Main St Clinic")
        tryit("money.read(job)['info']['project']",
              lambda: money.read(w._view.doc)["info"]["project"])
        res = tryit("new_from_form", lambda: w.new_from_form((e, True, True)))
        dump_widgets(w._view.doc, "opened form")
        vals = {x.field_name: x.field_value for x in w._view.doc[0].widgets()}
        out(f"    TEST CHECK ProjectName == 'Main St Clinic': "
            f"{vals.get('ProjectName') == 'Main St Clinic'} "
            f"({vals.get('ProjectName')!r}); filled={res and res[1]}")
        w._view.dirty = False


def main():
    versions()
    for sec in (section_forms, section_takeoff, section_qt):
        with step(sec.__name__):
            sec()
    out(f"\ndone. temp files left in {TMP} (delete when finished)")


if __name__ == "__main__":
    try:
        main()
    finally:
        if "--clean" in sys.argv:
            shutil.rmtree(TMP, ignore_errors=True)
