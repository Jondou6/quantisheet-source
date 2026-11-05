"""Job info (brief item 6): description, website / contact, job ZIP and a
project image saved in the PDF with the proposal details; the ZIP picks
the location region; the image and description on the proposal cover;
images over 10 MB refused. Made-up job, ZIP 99903 and a made-up 400x300
PNG only."""
import os
import struct
import zlib

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QMessageBox                    # noqa: E402

from app import (costbook, embfiles, jobinfo, locfactors,    # noqa: E402
                 pricedb, proposal, settings)

COMP = {"name": "Example Builders", "address": "1 Test St, Testville PA"}


def png(path, w=400, h=300):
    """A made-up w x h PNG (a grey gradient), written without any image
    library."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data +
                struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    # 8-bit RGB rows, each starting with filter byte 0
    raw = b"".join(b"\x00" + bytes(v for x in range(w)
                                   for v in (x * 255 // w,) * 3)
                   for _ in range(h))
    data = (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(pricedb, "user", lambda: "Pat Example")
    pricedb.state.update(offline="", copied=0.0)
    seen = []
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(
            lambda *a, **k: seen.append(a[2] if len(a) > 2 else "") or 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    return seen


@pytest.fixture
def doc(tmp_path):
    d = fitz.open()
    d.new_page()
    return d


def _testville():
    locfactors.save([{"region": "Testville", "state": "PA",
                      "zips": "99901-99905", "materials": 1.10,
                      "labor": 1.20, "equipment": 1.00}])


def test_fields_and_image_survive_save_and_reopen(qtbot, doc, tmp_path):
    from app.jobinfo_ui import JobInfoWidget
    img = png(tmp_path / "test_sketch.png")
    w = JobInfoWidget(doc)
    qtbot.addWidget(w)
    w.description.setPlainText("Test garage")
    w.website.setText("example.com")
    w.zip.setText("99903")
    assert w.pick_image(img)
    assert w.commit()
    jobinfo.write(doc, **w.values())
    path = str(tmp_path / "job.pdf")
    doc.save(path)
    again = fitz.open(path)
    info = jobinfo.read(again)
    assert info["description"] == "Test garage"
    assert info["website"] == "example.com"
    assert info["job_zip"] == "99903"
    assert info["has_image"] and info["image_name"] == "test_sketch.png"
    with open(img, "rb") as f:
        assert jobinfo.image_bytes(again) == f.read()
    # kept with the proposal details, in the PDF
    assert proposal.read(again)["description"] == "Test garage"
    assert proposal.JOB_FILE in embfiles.names(again)


def test_zip_picks_the_region_without_picking(qtbot, doc):
    from app.jobinfo_ui import JobInfoWidget
    _testville()
    w = JobInfoWidget(doc)
    qtbot.addWidget(w)
    w.zip.setText("99903")
    assert "Testville" in w.region_label.text()
    assert w.current_region() == ("Testville", "zip")
    jobinfo.write(doc, **w.values())
    assert jobinfo.region(doc) == "Testville"
    assert costbook.job_region(doc) == "Testville"
    w.zip.setText("00000")
    assert "No region for 00000 - pick one or add it" in \
        w.region_label.text()


def test_proposal_cover_has_the_image_and_description(doc, tmp_path):
    jobinfo.set_image(doc, png(tmp_path / "test_sketch.png"))
    jobinfo.write(doc, description="Test garage", website="example.com")
    data = proposal.read(doc)
    out = proposal.make_pdf(doc, data, COMP)
    first = out[0]
    assert len(first.get_images(full=True)) == 1
    text = first.get_text()
    assert "Test garage" in text and "example.com" in text
    # no image, no image object
    jobinfo.clear_image(doc)
    assert jobinfo.image_bytes(doc) is None
    out = proposal.make_pdf(doc, proposal.read(doc), COMP)
    assert out[0].get_images() == []


def test_image_over_10_mb_is_refused(qtbot, doc, tmp_path, _isolated):
    from app.jobinfo_ui import JobInfoWidget
    big = tmp_path / "test_big.png"
    with open(big, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\0" * (10 * 1024 * 1024))
    with pytest.raises(jobinfo.ImageError) as e:
        jobinfo.set_image(doc, str(big))
    assert "10 MB" in str(e.value)
    assert jobinfo.IMAGE_FILE not in embfiles.names(doc)
    w = JobInfoWidget(doc)
    qtbot.addWidget(w)
    assert w.pick_image(str(big)) is False
    assert any("10 MB" in m for m in _isolated)        # said so
    assert w.image.text() == "" and w.commit()
    assert jobinfo.image_bytes(doc) is None
    assert jobinfo.IMAGE_FILE not in embfiles.names(doc)


def test_proposal_dialog_has_the_job_info_tab(qtbot, doc):
    from app.proposal_ui import ProposalDialog
    _testville()
    dlg = ProposalDialog(doc)
    qtbot.addWidget(dlg)
    dlg.job_info.description.setPlainText("Test garage")
    dlg.job_info.zip.setText("99903")
    data = dlg.values()
    assert data["description"] == "Test garage"
    assert data["job_zip"] == "99903"
    assert jobinfo.region(doc, data) == "Testville"
