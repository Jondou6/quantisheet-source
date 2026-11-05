"""Technician recommendations become an option quote in one click."""
import os

import fitz
import pytest

from app.estimating import service
from app.service import pricebook, recommend
from r111_support import isolate, png, qapp, records, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def test_notes_and_tasks_become_one_option_quote(tmp_path, monkeypatch):
    use_company(monkeypatch)
    rec, _p, eq = records()
    book = pricebook.blank()
    pricebook.add_task(book, "Test coil cleaning", "220", "180", code="COIL",
                       tier="Better")
    pricebook.add_task(book, "Test coil replacement", "640", "500", code="NEW",
                       tier="Best")
    store = recommend.blank()
    photo = png(tmp_path / "coil.png")
    recommend.add(store, rec, eq, note="Clean the test coil", photo=photo,
                  task_id=book["tasks"][0]["id"], tier="Better")
    recommend.add(store, rec, eq, note="Replace the test coil",
                  task_id=book["tasks"][1]["id"], tier="Best")
    recommend.add(store, rec, eq, note="Optional test gauge", price="45",
                  tier="option")
    q = recommend.quote_for_unit(store, eq, pricebook=book, member=True,
                                 selected_tier="Better")
    by_name = {t["name"]: t for t in q["tiers"]}
    assert by_name["Better"]["price"] == __import__("decimal").Decimal("180.00")
    assert by_name["Best"]["price"] == __import__("decimal").Decimal("500.00")
    assert q["options"][0]["desc"] == "Optional test gauge"
    assert q["options"][0]["price"] == __import__("decimal").Decimal("45.00")
    assert q["selected"]["total"] == __import__("decimal").Decimal("180.00")
    path = recommend.save_quote(str(tmp_path / "rec.pdf"), q)
    with fitz.open(path) as doc:
        text = "".join(page.get_text() for page in doc)
        images = [img for page in doc for img in page.get_images()]
    assert "Test Plumbing Co" in text
    assert "Clean the test coil" in text
    assert "$180.00" in text
    assert images  # the recommendation photo
    bare = recommend.blank()
    recommend.add(bare, rec, eq, note="Look at the test drain")
    try:
        recommend.quote_for_unit(bare, eq)
        assert False, "a note with no price cannot be quoted"
    except recommend.RecommendError:
        pass


def test_window_quotes_the_selected_unit(qapp, tmp_path, monkeypatch):
    use_company(monkeypatch)
    rec, _p, _eq = records()
    service.save(rec)
    from app.service.recommend_ui import RecommendWindow
    win = RecommendWindow()
    win.note.setText("Replace the test filter")
    win.price.setText("75")
    win.tier.setCurrentText("Good")
    win.add_clicked()
    assert win.table.rowCount() == 1
    assert "filter" in win.table.item(0, 1).text()
    path = win.quote_to(str(tmp_path / "one.pdf"))
    assert path and os.path.isfile(path)
    with fitz.open(path) as doc:
        text = doc[0].get_text()
    assert "Replace the test filter" in text
    assert "Test Plumbing Co" in text
    win.close()
