"""M3 opens an M1/M2 company database in place: new tables are created and
new columns on shipped tables are added without touching existing rows."""
import sqlite3

from quantisheet_backoffice import store


def test_m2_database_gains_m3_tables_and_columns(bo_home):
    path = str(bo_home / "data" / "company.qsbo")
    (bo_home / "data").mkdir(parents=True)
    conn = sqlite3.connect(path)
    m2 = {k: v for k, v in store.TABLES.items()
          if k in ("bank_accounts", "statement_lines", "company")}
    for name, cols in m2.items():                   # as M1/M2 shipped them
        conn.execute(f"CREATE TABLE {name} ({store.STD}, {cols})")
    conn.execute("INSERT INTO bank_accounts (name, last4, kind) "
                 "VALUES ('Ops card', '4242', 'card')")
    conn.commit()
    conn.close()
    db = store.DB(path)
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(bank_accounts)")}
    assert {"cardholder", "cardholder_user_id", "default_job_id"} <= cols
    assert "receipt_id" in {r[1] for r in db.conn.execute(
        "PRAGMA table_info(statement_lines)")}
    (row,) = db.rows("SELECT * FROM bank_accounts")
    assert (row["name"], row["last4"], row["cardholder"]) == ("Ops card",
                                                              "4242", None)
    for t in ("employees", "pay_periods", "payroll_lines", "card_receipts",
              "punches", "certified_reports"):
        db.conn.execute(f"SELECT * FROM {t}")
    db.close()
    store.DB(path).close()                          # second open is a no-op
