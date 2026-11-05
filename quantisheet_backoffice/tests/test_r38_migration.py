"""r38 G2.1: a 0.13.9 company database opens in place. The two per diem
tables are created; nothing already there changes; a second open is a no-op.
(The full 0.13.9-code -> patched -> 0.13.9-code round trip is the gate tool
tools/t_bo_migration.py.)"""
import sqlite3

from quantisheet_backoffice import store

NEW = ("per_diem_lines", "per_diem_rates")


def _schema(conn):
    return sorted(tuple(r) for r in conn.execute("SELECT name, sql FROM sqlite_master"))


def test_r38_0139_database_gains_per_diem_tables(bo_home):
    path = str(bo_home / "data" / "company.qsbo")
    (bo_home / "data").mkdir(parents=True)
    conn = sqlite3.connect(path)
    for name, cols in store.TABLES.items():            # as 0.13.9 shipped
        if name not in NEW:
            conn.execute(f"CREATE TABLE {name} ({store.STD}, {cols})")
    conn.execute("INSERT INTO time_lines (worker_id, date, job_id, cost_code,"
                 " pay_type, hours, status) VALUES (1, '2026-10-20', 1,"
                 " '03-3000', 'OT', 250, 'Locked')")
    conn.commit()
    before = conn.execute("SELECT * FROM time_lines").fetchall()
    conn.close()
    db = store.DB(path)
    for t in NEW:
        assert db.rows(f"SELECT * FROM {t}") == []
    assert [tuple(r) for r in db.conn.execute("SELECT * FROM time_lines")] == \
        [tuple(r) for r in before]
    s1 = _schema(db.conn)
    db.close()
    db = store.DB(path)                               # second open: no change
    assert _schema(db.conn) == s1
    db.close()
