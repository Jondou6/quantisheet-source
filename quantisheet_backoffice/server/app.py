"""The self-service and punch server: a small WSGI app.

Workers sign in with their employee number and a password (PBKDF2, 5 wrong
tries lock 15 minutes) and see only their own pay stubs, PTO and contact
details. Every lookup is scoped to the signed-in worker: someone else's
stub id answers 404 and is logged. Contact changes and PTO requests wait in
an outbox until the office pulls them into HR's queue; nothing changes the
employee file here. Punches keep the phone's punch time and the time they
reached the server; a punch outside the job's geofence is accepted and
flagged. A punch photo is kept only with the worker's written consent on
file; there is no face recognition.

Everything personal is encrypted at rest with the server's own key. SSN and
bank numbers never reach the server except as last-4 masks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

from .. import security
from . import geo

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 4 * 1024 * 1024
SESSION_HOURS = 12
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (employee_no TEXT PRIMARY KEY, data TEXT,
  pw_hash TEXT, must_change INTEGER DEFAULT 1, failed INTEGER DEFAULT 0,
  locked_until TEXT, photo_consent INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS stubs (stub_id TEXT PRIMARY KEY, employee_no TEXT,
  data TEXT);
CREATE TABLE IF NOT EXISTS jobs (number TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY,
  employee_no TEXT, expires TEXT);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, kind TEXT,
  client_id TEXT UNIQUE, employee_no TEXT, data TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS log (id INTEGER PRIMARY KEY, ts TEXT, who TEXT,
  event TEXT, detail TEXT);
"""
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", "default-src 'self'; img-src 'self' data: "
     "blob:; style-src 'self' 'unsafe-inline'"),
]


class _Err(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status, self.msg = status, msg


def _hash_token(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


class ServerApp:
    def __init__(self, data_dir, key=None, office_token=None, now=None):
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        key = key or os.environ.get("QSBO_SERVER_KEY") or self._key_file()
        self.f = Fernet(key.encode() if isinstance(key, str) else key)
        tok = office_token or os.environ.get("QSBO_OFFICE_TOKEN") or ""
        if len(tok) < 24:
            raise ValueError("set QSBO_OFFICE_TOKEN (24+ random characters)")
        self.office_hash = _hash_token(tok)
        self.now = now or (lambda: datetime.now().astimezone())
        self.lock = threading.Lock()
        self.db = sqlite3.connect(os.path.join(data_dir, "selfservice.sqlite"),
                                  check_same_thread=False,
                                  isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _key_file(self):
        """Sealed in the OS user's profile. data_dir/server.key is a stub,
        not the key (QS-025)."""
        from ..r111.paykeys import server_key
        return server_key(self.data_dir)

    # ---- helpers -------------------------------------------------------
    def enc(self, obj) -> str:
        return self.f.encrypt(json.dumps(obj).encode("utf-8")).decode("ascii")

    def dec(self, s):
        return json.loads(self.f.decrypt(s.encode("ascii")).decode("utf-8"))

    def iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def log(self, who, event, detail=""):
        self.db.execute("INSERT INTO log (ts, who, event, detail) VALUES "
                        "(?,?,?,?)", (self.iso(), who, event, detail))

    def logs(self, event=None):
        q = "SELECT * FROM log" + (" WHERE event = ?" if event else "")
        return [dict(r) for r in self.db.execute(q + " ORDER BY id",
                                                  (event,) if event else ())]

    # ---- WSGI ----------------------------------------------------------
    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/") or "/"
        try:
            with self.lock:
                status, body, ctype = self.route(method, path, environ)
        except _Err as e:
            status, body, ctype = e.status, json.dumps({"error": e.msg}), \
                "application/json"
        if isinstance(body, str):
            body = body.encode("utf-8")
        headers = [("Content-Type", ctype),
                   ("Content-Length", str(len(body))),
                   ("Cache-Control", "no-store")] + SECURITY_HEADERS
        start_response(status, headers)
        return [body]

    def _body(self, environ) -> dict:
        try:
            n = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            raise _Err("413 Payload Too Large", "too large")
        raw = environ["wsgi.input"].read(n) if n else b"{}"
        try:
            v = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise _Err("400 Bad Request", "not JSON") from None
        if not isinstance(v, dict):
            raise _Err("400 Bad Request", "expected an object")
        return v

    def route(self, method, path, environ):
        j = "application/json"
        if method == "GET" and path in ("/", "/index.html"):
            return "200 OK", self._static("index.html"), "text/html; charset=utf-8"
        if method == "GET" and path in ("/punch", "/punch.html"):
            return "200 OK", self._static("punch.html"), "text/html; charset=utf-8"
        if method == "GET" and path == "/app.js":
            return "200 OK", self._static("app.js"), "text/javascript"
        if method == "GET" and path == "/health":
            return "200 OK", "ok", "text/plain"
        if path.startswith("/office/"):
            self._office_auth(environ)
            return "200 OK", json.dumps(self.office(method, path[8:], environ)), j
        if method == "POST" and path == "/api/login":
            return "200 OK", json.dumps(self.login(
                self._body(environ), environ.get("REMOTE_ADDR") or "")), j
        if path.startswith("/api/"):
            who = self._worker(environ)
            return "200 OK", json.dumps(self.api(method, path[5:], who,
                                                 environ)), j
        raise _Err("404 Not Found", "not found")

    def _static(self, name):
        with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
            return fh.read()

    # ---- auth ----------------------------------------------------------
    def _office_auth(self, environ):
        h = environ.get("HTTP_AUTHORIZATION", "")
        tok = h[len("Office "):] if h.startswith("Office ") else ""
        if not tok or not hmac.compare_digest(_hash_token(tok),
                                              self.office_hash):
            self.log("?", "office auth failed")
            raise _Err("401 Unauthorized", "office token required")

    def _worker(self, environ) -> str:
        h = environ.get("HTTP_AUTHORIZATION", "")
        tok = h[len("Bearer "):] if h.startswith("Bearer ") else ""
        r = self.db.execute("SELECT * FROM sessions WHERE token_hash = ?",
                            (_hash_token(tok),)).fetchone() if tok else None
        if r is None or r["expires"] < self.iso():
            raise _Err("401 Unauthorized", "please sign in")
        return r["employee_no"]

    # Wrong passwords lock out the ADDRESS they come from for 15 minutes
    # after 5 tries (per account), so someone who only knows an employee
    # number can't lock the worker out from their own phone; the account
    # itself locks only after ACCOUNT_LOCK_AFTER failures from anywhere
    # (many addresses guessing at once). Threat model T-013.
    ACCOUNT_LOCK_AFTER = 50

    def login(self, b, src="") -> dict:
        no = str(b.get("employee_no", "")).strip()
        pw = str(b.get("password", ""))
        fails = self.__dict__.setdefault("_src_fails", {})
        key = (no, src)
        now = self.now()
        f = fails.get(key)
        if f and f[1] and f[1] > now:
            self.log(no, "login while locked (this address)")
            raise _Err("403 Forbidden", "locked for 15 minutes after 5 wrong "
                                        "passwords")
        a = self.db.execute("SELECT * FROM accounts WHERE employee_no = ? AND "
                            "active = 1", (no,)).fetchone()
        if a is not None and a["locked_until"] and a["locked_until"] > self.iso():
            self.log(no, "login while locked")
            raise _Err("403 Forbidden", "locked for 15 minutes after many "
                                        "wrong passwords")
        if a is None or not a["pw_hash"] or \
                not security.check_password(pw, a["pw_hash"]):
            n = (f[0] if f and not (f[1] and f[1] <= now) else 0) + 1
            fails[key] = (0 if n >= security.LOCK_AFTER else n,
                          now + timedelta(minutes=security.LOCK_MINUTES)
                          if n >= security.LOCK_AFTER else None)
            if a is not None:
                failed = a["failed"] + 1
                until = (now + timedelta(minutes=security.LOCK_MINUTES)
                         ).isoformat(timespec="seconds") \
                    if failed >= self.ACCOUNT_LOCK_AFTER else None
                self.db.execute("UPDATE accounts SET failed = ?, locked_until "
                                "= ? WHERE employee_no = ?",
                                (0 if until else failed, until, no))
            self.log(no or "?", "login failed")
            raise _Err("401 Unauthorized", "wrong employee number or password")
        fails.pop(key, None)
        if security.needs_rehash(a["pw_hash"]):
            self.db.execute("UPDATE accounts SET pw_hash = ? WHERE "
                            "employee_no = ?",
                            (security.hash_password(pw), no))
        tok = secrets.token_urlsafe(32)
        exp = (self.now() + timedelta(hours=SESSION_HOURS)).isoformat(
            timespec="seconds")
        self.db.execute("UPDATE accounts SET failed = 0, locked_until = NULL "
                        "WHERE employee_no = ?", (no,))
        self.db.execute("INSERT INTO sessions VALUES (?,?,?)",
                        (_hash_token(tok), no, exp))
        self.log(no, "login")
        return {"token": tok, "must_change": bool(a["must_change"])}

    # ---- worker API ----------------------------------------------------
    def _account(self, no):
        a = self.db.execute("SELECT * FROM accounts WHERE employee_no = ?",
                            (no,)).fetchone()
        return dict(a, data=self.dec(a["data"]))

    def _queue(self, kind, no, data, client_id=None):
        cid = client_id or secrets.token_hex(12)
        try:
            self.db.execute("INSERT INTO outbox (kind, client_id, employee_no, "
                            "data, created) VALUES (?,?,?,?,?)",
                            (kind, cid, no, self.enc(data), self.iso()))
        except sqlite3.IntegrityError:
            return cid, False                 # already have it (re-sync)
        return cid, True

    def api(self, method, path, no, environ):
        parts = [p for p in path.split("/") if p]
        if method == "POST" and parts == ["password"]:
            b = self._body(environ)
            a = self._account(no)
            if not security.check_password(str(b.get("old", "")), a["pw_hash"]):
                raise _Err("403 Forbidden", "the current password is wrong")
            new = str(b.get("new", ""))
            if len(new) < 10:
                raise _Err("400 Bad Request", "use at least 10 characters")
            self.db.execute("UPDATE accounts SET pw_hash = ?, must_change = 0 "
                            "WHERE employee_no = ?",
                            (security.hash_password(new), no))
            self.log(no, "password changed")
            return {"ok": True}
        if method == "GET" and parts == ["stubs"]:
            rows = self.db.execute("SELECT * FROM stubs WHERE employee_no = ?",
                                   (no,)).fetchall()
            out = []
            for r in rows:
                d = self.dec(r["data"])
                out.append({"id": r["stub_id"], "period": d["period"],
                            "pay_date": d["pay_date"], "net": d["net"]})
            return sorted(out, key=lambda x: x["pay_date"], reverse=True)
        if method == "GET" and len(parts) == 2 and parts[0] == "stubs":
            r = self.db.execute("SELECT * FROM stubs WHERE stub_id = ? AND "
                                "employee_no = ?", (parts[1], no)).fetchone()
            if r is None:
                self.log(no, "stub not found",
                         f"asked for {parts[1][:64]!r}")
                raise _Err("404 Not Found", "not found")
            return dict(self.dec(r["data"]), id=r["stub_id"])
        if method == "GET" and parts == ["me"]:
            a = self._account(no)
            info = a["data"]
            pending = [self.dec(r["data"]) for r in self.db.execute(
                "SELECT data FROM outbox WHERE employee_no = ? AND kind = "
                "'address_change'", (no,))]
            return {"name": info.get("name"), "employee_no": no,
                    "address": info.get("address", ""),
                    "phone": info.get("phone", ""),
                    "email": info.get("email", ""),
                    "ssn": info.get("ssn_mask", ""),
                    "bank": info.get("bank_mask", ""),
                    "waiting_for_hr": pending}
        if method == "POST" and parts == ["me"]:
            b = self._body(environ)
            field = b.get("field")
            if field not in ("address", "phone", "email"):
                raise _Err("400 Bad Request", "you can change address, phone "
                                              "or email")
            value = str(b.get("value", ""))[:500]
            cid, _ = self._queue("address_change", no,
                                 {"field": field, "value": value})
            self.log(no, "change requested", field)
            return {"ok": True, "status": "waiting for HR", "id": cid}
        if method == "GET" and parts == ["pto"]:
            a = self._account(no)
            reqs = [self.dec(r["data"]) for r in self.db.execute(
                "SELECT data FROM outbox WHERE employee_no = ? AND kind = "
                "'pto_request'", (no,))]
            return {"balance": a["data"].get("pto", ""),
                    "requests": a["data"].get("pto_requests", []) + [
                        dict(r, status="sent to the office") for r in reqs]}
        if method == "POST" and parts == ["pto"]:
            b = self._body(environ)
            req = {k: str(b.get(k, ""))[:200] for k in
                   ("date_from", "date_to", "hours_per_day", "note")}
            for k in ("date_from", "date_to"):
                try:
                    datetime.strptime(req[k], "%Y-%m-%d")
                except ValueError:
                    raise _Err("400 Bad Request", f"{k} must be YYYY-MM-DD") \
                        from None
            cid, _ = self._queue("pto_request", no, req)
            self.log(no, "pto requested")
            return {"ok": True, "id": cid}
        if method == "GET" and parts == ["jobs"]:
            return [self.dec(r["data"]) for r in
                    self.db.execute("SELECT data FROM jobs ORDER BY number")]
        if method == "POST" and parts == ["punch"]:
            return self.punch(no, self._body(environ))
        raise _Err("404 Not Found", "not found")

    def punch(self, no, b) -> list[dict]:
        a = self._account(no)
        out = []
        for p in (b.get("punches") or [])[:200]:
            if not isinstance(p, dict):
                continue
            cid = str(p.get("id") or "")[:64]
            if not cid:
                raise _Err("400 Bad Request", "each punch needs an id")
            try:
                t = datetime.fromisoformat(str(p.get("time")))
            except ValueError:
                raise _Err("400 Bad Request", "punch time must be ISO "
                                              "date-time") from None
            job = self.db.execute("SELECT data FROM jobs WHERE number = ?",
                                  (str(p.get("job", "")),)).fetchone()
            fence = self.dec(job["data"]).get("geofence") if job else None
            lat, lon = p.get("lat"), p.get("lon")
            dist, inside = geo.check(fence, lat, lon)
            photo, note = p.get("photo"), ""
            if photo and not a["photo_consent"]:
                photo, note = None, "photo not kept: no written consent on file"
            if photo and len(photo) > 3_000_000:
                photo, note = None, "photo too large"
            rec = {"kind": "in" if p.get("kind") != "out" else "out",
                   "time": t.isoformat(timespec="seconds"),
                   "synced": self.iso(), "job": str(p.get("job", "")),
                   "cost_code": str(p.get("cost_code", ""))[:40],
                   "lat": None if lat in (None, "") else str(lat),
                   "lon": None if lon in (None, "") else str(lon),
                   "accuracy": None if p.get("accuracy") in (None, "")
                   else str(p.get("accuracy")),
                   "distance_m": dist, "inside": inside, "photo": photo,
                   "photo_note": note,
                   "device": str(p.get("device", ""))[:80]}
            _, new = self._queue("punch", no, rec, client_id=f"punch:{no}:{cid}")
            out.append({"id": cid, "stored": True, "duplicate": not new,
                        "distance_m": dist, "inside": inside,
                        "synced": rec["synced"], "photo_note": note})
        self.log(no, "punches synced", str(len(out)))
        return out

    # ---- office API ----------------------------------------------------
    def office(self, method, path, environ):
        if method == "POST" and path == "publish":
            b = self._body(environ)
            for acc in b.get("accounts") or []:
                no = str(acc["employee_no"])
                old = self.db.execute("SELECT * FROM accounts WHERE "
                                      "employee_no = ?", (no,)).fetchone()
                data = self.enc(acc.get("info") or {})
                if old is None:
                    self.db.execute(
                        "INSERT INTO accounts (employee_no, data, pw_hash, "
                        "must_change, photo_consent, active) VALUES "
                        "(?,?,?,?,?,?)", (no, data, acc.get("pw_hash"), 1,
                                          1 if acc.get("photo_consent") else 0,
                                          1 if acc.get("active", True) else 0))
                else:
                    self.db.execute(
                        "UPDATE accounts SET data = ?, photo_consent = ?, "
                        "active = ? WHERE employee_no = ?",
                        (data, 1 if acc.get("photo_consent") else 0,
                         1 if acc.get("active", True) else 0, no))
                    if acc.get("pw_hash"):
                        self.db.execute("UPDATE accounts SET pw_hash = ?, "
                                        "must_change = 1, failed = 0, "
                                        "locked_until = NULL WHERE "
                                        "employee_no = ?",
                                        (acc["pw_hash"], no))
                if not acc.get("active", True):
                    self.db.execute("DELETE FROM sessions WHERE employee_no = ?",
                                    (no,))
            for s in b.get("stubs") or []:
                self.db.execute("INSERT OR REPLACE INTO stubs VALUES (?,?,?)",
                                (s["id"], str(s["employee_no"]),
                                 self.enc(s["data"])))
            if "jobs" in b:
                self.db.execute("DELETE FROM jobs")
                for jb in b["jobs"]:
                    self.db.execute("INSERT INTO jobs VALUES (?,?)",
                                    (str(jb["number"]), self.enc(jb)))
            self.log("office", "publish",
                     f"{len(b.get('accounts') or [])} accounts, "
                     f"{len(b.get('stubs') or [])} stubs")
            return {"ok": True}
        if method == "GET" and path == "pull":
            rows = self.db.execute("SELECT * FROM outbox ORDER BY id").fetchall()
            return [{"id": r["id"], "kind": r["kind"],
                     "client_id": r["client_id"],
                     "employee_no": r["employee_no"], "created": r["created"],
                     "data": self.dec(r["data"])} for r in rows]
        if method == "POST" and path == "ack":
            ids = [int(i) for i in self._body(environ).get("ids") or []]
            self.db.executemany("DELETE FROM outbox WHERE id = ?",
                                [(i,) for i in ids])
            self.log("office", "ack", str(len(ids)))
            return {"ok": True, "removed": len(ids)}
        raise _Err("404 Not Found", "not found")


def create_app(data_dir=None, **kw) -> ServerApp:
    return ServerApp(data_dir or os.environ.get("QSBO_SERVER_DATA", "/data"),
                     **kw)
