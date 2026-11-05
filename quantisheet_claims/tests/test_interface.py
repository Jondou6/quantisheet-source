"""T16: the snapshot interface."""
import json
import os

import pytest

from quantisheet_claims.interface import (MAX_ITEMS, SnapshotError, load_snapshot,
                                        parse_snapshot)

DATA = os.path.join(os.path.dirname(__file__), "data", "sample_snapshot.json")


def _snap(items, version=1):
    return {"interface_version": version, "source": {"file": "x.pdf"},
            "items": items}


def _item(**kw):
    d = {"name": "Interior Wall", "qty": "1.0000", "unit": "sf",
         "page_label": "A-101", "color": "#ff0000"}
    d.update(kw)
    return d


def test_t16_sample_loads():
    s = load_snapshot(DATA)
    assert s.source_file == "Smith Residence.pdf"
    assert len(s.items) == 3 and not s.rejected
    assert s.items[0].qty_q4 == 12_345_000


def test_t16_version_2_refused():
    with pytest.raises(SnapshotError):
        parse_snapshot(_snap([], version=2))


def test_t16_bad_items_rejected_never_zero():
    s = parse_snapshot(_snap([_item(qty="12,5OO"), _item(color="red"),
                              _item(qty="1,234.50"), _item(qty=5),
                              _item(qty="-1"), _item(name="x" * 121)]))
    assert [i.qty_q4 for i in s.items] == [12_345_000]
    assert [r.index for r in s.rejected] == [0, 1, 3, 4, 5]
    assert "qty" in s.rejected[0].reason and "color" in s.rejected[1].reason


def test_t16_too_many_items_refused():
    with pytest.raises(SnapshotError):
        parse_snapshot(_snap([_item()] * (MAX_ITEMS + 1)))
    assert len(parse_snapshot(_snap([_item()] * MAX_ITEMS)).items) == MAX_ITEMS


def test_not_json(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{nope", encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(str(p))
