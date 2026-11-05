from app.collab.oplog import OpLog


def test_oplog_union_no_dupes():
    a = OpLog("a"); b = OpLog("b")
    a.add_local("add_highlight", 0, rect=[10, 10, 40, 20])
    b.merge(a.to_list()); b.merge(a.to_list())
    assert len(b.ops) == 1


def test_concurrent_edits_both_survive():
    a = OpLog("a"); b = OpLog("b")
    a.add_local("add_highlight", 0, rect=[10, 10, 40, 20])
    b.add_local("add_rect", 0, rect=[100, 100, 140, 130])
    a.merge(b.to_list()); b.merge(a.to_list())
    assert len(a.ops) == 2 and len(b.ops) == 2


def test_restart_does_not_reuse_ids():
    a = OpLog("same")
    first = a.add_local("add_highlight", 0, rect=[1, 1, 2, 2])
    again = OpLog("same")                 # e.g. app restarted, same id
    again.merge(a.to_list())              # learns its own history back
    nxt = again.add_local("add_highlight", 0, rect=[1, 1, 2, 2])
    assert nxt.id != first.id and nxt.seq == 2


def test_rect_objects_serialise_like_lists():
    class R(tuple):
        pass
    a = OpLog("a")
    o = a.add_local("add_rect", 0, rect=R((1.0, 2.0, 3.0, 4.0)))
    b = OpLog("b")
    assert b.add_remote(o.to_dict()) is not None   # same id after JSON trip


def _three_sessions():
    import fitz
    from app.collab.session import CollabSession

    class View:
        def __init__(self):
            self.doc = fitz.open()
            self.doc.new_page()
            self.page = 0

        def _render(self):
            pass
    out = []
    for name in ("host", "a", "b"):
        s = CollabSession(View(), "ws://127.0.0.1:1", role="peer")
        s.client.send_event = lambda *a, **k: None       # offline
        out.append(s)
    return out


def _colour(session):
    from app import annotate
    a = next(iter(annotate.iter_annots(session.view.doc[0])))
    return tuple(round(c, 2) for c in (a.colors or {}).get("stroke") or ())


def test_concurrent_set_annot_converges():
    """Two people recolour the same markup at the same time; every copy
    ends up the same however the edits arrive (review R11)."""
    import random
    from app import annotate
    rnd = random.Random(1)
    for rep in range(50):
        host, a, b = _three_sessions()
        add = host.local_op("add_rect", 0, rect=[50, 50, 150, 120],
                            color=[1, 0, 0])
        annotate.apply_op(host.view.doc, add)
        a._merge_remote([add])
        b._merge_remote([add])
        ea = a.local_op("set_annot", 0, target=add["id"],
                        color=[0, 0.6, 0])
        annotate.apply_op(a.view.doc, ea)
        eb = b.local_op("set_annot", 0, target=add["id"],
                        color=[0, 0, 1])
        annotate.apply_op(b.view.doc, eb)
        first = rnd.random() < 0.5
        host._merge_remote([ea] if first else [eb])
        host._merge_remote([eb] if first else [ea])
        a._merge_remote([eb])
        b._merge_remote([ea])
        cols = {_colour(s) for s in (host, a, b)}
        assert len(cols) == 1, (rep, cols)
