"""Every Back Office page opens offscreen, in both accounting modes, on the
fixture data (not a brief test: a smoke check of the screens)."""
import pytest

from quantisheet_backoffice import fileguard


@pytest.mark.parametrize("mode", ["export", "full"])
def test_every_page_opens(office, job3, qapp, mode, tmp_path):
    office.set_company(accounting_mode=mode)
    from quantisheet_backoffice.ui.main_window import NAV, BackOfficeWindow
    from PySide6.QtWidgets import QLabel
    w = BackOfficeWindow(office)
    assert w.page_names() == NAV
    for i, name in enumerate(NAV):
        w.nav.setCurrentRow(i)
        qapp.processEvents()
        pg = w.pages[name]
        assert not (isinstance(pg, QLabel) and pg.text().startswith(name + ":")), \
            pg.text()
    assert "Signed in: Ann Admin" in w.statusBar().currentMessage()
    assert "snapshot: 2026-" in w.statusBar().currentMessage()
    pay = w.show_page(NAV.index("Payables"))
    assert pay.drop_file(str(tmp_path / "Books.QBB")) == fileguard.MESSAGE
    w.close()


def test_people_page_reveal_is_logged_and_billing_cannot(office, qapp):
    from quantisheet_backoffice import hr, security
    from quantisheet_backoffice.ui.people_pages import PeoplePage
    from .m3_helpers import add_hr
    add_hr(office)
    office.act_as("hr@bo.test")
    hr.add_employee(office, "M. Chen", "E101", "2026-03-02",
                    ssn="900-00-1234")
    pg = PeoplePage(office)
    assert pg.grid.item(0, 5).text() == "***-**-1234"
    pg.grid.selectRow(0)
    pg.reveal_ssn()
    assert pg.revealed.text() == "M. Chen: 900-00-1234"
    assert len(security.audit_rows(office.db, action="reveal")) == 1
    office.act_as("bill@bo.test")
    pg2 = PeoplePage(office)
    assert pg2.grid.item(0, 5).text() == "***-**-1234"
    assert not pg2.reveal_btn.isEnabled()
