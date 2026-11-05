"""Nov 1: AI item names you renamed are used by the next AI Takeoff."""
import pytest

from app import name_memory as nm, settings  # noqa: E402

AI = "AI takeoff: devices"
ROOM = "AI takeoff: rooms"


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "home"))
    store = {}
    monkeypatch.setattr(settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(settings, "set", lambda k, v: store.__setitem__(k, v))
    yield store


def _mark(group, method=AI, mtype="count", label=None):
    return (0, "add_count", {"label": label or f"{group}: 1",
                             "measure": {"type": mtype, "group": group,
                                         "method": method, "value": 1}})


def test_a_renamed_ai_item_is_used_next_time():
    assert nm.learn("DUPLEX CONVENIENCE OUTLET", "Duplex receptacle",
                    "count", [AI])
    marks = [_mark("DUPLEX CONVENIENCE OUTLET"), _mark("EXIT SIGN")]
    done = nm.rename_marks(marks)
    assert done == {"DUPLEX CONVENIENCE OUTLET": "Duplex receptacle"}
    m = marks[0][2]
    assert m["measure"]["group"] == "Duplex receptacle"
    assert m["measure"]["ai_name"] == "DUPLEX CONVENIENCE OUTLET"
    assert m["label"] == "Duplex receptacle: 1"
    assert marks[1][2]["measure"]["group"] == "EXIT SIGN"


def test_own_items_teach_nothing():
    assert nm.learn("My item", "Other", "count", ["manual"]) is None
    assert nm.learn("X", "X", "count", [AI]) is None
    assert nm.pairs() == []


def test_hand_measurements_are_never_renamed():
    nm.learn("EXIT SIGN", "Exit sign", "count", [AI])
    marks = [_mark("EXIT SIGN", method="manual")]
    assert nm.rename_marks(marks) == {}


def test_rooms_any_number_and_keeping_the_number():
    nm.learn("OFFICE 101", "Office - ACT", "area", [ROOM])
    nm.learn("STORAGE 12", "Storage 12 (sealed concrete)", "area", [ROOM])
    marks = [_mark("OFFICE 205", ROOM, "area", "OFFICE 205: 120 sq ft"),
             _mark("STORAGE 3B", ROOM, "area"),
             _mark("OFFICE", ROOM, "area")]
    done = nm.rename_marks(marks)
    assert marks[0][2]["measure"]["group"] == "Office - ACT"
    assert marks[0][2]["label"] == "Office - ACT: 120 sq ft"
    assert marks[1][2]["measure"]["group"] == "Storage 3B (sealed concrete)"
    assert marks[2][2]["measure"]["group"] == "Office - ACT"
    assert len(done) == 3


def test_split_room():
    assert nm.split_room("OFFICE 101") == ("OFFICE", "101")
    assert nm.split_room("VESTIBULE 101.1") == ("VESTIBULE", "101.1")
    assert nm.split_room("STORAGE B12") == ("STORAGE", "B12")
    assert nm.split_room("LOBBY") == ("LOBBY", None)


def test_the_run_result_follows_so_the_queue_pairs_them():
    nm.learn("OFFICE 101", "Office", "area", [ROOM])
    marks = [_mark("OFFICE 205", ROOM, "area")]
    done = nm.rename_marks(marks)
    res = {"review": [{"engine": "rooms", "name": "OFFICE 205"}],
           "quantities": [{"name": "OFFICE 205"}, {"name": "LOBBY"}]}
    assert nm.rename_result(res, done) == 2
    assert res["review"][0]["name"] == "Office"
    assert res["review"][0]["ai_name"] == "OFFICE 205"
    assert res["quantities"][1]["name"] == "LOBBY"


def test_switch_off(_home):
    nm.learn("EXIT SIGN", "Exit sign", "count", [AI])
    _home["remember_item_names"] = False
    assert nm.rename_marks([_mark("EXIT SIGN")]) == {}


def test_forget_and_bad_file():
    k = nm.learn("EXIT SIGN", "Exit sign", "count", [AI])
    assert [p["to"] for p in nm.pairs()] == ["Exit sign"]
    assert nm.forget(k) and nm.pairs() == []
    with open(nm.path(), "w", encoding="utf-8") as f:
        f.write("not json")
    assert nm.pairs() == [] and nm.rename_marks([_mark("EXIT SIGN")]) == {}


def test_shared_with_the_price_database(monkeypatch, tmp_path):
    from app import pricedb
    share = tmp_path / "share"
    share.mkdir()
    monkeypatch.setattr(pricedb, "path", lambda: str(share / "p.db"))
    monkeypatch.setattr(pricedb, "is_shared", lambda p=None: True)
    nm.learn("EXIT SIGN", "Exit sign", "count", [AI])
    assert (share / nm.FILENAME).exists()


# ---- the window ------------------------------------------------------------
fitz = pytest.importorskip("fitz")
from test_gui import win, qapp  # noqa: E402,F401


def _ai_count(v, group, x):
    from app import annotate
    v.apply_marks([(v.page, "add_count", {
        "pt": [x, 500], "n": 1, "color": [1, 0, 0],
        "measure": {"type": "count", "value": 1, "unit": "ea",
                    "group": group, "method": AI}})])
    return annotate


def test_window_rename_item_and_move_to_item_learn(win):
    v = win._view
    _ai_count(v, "EXIT SIGN", 400)
    _ai_count(v, "FIRE ALARM PULL STATION", 450)
    tree = win.takeoff_tree if hasattr(win, "takeoff_tree") else None
    if tree is None:
        from app.takeoff_tree import TakeoffTree
        tree = next(w for w in win.findChildren(TakeoffTree))
    tree.set_doc(v.doc)                  # (the panel refreshes later on)
    assert tree.rename_item("EXIT SIGN", "count", "Exit sign (LED)") == 1
    assert nm.name_for("EXIT SIGN", "count") == "Exit sign (LED)"
    from app import annotate
    a = next(a for a in annotate.iter_annots(v.pg)
             if (a.info or {}).get("subject", "").endswith(
                 ":FIRE ALARM PULL STATION"))
    v.select(a)
    assert v.reassign_selected("Pull station")
    assert nm.name_for("FIRE ALARM PULL STATION", "count") == "Pull station"
