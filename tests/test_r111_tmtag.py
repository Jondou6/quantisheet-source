"""Signed T&M tags, linked to a change event. signer.py is only called."""
import os
from decimal import Decimal

import fitz
import pytest

from app.pm.cost import event_cost, event_price
from app.pm.store import ProjectStore
from app.service import tmtag
from r111_support import isolate, qapp, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _tag():
    store = tmtag.blank()
    tid = tmtag.add(store, "Test Smith", "1 Test Lane",
                    "Extra test piping")
    tmtag.add_line(store, tid, "labor", "Test fitter", "4", "hr", "50", "95")
    tmtag.add_line(store, tid, "material", "Test copper", "10", "ft", "3", "6")
    tmtag.add_line(store, tid, "equipment", "Test pump", "1", "ea", "200", "350")
    return store, tmtag.get(store, tid)


def test_totals_and_printable_tag(tmp_path, monkeypatch):
    use_company(monkeypatch)
    _store, tag = _tag()
    got = tmtag.totals(tag)
    # labor 4*95=380, material 10*6=60, equipment 350; cost 4*50+10*3+200=430
    assert got["price"] == Decimal("790.00")
    assert got["cost"] == Decimal("430.00")
    assert got["profit"] == Decimal("360.00")
    path = tmtag.build_pdf(tag, str(tmp_path / "tag.pdf"))
    with fitz.open(path) as doc:
        text = doc[0].get_text()
    assert "Test Plumbing Co" in text
    assert "Test Smith" in text
    assert "Test pump" in text
    assert "$790.00" in text
    assert "Customer signature" in text


def test_sign_uses_signer_and_links_a_change_event(tmp_path, monkeypatch):
    use_company(monkeypatch)
    store, tag = _tag()
    src = tmtag.build_pdf(tag, str(tmp_path / "tag.pdf"))
    dest = str(tmp_path / "tag-signed.pdf")
    tmtag.sign(tag, src, dest, signer_name="A Tester")
    assert tag["status"] == "signed"
    assert os.path.isfile(dest)
    assert os.path.getsize(dest) > os.path.getsize(src)
    pm = ProjectStore(str(tmp_path / "job"))
    rec = tmtag.link_change_event(tag, pm, reason="Unforeseen Condition")
    pm.flush()
    assert tag["change_event_id"] == rec["_id"]
    assert rec["_no"].startswith("CE-")
    assert tag["change_event_no"] == rec["_no"]
    assert rec["reason"] == "Unforeseen Condition"
    assert rec["title"].startswith("T&M TM-")
    assert event_price(rec) == 790.0
    assert event_cost(rec) == 430.0
    kinds = {ln["description"].split(":")[0] for ln in rec["lines"]}
    assert kinds == {"labor", "material", "equipment"}
    saved = tmtag.blank()
    try:
        tmtag.sign(tmtag.get(saved, "none"), src, dest)
        assert False
    except tmtag.TagError:
        pass
    empty = tmtag.blank()
    eid = tmtag.add(empty, "Test Smith", "1 Test Lane")
    try:
        tmtag.sign(tmtag.get(empty, eid), src, str(tmp_path / "nope.pdf"))
        assert False, "a tag with no lines is not signed"
    except tmtag.TagError:
        pass


def test_window_adds_lines(qapp):
    from app.service.tmtag_ui import TagWindow
    win = TagWindow()
    win.customer.setText("Test Smith")
    win.site.setText("1 Test Lane")
    win.description.setText("Test extra")
    win.new_clicked()
    win.table.selectRow(0)
    win.kind.setCurrentText("labor")
    win.desc.setText("Test fitter")
    win.qty.setText("2")
    win.unit_name.setText("hr")
    win.cost.setText("40")
    win.price.setText("80")
    win.line_clicked()
    assert "$160.00" in win.table.item(0, 3).text()
    win.close()
