import fitz
from app.collab.oplog import OpLog
from app.collab import merge


def _doc():
    d = fitz.open()
    d.new_page(width=612, height=792)
    return d


def test_oplog_union_no_dupes():
    a = OpLog("a"); b = OpLog("b")
    o1 = a.add_local("add_highlight", 0, rect=[10, 10, 40, 20])
    b.merge(a.to_list())
    b.merge(a.to_list())  # duplicate merge
    assert len(b.ops) == 1
    assert o1.id in b.ops


def test_concurrent_edits_both_survive():
    a = OpLog("a"); b = OpLog("b")
    a.add_local("add_highlight", 0, rect=[10, 10, 40, 20])
    b.add_local("add_rect", 0, rect=[100, 100, 140, 130])
    a.merge(b.to_list()); b.merge(a.to_list())
    assert len(a.ops) == 2 and len(b.ops) == 2


def test_apply_merged_draws_both():
    d = _doc()
    ops = [
        {"id": "1", "kind": "add_highlight", "client_id": "a", "seq": 1,
         "page": 0, "payload": {"rect": [10, 10, 40, 20]}, "ts": 1},
        {"id": "2", "kind": "add_rect", "client_id": "b", "seq": 1,
         "page": 0, "payload": {"rect": [100, 100, 140, 130]}, "ts": 2},
    ]

    class V:
        def __init__(self, doc): self.doc = doc
        def _render(self): pass
    merge.apply_merged(V(d), ops)
    assert d[0].first_annot is not None
