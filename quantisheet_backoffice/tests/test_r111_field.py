"""Safety meetings, incidents, pre-task plans, equipment, crew board,
warranty calls and checklist templates. Made-up people only.
"""
import csv

import pytest

from quantisheet_backoffice import cents, jobs, security, timeentry
from quantisheet_backoffice.r111 import (crewboard, equipment, incident, jha,
                                        qatemplates, safety, warranty)


def _png(path):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=40, height=40)
    page.draw_rect(fitz.Rect(4, 4, 36, 36), fill=(0.2, 0.3, 0.8))
    page.get_pixmap().save(path)
    doc.close()


def test_safety_meeting_sheet(office, job, tmp_path):
    titles = [t["title"] for t in safety.topics(office)]
    assert "Ladder setup" in titles
    tid = safety.add_topic(office, "Night work", "Lights on before sunset.")
    mid = safety.add_meeting(office, "2026-10-22", topic_id=tid, job_id=job,
                             presenter="R. Silva")
    a = safety.add_attendee(office, mid, "J. Ruiz", "Own crew")
    b = safety.add_attendee(office, mid, "M. Chen", "Own crew")
    safety.sign(office, a, [[[100, 100], [400, 120], [700, 400]]])
    path = safety.signin_pdf(office, mid, str(tmp_path / "sheet.pdf"))
    import fitz
    text = fitz.open(path)[0].get_text()
    assert "Night work" in text and "J. Ruiz" in text and "M. Chen" in text
    assert "not signed" in text
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        safety.add_meeting(office, "2026-10-23", title="Tailgate")


def test_incident_packet_and_osha_style_log(office, job, tmp_path):
    iid = incident.add(office, "injury", "2026-10-20",
                       "Slipped on a wet ramp at the north stair.",
                       job_id=job, occurred_time="14:10", weather="Rain",
                       location="North stair")
    who = incident.add_person(office, iid, "A. Nguyen", "injured",
                              statement="I lost my footing on the ramp.",
                              job_title="Laborer")
    incident.add_person(office, iid, "L. Ortiz", "witness",
                        statement="The ramp had no grit.")
    hidden = incident.add_person(office, iid, "P. Secret", "injured",
                                 job_title="Apprentice",
                                 statement="Not for the log under my name.")
    photo = str(tmp_path / "ramp.png")
    _png(photo)
    incident.add_photo(office, iid, photo, caption="North stair ramp")
    incident.mark_recordable(office, who, "days away", days_away=2)
    incident.mark_recordable(office, hidden, "other recordable", privacy=True)
    office.act_as("pm@bo.test")
    incident.review(office, iid, "Ramp to be gritted tomorrow.")
    assert incident.get(office, iid)["status"] == "reviewed"
    packet = incident.packet_pdf(office, iid, str(tmp_path / "inc.pdf"))
    import fitz
    text = "".join(p.get_text() for p in fitz.open(packet))
    assert "A. Nguyen" in text and "Rain" in text
    assert "North stair ramp" in text
    assert fitz.open(packet)[0].get_images()
    log = incident.export_log(office, 2026, str(tmp_path / "log.pdf"))
    log_text = fitz.open(log)[0].get_text()
    assert "A. Nguyen" in log_text
    assert "P. Secret" not in log_text
    assert "Privacy case" in log_text
    assert "days away" in log_text
    csv_path = incident.export_log(office, 2026, str(tmp_path / "log.csv"))
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    assert {r["Employee"] for r in rows} == {"A. Nguyen", "Privacy case"}
    assert rows[0]["Days away"] in ("2", "0")


def test_jha_copies_yesterday_and_prints_signatures(office, job, tmp_path):
    jha.add_plan(office, "2026-10-21", job, "Set glass",
                 "Sharp edges", "Gloves and a cut-resistant sleeve")
    copied = jha.copy_yesterday(office, job, "2026-10-22")
    plan = jha.get_plan(office, copied)
    assert plan["task"] == "Set glass" and plan["copied_from"]
    assert jha.signatures(office, copied) == []
    jha.sign(office, copied, "J. Ruiz", [[[50, 50], [200, 80]]])
    path = jha.pdf(office, copied, str(tmp_path / "jha.pdf"))
    import fitz
    assert "J. Ruiz" in fitz.open(path)[0].get_text()
    assert "Sharp edges" in fitz.open(path)[0].get_text()
    with pytest.raises(jha.JhaError):
        jha.copy_yesterday(office, job, "2026-01-01")


def test_equipment_hours_and_in_app_reminders(office, job):
    timeentry.add_worker(office, "J. Ruiz", "LAB")
    wid = timeentry.worker_by_name(office, "J. Ruiz")["id"]
    timeentry.add_line(office, wid, "2026-10-21", job, "03-3000", "8",
                       equipment_code="EX-1", equipment_hours="6")
    timeentry.add_line(office, wid, "2026-10-21", job, "03-3000", "1",
                       equipment_code="NO-SUCH", equipment_hours="1")
    eid = equipment.add_unit(office, "EX-1", "North lift", kind="equipment",
                             meter="90", next_service_hours="100",
                             next_inspection_on="2026-10-01")
    equipment.add_unit(office, "VH-2", "Site van", kind="vehicle",
                       plate="OR-TEST", next_inspection_on="2026-12-01")
    pulled = equipment.sync_time(office)
    assert pulled["unmatched"] == ["NO-SUCH"]
    assert len(pulled["added"]) == 1
    again = equipment.sync_time(office)
    assert again["added"] == []
    unit = equipment.by_code(office, "EX-1")
    assert unit["meter"] == cents.hours("96")
    assert [d["why"] for d in equipment.reminders(office)
            if d["code"] == "EX-1"] == ["inspection"]
    equipment.log_hours(office, eid, "2026-10-22", "10", note="Extra pick")
    whys = [d["why"] for d in equipment.reminders(office) if d["code"] == "EX-1"]
    assert "service" in whys and "inspection" in whys
    assert "VH-2" not in {d["code"] for d in equipment.reminders(office)}


def test_crew_board_copy_prefill_and_pdf(office, job, tmp_path):
    wid = timeentry.add_worker(office, "J. Ruiz", "LAB")
    wid2 = timeentry.add_worker(office, "M. Chen", "LAB")
    cid = timeentry.add_crew(office, "Glass crew", members=[wid, wid2])
    crewboard.assign(office, "2026-10-21", cid, job, "03-3000", "8")
    done = crewboard.copy_yesterday(office, "2026-10-22")
    assert done["from"] == "2026-10-21" and done["copied"] == 1
    assert len(crewboard.board(office, "2026-10-22")) == 1
    again = crewboard.copy_yesterday(office, "2026-10-22")
    assert again["copied"] == 0
    filled = crewboard.prefill(office, "2026-10-22")
    assert len(filled["time_lines"]) == 2
    assert crewboard.prefill(office, "2026-10-22")["time_lines"] == []
    logs = jobs.section(office, job, "daily_logs")
    hit = [lg for lg in logs if lg["date"] == "2026-10-22"]
    assert hit and hit[0]["manpower"][0]["workers"] == "2"
    assert hit[0]["manpower"][0]["company"] == "Example Builders LLC"
    path = crewboard.print_pdf(office, "2026-10-22", str(tmp_path / "crews.pdf"))
    import fitz
    text = fitz.open(path)[0].get_text()
    assert "Glass crew" in text and "2611" in text
    with pytest.raises(crewboard.CrewError):
        crewboard.copy_yesterday(office, "2020-01-01")


def test_warranty_calls_on_a_closed_job(office, job, tmp_path):
    with pytest.raises(warranty.WarrantyError):
        warranty.add_call(office, job, "D. Ortiz", "Door will not latch")
    warranty.close_job(office, job, "2026-10-01")
    cid = warranty.add_call(office, job, "D. Ortiz", "Door will not latch",
                            assigned="J. Ruiz", phone="555-0100")
    photo = str(tmp_path / "door.png")
    _png(photo)
    warranty.add_photo(office, cid, photo, caption="Strike plate")
    warranty.close_call(office, cid, note="Adjusted the strike")
    path = warranty.report_pdf(office, job, str(tmp_path / "wr.pdf"))
    import fitz
    doc = fitz.open(path)
    text = doc[0].get_text()
    assert "D. Ortiz" in text and "Door will not latch" in text
    assert "closed" in text and "Strike plate" in text
    assert doc[0].get_images()


def test_checklist_editor_saves_and_hides(office):
    names = [t["name"] for t in qatemplates.templates(office)]
    assert "Pre-pour" in names
    assert "Forms match the drawings" in qatemplates.items(office, "Pre-pour")
    qatemplates.save(office, "Pre-pour",
                     ["Forms match the drawings", "Pump is on site"])
    assert qatemplates.items(office, "Pre-pour") == [
        "Forms match the drawings", "Pump is on site"]
    qatemplates.save(office, "Roof dry-in", ["Felt is down", "Drains are open"])
    qatemplates.delete(office, "Roof dry-in")
    assert "Roof dry-in" not in [t["name"] for t in qatemplates.templates(office)]
    office.act_as("viewer@bo.test")
    with pytest.raises(security.Denied):
        qatemplates.save(office, "Pre-pour", ["Something"])
    office.act_as("admin@bo.test")
    with pytest.raises(qatemplates.QAError):
        qatemplates.save(office, "Empty", ["  ", ""])
