"""Local-first SQLite store with atomic transactions and kept backups.

Every table has id, created/updated time and user and a soft-delete flag;
nothing financial is hard-deleted (voids keep the record). Floats are
refused on every write: money is int cents, hours int hundredths, rates
and percentages decimal strings.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sqlite3

from . import clock, settings

STD = ("id INTEGER PRIMARY KEY, created_at TEXT, created_by TEXT, "
       "updated_at TEXT, updated_by TEXT, deleted INTEGER NOT NULL DEFAULT 0")

TABLES = {
    # P1-01 / company
    "company": "name TEXT, address TEXT, logo TEXT, fiscal_year_start TEXT,"
               " invoice_format TEXT, net_terms INTEGER, accounting_mode TEXT,"
               " state TEXT",
    "counters": "kind TEXT UNIQUE, next INTEGER",
    # P1-03 security
    "users": "name TEXT, email TEXT UNIQUE, role TEXT, title TEXT,"
             " pw_hash TEXT, active INTEGER DEFAULT 1,"
             " failed INTEGER DEFAULT 0, locked_until TEXT",
    "audit": "ts TEXT, user TEXT, action TEXT, record_type TEXT,"
             " record_id TEXT, before TEXT, after TEXT, prev_hash TEXT,"
             " hash TEXT",
    # P1-02 jobs and snapshot copies (read-only)
    "jobs": "number TEXT UNIQUE, name TEXT, project TEXT,"
            " retainage_work TEXT, retainage_stored TEXT, state TEXT,"
            " last_snapshot_at TEXT, source TEXT",
    "job_team": "job_id INTEGER, title TEXT, user_id INTEGER",
    "snapshot_imports": "job_id INTEGER, taken_at TEXT, source TEXT,"
                        " file_hash TEXT, counts TEXT, rejected TEXT,"
                        " changes TEXT",
    "snap_records": "job_id INTEGER, section TEXT, key TEXT, data TEXT,"
                    " first_import INTEGER, last_import INTEGER,"
                    " frozen INTEGER DEFAULT 0",
    # P1-05 time
    "labor_classes": "code TEXT UNIQUE, description TEXT, cost_rate INTEGER,"
                     " burden_pct TEXT, billing_rate INTEGER",
    "crews": "name TEXT, foreman_user_id INTEGER",
    "workers": "name TEXT, employee_no TEXT, labor_class TEXT,"
               " crew_id INTEGER, active INTEGER DEFAULT 1, user_id INTEGER",
    "time_lines": "worker_id INTEGER, date TEXT, job_id INTEGER, phase TEXT,"
                  " cost_code TEXT, pay_type TEXT, hours INTEGER,"
                  " equipment_code TEXT, equipment_hours INTEGER, note TEXT,"
                  " status TEXT, source TEXT, source_key TEXT,"
                  " reject_reason TEXT",
    # P1-06 approvals
    "approval_paths": "job_id INTEGER, record_type TEXT, steps TEXT",
    "approval_requests": "record_type TEXT, record_id INTEGER, job_id INTEGER,"
                         " steps TEXT, step INTEGER, status TEXT,"
                         " step_started TEXT, escalate_days INTEGER,"
                         " escalate_to TEXT, approved_in_step TEXT,"
                         " reassigned TEXT",
    "approval_actions": "record_type TEXT, record_id INTEGER, step INTEGER,"
                        " user_id INTEGER, decision TEXT, reason TEXT, ts TEXT",
    "week_locks": "week_ending TEXT, locked_by TEXT, ts TEXT,"
                  " unlocked_by TEXT, unlock_reason TEXT, active INTEGER",
    # P1-08 / P1-09 AP
    "vendors": "name TEXT, address TEXT, email TEXT, phone TEXT,"
               " default_cost_code TEXT, terms INTEGER, is_1099 INTEGER,"
               " box_1099 TEXT, tax_id TEXT, bank TEXT,"
               " insurance_expires TEXT, license_expires TEXT, w9 INTEGER,"
               " account_id INTEGER, waiver_required INTEGER DEFAULT 0",
    "ap_invoices": "number TEXT, vendor_id INTEGER, invoice_no TEXT,"
                   " invoice_date TEXT, due_date TEXT, gl_date TEXT,"
                   " total INTEGER, tax INTEGER, retainage INTEGER,"
                   " commitment_no TEXT, job_id INTEGER, status TEXT,"
                   " doc_path TEXT, doc_hash TEXT, ocr_text TEXT,"
                   " ocr_conf TEXT, dup_override TEXT,"
                   " overcommit_reason TEXT, use_tax_code INTEGER,"
                   " exported_batch INTEGER, pre_export_status TEXT,"
                   " entry_id INTEGER, final INTEGER DEFAULT 0",
    "ap_lines": "invoice_id INTEGER, line_no INTEGER, job_id INTEGER,"
                " phase TEXT, cost_code TEXT, category TEXT,"
                " description TEXT, amount INTEGER, account_id INTEGER,"
                " box_1099 TEXT",
    "routing_rules": "priority INTEGER, job_id INTEGER, vendor_id INTEGER,"
                     " cost_code TEXT, min_amount INTEGER, max_amount INTEGER,"
                     " steps TEXT, escalate_days INTEGER, escalate_to TEXT,"
                     " active INTEGER DEFAULT 1",
    "compliance_holds": "invoice_id INTEGER, reason TEXT, cleared_by TEXT,"
                        " cleared_at TEXT, note TEXT",
    # P1-10..P1-13 AR
    "billing_contracts": "job_id INTEGER UNIQUE, owner TEXT, bill_to TEXT,"
                         " contact_email TEXT, terms INTEGER,"
                         " retainage_work TEXT, retainage_stored TEXT,"
                         " release_rule TEXT, tax_code_id INTEGER,"
                         " template_id INTEGER, material_markup TEXT,"
                         " sub_markup TEXT, tax_flags TEXT",
    "billing_rates": "contract_id INTEGER, kind TEXT, code TEXT,"
                     " regular INTEGER, overtime INTEGER, double INTEGER,"
                     " rate INTEGER",
    "ar_invoices": "number TEXT, job_id INTEGER, contract_id INTEGER,"
                   " customer TEXT, type TEXT, invoice_date TEXT,"
                   " due_date TEXT, gl_date TEXT, period_to TEXT,"
                   " amount INTEGER, retainage INTEGER, tax INTEGER,"
                   " total INTEGER, status TEXT, payapp_no INTEGER,"
                   " pdf_path TEXT, pdf_hash TEXT, sent_on TEXT,"
                   " sent_to TEXT, change_ref TEXT, void_date TEXT,"
                   " exported_batch INTEGER, entry_id INTEGER, note TEXT,"
                   " tax_code_id INTEGER",
    "ar_lines": "invoice_id INTEGER, line_no INTEGER, description TEXT,"
                " sov_item TEXT, cost_code TEXT, kind TEXT, quantity TEXT,"
                " rate INTEGER, amount INTEGER, taxable INTEGER DEFAULT 0",
    "billed_links": "ar_line_id INTEGER, invoice_id INTEGER,"
                    " source_type TEXT, source_id INTEGER,"
                    " active INTEGER DEFAULT 1",
    "retainage_ledger": "job_id INTEGER, invoice_id INTEGER, kind TEXT,"
                        " amount INTEGER, date TEXT",
    # P1-14
    "waivers": "direction TEXT, kind TEXT, job_id INTEGER, party TEXT,"
               " vendor_id INTEGER, through TEXT, amount INTEGER,"
               " exceptions TEXT, state TEXT, form TEXT, form_path TEXT,"
               " status TEXT, signed_path TEXT, signed_hash TEXT,"
               " ar_invoice_id INTEGER, payment_id INTEGER,"
               " ap_invoice_id INTEGER, commitment_no TEXT",
    "waiver_requirements": "job_id INTEGER, vendor_id INTEGER, kind TEXT",
    # P1-15
    "payments": "customer TEXT, date TEXT, method TEXT, reference TEXT,"
                " amount INTEGER, deposited_on TEXT, note TEXT,"
                " entry_id INTEGER, job_id INTEGER, void INTEGER DEFAULT 0,"
                " exported_batch INTEGER",
    "payment_apps": "payment_id INTEGER, invoice_id INTEGER,"
                    " credit_id INTEGER, amount INTEGER, date TEXT",
    "credits": "customer TEXT, amount INTEGER, source_payment_id INTEGER",
    # P1-16
    "templates": "name TEXT, logo TEXT, header TEXT, remit_to TEXT,"
                 " footer TEXT",
    "sent_log": "invoice_id INTEGER, sent_to TEXT, ts TEXT, file_hash TEXT,"
                " recorded_by TEXT",
    # P1-17
    "export_batches": "number TEXT, type TEXT, format TEXT, ts TEXT,"
                      " record_count INTEGER, total INTEGER, file_path TEXT,"
                      " file_hash TEXT, status TEXT, void_reason TEXT,"
                      " date_from TEXT, date_to TEXT",
    "export_items": "batch_id INTEGER, record_type TEXT, record_id INTEGER",
    "column_maps": "target TEXT, record_type TEXT, columns TEXT,"
                   " code_format TEXT",
    # P1-18..P1-21 ledger
    "accounts": "number TEXT UNIQUE, name TEXT, type TEXT, subtype TEXT,"
                " parent_id INTEGER, active INTEGER DEFAULT 1,"
                " qb_name TEXT, sage_gl TEXT, description TEXT,"
                " system INTEGER DEFAULT 0",
    "posting_defaults": "key TEXT UNIQUE, account_id INTEGER",
    "cost_code_accounts": "cost_code TEXT UNIQUE, account_id INTEGER",
    "journal_entries": "number TEXT, date TEXT, source_type TEXT,"
                       " source_id INTEGER, memo TEXT, posted_by TEXT,"
                       " posted_at TEXT, reverses_id INTEGER,"
                       " reversed_by_id INTEGER, auto_reverse INTEGER,"
                       " batch_id INTEGER",
    "journal_lines": "entry_id INTEGER, account_id INTEGER, debit INTEGER,"
                     " credit INTEGER, job_id INTEGER, cost_code TEXT,"
                     " category TEXT, party TEXT, memo TEXT,"
                     " statement_line_id INTEGER, cash_date TEXT",
    "period_closes": "closed_through TEXT, closed_by TEXT, ts TEXT,"
                     " reopened_by TEXT, reopen_reason TEXT, reopened_at TEXT,"
                     " active INTEGER",
    "bill_payments": "vendor_id INTEGER, date TEXT, method TEXT,"
                     " reference TEXT, amount INTEGER,"
                     " bank_account_id INTEGER, note TEXT, final INTEGER,"
                     " override_reason TEXT, entry_id INTEGER,"
                     " void INTEGER DEFAULT 0, exported_batch INTEGER",
    "bill_payment_apps": "payment_id INTEGER, invoice_id INTEGER, kind TEXT,"
                         " amount INTEGER",
    # Phase 2 accounting
    "bank_accounts": "name TEXT, last4 TEXT, account_id INTEGER, kind TEXT,"
                     " statement_format TEXT, column_map TEXT",
    "statement_lines": "bank_account_id INTEGER, date TEXT, payee TEXT,"
                       " memo TEXT, amount INTEGER, bank_id TEXT,"
                       " content_hash TEXT, status TEXT,"
                       " journal_line_id INTEGER, entry_id INTEGER,"
                       " suggestion TEXT, user_categorized INTEGER DEFAULT 0,"
                       " account_id INTEGER, job_id INTEGER, cost_code TEXT,"
                       " reconciliation_id INTEGER, import_batch TEXT,"
                       " reference TEXT",
    "bank_rules": "priority INTEGER, field TEXT, operator TEXT, text TEXT,"
                  " amount_min INTEGER, amount_max INTEGER, account_id INTEGER,"
                  " job_id INTEGER, cost_code TEXT, active INTEGER DEFAULT 1,"
                  " times_used INTEGER DEFAULT 0",
    "reconciliations": "bank_account_id INTEGER, period_start TEXT,"
                       " period_end TEXT, beginning INTEGER, ending INTEGER,"
                       " cleared_total INTEGER, status TEXT,"
                       " finished_by TEXT, finished_at TEXT,"
                       " undone_by TEXT, undo_reason TEXT, cleared TEXT",
    "tax_codes": "name TEXT, jurisdiction TEXT, rate TEXT, kind TEXT,"
                 " effective_from TEXT, effective_to TEXT,"
                 " account_id INTEGER",
    "tax_lines": "doc_type TEXT, doc_id INTEGER, tax_code_id INTEGER,"
                 " taxable INTEGER, tax INTEGER, date TEXT,"
                 " entry_id INTEGER, paid_entry_id INTEGER",
    "import_batches": "source TEXT, files TEXT, counts TEXT, created TEXT,"
                      " applied_by TEXT, ts TEXT, undone_by TEXT,"
                      " status TEXT",
    "customers": "name TEXT UNIQUE, address TEXT, email TEXT, phone TEXT,"
                 " import_batch INTEGER",
    "items": "name TEXT UNIQUE, kind TEXT, account TEXT, import_batch INTEGER",
    "classes": "name TEXT UNIQUE, import_batch INTEGER",
    # Phase 2 people, payroll and field (M3). Encrypted columns hold
    # 'enc1:' tokens only (crypto.FieldCrypto).
    "employees": "worker_id INTEGER, name TEXT, employee_no TEXT,"
                 " address TEXT, phone TEXT, email TEXT, hire_date TEXT,"
                 " termination_date TEXT, status TEXT, labor_class TEXT,"
                 " classification TEXT, union_local TEXT, pay_rate INTEGER,"
                 " ssn TEXT, dob TEXT, bank_routing TEXT, bank_account TEXT,"
                 " w4 TEXT, state_form TEXT, i9_status TEXT,"
                 " i9_retain_until TEXT, language TEXT, location TEXT,"
                 " photo_consent_on TEXT, pto_policy_id INTEGER,"
                 " apprentice INTEGER DEFAULT 0, remote_pw TEXT",
    "hr_documents": "employee_id INTEGER, type TEXT, file_path TEXT,"
                    " file_hash TEXT, uploaded_by TEXT, ts TEXT,"
                    " retention_until TEXT, expires TEXT, form_edition TEXT",
    "onboarding_packets": "name TEXT, role TEXT, language TEXT,"
                          " location TEXT, items TEXT",
    "onboardings": "employee_id INTEGER, packet_id INTEGER, items TEXT,"
                   " status TEXT, submitted_at TEXT, reviewed_by TEXT,"
                   " reviewed_at TEXT, note TEXT",
    "hr_change_requests": "employee_id INTEGER, field TEXT, value TEXT,"
                          " source TEXT, remote_id TEXT, status TEXT,"
                          " decided_by TEXT, decided_at TEXT, note TEXT",
    "cert_types": "name TEXT UNIQUE, renew_months INTEGER",
    "employee_certs": "employee_id INTEGER, type_id INTEGER, number TEXT,"
                      " issued TEXT, expires TEXT, file_path TEXT",
    "job_cert_requirements": "job_id INTEGER, type_id INTEGER",
    "pto_policies": "name TEXT, per_hours TEXT, per_period INTEGER,"
                    " cap INTEGER, carryover INTEGER, tenure TEXT,"
                    " union_local TEXT, jobsite TEXT,"
                    " allow_negative INTEGER DEFAULT 0",
    "pto_ledger": "employee_id INTEGER, date TEXT, kind TEXT, hours INTEGER,"
                  " ref TEXT, note TEXT",
    "pto_requests": "employee_id INTEGER, date_from TEXT, date_to TEXT,"
                    " hours_per_day INTEGER, total INTEGER, status TEXT,"
                    " source TEXT, remote_id TEXT, decided_by TEXT,"
                    " decided_at TEXT, note TEXT",
    "holidays": "date TEXT, name TEXT",
    "pay_periods": "start TEXT, end TEXT, pay_date TEXT, status TEXT,"
                   " ot_rule_id INTEGER, finalized_by TEXT,"
                   " finalized_at TEXT",
    "rate_tables": "kind TEXT, labor_class TEXT, union_local TEXT,"
                   " job_id INTEGER, determination_no TEXT,"
                   " classification TEXT, effective_from TEXT,"
                   " effective_to TEXT, base_rate INTEGER, fringes TEXT",
    "ot_rules": "name TEXT, weekly_over INTEGER, daily_over INTEGER,"
                " daily_dt_over INTEGER, rate_basis TEXT,"
                " is_default INTEGER DEFAULT 0",
    "payroll_lines": "period_id INTEGER, worker_id INTEGER, job_id INTEGER,"
                     " cost_code TEXT, date TEXT, pay_type TEXT,"
                     " hours INTEGER, rate INTEGER, base INTEGER,"
                     " gross INTEGER, fringe_cash INTEGER, fringe_plan INTEGER,"
                     " fringes TEXT, rate_source TEXT, rule TEXT,"
                     " time_line_id INTEGER, prevailing INTEGER DEFAULT 0",
    "provider_maps": "name TEXT, columns TEXT, earning_codes TEXT,"
                     " detail TEXT, register_columns TEXT",
    "provider_registers": "period_id INTEGER, worker_id INTEGER,"
                          " employee_no TEXT, gross INTEGER,"
                          " employer_taxes INTEGER, taxes TEXT,"
                          " deductions TEXT, net INTEGER, reference TEXT,"
                          " pay_date TEXT, import_batch TEXT",
    "certified_reports": "number TEXT, job_id INTEGER, week_ending TEXT,"
                         " payroll_no INTEGER, revision INTEGER,"
                         " final INTEGER, signer TEXT, signer_title TEXT,"
                         " signed_on TEXT, file_path TEXT, file_hash TEXT,"
                         " status TEXT, submitted_on TEXT, totals TEXT,"
                         " revises_id INTEGER",
    "cp_signers": "name TEXT, title TEXT, active INTEGER",
    "card_receipts": "card_id INTEGER, cardholder TEXT, date TEXT,"
                     " merchant TEXT, amount INTEGER, file_path TEXT,"
                     " file_hash TEXT, statement_line_id INTEGER,"
                     " status TEXT, job_id INTEGER, cost_code TEXT",
    "punches": "remote_id TEXT UNIQUE, worker_id INTEGER, employee_no TEXT,"
               " job_id INTEGER, job_number TEXT, cost_code TEXT, kind TEXT,"
               " punch_time TEXT, synced_at TEXT, lat TEXT, lon TEXT,"
               " accuracy TEXT, distance_m INTEGER, inside INTEGER,"
               " photo_path TEXT, photo_note TEXT, device_id TEXT,"
               " status TEXT, time_line_id INTEGER",
    "geofences": "job_id INTEGER UNIQUE, lat TEXT, lon TEXT,"
                 " radius_m INTEGER, photo_required INTEGER DEFAULT 0",
    "remote_settings": "url TEXT, token TEXT, last_publish TEXT,"
                       " last_pull TEXT, stub_secret TEXT",
    # ---- Phase 3 (M4) ----
    # P3-05: every AI / similarity suggestion and what the user did with it
    "ai_log": "kind TEXT, layer TEXT, model TEXT, model_version TEXT,"
              " input_hash TEXT, record_type TEXT, record_id INTEGER,"
              " proposal TEXT, confidence TEXT, reason TEXT, status TEXT,"
              " decided_by TEXT, decided_at TEXT, entry_id INTEGER,"
              " undo TEXT",
    # P3-01 / P3-06: assistant questions, proposed changes, apply / undo
    "ai_actions": "question TEXT, tool TEXT, params TEXT, records_read TEXT,"
                  " answer TEXT, kind TEXT, before TEXT, after TEXT,"
                  " status TEXT, applied_by TEXT, applied_at TEXT,"
                  " undo TEXT, undone_by TEXT, undone_at TEXT, model TEXT,"
                  " input_hash TEXT, model_version TEXT",
    # P3-04: a job's estimated cost when the user overrides the forecast
    "wip_estimates": "job_id INTEGER, amount INTEGER, note TEXT",
    # P3-02: file sync with an accounting system
    "erp_runs": "system TEXT, direction TEXT, record_type TEXT,"
                " file_name TEXT, file_hash TEXT, counts TEXT,"
                " differences TEXT, status TEXT, applied_by TEXT,"
                " applied_at TEXT, batch_id INTEGER, ignored TEXT",
    "erp_links": "system TEXT, record_type TEXT, erp_key TEXT,"
                 " erp_name TEXT, local_type TEXT, local_id INTEGER",
    "erp_records": "system TEXT, record_type TEXT, erp_key TEXT, data TEXT,"
                   " run_id INTEGER",
    # P3-03: live connectors (none shipped; decision 15 = A)
    "connectors": "system TEXT UNIQUE, endpoint TEXT, agreement_ref TEXT,"
                  " credentials TEXT, status TEXT, last_run TEXT,"
                  " last_result TEXT",
    # r38 G2.1: per diem (a flat daily amount for a worker-day on a job;
    # amounts are int cents). New tables only: a 0.13.9 database gains them
    # on open and nothing already there is changed.
    "per_diem_lines": "worker_id INTEGER, date TEXT, job_id INTEGER,"
                      " cost_code TEXT, kind TEXT, amount INTEGER, note TEXT,"
                      " status TEXT, source TEXT, source_key TEXT,"
                      " reject_reason TEXT",
    "per_diem_rates": "job_id INTEGER, amount INTEGER, cost_code TEXT,"
                      " effective_from TEXT",
}

# Columns added after a table first shipped: added in place to an existing
# database (ALTER TABLE ... ADD COLUMN), never by rebuilding the table.
ADDED_COLUMNS = {
    "bank_accounts": {"cardholder": "TEXT", "cardholder_user_id": "INTEGER",
                      "default_job_id": "INTEGER"},
    "statement_lines": {"receipt_id": "INTEGER"},
    # review fix: encrypted backups (backup.py)
    "company": {"backup_salt": "TEXT", "backup_key": "TEXT"},
    # M4 review: the model's version / digest on assistant actions
    "ai_actions": {"model_version": "TEXT"},
}

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal_lines
BEGIN SELECT RAISE(ABORT, 'posted journal lines are never deleted'); END;
CREATE TRIGGER IF NOT EXISTS journal_line_fixed BEFORE UPDATE OF debit, credit,
account_id, entry_id ON journal_lines
BEGIN SELECT RAISE(ABORT, 'posted journal lines are never edited'); END;
CREATE TRIGGER IF NOT EXISTS journal_entry_fixed BEFORE UPDATE OF date
ON journal_entries
BEGIN SELECT RAISE(ABORT, 'posted journal entries are never edited'); END;
"""


class StoreError(RuntimeError):
    pass


def _check_value(k, v):
    if isinstance(v, float):
        raise TypeError(f"{k}: floats are not stored (got {v!r}); "
                        "use int cents or a decimal string")
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    return v


# Columns kept encrypted at rest (0.13.14, threat model T-004): the
# database layer encrypts them on insert/update and every read through
# get/rows/one/scalar gives the plain value back. Payroll money is added
# up in Python, never in SQL, so these columns are never filtered, sorted
# or summed by SQL (a test checks the code for that).
AUTO_ENCRYPT = {
    "employees": ("address", "phone", "email", "pay_rate"),
    "payroll_lines": ("rate", "base", "gross", "fringe_cash", "fringe_plan",
                      "fringes"),
    "provider_registers": ("gross", "employer_taxes", "taxes", "deductions",
                           "net"),
    "audit": ("before", "after"),
}
_ENC2 = "enc2:"


class DB:
    """One company database."""

    def __init__(self, path: str):
        settings.check_safe(path)
        from . import fileguard
        fileguard.refuse_company_file(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.user = "system"
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._depth = 0
        self.crypto = None          # set by Office: AUTO_ENCRYPT needs it
        # set by Office: called as after_insert(table, new id) - records
        # who entered a record by user id (separation of duties)
        self.after_insert = None
        self._create()

    def _create(self):
        for name, cols in TABLES.items():
            self.conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({STD}, {cols})")
        for name, cols in ADDED_COLUMNS.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({name})")}
            for col, typ in cols.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {name} ADD COLUMN {col} {typ}")
        self.conn.executescript(TRIGGERS)

    def close(self):
        self.conn.close()

    # ---- transactions --------------------------------------------------
    @contextlib.contextmanager
    def tx(self):
        """Atomic: everything inside commits together or not at all."""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("COMMIT")

    # ---- rows ----------------------------------------------------------
    def _enc(self, table, fields):
        cols = AUTO_ENCRYPT.get(table)
        if not cols or self.crypto is None:
            return fields
        return {k: (self.crypto.encrypt_value(v)
                    if k in cols and v is not None and
                    not (isinstance(v, str) and v.startswith(_ENC2)) else v)
                for k, v in fields.items()}

    def _dec(self, row):
        if row is None:
            return None
        d = dict(row)
        if self.crypto is not None:
            for k, v in d.items():
                if isinstance(v, str) and v.startswith(_ENC2):
                    d[k] = self.crypto.decrypt_value(v)
        return d

    def insert(self, table: str, **fields) -> int:
        now = clock.iso_now()
        fields = {k: _check_value(k, v) for k, v in fields.items()}
        fields = self._enc(table, fields)
        fields.update(created_at=now, created_by=self.user,
                      updated_at=now, updated_by=self.user)
        cols = ", ".join(fields)
        q = ", ".join("?" for _ in fields)
        cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({q})",
                                list(fields.values()))
        rid = cur.lastrowid
        if self.after_insert is not None:
            self.after_insert(table, rid)
        return rid

    def update(self, table: str, rid: int, **fields) -> None:
        fields = {k: _check_value(k, v) for k, v in fields.items()}
        fields = self._enc(table, fields)
        fields.update(updated_at=clock.iso_now(), updated_by=self.user)
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?",
                          list(fields.values()) + [rid])

    def get(self, table: str, rid) -> dict | None:
        r = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?",
                              (rid,)).fetchone()
        return self._dec(r)

    def rows(self, sql: str, params=()) -> list[dict]:
        return [self._dec(r) for r in self.conn.execute(sql,
                                                        params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        return self._dec(self.conn.execute(sql, params).fetchone())

    def scalar(self, sql: str, params=()):
        r = self.conn.execute(sql, params).fetchone()
        if not r:
            return None
        v = r[0]
        if self.crypto is not None and isinstance(v, str) and \
                v.startswith(_ENC2):
            return self.crypto.decrypt_value(v)
        return v

    def encrypt_existing(self) -> int:
        """Encrypt AUTO_ENCRYPT values still stored plain (databases from
        before 0.13.14). Once, in one transaction; returns values done."""
        if self.crypto is None:
            return 0
        n = 0
        with self.tx():
            for table, cols in AUTO_ENCRYPT.items():
                have = {r[1] for r in self.conn.execute(
                    f"PRAGMA table_info({table})")}
                for col in cols:
                    if col not in have:
                        continue
                    for rid, v in self.conn.execute(
                            f"SELECT id, {col} FROM {table} WHERE {col} IS "
                            f"NOT NULL").fetchall():
                        if isinstance(v, str) and v.startswith(_ENC2):
                            continue
                        self.conn.execute(
                            f"UPDATE {table} SET {col} = ? WHERE id = ?",
                            (self.crypto.encrypt_value(v), rid))
                        n += 1
        return n

    def soft_delete(self, table: str, rid: int) -> None:
        self.update(table, rid, deleted=1)

    # ---- numbers -------------------------------------------------------
    def next_number(self, kind: str, fmt: str, start: int = 1) -> str:
        with self.tx():
            r = self.one("SELECT id, next FROM counters WHERE kind = ?", (kind,))
            if r is None:
                n = start
                self.insert("counters", kind=kind, next=n + 1)
            else:
                n = r["next"]
                self.update("counters", r["id"], next=n + 1)
        return fmt.format(n=n)

    def set_counter(self, kind: str, next_n: int) -> None:
        with self.tx():
            r = self.one("SELECT id FROM counters WHERE kind = ?", (kind,))
            if r is None:
                self.insert("counters", kind=kind, next=next_n)
            else:
                self.update("counters", r["id"], next=next_n)

    # ---- backups -------------------------------------------------------
    def row_counts(self) -> dict:
        return {t: self.scalar(f"SELECT COUNT(*) FROM {t}") for t in TABLES}

    def dump(self, path: str) -> None:
        """Online copy of this database to `path` (plain SQLite). Only
        backup.py calls it, into a temp file it encrypts and deletes."""
        out = sqlite3.connect(path)
        try:
            self.conn.backup(out)
        finally:
            out.close()


def owner_only(path):
    """The database file readable by this Windows user only (threat model
    T-004). Best effort: a failure is logged, never fatal. Off Windows:
    mode 600."""
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
            return
        import getpass
        import subprocess
        user = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser() \
            if os.environ.get("USERDOMAIN") else getpass.getuser()
        sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "icacls.exe")
        subprocess.run([sysdir, path, "/inheritance:r", "/grant:r",
                        f"{user}:(F)", "/grant:r", "*S-1-5-18:(F)"],
                       capture_output=True, timeout=20,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))
    except Exception:                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "couldn't limit %s to this user", path, exc_info=True)


def on_network_share(path: str) -> bool:
    """A UNC path or a mapped network drive (threat model: keep payroll
    off shares)."""
    p = os.path.abspath(path)
    if p.startswith("\\\\"):
        return True
    if os.name == "nt" and len(p) > 1 and p[1] == ":":
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(p[:3]) == 4
        except Exception:                                 # noqa: BLE001
            return False
    return False


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_into(folder: str, path: str) -> str:
    """Copy a document into the data folder (documents/), returns new path."""
    from . import fileguard
    os.makedirs(folder, exist_ok=True)
    dest = fileguard.safe_path(folder, os.path.basename(path))
    base, ext = os.path.splitext(dest)
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = f"{base}-{n}{ext}"
    shutil.copy2(path, dest)
    return dest
