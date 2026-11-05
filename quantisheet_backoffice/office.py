"""The open company: database, field encryption, signed-in user and the
permission check every model function goes through."""
from __future__ import annotations

import os

from . import clock, security, settings
from .crypto import FieldCrypto
from .store import DB

MODES = {"export": "Export to my accounting system",
         "full": "Keep the full books here"}


class ModeError(RuntimeError):
    """A full-books feature was used in 'Export to my accounting system' mode."""


class Office:
    def __init__(self, folder: str | None = None, crypto_backend=None):
        self.folder = settings.check_safe(folder or settings.data_folder())
        os.makedirs(self.folder, exist_ok=True)
        self.db = DB(os.path.join(self.folder, "backoffice.sqlite"))
        self.crypto = FieldCrypto(self.folder, crypto_backend)
        self.db.crypto = self.crypto        # AUTO_ENCRYPT columns (0.13.14)
        self.user: dict | None = None       # before the hook can fire
        self.db.after_insert = self._entered
        self._protect_once()
        if self.db.one("SELECT id FROM company") is None:
            with self.db.tx():
                self.db.insert("company", name="", address="", logo="",
                               fiscal_year_start="01-01",
                               invoice_format="INV-{n:04d}", net_terms=30,
                               accounting_mode="export", state="")
        from . import ledger, ap
        ledger.seed_default_chart(self)
        ap.seed_default_rules(self)

    def _protect_once(self):
        """0.13.14 (threat model T-004), once per company database:
        encrypt the payroll / contact / audit values still stored plain,
        re-sign the audit chain with the key kept outside the database,
        and limit the database and key files to this Windows user."""
        from . import store
        if self.db.one("SELECT id FROM counters WHERE kind = ?",
                       ("protect_v2",)):
            return
        with self.db.tx():                     # all of it, or none of it
            # the append-only trigger is lifted for this one rewrite only,
            # inside the same transaction, and put back before it commits
            self.db.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
            old_chain = security.verify_chain(self.db, key=None)
            n = self.db.encrypt_existing()
            security.rekey_chain(self.db, self.crypto.audit_key())
            self.db.set_counter("protect_v2", 1)
            security.audit(self.db, "system", "protect", "database", "",
                           None, {"values_encrypted": n,
                                  "old_chain_ok": old_chain["ok"],
                                  "old_chain_broken_from":
                                      old_chain["broken_from"]})
            self.db.conn.execute(
                "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit "
                "BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); "
                "END")
        for f in ("backoffice.sqlite", "datakey.bin"):
            store.owner_only(os.path.join(self.folder, f))

    @property
    def on_share(self) -> bool:
        """The company database is on a network share (warn: payroll
        belongs on this PC, backed up encrypted)."""
        from . import store
        return store.on_network_share(self.db.path)

    def close(self):
        self.db.close()

    # ---- who ---------------------------------------------------------------
    @property
    def who(self) -> str:
        return self.user["name"] if self.user else "system"

    @property
    def role(self) -> str:
        return self.user["role"] if self.user else "Viewer"

    def _entered(self, table, rid):
        """Who entered a record that someone else must approve: kept by
        user id, not by name (reviews 1 + 2, Nov 4 - a rename or two
        people with one name defeated the name match)."""
        if not getattr(self, "user", None):
            return
        from .r111 import duties
        kind = duties.KIND_OF_TABLE.get(table)
        if kind:
            try:
                duties.note(self, kind, rid, "entered")
            except Exception:                             # noqa: BLE001
                pass

    def sign_in(self, email: str, password: str) -> dict:
        self.user = security.login(self.db, email, password)
        self.db.user = self.who
        return self.user

    def act_as(self, who) -> dict:
        """Switch the acting user by id or email (tests and scripts; the
        window always signs in with a password)."""
        if isinstance(who, int):
            u = self.db.get("users", who)
        else:
            u = self.db.one("SELECT * FROM users WHERE email = ?",
                            (str(who).lower(),))
        if u is None:
            raise security.AuthError(f"no user {who!r}")
        self.user = u
        self.db.user = u["name"]
        return u

    def user_id(self, email: str) -> int:
        u = self.db.one("SELECT id FROM users WHERE email = ?", (email.lower(),))
        if u is None:
            raise KeyError(email)
        return u["id"]

    def can(self, perm: str) -> bool:
        return self.user is not None and bool(self.user["active"]) and \
            security.allowed(self.user["role"], perm)

    def require(self, perm: str, record_type: str = "", record_id="") -> None:
        if not self.can(perm):
            self.audit("denied", record_type, record_id, None,
                       {"permission": perm, "role": self.role})
            raise security.Denied(f"{self.who} ({self.role}) may not do this "
                                  f"({perm}).")

    def decrypt_field(self, perm: str, token, record_type: str = "",
                      record_id="") -> str | None:
        """Plaintext of one encrypted field, only after `perm` passes
        (0.13.5 security fix). FieldCrypto.decrypt itself stays free of
        permission checks so internal callers (masking, the AI redaction
        list, backups) keep working; every path that shows a protected
        value to a person goes through here instead."""
        self.require(perm, record_type, record_id)
        return self.crypto.decrypt(token)

    def decrypt_blob(self, perm: str, data: bytes, record_type: str = "",
                     record_id="") -> bytes:
        """The same for an encrypted document file's bytes."""
        self.require(perm, record_type, record_id)
        return self.crypto.decrypt_bytes(data)

    def audit(self, action, record_type="", record_id="", before=None,
              after=None) -> int:
        return security.audit(self.db, self.who, action, record_type,
                              record_id, before, after)

    # ---- company -----------------------------------------------------------
    def company(self) -> dict:
        return self.db.one("SELECT * FROM company ORDER BY id LIMIT 1")

    def set_company(self, **fields) -> None:
        self.require("settings.edit", "company", 1)
        if "accounting_mode" in fields and fields["accounting_mode"] not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        c = self.company()
        with self.db.tx():
            self.db.update("company", c["id"], **fields)
            self.audit("change", "company", c["id"],
                       {k: c.get(k) for k in fields}, fields)

    @property
    def mode(self) -> str:
        return self.company()["accounting_mode"] or "export"

    def require_full_books(self, feature: str) -> None:
        if self.mode != "full":
            raise ModeError(f"{feature} needs Settings > Accounting set to "
                            f"'{MODES['full']}'.")

    def documents_folder(self) -> str:
        return os.path.join(self.folder, "documents")

    def output_folder(self) -> str:
        return os.path.join(self.folder, "output")

    def today(self):
        return clock.today()
