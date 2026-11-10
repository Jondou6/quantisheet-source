"""ClaimIT 0.2 window (Jon, Oct 31: "make it better and easier to use"):
start page, new-claim wizard, rooms, kits, find/duplicate/copy, edits that
apply as you type, undo/redo, diary and payments, totals bar, checklist,
autosave. Offscreen; made-up data only."""
import os

import pytest

from quantisheet_claims import library, kits, practice, settings
from quantisheet_claims.__main__ import build_window, parse_args


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _win():
    from quantisheet_claims.ui.workspace import ClaimsWindow
    return ClaimsWindow()


def _pump(qapp):
    qapp.processEvents()
    qapp.processEvents()


def test_start_page_then_wizard(qapp):
    win = build_window(parse_args([]))
    assert win.claim is None and win.stack.currentIndex() == 0
    assert not win.start.buttons["takeoff"].isVisibleTo(win.start)
    c = win.new_claim_dialog("residential", values=dict(
        claim_number="EX-100", insured="Example Owner",
        carrier="Example Insurance", loss_address="1 Example St",
        loss_date="2026-10-01", peril="Wind", limit="250,000",
        deductible="1,000"))
    assert c is not None and win.stack.currentIndex() == 1
    assert win.claim.claim_number == "EX-100" and win.claim.peril == "Wind"
    assert win.claim.coverage_a_limit() == 25_000_000
    assert win.claim.deductible.amount_cents == 100_000
    assert win.tabs.currentIndex() == 2                 # rooms & lines next
    assert os.path.exists(win.open_claims[0]["path"])   # saved straight away
    # missing insured: an error, no claim
    assert win.new_claim_dialog("residential", values=dict(
        claim_number="EX-101")) is None
    assert "insured" in win.last_error
    assert win.new_claim_dialog("residential", values=dict(
        claim_number="EX-102", insured="Example")) is None   # no date
    assert "date of loss" in win.last_error
    win.close_claim()
    assert win.stack.currentIndex() == 0
    assert win.start.refresh() == 1                      # in recent claims
    win.close()


def test_rooms_kits_and_line_tools(qapp):
    from quantisheet_claims import rooms
    win = _win()
    win.open_practice()
    c = win.claim
    assert win.room_list.count() == 1 + len(c.rooms)     # All rooms + 2
    # add a room, its lines come next
    assert win.add_room(rooms.new_room("Example Bedroom", "12", "11", "8",
                                       doors=1, windows=2))
    bed = win.selected_room()
    assert bed.name == "Example Bedroom"
    assert "floor 132.00 SF" in win.room_info.text()
    assert win.add_line()
    assert win.claim.lines[-1].room_id == bed.id
    # kit from the user's own library
    library.add_item("EX-PNT", "Example paint", "PAINTING", "SF", other="1.00")
    kits.save_kit("Example paint room", [("EX-PNT", "walls", "1")])
    n = len(win.claim.lines)
    assert win.add_kit_to_room("Example paint room")
    ln = win.claim.lines[-1]
    assert len(win.claim.lines) == n + 1 and ln.room_id == bed.id
    assert ln.qty_q4 == rooms.qty_q4(bed, "walls")
    # filter: only the bedroom's rows show
    visible = [r for r in range(win.lines_table.rowCount())
               if not win.lines_table.isRowHidden(r)]
    assert len(visible) == 2
    win.select_room("")
    win.line_find.setText("example paint")
    visible = [r for r in range(win.lines_table.rowCount())
               if not win.lines_table.isRowHidden(r)]
    assert len(visible) == 1
    win.line_find.setText("")
    # duplicate and copy to another room
    last = len(win.claim.lines) - 1
    win.lines_table.selectRow(last)
    assert win.duplicate_line()
    assert len(win.claim.lines) == last + 2
    win.lines_table.clearSelection()
    win.lines_table.selectRow(0)
    kitchen = win.claim.rooms[0]
    assert win.copy_to_room(kitchen.id)
    assert win.claim.lines[-1].room_id == kitchen.id
    # edit a room: measurements change, lines keep their room
    win.select_room(bed.id)
    assert win.edit_room(rooms.new_room("Example Bedroom", "10", "10", "8"))
    assert win.selected_room().length_ft == 10
    # delete a room: its lines stay, without a room
    assert win.delete_room()
    assert all(ln.room_id != bed.id for ln in win.claim.lines)
    win.close()


def test_edits_apply_as_you_type_and_undo(qapp):
    win = _win()
    win.open_practice()
    before = win.claim.lines[0].description
    win.lines_table.item(0, 1).setText("Example edited text")
    _pump(qapp)
    assert win.claim.lines[0].description == "Example edited text"
    # move a line to a room by typing its name
    win.lines_table.item(0, 9).setText("hall")
    _pump(qapp)
    assert win.claim.lines[0].room_id == win.claim.rooms[1].id
    win.lines_table.item(0, 9).setText("No Such Room")
    _pump(qapp)
    assert "no room named" in win.last_error
    assert win.undo() and win.undo()
    assert win.claim.lines[0].description == before
    assert win.redo()
    assert win.claim.lines[0].description == "Example edited text"
    win.close()


def test_undo_with_nothing_to_undo(qapp):
    win = _win()
    win.open_practice()
    assert win.undo() is False and "Nothing to undo" in win.last_error
    assert win.redo() is False


def test_diary_payments_and_totals_bar(qapp):
    win = _win()
    win.open_practice()
    assert win.add_diary("2026-10-02", "inspection", "Example: met adjuster")
    assert win.diary_table.rowCount() == 2
    assert win.add_diary("02/10/2026", "note", "x") is False
    # more than the practice claim's $340.00: says so and asks (Nov 7)
    asked = []
    assert win.add_payment("2026-10-05", "500.00", "acv", "CHK 1",
                           confirm=lambda t: asked.append(t) or True)
    assert asked
    assert win.claim.paid_cents() == 50_000
    assert "paid $500.00" in win.balance_label.text()
    # $500 against $340 owed: "Overpaid $160.00", never "Still open -$160"
    assert "Overpaid" in win.totals["open"].text()
    assert "-$" not in win.totals["open"].text()
    assert win.add_payment("2026-10-05", "abc", "acv") is False
    win.pay_table.selectRow(0)
    assert win.remove_payment() and win.claim.payments == ()
    win.close()


def test_checklist_and_its_tabs(qapp):
    from quantisheet_claims.ui.workspace import new_claim
    win = _win()
    win.add_claim(new_claim("residential"))
    assert "to fix" in win.check_btn.text()
    dlg = win.checklist_dialog(show=False)
    assert dlg.list.count() >= 3
    dlg._go(dlg.list.item(0))
    assert win.tabs.currentIndex() == 0                 # claim number first
    win.open_practice()
    assert win.check_btn.text() == "Checklist: Ready: nothing to check"
    win.close()


def test_autosave_only_real_claims(qapp):
    from quantisheet_claims.ui.workspace import new_claim
    win = _win()
    win.add_claim(new_claim("residential"))           # NEW-CLAIM: not saved
    win.open_practice()                               # practice: not saved
    assert win.autosave() == 0
    win.add_claim(new_claim("residential", "EX-200"))
    assert win.add_line()
    assert win.autosave() == 1
    assert win.autosave() == 0                        # nothing changed since
    win.close()


def test_getting_started_and_kits_dialog(qapp):
    win = _win()
    assert win.getting_started(show=False).windowTitle() == "Getting started"
    library.add_item("EX-A", "Example A", "OTHER", "EA", other="1")
    dlg = win.kits_dialog(show=False)
    dlg.name.setText("Example kit")
    dlg.add_row("EX-A", "each", "2")
    assert dlg.save() and "Example kit" in kits.all_kits()
    dlg.add_row("NOT-MINE", "each", "1")
    assert dlg.save() is False and "isn't in your library" in dlg.msg.text()
    win.close()


def test_room_dialog_preview(qapp):
    from quantisheet_claims.ui.extras import RoomDialog
    d = RoomDialog()
    d.name.setText("Example")
    d.length.setText("10")
    d.width.setText("10")
    d.height.setText("8")
    assert "Floor 100.00 SF" in d.preview.text()
    d.length.setText("-3")
    assert d.preview.text().startswith("⚠")


# ---- independent review fixes --------------------------------------------
def test_revision_work_is_saved(qapp):
    from quantisheet_claims import store
    from quantisheet_claims.ui.workspace import new_claim
    win = _win()
    win.add_claim(new_claim("residential", "EX-300"))
    assert win.save()
    assert win.new_revision()
    assert win.autosave() == 1                       # the revision counted
    _c, revs = store.load(win.open_claims[0]["path"])
    assert len(revs) == 1
    win.close()


def test_no_claim_is_overwritten(qapp):
    from quantisheet_claims.ui.workspace import new_claim
    win = _win()
    v = dict(claim_number="EX-400", insured="Example Owner",
             loss_date="2026-10-01")             # all three are needed
    assert win.new_claim_dialog("residential", values=v) is not None
    # a second claim with the same number: refused, the first is untouched
    assert win.new_claim_dialog("residential", values=v) is None
    assert "already exists" in win.last_error
    other = new_claim("residential", "EX-400")
    win.add_claim(other)
    assert win.save() is None and "different claim" in win.last_error
    # opening a file that's already open switches to it
    path = win.open_claims[0]["path"]
    n = len(win.open_claims)
    win.open_path(path)
    assert len(win.open_claims) == n and win.current == 0
    win.close()


def test_room_names_are_unique_and_lines_stay_put(qapp):
    from quantisheet_claims import rooms
    win = _win()
    win.open_practice()
    assert win.add_room(rooms.new_room("kitchen")) is False   # any case
    assert "already a room" in win.last_error
    hall = win.claim.rooms[1]
    owners = [ln.room_id for ln in win.claim.lines]
    win.lines_table.item(0, 1).setText("Example new words")
    _pump(qapp)
    assert [ln.room_id for ln in win.claim.lines] == owners
    win.select_room(hall.id)
    assert win.edit_room(rooms.new_room("Kitchen")) is False
    win.close()


def test_hidden_lines_are_never_acted_on(qapp):
    win = _win()
    win.open_practice()
    kitchen, hall = win.claim.rooms
    hall_row = next(i for i, ln in enumerate(win.claim.lines)
                    if ln.room_id == hall.id)
    win.lines_table.selectRow(hall_row)
    win.select_room(kitchen.id)                 # the hall line is now hidden
    n = len(win.claim.lines)
    assert win.delete_line() is False and len(win.claim.lines) == n
    assert win.duplicate_line() is False
    win.lines_table.selectAll()
    assert win.copy_to_room(hall.id)
    copied = len(win.claim.lines) - n
    assert copied == sum(1 for ln in win.claim.lines[:n]
                         if ln.room_id == kitchen.id)
    win.close()


def test_undo_never_unsubmits(qapp):
    win = _win()
    win.open_practice()
    assert win.add_diary("2026-10-03", "note", "Example")
    win.status_box.setCurrentText("submitted")
    assert win.apply_claim_tab()
    assert win.undo() is False and win.claim.status == "submitted"
    win.close()


def test_one_bad_row_never_blocks_other_edits(qapp):
    import dataclasses
    win = _win()
    c = practice.claim()
    bad = dataclasses.replace(c.lines[0], category="NOT-ON-THIS-PC")
    win.add_claim(dataclasses.replace(c, lines=(bad,) + c.lines[1:]))
    win.lines_table.item(1, 1).setText("Example fixed words")
    _pump(qapp)
    assert win.claim.lines[1].description == "Example fixed words"
    # an error puts the cell back
    win.lines_table.item(2, 3).setText("lots")
    _pump(qapp)
    assert "lots" not in win.lines_table.item(2, 3).text()
    win.close()


def test_submitted_claim_table_is_read_only(qapp):
    from PySide6.QtWidgets import QAbstractItemView
    win = _win()
    win.open_practice()
    win.status_box.setCurrentText("submitted")
    assert win.apply_claim_tab()
    assert win.lines_table.editTriggers() == QAbstractItemView.NoEditTriggers
    win.close()


def test_practice_claim_saved_by_the_user_autosaves(qapp):
    win = _win()
    win.open_practice()
    assert win.save()
    assert win.add_diary("2026-10-04", "note", "Example")
    assert win.autosave() == 1
    win.close()


# ---- r47 review (Chief, Oct 31) ------------------------------------------
def test_r47_depreciation_over_100_is_refused(qapp):
    win = _win()
    win.open_practice()
    win.lines_table.item(0, 6).setText("150")
    _pump(qapp)
    assert "0% to 100%" in win.last_error
    assert win.claim.lines[0].dep_bp == 0
    win.close()


def test_r47_status_box_cant_unsubmit_but_a_supplement_can(qapp):
    win = _win()
    win.open_practice()
    win.status_box.setCurrentText("submitted")
    assert win.apply_claim_tab()
    win.status_box.setCurrentText("draft")
    assert win.apply_claim_tab() is False
    assert "start a supplement" in win.last_error
    assert win.claim.status == "submitted"
    n = len(win.revisions)
    assert win.start_supplement()
    assert win.claim.status == "draft" and len(win.revisions) == n + 1
    assert win.revisions[-1].claim.status == "submitted"   # sent version kept
    assert win.start_supplement() is False                  # not sent now
    win.close()


def test_r47_measured_lines_follow_their_room(qapp):
    from quantisheet_claims import rooms
    win = _win()
    win.open_practice()
    library.add_item("EX-B", "Example base", "FLOORING", "LF", other="1")
    kits.save_kit("Example base kit", [("EX-B", "baseboard", "1")])
    kitchen, hall = win.claim.rooms
    win.select_room(kitchen.id)
    assert win.add_kit_to_room("Example base kit")
    ln = win.claim.lines[-1]
    assert ln.qty_q4 == rooms.qty_q4(kitchen, "baseboard")
    win.select_room("")
    win.lines_table.clearSelection()
    win.lines_table.selectRow(len(win.claim.lines) - 1)
    assert win.copy_to_room(hall.id)
    assert win.claim.lines[-1].qty_q4 == rooms.qty_q4(hall, "baseboard")
    win.select_room(kitchen.id)
    bigger = rooms.new_room("Kitchen", "20", "12", "8", doors=1, windows=1)
    assert win.edit_room(bigger)
    kline = next(x for x in win.claim.lines if x.id == ln.id)
    assert kline.qty_q4 == rooms.qty_q4(win.selected_room(), "baseboard")
    # a quantity typed by hand stops following the room
    row = [x.id for x in win.claim.lines].index(ln.id)
    win.lines_table.item(row, 3).setText("5")
    _pump(qapp)
    kline = next(x for x in win.claim.lines if x.id == ln.id)
    assert kline.qty_q4 == 50_000 and kline.qty_from == ""
    win.close()


def test_r47_renamed_claim_keeps_one_file(qapp):
    from quantisheet_claims.ui.workspace import new_claim
    win = _win()
    win.add_claim(new_claim("residential", "EX-501"))
    old = win.save()
    win.f["claim_number"].setText("EX-502")
    assert win.apply_claim_tab()
    new = win.save()
    assert new != old and os.path.exists(new) and not os.path.exists(old)
    bak = os.path.join(os.path.dirname(old), ".backup")
    assert any(x.startswith("EX-501.claim.json.") for x in os.listdir(bak))
    win.close()


def test_r47_undo_keeps_the_audit_trail(qapp):
    win = _win()
    win.open_practice()
    assert win.add_diary("2026-10-05", "note", "Example")
    n = len(win.claim.audit)
    assert win.undo()
    assert len(win.claim.audit) == n + 1
    assert win.claim.audit[-1].action == "undo"
    win.close()


def test_r47_export_tab_has_no_internal_note(qapp):
    from PySide6.QtWidgets import QLabel
    win = _win()
    texts = " ".join(lab.text() for lab in
                     win.tabs.widget(8).findChildren(QLabel))
    assert "ESX" not in texts and "Jon" not in texts
    win.close()
