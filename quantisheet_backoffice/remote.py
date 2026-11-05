"""Desktop side of the optional self-service / punch server (P2-07, P2-08).

Nothing moves by itself: Publish and Pull run only when a person clicks
them. Publish sends what self-service needs (name, contact details, last-4
masks, PTO balance, pay stubs from the provider's register, jobs, cost
codes and geofences). Pull brings back contact-change requests (into HR's
queue; the employee file changes only when HR approves), PTO requests
(into PTO Requests) and punches (kept with their punch time and the time
they reached the server; outside-geofence punches are flagged).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import urllib.request
from datetime import datetime

from . import cents, clock, hr, jobs, pto, provider, security, store
from .server import geo


class RemoteError(RuntimeError):
    pass


# ---- transports -------------------------------------------------------------

class HttpTransport:
    """HTTPS to the company's own server (urllib; no third-party service)."""

    def __init__(self, url, token, timeout=30):
        # the scheme and host are read, not prefix-matched: an address like
        # http://localhost.example.com is not this PC (threat model T-012)
        from urllib.parse import urlsplit
        u = urlsplit(url.strip())
        local = u.scheme == "http" and (u.hostname or "") in (
            "127.0.0.1", "localhost", "::1")
        if not (u.scheme == "https" and u.hostname) and not local:
            raise RemoteError("Use an https:// address for the server.")
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type":
                                              "application/json",
                                              "Authorization":
                                              f"Office {self.token}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))


class WsgiTransport:
    """Calls a WSGI app in the same process (tests, local trial)."""

    def __init__(self, app, token=None, auth="Office"):
        self.app, self.token, self.auth = app, token, auth

    def request(self, method, path, body=None, token=None, auth=None):
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        env = {"REQUEST_METHOD": method, "PATH_INFO": path,
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
               "HTTP_AUTHORIZATION": f"{auth or self.auth} "
                                     f"{token or self.token}"}
        out = {}

        def start(status, headers):
            out["status"] = status
        body_out = b"".join(self.app(env, start))
        out["body"] = json.loads(body_out.decode("utf-8")) \
            if body_out[:1] in (b"{", b"[") else body_out.decode("utf-8")
        if not out["status"].startswith("200"):
            raise RemoteError(f"{out['status']}: "
                              f"{out['body'].get('error') if isinstance(out['body'], dict) else out['body']}")
        return out["body"]


# ---- settings ---------------------------------------------------------------

def configure(office, url, token) -> None:
    office.require("remote.sync", "remote_settings", 1)
    row = office.db.one("SELECT id FROM remote_settings WHERE deleted = 0")
    with office.db.tx():
        if row:
            office.db.update("remote_settings", row["id"], url=url,
                             token=office.crypto.encrypt(token))
        else:
            office.db.insert("remote_settings", url=url,
                             token=office.crypto.encrypt(token))
        office.audit("configure", "remote_settings", 1, None, {"url": url})


def _transport(office, transport):
    if transport is not None:
        return transport
    row = office.db.one("SELECT * FROM remote_settings WHERE deleted = 0")
    if not row or not row["url"]:
        raise RemoteError("Set up the self-service server first.")
    return HttpTransport(row["url"], office.crypto.decrypt(row["token"]))


def set_password(office, employee_id, temp_password) -> None:
    """A one-time password for self-service; the worker must change it."""
    office.require("hr.edit", "employee", employee_id)
    if len(temp_password) < 10:
        raise RemoteError("Use at least 10 characters.")
    with office.db.tx():
        office.db.update("employees", employee_id,
                         remote_pw=security.hash_password(temp_password))
        office.audit("self-service password", "employee", employee_id)


def set_geofence(office, job_id, lat, lon, radius_m, photo_required=False):
    office.require("hr.edit", "job", job_id)
    old = office.db.one("SELECT id FROM geofences WHERE job_id = ?", (job_id,))
    with office.db.tx():
        f = dict(lat=str(lat), lon=str(lon), radius_m=int(radius_m),
                 photo_required=1 if photo_required else 0)
        if old:
            office.db.update("geofences", old["id"], **f)
        else:
            office.db.insert("geofences", job_id=job_id, **f)
        office.audit("geofence", "job", job_id, None, f)


def _fence(office, job_id):
    return office.db.one("SELECT * FROM geofences WHERE job_id = ? AND "
                         "deleted = 0", (job_id,))


def stub_id(office, register_id) -> str:
    """Stable, unguessable stub id (not the database row number)."""
    import hmac
    import secrets
    row = office.db.one("SELECT * FROM remote_settings WHERE deleted = 0")
    if row is None or not row["stub_secret"]:
        new = office.crypto.encrypt(secrets.token_hex(32))
        with office.db.tx():
            if row is None:
                office.db.insert("remote_settings", stub_secret=new)
            else:
                office.db.update("remote_settings", row["id"], stub_secret=new)
        row = office.db.one("SELECT * FROM remote_settings WHERE deleted = 0")
    key = office.crypto.decrypt(row["stub_secret"]).encode()
    return hmac.new(key, f"stub:{register_id}".encode(),
                    hashlib.sha256).hexdigest()[:32]


# ---- publish / pull ---------------------------------------------------------

def payload(office) -> dict:
    accounts, stubs = [], []
    for e in office.db.rows("SELECT * FROM employees WHERE deleted = 0 AND "
                            "employee_no IS NOT NULL AND employee_no != ''"):
        info = {"name": e["name"], "address": e["address"] or "",
                "phone": e["phone"] or "", "email": e["email"] or "",
                "ssn_mask": hr._masked("ssn", office.crypto.decrypt(e["ssn"]))
                if e["ssn"] else "",
                "bank_mask": hr._masked("bank_account", office.crypto.decrypt(
                    e["bank_account"])) if e["bank_account"] else ""}
        if e["pto_policy_id"]:
            info["pto"] = pto.balance(office, e["id"])["text"]
            info["pto_requests"] = [
                {"date_from": r["date_from"], "date_to": r["date_to"],
                 "hours": cents.hours_text(r["total"]), "status": r["status"]}
                for r in office.db.rows("SELECT * FROM pto_requests WHERE "
                                        "employee_id = ? AND deleted = 0",
                                        (e["id"],))]
        accounts.append({"employee_no": e["employee_no"], "info": info,
                         "pw_hash": e["remote_pw"],
                         "photo_consent": bool(e["photo_consent_on"]),
                         "active": e["status"] != "Terminated"})
        if e["worker_id"]:
            for r in provider.stubs_for(office, e["worker_id"]):
                stubs.append({"id": stub_id(office, r["id"]),
                              "employee_no": e["employee_no"],
                              "data": {"period": f"{r['start']} to {r['end']}",
                                       "pay_date": r["pay_date"],
                                       "gross": cents.text(r["gross"]),
                                       "taxes": {k: cents.text(v) for k, v in
                                                 r["taxes"].items()},
                                       "deductions": {k: cents.text(v) for k, v
                                                      in r["deductions"].items()},
                                       "net": cents.text(r["net"]),
                                       "reference": r["reference"]}})
    jb = []
    for j in jobs.jobs(office):
        f = _fence(office, j["id"])
        jb.append({"number": j["number"], "name": j["name"],
                   "cost_codes": sorted(jobs.cost_codes(office, j["id"])),
                   "geofence": {"lat": f["lat"], "lon": f["lon"],
                                "radius_m": f["radius_m"]} if f else None,
                   "photo_required": bool(f and f["photo_required"])})
    return {"accounts": accounts, "stubs": stubs, "jobs": jb}


def publish(office, transport=None) -> dict:
    office.require("remote.sync", "remote", "publish")
    t = _transport(office, transport)
    p = payload(office)
    t.request("POST", "/office/publish", p)
    with office.db.tx():
        office.db.conn.execute("UPDATE employees SET remote_pw = NULL WHERE "
                               "remote_pw IS NOT NULL")
        office.audit("publish", "remote", "", None,
                     {"accounts": len(p["accounts"]), "stubs": len(p["stubs"]),
                      "jobs": len(p["jobs"])})
    return {"accounts": len(p["accounts"]), "stubs": len(p["stubs"]),
            "jobs": len(p["jobs"])}


def pull(office, transport=None) -> dict:
    office.require("remote.sync", "remote", "pull")
    t = _transport(office, transport)
    items = t.request("GET", "/office/pull")
    done, counts, problems = [], {"changes": 0, "pto": 0, "punches": 0}, []
    for it in items:
        e = hr.by_number(office, it["employee_no"])
        if e is None:
            problems.append(f"employee {it['employee_no']} is not known; "
                            f"left on the server")
            continue
        d = it["data"]
        try:
            if it["kind"] == "address_change":
                hr.request_change(office, e["id"], d["field"], d["value"],
                                  source="self-service",
                                  remote_id=it["client_id"])
                counts["changes"] += 1
            elif it["kind"] == "pto_request":
                pto.request(office, e["id"], d["date_from"], d["date_to"],
                            d.get("hours_per_day") or "8",
                            source="self-service", remote_id=it["client_id"],
                            note=d.get("note", ""))
                counts["pto"] += 1
            elif it["kind"] == "punch":
                _store_punch(office, e, it["client_id"], d)
                counts["punches"] += 1
        except (ValueError, KeyError) as ex:
            problems.append(f"{it['kind']} from {it['employee_no']}: {ex}")
            continue
        done.append(it["id"])
    if done:
        t.request("POST", "/office/ack", {"ids": done})
    office.audit("pull", "remote", "", None, dict(counts,
                                                  problems=len(problems)))
    return dict(counts, problems=problems)


def _store_punch(office, e, remote_id, d):
    if office.db.one("SELECT id FROM punches WHERE remote_id = ?", (remote_id,)):
        return
    j = office.db.one("SELECT id FROM jobs WHERE number = ? AND deleted = 0",
                      (d.get("job") or "",))
    dist, inside = d.get("distance_m"), d.get("inside")
    fence = _fence(office, j["id"]) if j else None
    if fence and d.get("lat") not in (None, ""):
        dist, inside = geo.check(fence, d["lat"], d["lon"])
    photo = None
    if d.get("photo"):
        raw = d["photo"].split(",", 1)[-1]
        folder = os.path.join(office.documents_folder(), "punch_photos")
        os.makedirs(folder, exist_ok=True)
        photo = os.path.join(folder, hashlib.sha256(remote_id.encode())
                             .hexdigest()[:24] + ".bin")
        with open(photo, "wb") as fh:
            fh.write(office.crypto._f.encrypt(base64.b64decode(raw)))
    with office.db.tx():
        pid = office.db.insert(
            "punches", remote_id=remote_id, worker_id=e["worker_id"],
            employee_no=e["employee_no"], job_id=j["id"] if j else None,
            job_number=d.get("job"), cost_code=d.get("cost_code"),
            kind=d.get("kind"), punch_time=d["time"], synced_at=d["synced"],
            lat=d.get("lat"), lon=d.get("lon"), accuracy=d.get("accuracy"),
            distance_m=dist, inside=None if inside is None else int(inside),
            photo_path=photo, photo_note=d.get("photo_note") or "",
            device_id=d.get("device"), status="New")
        office.audit("punch", "punch", pid, None,
                     {"worker": e["worker_id"], "time": d["time"],
                      "synced": d["synced"], "inside": inside})


# ---- office review ------------------------------------------------------------

def _hm(iso) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M")


def punches(office, date=None) -> list[dict]:
    q = ("SELECT p.*, w.name FROM punches p LEFT JOIN workers w ON w.id = "
         "p.worker_id WHERE p.deleted = 0")
    args = []
    if date:
        q += " AND substr(p.punch_time, 1, 10) = ?"
        args.append(str(date))
    rows = office.db.rows(q + " ORDER BY p.punch_time", args)
    for r in rows:
        late = r["punch_time"][:16] != r["synced_at"][:16]
        r["when"] = f"{r['kind']} {_hm(r['punch_time'])}" + (
            f" (synced {_hm(r['synced_at'])})" if late else "")
        r["flags"] = _flags(office, r)
    return rows


def _flags(office, r) -> list[str]:
    out = []
    fence = _fence(office, r["job_id"]) if r["job_id"] else None
    if fence and r["inside"] == 0:
        out.append(f"outside the {fence['radius_m']} m geofence "
                   f"({r['distance_m']} m away)")
    if fence and r["lat"] in (None, ""):
        out.append("no location")
    if fence and fence["photo_required"] and not r["photo_path"]:
        out.append("no photo" + (f": {r['photo_note']}" if r["photo_note"]
                                 else ""))
    if not r["job_id"]:
        out.append(f"unknown job {r['job_number'] or ''}".strip())
    return out


def exceptions(office) -> list[dict]:
    """Punches for the approver to look at (they are accepted either way)."""
    return [r for r in punches(office) if r["flags"]]


def punches_to_time_for_day(office, date) -> list[int]:
    """Every worker's New punches on `date` paired into Draft time lines
    (r38: the Time page's Convert Punches button). An unpaired "in" stays
    New; a day already converted adds nothing."""
    office.require("time.edit", "punch", str(date))
    wids = []
    for r in punches(office, date):
        if r["status"] == "New" and r["worker_id"] and \
                r["worker_id"] not in wids:
            wids.append(r["worker_id"])
    out = []
    for wid in wids:
        out += punches_to_time(office, wid, date)
    return out


def punches_to_time(office, worker_id, date) -> list[int]:
    """Pair the day's in/out punches into Draft time lines (P1-05)."""
    from . import timeentry
    office.require("time.edit", "punch", worker_id)
    rows = [r for r in punches(office, date) if r["worker_id"] == worker_id
            and r["status"] == "New"]
    ids, open_in = [], None
    for r in rows:
        if r["kind"] == "in":
            open_in = r
        elif open_in is not None:
            a = datetime.fromisoformat(open_in["punch_time"])
            b = datetime.fromisoformat(r["punch_time"])
            mins = int((b - a).total_seconds() // 60)
            h = cents.round_half_up(cents.D(mins) / 60, "0.01")
            lid = timeentry.add_line(office, worker_id, str(date),
                                     open_in["job_id"], open_in["cost_code"],
                                     str(h), source="punch",
                                     source_key=f"punch:{open_in['id']}")
            with office.db.tx():
                for p in (open_in, r):
                    office.db.update("punches", p["id"], status="Used",
                                     time_line_id=lid)
            ids.append(lid)
            open_in = None
    return ids
