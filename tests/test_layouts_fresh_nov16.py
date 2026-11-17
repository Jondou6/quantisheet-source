"""Nov 16 (Jon: "start fresh"): when the estimate layouts saved in a PDF
can't be read, saving, deleting, loading or tagging offers to keep a copy
of the damaged data and start fresh, instead of refusing for good."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
fitz = pytest.importorskip("fitz")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication                    # noqa: E402

from app import embfiles, estimate_layouts as L               # noqa: E402
from app import estimate_ui                                   # noqa: E402


@pytest.fixture
def doc(tmp_path, monkeypatch):
    from app import assemblies, settings
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    QApplication.instance() or QApplication([])
    d = fitz.open()
    d.new_page(width=612, height=792)
    L.save_layout(d, L.new_layout("Example A"))
    L.set_tag(d, "example-line-1", "Phase 1")
    good = bytes(embfiles.get(d, L.FILE))
    assert json.loads(good)["tags"]
    embfiles.put(d, L.FILE, good[:-5], "QuantiSheet estimate layouts")
    assert L.is_damaged(d)
    yield d
    d.close()


def test_say_no_and_nothing_changes(doc):
    bad = bytes(embfiles.get(doc, L.FILE))
    asked = []
    with pytest.raises(L.LayoutStoreDamaged):
        estimate_ui.with_fresh_start(
            None, doc, lambda: L.save_layout(doc, L.new_layout("Example B")),
            ask=lambda: asked.append(1) or False)
    assert asked == [1]
    assert bytes(embfiles.get(doc, L.FILE)) == bad
    assert L.is_damaged(doc)


def test_say_yes_keeps_a_copy_and_the_save_goes_through(doc):
    bad = bytes(embfiles.get(doc, L.FILE))
    lay = estimate_ui.with_fresh_start(
        None, doc, lambda: L.save_layout(doc, L.new_layout("Example B")),
        ask=lambda: True)
    assert lay["name"] == "Example B"
    assert not L.is_damaged(doc)
    kept = [n for n in embfiles.names(doc) if ".damaged-" in n]
    assert len(kept) == 1 and bytes(embfiles.get(doc, kept[0])) == bad
    assert [x["name"] for x in L.layouts(doc) if not x.get("builtin")] == [
        "Example B"]


def test_not_damaged_asks_nothing(doc):
    embfiles.delete(doc, L.FILE)
    assert estimate_ui.start_fresh(None, doc, ask=lambda: 1 / 0) is None
    assert estimate_ui.with_fresh_start(None, doc, lambda: 7,
                                        ask=lambda: 1 / 0) == 7


def test_the_layouts_and_tags_windows_offer_it(doc):
    dlg = estimate_ui.LayoutsDialog(doc)
    dlg.ask_fresh = lambda: False
    dlg.new()
    dlg.name.setText("By phase")
    assert dlg.save_current() is None
    assert "can't be read" in dlg.msg.text()
    assert "Keep a Copy and Start Fresh" in dlg.msg.text()
    assert L.is_damaged(doc)
    dlg.ask_fresh = lambda: True
    lay = dlg.save_current()
    assert lay and lay["name"] == "By phase" and not L.is_damaged(doc)
    dlg.close()
    # tagging: damage it again, then say yes from the tags window
    raw = bytes(embfiles.get(doc, L.FILE))
    embfiles.put(doc, L.FILE, raw[:-5], "QuantiSheet estimate layouts")
    tags = estimate_ui.TagsDialog(doc)
    tags.ask_fresh = lambda: True
    from PySide6.QtWidgets import QTableWidgetItem
    from PySide6.QtCore import Qt
    item = QTableWidgetItem("Phase 2")
    item.setData(Qt.UserRole, "example-line-9")
    tags._filling = True
    tags.table.setRowCount(1)
    tags.table.setItem(0, 3, item)
    tags._filling = False
    tags._edited(tags.table.item(0, 3))
    assert L.tags(doc) == {"example-line-9": "Phase 2"}
    assert not L.is_damaged(doc)
    assert tags.msg.text() == ""
    tags.close()
