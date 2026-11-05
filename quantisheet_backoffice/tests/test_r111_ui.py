"""The 1.1.1 screens: Copy Yesterday's Crews is a visible button, the
checklist editor is on the page, and Waiting on me approves in one click.
"""
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent

from quantisheet_backoffice import ap, timeentry
from quantisheet_backoffice.r111 import crewboard, qatemplates
from quantisheet_backoffice.r111.ui import (CrewBoardPage, QaTemplatePage,
                                           WaitingPage)


def _invoice(office, job):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Harbor Glass Supply")
    iid = ap.create_invoice(
        office, vid, "HG-UI", "2026-10-12", "40.00", job_id=job,
        lines=[{"cost_code": "03-3000", "amount": "40.00",
                "description": "Glass"}])
    ap.submit(office, iid)
    office.act_as("pm@bo.test")
    return iid


def test_waiting_page_approves_in_one_click(office, job, qapp):
    iid = _invoice(office, job)
    page = WaitingPage(office)
    page.show()
    qapp.processEvents()
    assert page.ids == [iid]
    assert "03-3000" in page.coding.toPlainText()
    assert "$40.00" in page.coding.toPlainText()
    page.approve_selected()
    qapp.processEvents()
    assert ap.invoice(office, iid)["status"] == "Approved"
    assert page.ids == []
    page.close()


def test_copy_yesterdays_crews_is_visible_and_drag_assigns(office, job, qapp):
    wid = timeentry.add_worker(office, "J. Ruiz", "LAB")
    cid = timeentry.add_crew(office, "Glass crew", members=[wid])
    crewboard.assign(office, "2026-10-21", cid, job, "03-3000", "8")
    page = CrewBoardPage(office)
    page.show()
    qapp.processEvents()
    assert page.copy_btn.text() == "Copy Yesterday's Crews"
    assert page.copy_btn.isVisible()
    assert not page.copy_btn.isHidden()
    page.copy_crews()
    qapp.processEvents()
    assert "2026-10-21" in page.status.text()
    assert page.grid.rowCount() == 1
    page.date.setText("2026-10-23")
    page.jobs.setCurrentRow(0)
    mime = QMimeData()
    mime.setText(f"crew:{cid}")
    event = QDropEvent(QPointF(4, 4), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.jobs.dropEvent(event)
    assert any(r["work_date"] == "2026-10-23" and r["crew_id"] == cid
               for r in office.db.rows(
                   "SELECT * FROM crew_assignments WHERE deleted = 0"))
    page.close()


def test_checklist_editor_is_on_the_page(office, qapp):
    page = QaTemplatePage(office)
    page.show()
    qapp.processEvents()
    assert page.editor.isVisible()
    assert "Forms match the drawings" in page.editor.toPlainText()
    page.name.setText("Pump day")
    page.editor.setPlainText("Hose is tied off\nSpotter is posted")
    page.save()
    qapp.processEvents()
    assert qatemplates.items(office, "Pump day") == [
        "Hose is tied off", "Spotter is posted"]
    page.close()
