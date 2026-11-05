"""Field screens: pre-task plan signatures and PDF, incident people /
photos / review / packet / log, equipment units and hours, and warranty
assignee / photos / close / report. Made-up data only; file dialogs are
injected."""
import csv
import os

import fitz
from PySide6.QtWidgets import QLabel, QPushButton

from quantisheet_backoffice import cents, timeentry
from quantisheet_backoffice.r111 import equipment, incident, jha, warranty
from quantisheet_backoffice.r111.ui import (EquipmentPage, IncidentPage,
                                           JhaPage, WarrantyPage)

STROKES = [[[100, 100], [300, 180], [600, 400]]]


def _png(path):
    from PySide6.QtGui import QColor, QImage
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(QColor(40, 80, 200))
    assert img.save(str(path), "PNG")
    return str(path)


def _buttons(page):
    return {b.text() for b in page.findChildren(QPushButton)}


def _labels(page):
    return {lab.text() for lab in page.findChildren(QLabel)}


def _pdf_text(path):
    with fitz.open(path) as doc:
        return "".join(p.get_text() for p in doc)


# ---- pre-task plan ---------------------------------------------------------

def test_plan_sign_refuses_unsaved_plan_and_blank_pad(office, job, qapp):
    pg = JhaPage(office)
    assert {"Sign Plan", "Plan PDF…", "Save Plan",
            "Copy Yesterday's Plan"} <= _buttons(pg)
    pg.signer.setText("A. Example")
    pg.pad.strokes = [list(s) for s in STROKES]
    assert pg.sign_plan() is None                   # nothing saved yet
    assert "Save the plan first" in pg.status.text()
    assert pg.plan_pdf() is None
    pg.job.setText("2611")
    pg.task.setText("Set glass")
    pg.hazards.setPlainText("Sharp edges")
    pg.controls.setPlainText("Cut-resistant gloves")
    pid = pg.save_plan()
    assert pid
    pg.pad.strokes = []
    assert pg.sign_plan() is None                   # blank pad
    assert "sign on the pad" in pg.status.text()
    assert jha.signatures(office, pid) == []
    pg.signer.setText("  ")
    pg.pad.strokes = [list(s) for s in STROKES]
    assert pg.sign_plan() is None                   # no name
    assert jha.signatures(office, pid) == []


def test_plan_sign_lists_signer_and_saves_pdf(office, job, tmp_path, qapp):
    out = str(tmp_path / "plan.pdf")
    pg = JhaPage(office, pick_save=lambda: out)
    pg.job.setText("2611")
    pg.task.setText("Set glass")
    pg.hazards.setPlainText("Sharp edges")
    pid = pg.save_plan()
    pg.signer.setText("A. Example")
    pg.pad.strokes = [list(s) for s in STROKES]
    assert pg.sign_plan()
    assert [s["name"] for s in jha.signatures(office, pid)] == ["A. Example"]
    assert pg.signed.count() == 1
    assert pg.signed.item(0).text().startswith("A. Example")
    assert pg.pad.strokes == [] and pg.signer.text() == ""
    path = pg.plan_pdf()
    assert path == out and os.path.isfile(out)
    assert out in pg.status.text()
    text = _pdf_text(out)
    assert "A. Example" in text and "Sharp edges" in text
    # a cancelled save dialog does nothing
    pg.pick_save = lambda: ""
    assert pg.plan_pdf() is None


def test_copied_plan_starts_with_no_signers(office, job, qapp):
    jha.add_plan(office, "2026-10-21", job, "Set glass", "Edges", "Gloves")
    pg = JhaPage(office)
    pg.job.setText("2611")
    pid = pg.copy_plan()
    assert pid and pg.plan_id == pid
    assert pg.signed.count() == 0


# ---- incidents -------------------------------------------------------------

def _filled_incident_page(office, tmp_path, **kw):
    pg = IncidentPage(office, **kw)
    pg.kind.setCurrentText("injury")
    pg.when.setText("2026-10-20")
    pg.time.setText("14:10")
    pg.job.setText("2611")
    pg.where.setText("North stair, 123 Example St")
    pg.weather.setText("Rain")
    pg.what.setPlainText("Slipped on a wet ramp.")
    return pg


def test_incident_boxes_are_labelled(office, qapp):
    pg = IncidentPage(office)
    for label in ("Type", "Date", "Time", "Where", "Weather",
                  "What happened"):
        assert label in _labels(pg)
    assert {"Save Incident", "Add Person", "Mark Recordable", "Add Photo…",
            "Accept Review", "Return for Changes", "Incident Packet PDF…",
            "Recordable Log…"} <= _buttons(pg)


def test_incident_needs_saving_before_people_and_bad_input(office, qapp):
    pg = IncidentPage(office)
    pg.person_name.setText("A. Example")
    assert pg.add_person() is None
    assert "Save or pick an incident first" in pg.status.text()
    pg.when.setText("yesterday")
    pg.what.setPlainText("Something")
    assert pg.save() is None
    assert "YYYY-MM-DD" in pg.status.text()
    pg.when.setText("2026-10-20")
    pg.what.setPlainText("   ")
    assert pg.save() is None
    assert "Describe what happened" in pg.status.text()
    pg.what.setPlainText("Something")
    pg.job.setText("NO-SUCH-JOB")
    assert pg.save() is None
    assert "No job" in pg.status.text()


def test_incident_people_photos_review_packet_and_log(office, job, tmp_path,
                                                     qapp):
    photo = _png(tmp_path / "ramp.png")
    saves = {"next": str(tmp_path / "packet.pdf")}
    pg = _filled_incident_page(office, tmp_path,
                               pick_images=lambda: [photo],
                               pick_save=lambda: saves["next"])
    iid = pg.save()
    assert iid and pg.incident_id == iid
    row = incident.get(office, iid)
    assert row["occurred_time"] == "14:10" and row["weather"] == "Rain"
    assert row["job_id"] == job and row["kind"] == "injury"
    assert pg.list.rowCount() == 1

    pg.person_name.setText("A. Example")
    pg.person_role.setCurrentText("injured")
    pg.person_title.setText("Laborer")
    pg.statement.setPlainText("I lost my footing on the ramp.")
    pid = pg.add_person()
    assert pid
    pg.person_name.setText("B. Example")
    pg.person_role.setCurrentText("witness")
    assert pg.add_person()
    folks = incident.people(office, iid)
    assert [p["name"] for p in folks] == ["A. Example", "B. Example"]
    assert folks[0]["statement"] == "I lost my footing on the ramp."
    assert pg.people_table.rowCount() == 2

    # recordable needs a picked person, whole-number days
    pg.people_table.clearSelection()
    pg.people_table.setCurrentCell(-1, -1)
    assert pg.mark_recordable() is None
    pg.people_table.selectRow(0)
    pg.days_away.setText("two")
    assert pg.mark_recordable() is None
    assert "whole numbers" in pg.status.text()
    pg.classification.setCurrentText("days away")
    pg.days_away.setText("2")
    assert pg.mark_recordable() == pid
    who = incident.people(office, iid)[0]
    assert who["recordable"] == 1 and who["classification"] == "days away"
    assert who["days_away"] == 2

    # photos are copied in by the model, not referenced in place
    pg.caption.setText("North stair ramp")
    added = pg.add_photos()
    assert len(added) == 1
    kept = incident.photos(office, iid)[0]
    assert kept["caption"] == "North stair ramp"
    assert kept["file_path"] != photo and os.path.isfile(kept["file_path"])
    assert pg.photo_list.count() == 1
    pg.pick_images = lambda: [str(tmp_path / "notes.txt")]
    assert pg.add_photos() == []
    assert "Not a photo" in pg.status.text()
    pg.pick_images = lambda: []
    assert pg.add_photos() == []

    # supervisor review: a note is required
    assert pg.accept_review() is None
    assert "review note is required" in pg.status.text()
    pg.review_note.setPlainText("Ramp to be gritted tomorrow.")
    assert pg.accept_review() == "reviewed"
    assert incident.get(office, iid)["status"] == "reviewed"

    path = pg.packet()
    assert path == saves["next"] and os.path.isfile(path)
    text = _pdf_text(path)
    assert "A. Example" in text and "Rain" in text
    assert "North stair ramp" in text

    saves["next"] = str(tmp_path / "log.csv")
    pg.year.setText("2026")
    log = pg.export_log()
    assert log == saves["next"]
    rows = list(csv.DictReader(open(log, encoding="utf-8")))
    assert [r["Employee"] for r in rows] == ["A. Example"]
    saves["next"] = str(tmp_path / "log")          # no extension: PDF
    log = pg.export_log()
    assert log.endswith(".pdf") and "A. Example" in _pdf_text(log)
    pg.year.setText("26")
    assert pg.export_log() is None
    assert "year" in pg.status.text()


def test_incident_return_for_changes(office, tmp_path, qapp):
    pg = _filled_incident_page(office, tmp_path)
    pg.job.setText("")
    iid = pg.save()
    pg.review_note.setPlainText("Add the witness statement.")
    assert pg.return_review() == "returned"
    assert incident.get(office, iid)["status"] == "returned"


def test_incident_list_is_for_hr_and_admin_only(office, tmp_path, qapp):
    """Incidents hold health information (reviews 1 + 2, Nov 4)."""
    incident.add(office, "near miss", "2026-10-20", "Dropped a level.",
                 location="123 Example St")
    pg = IncidentPage(office)                       # Admin: allowed
    assert not pg.body.isHidden() and pg.list.rowCount() == 1
    for email in ("viewer@bo.test", "bill@bo.test", "pm@bo.test",
                  "ap@bo.test"):
        office.act_as(email)
        pg = IncidentPage(office)
        assert pg.body.isHidden()
        assert pg.list.rowCount() == 0
        assert "can view incidents" in pg.status.text()
        assert "Admin" in pg.status.text()
        pg.what.setPlainText("Should not save")
        assert pg.save() is None
        assert pg.export_log() is None
    office.act_as("admin@bo.test")
    assert len(office.db.rows("SELECT id FROM incidents WHERE deleted = 0")) == 1


# ---- equipment -------------------------------------------------------------

def test_equipment_add_unit_and_log_hours(office, qapp):
    pg = EquipmentPage(office)
    assert {"Add Unit", "Log Hours", "Update From Time Cards",
            "Show Reminders"} <= _buttons(pg)
    assert pg.units.rowCount() == 0
    pg.code.setText("EX-1")
    pg.name.setText("Example lift")
    pg.kind.setCurrentText("equipment")
    pg.serial.setText("SN-0001")
    pg.meter.setText("90")
    pg.service_hours.setText("100")
    pg.inspection_on.setText("2026-12-01")
    uid = pg.add_unit()
    assert uid and pg.units.rowCount() == 1
    unit = equipment.by_code(office, "EX-1")
    assert unit["meter"] == cents.hours("90")
    assert unit["next_service_hours"] == cents.hours("100")
    assert unit["serial_no"] == "SN-0001"
    # duplicate code, bad numbers and dates are refused, not crashed on
    pg.code.setText("EX-1")
    pg.name.setText("Again")
    assert pg.add_unit() is None
    assert "already" in pg.status.text()
    pg.code.setText("VH-2")
    pg.name.setText("Example van")
    pg.kind.setCurrentText("vehicle")
    pg.meter.setText("lots")
    assert pg.add_unit() is None
    assert "number" in pg.status.text()
    pg.meter.setText("0")
    pg.service_on.setText("12/01/2026")
    assert pg.add_unit() is None
    assert "YYYY-MM-DD" in pg.status.text()
    pg.service_on.setText("")
    pg.plate.setText("EX-TEST")
    assert pg.add_unit()
    assert pg.units.rowCount() == 2

    pg.units.clearSelection()
    pg.units.setCurrentCell(-1, -1)
    pg.log_hours_box.setText("4")
    assert pg.log_hours() is None
    assert "Pick a unit" in pg.status.text()
    pg.units.selectRow(pg.unit_ids.index(uid))
    pg.log_hours_box.setText("abc")
    assert pg.log_hours() is None
    pg.log_hours_box.setText("12.5")
    pg.log_note.setText("Extra pick")
    assert pg.log_hours()
    assert equipment.by_code(office, "EX-1")["meter"] == cents.hours("102.5")
    assert "EX-1" in pg.notes.toPlainText()        # service now due


def test_equipment_update_from_time_cards(office, job, qapp):
    wid = timeentry.add_worker(office, "A. Example", "LAB")
    timeentry.add_line(office, wid, "2026-10-21", job, "03-3000", "8",
                       equipment_code="EX-1", equipment_hours="6")
    timeentry.add_line(office, wid, "2026-10-21", job, "03-3000", "1",
                       equipment_code="NO-SUCH", equipment_hours="1")
    equipment.add_unit(office, "EX-1", "Example lift", meter="10")
    pg = EquipmentPage(office)
    done = pg.sync_time()
    assert len(done["added"]) == 1 and done["unmatched"] == ["NO-SUCH"]
    assert "Pulled 1" in pg.status.text() and "NO-SUCH" in pg.status.text()
    assert equipment.by_code(office, "EX-1")["meter"] == cents.hours("16")
    assert pg.sync_time()["added"] == []


# ---- warranty --------------------------------------------------------------

def test_warranty_assignee_photos_close_and_report(office, job, tmp_path,
                                                  qapp):
    photo = _png(tmp_path / "door.png")
    out = str(tmp_path / "warranty.pdf")
    pg = WarrantyPage(office, pick_images=lambda: photo,
                      pick_save=lambda: out)
    assert {"Close Out Job", "Log Call", "Show Calls", "Add Photo…",
            "Close Call", "Warranty Report…"} <= _buttons(pg)
    pg.job.setText("not a job")
    assert pg.log_call() is None
    assert "No job" in pg.status.text()
    pg.job.setText("2611")
    pg.caller.setText("A. Example")
    pg.issue.setPlainText("Door will not latch at 123 Example St")
    assert pg.log_call() is None                    # job not closed out
    assert "Close the job out" in pg.status.text()
    assert pg.mark_closed()
    assert warranty.is_closed(office, job)
    pg.caller.setText("A. Example")
    pg.phone.setText("555-0100")
    pg.assigned.setText("B. Example")
    pg.issue.setPlainText("Door will not latch at 123 Example St")
    cid = pg.log_call()
    assert cid
    call = warranty.calls(office, job)[0]
    assert call["assigned"] == "B. Example" and call["phone"] == "555-0100"
    assert pg.calls.rowCount() == 1

    pg.calls.selectRow(0)
    pg.caption.setText("Strike plate")
    assert len(pg.add_photos()) == 1
    kept = office.db.rows("SELECT * FROM warranty_photos WHERE call_id = ?",
                          (cid,))
    assert kept and kept[0]["file_path"] != photo
    assert os.path.isfile(kept[0]["file_path"])

    pg.calls.selectRow(0)
    pg.close_note.setText("Adjusted the strike")
    assert pg.close_call() == cid
    call = warranty.calls(office, job)[0]
    assert call["status"] == "closed" and call["note"] == "Adjusted the strike"

    path = pg.report()
    assert path == out and os.path.isfile(out)
    text = _pdf_text(out)
    assert "A. Example" in text and "B. Example" in text
    assert "Strike plate" in text and "closed" in text


def test_warranty_buttons_need_a_picked_call(office, job, qapp):
    pg = WarrantyPage(office, pick_images=lambda: [])
    pg.job.setText("2611")
    pg.refresh_calls()
    assert "not closed out" in pg.status.text()
    assert pg.add_photos() == []
    assert "Pick a call" in pg.status.text()
    assert pg.close_call() is None
