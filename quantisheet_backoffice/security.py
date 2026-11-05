"""Users, roles, permissions and the hash-chained audit log (P1-03).

Roles line up with Project Center's idea of roles, but Back Office keeps
its own logins and never reads QuantiSheet or hub passwords.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from . import clock

ROLES = ("Admin", "Controller", "AP Clerk", "Billing", "Approver", "Viewer",
         "Payroll/HR")
TITLES = ("PM", "Superintendent", "Foreman", "")
LOCK_AFTER = 5
LOCK_MINUTES = 15
PBKDF2_ROUNDS = 600_000          # OWASP 2023+ for PBKDF2-HMAC-SHA256

_ALL = "*"
PERMS = {
    "Admin": {_ALL},
    "Controller": {
        "settings.edit", "snapshot.import", "time.edit", "time.approve",
        "ap.edit", "ap.approve", "compliance.clear", "ar.edit", "ar.approve",
        "payments.edit", "billpay.edit", "waivers.edit", "waiver.override",
        "export.run", "export.void", "gl.manage", "gl.journal",
        "period.close", "bank.edit", "recon.undo", "tax.edit",
        "1099.full_tin", "audit.view", "backup.run", "routing.edit",
        "hr.view", "payroll.run", "payroll.export", "certified.edit",
        "certs.edit", "cards.edit", "ai.use", "sync.run"},
    "AP Clerk": {"snapshot.import", "time.edit", "ap.edit", "billpay.edit",
                 "waivers.edit", "export.run", "bank.edit", "hr.view",
                 "cards.edit", "ai.use"},
    "Billing": {"snapshot.import", "ar.edit", "ar.approve", "payments.edit",
                "waivers.edit", "export.run", "hr.view", "ai.use"},
    "Approver": {"time.edit", "time.approve", "ap.approve", "cards.approve",
                 "ai.use"},
    # Phase 2: the only role besides Admin that sees full SSN / bank / DOB
    # (after a logged reveal) and runs payroll.
    "Payroll/HR": {"snapshot.import", "time.edit", "time.approve", "hr.view",
                   "hr.edit", "hr.reveal", "hr.approve", "payroll.run",
                   "payroll.export", "certified.edit", "certs.edit",
                   "pto.edit", "pto.approve", "remote.sync", "ai.use"},
    "Viewer": set(),
}


class AuthError(PermissionError):
    pass


class Denied(PermissionError):
    pass


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, rounds, salt, dk = stored.split("$")
    except (ValueError, AttributeError):
        return False
    got = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt),
                              int(rounds))
    return hmac.compare_digest(got.hex(), dk)


def needs_rehash(stored: str) -> bool:
    """True for a hash made with fewer rounds than PBKDF2_ROUNDS (it still
    verifies; login replaces it with a current one)."""
    try:
        return int(stored.split("$")[1]) < PBKDF2_ROUNDS
    except (IndexError, ValueError, AttributeError):
        return True


def allowed(role: str, perm: str) -> bool:
    p = PERMS.get(role, set())
    return _ALL in p or perm in p


# ---- audit chain ---------------------------------------------------------

_DB_KEY = object()         # "the key of the database's own data key"


def _key_of(db, key):
    if key is _DB_KEY:
        c = getattr(db, "crypto", None)
        return c.audit_key() if c is not None else None
    return key


def _entry_hash(prev_hash: str, e: dict, key: bytes | None = None) -> str:
    """SHA-256 of the entry and the hash before it; with `key` (0.13.14)
    an HMAC, written 'h2:...', that only the holder of the data key -
    kept outside the database, DPAPI-protected - can produce."""
    body = json.dumps([prev_hash, e["ts"], e["user"], e["action"],
                       e["record_type"], str(e["record_id"]), e["before"],
                       e["after"]], sort_keys=True)
    if key:
        import hmac
        return "h2:" + hmac.new(key, body.encode("utf-8"),
                                hashlib.sha256).hexdigest()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _dump(v):
    if v is None:
        return None
    return json.dumps(v, sort_keys=True, default=str)


def audit(db, user: str, action: str, record_type: str = "",
          record_id="", before=None, after=None, key=_DB_KEY) -> int:
    key = _key_of(db, key)
    last = db.one("SELECT hash FROM audit ORDER BY id DESC LIMIT 1")
    prev = last["hash"] if last else ""
    e = {"ts": clock.iso_now(), "user": user or "system", "action": action,
         "record_type": record_type, "record_id": str(record_id),
         "before": _dump(before), "after": _dump(after)}
    e["prev_hash"] = prev
    e["hash"] = _entry_hash(prev, e, key)
    return db.insert("audit", **e)


def verify_chain(db, key=_DB_KEY) -> dict:
    """{'ok': bool, 'broken_from': id or None, 'broken': [ids...]}: every
    entry from the first one that doesn't match its stored hash on. With
    the data key (the normal case) every entry must carry a keyed 'h2:'
    hash - an unkeyed one is a rewrite."""
    key = _key_of(db, key)
    prev = ""
    broken_from = None
    ids = []
    for e in db.rows("SELECT * FROM audit ORDER BY id"):
        ok = e["prev_hash"] == prev and _entry_hash(prev, e, key) == e["hash"]
        if not ok and broken_from is None:
            broken_from = e["id"]
        if broken_from is not None:
            ids.append(e["id"])
        prev = e["hash"]
    return {"ok": broken_from is None, "broken_from": broken_from,
            "broken": ids}


def rekey_chain(db, key: bytes) -> int:
    """Re-sign every entry with the keyed hash (once, 0.13.14 - Office
    checks the old chain first and records the result in the next entry).
    Returns entries signed."""
    prev, n = "", 0
    with db.tx():
        for e in db.rows("SELECT * FROM audit ORDER BY id"):
            h = _entry_hash(prev, e, key)
            db.conn.execute("UPDATE audit SET prev_hash = ?, hash = ? "
                            "WHERE id = ?", (prev, h, e["id"]))
            prev, n = h, n + 1
    return n


def audit_rows(db, user=None, action=None, record_type=None, since=None):
    q, p = "SELECT * FROM audit WHERE 1=1", []
    for col, v in (("user", user), ("action", action),
                   ("record_type", record_type)):
        if v:
            q += f" AND {col} = ?"
            p.append(v)
    if since:
        q += " AND ts >= ?"
        p.append(since)
    return db.rows(q + " ORDER BY id", p)


# ---- users ---------------------------------------------------------------

def add_user(db, name, email, role, password, title="", by="system") -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    with db.tx():
        uid = db.insert("users", name=name, email=email.lower(), role=role,
                        title=title, pw_hash=hash_password(password),
                        active=1, failed=0)
        audit(db, by, "create", "user", uid, None,
              {"name": name, "email": email.lower(), "role": role,
               "title": title})
    return uid


def login(db, email: str, password: str) -> dict:
    u = db.one("SELECT * FROM users WHERE email = ? AND deleted = 0",
               (email.lower(),))
    now = clock.now()
    if u is None or not u["active"]:
        audit(db, email, "login failed", "user", u["id"] if u else "",
              None, {"reason": "unknown or inactive user"})
        raise AuthError("Wrong email or password.")
    if u["locked_until"] and clock.now().isoformat() < u["locked_until"]:
        audit(db, u["name"], "login refused", "user", u["id"], None,
              {"reason": "locked", "until": u["locked_until"]})
        raise AuthError(f"Account locked until {u['locked_until'][11:16]}.")
    if not check_password(password, u["pw_hash"]):
        failed = (u["failed"] or 0) + 1
        with db.tx():
            if failed >= LOCK_AFTER:
                until = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(
                    timespec="seconds")
                db.update("users", u["id"], failed=0, locked_until=until)
                audit(db, u["name"], "lockout", "user", u["id"], None,
                      {"failed": failed, "until": until})
            else:
                db.update("users", u["id"], failed=failed)
                audit(db, u["name"], "login failed", "user", u["id"], None,
                      {"failed": failed})
        if failed >= LOCK_AFTER:
            raise AuthError(f"Too many wrong passwords: locked for "
                            f"{LOCK_MINUTES} minutes.")
        raise AuthError("Wrong email or password.")
    with db.tx():
        db.update("users", u["id"], failed=0, locked_until=None)
        if needs_rehash(u["pw_hash"]):
            db.update("users", u["id"], pw_hash=hash_password(password))
            audit(db, u["name"], "password hash upgraded", "user", u["id"],
                  None, {"rounds": PBKDF2_ROUNDS})
        audit(db, u["name"], "login", "user", u["id"])
    return db.get("users", u["id"])
