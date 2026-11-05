"""M4 pages build offscreen without contacting any model, and every P3-05
/ P3-06 button exists and works: Ask (off the UI thread, with Cancel), the
plain search when AI is unavailable, Apply / Undo, bank suggestions with
the 'AI suggested' badge, Accept, Accept-at-threshold, Undo accept,
reconciliation Suggest / Apply / Finish, the AI activity log, Settings > AI
(runtime, model, Test connection, threshold), Sync Confirm / Apply and the
WIP estimate override. The model is a fake local server."""
import time

import pytest

from quantisheet_backoffice import (actions, aitrail, ap, banking, erpsync,
                                    localai, reconcile, wip)

from .ai_fake import router


@pytest.fixture
def errs(monkeypatch):
    from quantisheet_backoffice.ui import ai_pages
    from quantisheet_backoffice.ui import main_window
    out = []
    monkeypatch.setattr(ai_pages, "error", lambda parent, e: out.append(e))
    monkeypatch.setattr(main_window, "error", lambda parent, e: out.append(e))
    return out


def _win(office):
    from quantisheet_backoffice.ui.main_window import NAV, BackOfficeWindow
    w = BackOfficeWindow(office)
    return w, NAV


def _select(t, row):
    t.selectRow(row)
    t.setCurrentCell(row, 0)


def test_m4_pages_build_and_no_model_says_unavailable(qapp, office, job,
                                                      errs):
    from quantisheet_backoffice.ui.ai_pages import (PLACEHOLDER, WARNING,
                                                    AssistantPage, SyncPage,
                                                    WipBox)
    office.set_company(accounting_mode="full")
    w, NAV = _win(office)
    assert isinstance(w.show_page(NAV.index("Assistant")), AssistantPage)
    assert isinstance(w.show_page(NAV.index("Sync Center")), SyncPage)
    books = w.show_page(NAV.index("Books & Reports"))
    assert books.findChildren(WipBox)
    st = w.show_page(NAV.index("Settings"))
    assert st.ai_url.text() == localai.DEFAULT_URL
    assert st.ai_threshold.text() == "0.80"
    pg = w.pages["Assistant"]
    assert pg.q.placeholderText() == PLACEHOLDER
    assert WARNING == "AI suggestions can be wrong; check before accepting."
    assert pg.warning.text() == WARNING
    assert "AI is unavailable" in pg.status.text()
    tabs = [pg.tabs.tabText(i) for i in range(pg.tabs.count())]
    assert tabs == ["Ask the books", "Findings", "Suggestions",
                    "Bank suggestions", "Reconciliation", "AI activity log"]
    pg.q.setText("Which lien waivers are missing at Example Clinic?")
    pg.ask_btn.click()
    txt = pg.answer.toPlainText()
    assert "AI is unavailable" in txt and "Routed by: none" in txt
    assert pg.search_t.rowCount() >= 1
    assert pg.search_t.item(0, 1).text() == "Job 2611 Example Clinic"
    assert actions.pending(office) == [] and errs == []
    w.close()


def _bank(office):
    b = banking.add_account(office, "Operating - Example Bank", "1000",
                            statement_format="csv")
    banking.import_statement(office, b, text=(
        "Date,Description,Amount\n10/07/2026,EXAMPLE POWER UTILITY,-41.00\n"
        "10/08/2026,EXAMPLE SIGNS,-20.00\n"), fmt="csv")
    return b


def test_ask_runs_off_thread_and_cancel(qapp, office, job, fake_ollama,
                                        errs):
    office.set_company(accounting_mode="full")
    w, NAV = _win(office)
    pg = w.show_page(NAV.index("Assistant"))
    fake_ollama.reply = router({"p&l": {"tool": "pl",
                                        "period": "this quarter"}})
    pg.q.setText("Pull this quarter's P&L")
    pg.ask_btn.click()
    txt = pg.answer.toPlainText()
    assert "Report: Profit and loss (accrual), 2026-10-01 to 2026-10-22" in txt
    assert "Routed by: local model" in txt

    def slow(body):
        time.sleep(3)
        return {"tool": "pl"}
    fake_ollama.reply = slow
    from PySide6.QtCore import QTimer
    QTimer.singleShot(200, pg.cancel_btn.click)
    t0 = time.monotonic()
    pg.ask_btn.click()
    assert time.monotonic() - t0 < 2.5
    assert pg.answer.toPlainText().startswith("Cancelled.")
    assert pg.ask_btn.isEnabled() and not pg.cancel_btn.isEnabled()
    assert errs == []
    w.close()


def test_bank_buttons_badge_accept_bulk_undo_and_log(qapp, office, job,
                                                     fake_ollama, errs):
    office.set_company(accounting_mode="full")
    b = _bank(office)
    fake_ollama.reply = lambda body: (
        {"account": "6010", "confidence": 0.9, "reason": "utility"}
        if "POWER" in body["messages"][1]["content"] else
        {"account": "6090", "confidence": 0.5, "reason": "overhead"})
    ids = [ln["id"] for ln in banking.review_queue(office, b)]
    st = lambda: [banking.line(office, i)["status"] for i in ids]  # noqa
    w, NAV = _win(office)
    pg = w.show_page(NAV.index("Assistant"))
    pg.suggest_btn.click()
    badges = [pg.bank_t.item(i, 5).text() for i in range(pg.bank_t.rowCount())]
    assert badges == ["AI suggested", "AI suggested (below threshold)"]
    assert pg.bank_t.item(0, 6).text() == "6010 Overhead - Utilities"
    assert pg.bank_t.item(0, 7).text() == "0.90"
    assert pg.bank_t.item(0, 8).text() == "utility"
    pg.bulk_btn.click()                          # 0.90 >= 0.80 only
    assert st() == ["Accepted", "Suggested"]
    shown = [ln["id"] for ln in pg._lines]
    assert shown == [ids[1], ids[0]]             # queue, then accepted AI
    assert pg.bank_t.item(1, 4).text() == "Accepted"
    _select(pg.bank_t, 1)
    pg.undo_accept_btn.click()
    assert st() == ["New", "Suggested"]
    row = [ln["id"] for ln in pg._lines].index(ids[1])
    _select(pg.bank_t, row)
    pg.accept_btn.click()                        # single accept
    assert st() == ["New", "Accepted"]
    pg.load_log()
    assert pg.log_t.rowCount() == len(aitrail.history(office))
    cols = [pg.log_t.horizontalHeaderItem(i).text()
            for i in range(pg.log_t.columnCount())]
    assert {"Model", "Version", "Suggestion", "Confidence", "By"} <= set(cols)
    assert pg.log_t.item(0, 4).text() == "llama3.2"
    assert pg.log_t.item(0, 5).text().startswith("0123456789ab")
    assert errs == []
    w.close()


def test_apply_and_undo_buttons_for_an_assistant_action(qapp, office, job,
                                                        fake_ollama, errs):
    office.set_company(accounting_mode="full")
    fake_ollama.reply = router({"rule": {"tool": "add_rule",
                                         "text": "EXAMPLE FUEL",
                                         "account": "6040"}})
    w, NAV = _win(office)
    pg = w.show_page(NAV.index("Assistant"))
    pg.q.setText("Add a rule for Example Fuel")
    pg.ask_btn.click()
    assert pg.sug_t.rowCount() == 1 and pg.tabs.currentIndex() == 2
    assert "EXAMPLE FUEL" in pg.sug_t.item(0, 3).text()
    _select(pg.sug_t, 0)
    pg.apply_btn.click()
    assert len(office.db.rows("SELECT * FROM bank_rules WHERE active = 1")) \
        == 1
    _select(pg.hist_t, 0)
    pg.undo_btn.click()
    assert office.db.rows("SELECT * FROM bank_rules WHERE active = 1") == []
    assert errs == []
    w.close()


def test_reconciliation_buttons_ready_to_finish_then_finish(qapp, office,
                                                            errs):
    office.set_company(accounting_mode="full")
    b = banking.add_account(office, "Operating - Example Bank", "1000",
                            statement_format="csv")
    banking.add_rule(office, "EXAMPLE LUMBER", "5020")
    banking.import_statement(office, b, text="Date,Description,Amount\n"
                             "10/05/2026,EXAMPLE LUMBER,-312.47\n",
                             fmt="csv")
    for ln in banking.review_queue(office, b):
        banking.accept(office, ln["id"])
    w, NAV = _win(office)
    pg = w.show_page(NAV.index("Assistant"))
    pg.rec_bal.setText("-312.47")
    pg.rec_end.setText("2026-10-31")
    pg.rec_start_btn.click()
    assert pg.rid and "Difference" in pg.rec_label.text()
    pg.rec_suggest_btn.click()
    assert pg.rec_t.rowCount() == 1
    pg.rec_apply_btn.click()
    assert "Difference $0.00 - Ready to finish" == pg.rec_label.text()
    assert reconcile.status(office, pg.rid)["status"] == "Open"
    pg.rec_finish_btn.click()
    assert reconcile.status(office, pg.rid)["status"] == "Finished"
    assert errs == []
    w.close()


def test_settings_ai_test_connection_threshold_and_runtime(qapp, office,
                                                           fake_ollama,
                                                           errs):
    w, NAV = _win(office)
    st = w.show_page(NAV.index("Settings"))
    assert st.ai_url.text() == fake_ollama.url
    st.ai_test.click()
    assert st.ai_test_result.text().startswith(
        "Connected: llama3.2:latest 0123456789ab")
    st.ai_find.click()
    assert st.ai_model.itemText(0) == "llama3.2:latest"
    st.ai_threshold.setText("0.90")
    st.ai_api.setCurrentIndex(1)
    st.save_btn.click()
    cfg = localai.config()
    assert cfg["threshold"] == "0.90" and cfg["api"] == "openai"
    st.ai_threshold.setText("2")
    st.save_btn.click()
    assert errs and localai.config()["threshold"] == "0.90"
    w.close()


def test_sync_confirm_and_apply_buttons(qapp, office, errs):
    office.act_as("ap@bo.test")
    vid = ap.add_vendor(office, "Example Framing")
    office.act_as("ctl@bo.test")
    erpsync.import_file(office, "Vista", "vendors", text=(
        "Vendor ID,Vendor Name\nV100,Example Framing LLC\n"
        "V300,Example Roofing Inc.\nV400,=BAD()\n"))
    w, NAV = _win(office)
    pg = w.show_page(NAV.index("Sync Center"))
    kinds = [pg.items_t.item(i, 0).text() for i in range(pg.items_t.rowCount())]
    assert kinds == ["likely", "new", "rejected"]
    _select(pg.items_t, 0)
    pg.confirm_btn.click()
    assert office.db.one("SELECT * FROM erp_links WHERE erp_key = 'V100'")[
        "local_id"] == vid
    _select(pg.items_t, 1)
    pg.apply_btn.click()
    assert ap.vendor_by_name(office, "Example Roofing Inc.")
    assert ap.vendor(office, vid)["name"] == "Example Framing"
    assert errs == []
    w.close()


def test_wip_set_estimate_button(qapp, office, job3, errs):
    from quantisheet_backoffice import billing
    from quantisheet_backoffice.ui.ai_pages import WipBox
    office.act_as("bill@bo.test")
    billing.set_contract(office, job3)
    office.act_as("admin@bo.test")
    box = WipBox(office)
    assert box.t.rowCount() == 1
    _select(box.t, 0)
    box.est.setText("430000.00")
    box.est_btn.click()
    [r] = wip.wip(office)
    assert r["estimated_cost"] == 43_000_000
    assert box.t.item(0, 9).text() == "your estimate"
    assert errs == []
