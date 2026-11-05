"""Safety fixes from the Nov 4 review (QS-001 signed PDFs, QS-002 redaction
left in the saved file). Made-up files only."""
import json
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QMessageBox           # noqa: E402

from app import redaction, savecheck, settings                    # noqa: E402

SECRET = "ZEBRAQUARTZ"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)   # never block
    from app.main_window import MainWindow
    w = MainWindow()
    yield w, tmp_path
    for v in w._all_views():
        v.dirty = False
    w.close()
    w.deleteLater()
    qapp.processEvents()



def _put_lock(lp, rec):
    """Rewrite a lock in place ("w" is refused on a hidden file on
    Windows, and the lock is hidden)."""
    if not os.path.exists(lp):
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        return
    with open(lp, "r+", encoding="utf-8") as f:
        f.seek(0)
        json.dump(rec, f)
        f.truncate()

def _doc(path, text=f"Owner {SECRET} account 4411 notes"):
    d = fitz.open()
    p = d.new_page(width=612, height=792)
    p.insert_text((72, 100), text, fontsize=12)
    p.insert_text((72, 300), "Keep this line", fontsize=12)
    d.save(path)
    return path


def _raw_has(path, word):
    """The word anywhere in the file: every object, streams unpacked."""
    d = fitz.open(path)
    try:
        for x in range(1, d.xref_length()):
            try:
                if d.xref_is_stream(x) and word.encode() in (
                        d.xref_stream(x) or b""):
                    return True
                if word in (d.xref_object(x) or ""):
                    return True
            except Exception:
                continue
    finally:
        d.close()
    return False


# ---- QS-002 -----------------------------------------------------------------

def test_redacted_word_is_gone_from_the_saved_file(win, qapp):
    """Before the fix: the save after a redaction added to the file, and
    the earlier revision still held the redacted word."""
    w, tmp = win
    path = _doc(str(tmp / "redact.pdf"))
    assert w.open_path(path)
    qapp.processEvents()
    v = w._view
    r = v.pg.search_for(SECRET)[0]
    v.commit_rect("add_redact", r + (-2, -2, 2, 2))
    assert SECRET not in v.pg.get_text()
    assert v.needs_full_save and SECRET in v.redacted_words
    assert w.save_file()
    assert not _raw_has(path, SECRET)
    assert w._last_leaks == {}
    assert not v.needs_full_save
    assert "Keep this line" in fitz.open(path)[0].get_text()


def test_leak_check_finds_job_data_and_metadata(tmp_path):
    path = str(tmp_path / "leak.pdf")
    d = fitz.open()
    d.new_page().insert_text((72, 72), "nothing secret here")
    d.embfile_add("quantisheet_notes.json", f'{{"note": "{SECRET}"}}'.encode())
    d.set_metadata({"title": f"Job {SECRET}"})
    d.save(path)
    leaks = redaction.leak_check(path, {SECRET, "secret"},
                                 visible={"secret"})
    assert "embedded file quantisheet_notes.json" in leaks
    assert "document properties" in leaks
    assert all("secret" not in w for w in sum(leaks.values(), []))


def test_words_under_a_box(tmp_path):
    d = fitz.open(_doc(str(tmp_path / "w.pdf")))
    r = d[0].search_for(SECRET)[0]
    assert SECRET in redaction.words_under(d[0], r)
    assert "Keep" not in redaction.words_under(d[0], r)


# ---- QS-001 -----------------------------------------------------------------

def _signed(tmp, monkeypatch):
    pytest.importorskip("pyhanko")
    from app.sign import signer
    monkeypatch.setattr(signer, "DEFAULT_DIR", str(tmp / "keys"))
    src = _doc(str(tmp / "unsigned.pdf"), "Approved for construction")
    out = str(tmp / "signed.pdf")
    signer.sign_pdf(src, out)
    return out


def test_signed_pdf_is_detected(tmp_path, monkeypatch):
    out = _signed(tmp_path, monkeypatch)
    assert savecheck.is_signed(fitz.open(out))
    assert not savecheck.is_signed(fitz.open(_doc(str(tmp_path / "u.pdf"))))


def test_signed_save_in_place_keeps_signature(win, qapp, monkeypatch):
    from app.sign import verify
    w, tmp = win
    out = _signed(tmp, monkeypatch)
    assert w.open_path(out)
    qapp.processEvents()
    v = w._view
    v.commit_rect("add_cloud", fitz.Rect(300, 400, 400, 450))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes))
    assert w.save_file()
    assert asked and "added after the signatures" in asked[0]
    res = [r for r in verify.verify_document(out) if "field" in r]
    assert res and all(r["intact"] for r in res), res
    assert not all(r["covers_whole_file"] for r in res)     # changed after
    # asked once per document
    v.commit_rect("add_cloud", fitz.Rect(300, 500, 400, 550))
    assert w.save_file() and len(asked) == 1


def test_signed_save_as_warns_signatures_wont_carry(win, qapp, monkeypatch):
    w, tmp = win
    out = _signed(tmp, monkeypatch)
    assert w.open_path(out)
    qapp.processEvents()
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    monkeypatch.setattr("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp / "copy.pdf"),
                                                      "")))
    assert not w.save_as()                       # said No: nothing written
    assert asked and "NOT be valid" in asked[0]
    assert not os.path.exists(tmp / "copy.pdf")


# ---- QS-004 version stamp / newer files ------------------------------------------

def _job_pdf(path):
    from app import annotate
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Sheet A1.1")
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft", name='1/4" = 1\'-0"'))
    d.save(path)
    return path


def test_stamp_and_newer_file_refuses_to_save(win, qapp, tmp_path):
    from app import embfiles, jobsafe
    w, tmp = win
    d = fitz.open(_job_pdf(str(tmp / "job.pdf")))
    assert jobsafe.stamp(d)
    assert jobsafe.read_meta(d)["schema"] == jobsafe.SCHEMA
    assert not jobsafe.stamp(d)                    # already stamped
    embfiles.put(d, jobsafe.META, b'{"schema": 99, "app": "9.0.0"}', "job")
    newer = str(tmp / "newer.pdf")
    d.save(newer)
    assert w.open_path(newer)
    qapp.processEvents()
    assert "newer version (9.0.0)" in (w._view.save_blocked or "")
    before = os.path.getsize(newer)
    assert not w.save_file()
    assert os.path.getsize(newer) == before


def test_migrations_run_for_an_older_stamp(monkeypatch):
    from app import embfiles, jobsafe
    d = fitz.open()
    d.new_page()
    embfiles.put(d, jobsafe.META, b'{"schema": 1}', "job")
    ran = []
    monkeypatch.setattr(jobsafe, "SCHEMA", 3)
    monkeypatch.setattr(jobsafe, "MIGRATIONS", {1: lambda doc: ran.append(1),
                                                2: lambda doc: ran.append(2)})
    info = jobsafe.check_open(d)
    assert not info["newer"] and info["migrated"] == [1, 2] and ran == [1, 2]


# ---- QS-003 / QS-031 data lost on the way -------------------------------------------

def test_lost_job_data_is_offered_back(win, qapp):
    from app import jobdata, jobsafe
    w, tmp = win
    path = _job_pdf(str(tmp / "takeoff.pdf"))
    assert w.open_path(path)
    qapp.processEvents()
    w._view.mark_dirty()
    assert w.save_file()
    assert os.path.isfile(jobsafe.backup_path(path))
    w.close_tab(w.tabs.currentIndex())
    # an email gateway strips the attachments
    d = fitz.open(path)
    jobdata.strip(d)
    stripped = str(tmp / "emailed" / "takeoff.pdf")
    os.makedirs(os.path.dirname(stripped))
    d.save(stripped)
    assert w.open_path(stripped)
    v = w._view
    found = w._job_safety_on_open(v, stripped, ask=lambda text: True)
    assert "lost" in found and "quantisheet_scale.json" in found["restored"]
    assert "quantisheet_scale.json" in jobdata.names(v.doc)


# ---- QS-005 two people, one file -----------------------------------------------------

def test_lock_and_changed_on_disk(win, qapp, monkeypatch):
    import json
    from app import jobsafe
    w, tmp = win
    path = _doc(str(tmp / "shared.pdf"))
    monkeypatch.setattr(jobsafe, "is_shared", lambda p: True)
    assert w.open_path(path)
    qapp.processEvents()
    v = w._view
    assert os.path.isfile(jobsafe.lock_path(path))
    assert jobsafe.who_has(path) is None               # it's ours
    # someone else's lock
    other = jobsafe.lock_path(str(tmp / "other.pdf"))
    with open(other, "w") as f:
        json.dump({"user": "pat", "machine": "OFFICE2",
                   "since": __import__("datetime").datetime.now()
                   .isoformat(timespec="seconds")}, f)
    assert jobsafe.who_has(str(tmp / "other.pdf"))["user"] == "pat"
    # changed by someone else since it was opened
    os.utime(path, (1, 1))
    v.mark_dirty()
    assert not w._changed_on_disk(path, ask="cancel")
    assert w._changed_on_disk(path, ask="overwrite")
    v.dirty = False
    w.close_tab(w.tabs.currentIndex())
    assert not os.path.exists(jobsafe.lock_path(path))   # removed on close


def test_only_shared_places_get_locks(tmp_path):
    from app import jobsafe
    assert jobsafe.is_shared(r"\\\\server\\jobs\\a.pdf") or os.name != "nt"
    assert jobsafe.is_shared("D:/Dropbox/a.pdf")
    assert jobsafe.is_shared("D:/OneDrive - Acme/Jobs/a.pdf")
    assert not jobsafe.is_shared(str(tmp_path / "a.pdf")) or os.name != "nt"


def test_lost_data_never_offers_another_jobs_copy(win, qapp, tmp_path):
    """Reviews 1 + 2 (Nov 4): two jobs' one-page 'A-101.pdf' with the same
    page count must not be mixed up; a renamed copy of the same drawings
    is still found."""
    from app import jobdata, jobsafe
    w, tmp = win

    def sheet(path, job):
        d = fitz.open()
        p = d.new_page(width=1224, height=792)
        p.insert_text((72, 72), f"{job} - FLOOR PLAN A-101", fontsize=18)
        d.save(path)
        d.close()
        return path
    os.makedirs(tmp / "jobA", exist_ok=True)
    a = sheet(str(tmp / "jobA" / "A-101.pdf"), "Example Clinic")
    d = fitz.open(a)
    jobdata.restore(d, {"quantisheet_scale.json": b'{"0": {"ppu": 1}}'},
                    overwrite=True)
    d.saveIncr()
    assert jobsafe.keep_copy(d, a)
    d.close()
    # another job, same name, same size, no data
    os.makedirs(tmp / "jobB", exist_ok=True)
    b = sheet(str(tmp / "jobB" / "A-101.pdf"), "Example Library")
    db = fitz.open(b)
    assert jobsafe.lost_data(db, b) is None
    db.close()
    # job A's sheet, emailed and renamed, data stripped
    da = fitz.open(a)
    jobdata.strip(da)
    moved = str(tmp_path / "A-101 from email.pdf")
    da.save(moved)
    da.close()
    dm = fitz.open(moved)
    rec = jobsafe.lost_data(dm, moved)
    assert rec is not None and rec["match"] == jobsafe.MATCH_DRAWINGS
    dm.close()


# ---- review 1 (Nov 4): hex strings, graded answer ---------------------------

def test_leak_check_reads_hex_and_octal_strings(tmp_path):
    path = str(tmp_path / "hex.pdf")
    d = fitz.open()
    d.new_page().insert_text((72, 72), "nothing here")
    x = d.get_new_xref()
    hexed = SECRET.encode("latin-1").hex().upper()
    d.update_object(x, f"<< /QSNote <{hexed}> >>")
    x2 = d.get_new_xref()
    octal = "".join("\\%03o" % ord(c) for c in SECRET)
    d.update_object(x2, f"<< /QSNote2 ({octal}) >>")
    d.save(path)
    d.close()
    leaks = redaction.leak_check(path, {SECRET})
    assert "other content in the file" in leaks


def test_check_says_what_is_still_showing_and_what_was_not_checked(tmp_path):
    path = str(tmp_path / "graded.pdf")
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), f"Header {SECRET}")
    from PySide6.QtGui import QImage
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(0x808080)
    png = str(tmp_path / "x.png")
    img.save(png)
    p.insert_image(fitz.Rect(72, 100, 120, 148), filename=png)
    d.save(path)
    d.close()
    res = redaction.check(path, {SECRET}, visible={SECRET})
    assert res["leaks"] == {}
    assert res["elsewhere"] == [SECRET]
    assert any("pictures" in u for u in res["unchecked"])


# ---- review 1 + 2 (Nov 4): the lock, done properly --------------------------

def test_lock_is_exclusive_and_knows_windows(tmp_path, monkeypatch):
    import json
    from app import jobsafe
    path = str(tmp_path / "x.pdf")
    open(path, "wb").write(b"%PDF-1.4\n")
    assert os.path.basename(jobsafe.lock_path(path)).startswith(".")
    assert "~$" not in jobsafe.lock_path(path)
    assert jobsafe.take_lock(path)
    assert jobsafe.who_has(path) is None               # this window
    assert jobsafe.touch_lock(path)        # heartbeat works on the hidden file
    rec = json.load(open(jobsafe.lock_path(path)))
    # the same person in another, still running window (this test's
    # parent process stands in for it)
    rec["pid"] = os.getppid()
    _put_lock(jobsafe.lock_path(path), rec)
    other = jobsafe.who_has(path)
    assert other and other.get("you")
    assert not jobsafe.take_lock(path)                 # it's held
    # a window that closed without tidying up: not a lock any more
    rec["pid"] = 999999
    _put_lock(jobsafe.lock_path(path), rec)
    monkeypatch.setattr(jobsafe, "_alive", lambda pid: False)
    assert jobsafe.who_has(path) is None
    assert jobsafe.take_lock(path)                     # taken over


def test_heartbeat_keeps_a_long_session_fresh(tmp_path):
    import datetime
    import json
    from app import jobsafe
    path = str(tmp_path / "y.pdf")
    open(path, "wb").write(b"%PDF-1.4\n")
    rec = {"user": "pat", "machine": "OFFICE2", "pid": 1,
           "since": "2026-01-01T07:00:00", "beat": "2026-01-01T07:00:00"}
    _put_lock(jobsafe.lock_path(path), rec)
    later = datetime.datetime(2026, 1, 1, 20, 0)
    assert jobsafe.who_has(path, now=later) is None    # 13 h without a beat
    rec["beat"] = "2026-01-01T19:30:00"
    _put_lock(jobsafe.lock_path(path), rec)
    assert jobsafe.who_has(path, now=later)["user"] == "pat"


def test_same_size_same_second_save_is_noticed(tmp_path):
    from app import jobsafe
    path = str(tmp_path / "z.pdf")
    open(path, "wb").write(b"A" * 1000)
    seen = jobsafe.fingerprint(path)
    st = os.stat(path)
    open(path, "wb").write(b"B" * 1000)                # same size
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # same time
    assert jobsafe.changed_since(path, seen)


def test_synced_folders_are_recognised():
    from app import jobsafe
    assert jobsafe.is_synced_folder("C:/Users/x/OneDrive/Jobs/a.pdf")
    assert jobsafe.is_synced_folder("C:/Users/x/Dropbox/a.pdf")
    assert not jobsafe.is_synced_folder("D:/Jobs/a.pdf")


def test_signature_found_on_a_big_set_without_reading_pages(tmp_path,
                                                            monkeypatch):
    """Review 2 (Nov 4): a 300-sheet signed set was skipped (>50 pages)."""
    out = _signed(tmp_path, monkeypatch)
    d = fitz.open(out)
    assert savecheck._signed_in_field_list(d)
    for _ in range(60):
        d.new_page()
    # SigFlags not set, many pages: the field list still says "signed"
    p = str(tmp_path / "big.pdf")
    d.save(p)
    b = fitz.open(p)
    monkeypatch.setattr(type(b), "get_sigflags", lambda self: 2)
    assert b.page_count > 50 and savecheck.is_signed(b)


def test_signature_check_says_expiry_timestamp_and_long_term(tmp_path,
                                                              monkeypatch):
    """Venice #4 (Nov 4): plain lines, not just 'intact'."""
    out = _signed(tmp_path, monkeypatch)
    from app.sign import verify
    res = [r for r in verify.verify_document(out) if "field" in r]
    assert res and res[0]["intact"]
    assert res[0]["cert_valid_to"] and "self_signed" in res[0]
    msg = res[0]["message"]
    assert "Signed by" in msg and "self-signed" in msg
    assert "timestamp" in msg and "long-term" in msg
    e = dict(res[0], cert_expired=True, cert_valid_when_signed=True)
    assert "expired on" in verify.describe(e)
    e = dict(res[0], intact=False)
    assert "not valid" in verify.describe(e)
