"""Nov 19 (Jon via Chief): a watched plan folder, opening a plan room
download from Explorer, and a bid-submittal checklist on Export Bid
Package. Made-up files only."""
import os
import sys
import time

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import bidpackage, bidsubmittal as bs, planwatch, shellverbs  # noqa: E402,E501

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def pdf(path, text="SHEET", big=True):
    d = fitz.open()
    p = d.new_page(width=2592 if big else 612, height=1728 if big else 792)
    p.insert_text((100, 100), text, fontsize=20)
    d.save(path)
    d.close()
    old = time.time() - 60                 # settled (not still downloading)
    os.utime(path, (old, old))
    return str(path)


def job(tmp_path):
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    p = tmp_path / "job.pdf"
    d.save(p)
    d.close()
    return fitz.open(p)


# ---- 1. watched plan folder ---------------------------------------------------
def test_only_new_settled_pdfs_are_offered(tmp_path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    pdf(folder / "A-101 Floor Plan.pdf")
    doc = job(tmp_path)
    assert planwatch.watch(doc, str(folder)) == 1
    assert planwatch.new_files(doc) == []          # there before: seen
    pdf(folder / "Addendum 2.pdf", "ADDENDUM NO. 2", big=False)
    (folder / "sub").mkdir()
    pdf(folder / "sub" / "A-102 Revised.pdf")
    pdf(folder / "C-1.pdf")
    (folder / "C-1.pdf.crdownload").write_bytes(b"")  # still downloading
    (folder / "notes.txt").write_text("not a PDF")
    items = planwatch.new_files(doc)
    by = {it["rel"]: it for it in items}
    assert set(by) == {"Addendum 2.pdf", "sub/A-102 Revised.pdf"}
    assert by["Addendum 2.pdf"]["kind"] == "Addenda"
    assert by["sub/A-102 Revised.pdf"]["kind"] == "Drawings"
    planwatch.mark_seen(doc, items)
    assert planwatch.new_files(doc) == []
    # a just-written file waits until it has settled
    fresh = folder / "A-103.pdf"
    pdf(fresh)
    os.utime(fresh, None)
    assert planwatch.new_files(doc) == []
    assert planwatch.new_files(doc, now=time.time() + 30)


def test_addenda_go_into_the_addenda_gate(tmp_path):
    from app.estimating import bidgate
    folder = tmp_path / "dl"
    folder.mkdir()
    doc = job(tmp_path)
    planwatch.watch(doc, str(folder))
    pdf(folder / "Addendum 1.pdf", "ADDENDUM NO. 1", big=False)
    items = planwatch.new_files(doc)
    ids = planwatch.log_addenda(doc, items)
    assert len(ids) == 1
    assert planwatch.log_addenda(doc, items) == []    # not twice
    blocks = bidgate.blockers(doc)
    assert blocks and "Addendum 1" in blocks[0]["item"]


def test_watch_survives_save_and_stop(tmp_path):
    folder = tmp_path / "dl2"
    folder.mkdir()
    doc = job(tmp_path)
    planwatch.watch(doc, str(folder))
    doc.saveIncr()
    name = doc.name
    doc.close()
    with fitz.open(name) as d:
        assert planwatch.folder_of(d) == str(folder)
        planwatch.stop(d)
        assert planwatch.folder_of(d) == ""
        assert planwatch.new_files(d) == []
    with pytest.raises(ValueError):
        planwatch.watch(fitz.open(), str(tmp_path / "nope"))


# ---- 2. Open Plan Set in QuantiSheet (.zip) ------------------------------------
def test_open_bid_switch_and_job_folder(tmp_path):
    z = tmp_path / "Made Up Clinic Bid Set.zip"
    z.write_bytes(b"PK")
    argv = ["QuantiSheet.exe", shellverbs.OPEN_BID, str(z)]
    assert shellverbs.parse(argv) == (shellverbs.OPEN_BID, str(z))
    first = shellverbs.job_folder(str(z))
    assert first == str(tmp_path / "Made Up Clinic Bid Set")
    os.makedirs(first)
    assert shellverbs.job_folder(str(z)) == first     # empty: used
    open(os.path.join(first, "x"), "w").close()
    assert shellverbs.job_folder(str(z)).endswith("Bid Set (2)")


def test_installer_adds_the_zip_action():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    iss = open(os.path.join(root, "installer", "quantisheet.iss"),
               encoding="utf-8").read()
    assert "\\.zip\\shell\\QuantiSheet.OpenBid" in iss
    assert "--qs-open-bid" in iss


# ---- 3. bid-submittal checklist ------------------------------------------------
def test_checklist_saved_with_the_job(tmp_path):
    doc = job(tmp_path)
    st = bs.read(doc)
    assert len(bs.missing(st)) == 5
    st["items"]["bid_form"]["done"] = True
    st["ref_no"] = "IFB-26-000 (made up)"
    bs.write(doc, st)
    doc.saveIncr()
    with fitz.open(doc.name) as d:
        st2 = bs.read(d)
        assert st2["ref_no"] == "IFB-26-000 (made up)"
        assert bs.missing(st2) == ["Bid bond (or bid security)",
                                   "Contractor's license",
                                   "Insurance certificate"]


def test_package_carries_attachments_and_the_checklist(tmp_path):
    doc = job(tmp_path)
    bond = pdf(tmp_path / "Made Up Bond.pdf", "BID BOND", big=False)
    st = bs.blank()
    st["items"]["bid_bond"].update(done=True, file=bond)
    st["items"]["license"].update(done=True, file=str(tmp_path / "gone.pdf"))
    st["ref_no"] = "REF-1"
    bs.write(doc, st)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = bidpackage.make(doc, str(out_dir), when="2026-11-19", comp={},
                          parts=("contents",))
    names = [os.path.basename(p) for _k, p in out["files"]]
    assert "Made Up Bond.pdf" in names
    text = open(dict(out["files"])["contents"], encoding="utf-8").read()
    assert "Bid submittal checklist:" in text
    assert "[x] Bid bond (or bid security) - Made Up Bond.pdf" in text
    assert "(file not found)" in text
    assert "[x] Bid reference number: REF-1" in text
    assert any("Not checked off for the bid submittal" in n
               for n in out["checks"])


# ---- the window ------------------------------------------------------------------
def test_window_offers_new_plans_and_the_checklist(win, tmp_path):
    folder = tmp_path / "plans"
    folder.mkdir()
    d = job(tmp_path)
    path = d.name
    d.close()
    assert win.open_path(path)
    assert win.watch_plan_folder(str(folder)) == 0
    assert win.check_plan_folder(quiet=True, show=False) == []
    pdf(folder / "Addendum 3.pdf", "ADDENDUM NO. 3", big=False)
    items = win.check_plan_folder(quiet=True, show=True)
    assert [it["rel"] for it in items] == ["Addendum 3.pdf"]
    dlg = win._plan_dlg
    assert len(dlg.log_addenda()) == 1
    dlg.close()
    # offered once: the next quiet look says nothing
    assert win.check_plan_folder(quiet=True, show=False) == []
    from app.bidsubmittal_ui import SubmittalDialog
    sd = SubmittalDialog(win._view.doc, win, ask_anyway=lambda t: True)
    sd.boxes["bid_form"].setChecked(True)
    sd.ref.setText("REF-9")
    assert sd.go() is True
    assert bs.read(win._view.doc)["ref_no"] == "REF-9"
    sd2 = SubmittalDialog(win._view.doc, win, ask_anyway=lambda t: False)
    assert sd2.go() is False                          # stays open
