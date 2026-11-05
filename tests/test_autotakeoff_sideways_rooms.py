"""Room names on a sheet whose text runs sideways in the file (a
landscape drawing saved on a portrait page and turned for viewing), and
room numbers like 03L / 03O (floor 3, room L / O)."""
import fitz

from app import autotakeoff


def _sideways_page():
    d = fitz.open()
    p = d.new_page(width=400, height=600)
    p.set_rotation(90)

    def put(sx, sy, t):
        u = fitz.Point(sx, sy) * p.derotation_matrix
        p.insert_text(u, t, fontsize=10, rotate=90)
    put(200, 150, "OFFICE")
    put(205, 163, "03O")
    put(320, 250, "HALLWAY")
    put(330, 263, "03L")
    # notes run sideways too (most of the sheet's text does)
    put(60, 340, "GENERAL NOTE: VERIFY ALL")
    put(60, 353, "DIMENSIONS IN FIELD")
    return d, p


def test_sideways_room_names_read_on_screen():
    d, p = _sideways_page()
    got = {t["name"]: t["pt"] for t in autotakeoff.room_labels(p)}
    assert "OFFICE 03O" in got and "HALLWAY 03L" in got, got
    pt = got["OFFICE 03O"]
    # the point is on screen, at the number under the name
    assert 195 <= pt.x <= 230 and 150 <= pt.y <= 170, pt


def test_upright_sheet_unchanged():
    d = fitz.open()
    p = d.new_page(width=600, height=400)
    p.insert_text((200, 150), "OFFICE", fontsize=10)
    p.insert_text((205, 163), "103", fontsize=10)
    names = [t["name"] for t in autotakeoff.room_labels(p)]
    assert names == ["OFFICE 103"]


def test_zero_led_numbers_need_a_letter():
    assert autotakeoff._is_room_no("03L")
    assert autotakeoff._is_room_no("03O")
    assert not autotakeoff._is_room_no("01")      # a keynote, not a room
    assert not autotakeoff._is_room_no("003")
