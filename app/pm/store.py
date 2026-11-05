"""A project's records, kept locally and synced with the hub.

The local copy lives in the project folder (``.quantisheet/project.json``),
so Project Center opens instantly and works with no connection. Edits are
applied locally at once and queued; ``sync()`` sends the queue and pulls
everyone else's changes. When two people change the same item, the fields
each one changed are merged (the later change to the same field wins).

A project without a hub is a plain local project: same features, numbers
given out locally, nothing shared until it is connected.
"""
import copy
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone

from .. import settings
from . import schema

log = logging.getLogger(__name__)
FILE = os.path.join(".quantisheet", "project.json")


def spec_number(text):
    """'03 30 00 Cast-in-Place Concrete' -> '03 30 00'."""
    import re
    m = re.match(r"\s*(\d{2})\s?(\d{2})\s?(\d{2})(\.\d+)?", text or "")
    if not m:
        return ""
    return f"{m.group(1)} {m.group(2)} {m.group(3)}{m.group(4) or ''}"


class StoreError(RuntimeError):
    pass


# record types whose every change is kept in the money history (P1)
MONEY = {"budget", "contract", "commitment", "event", "cost", "payapp",
         "subpay"}

# Records that are final once in one of these statuses: only the listed
# fields may still change (PM review NW-07: a certified owner pay app was
# edited and every later G702 silently changed). Corrections go on the
# next application.
LOCKED = {
    "payapp": (("Certified", "Paid"),
               {"status", "received", "received_on", "notes", "attachments",
                "thread", "certified_values", "certified", "certified_by"}),
}
# set once, on the move to Certified (or the first save of an app
# certified before 0.13.14), then never changed (Chief review Q1)
WRITE_ONCE = {"payapp": {"certified_values", "certified", "certified_by"}}


def locked_reason(coll, old, new=None):
    """Why this change to a final record is refused, or ''."""
    rule = LOCKED.get(coll)
    if not rule or not old or old.get("status") not in rule[0]:
        return ""
    label = old.get("_no") or old.get("period_to") or "this record"
    if new is None:
        return (f"{label} is {old.get('status')}: it can't be deleted.")
    if new.get("status") not in rule[0]:
        return (f"{label} is {old.get('status')}: it can't go back to "
                f"{new.get('status') or 'Draft'}. Put corrections on the "
                "next application.")
    once = WRITE_ONCE.get(coll, set())
    bad = sorted(k for k in set(new) | set(old)
                 if not k.startswith("_") and new.get(k) != old.get(k) and
                 (k not in rule[1] or
                  (k in once and old.get(k) not in (None, "", {}, []))))
    if bad:
        return (f"{label} is {old.get('status')}, so its numbers are final "
                f"({', '.join(bad)} can't change). Put corrections on the "
                "next application.")
    return ""


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Saves are coalesced: a burst of field commits writes the file once, 300 ms
# after the last change (review 3 #2). Any other store opening the same file,
# a sync, closing, and interpreter exit flush first.
SAVE_DELAY = 0.3
_DIRTY = {}                 # path -> store with an unwritten change
_DIRTY_LOCK = threading.Lock()


def flush_all():
    with _DIRTY_LOCK:
        stores = list(_DIRTY.values())
    for st in stores:
        st.flush()


import atexit  # noqa: E402
atexit.register(flush_all)


class ProjectStore:
    def __init__(self, folder):
        self.folder = os.path.abspath(folder)
        from .. import oldnames            # a job saved under the old name
        data_dir = oldnames.job_dir(self.folder)
        self.path = os.path.join(data_dir, os.path.basename(FILE))
        with _DIRTY_LOCK:
            other = _DIRTY.get(self.path)
        if other is not None:
            other.flush()
        self._timer = None
        self.lock = threading.RLock()
        self.listeners = []
        self.version = 0                  # bumped on every change
        self.last_sync = None
        self.last_error = ""
        self.last_denied = ""
        self._load()

    # ---------------------------------------------------------- disk
    def _load(self):
        self.damaged = ""
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
            if not isinstance(self.data, dict):
                raise ValueError("not a JSON object")
        except FileNotFoundError:
            self.data = {}
        except ValueError:
            bad = self.path + ".damaged"
            os.replace(self.path, bad)
            log.warning("project database damaged; moved to %s", bad)
            self.damaged = bad          # the window tells the user
            self.data = {}
        self.data.setdefault("name", os.path.basename(self.folder))
        self.data.setdefault("hub", None)       # {url, project, key}
        self.data.setdefault("seq", 0)
        self.data.setdefault("records", {})
        self.data.setdefault("pending", [])
        self.data.setdefault("next", {})
        self.data.setdefault("settings", {})

    def save(self, now=False):
        """Write the project file, at most once per SAVE_DELAY burst."""
        if now or not os.path.exists(self.path):
            return self.flush(force=True)    # the first save makes the folder
        with self.lock:
            with _DIRTY_LOCK:
                _DIRTY[self.path] = self
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(SAVE_DELAY, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self, force=False):
        """Write any unsaved change now."""
        with self.lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            with _DIRTY_LOCK:
                dirty = _DIRTY.get(self.path) is self
                if dirty:
                    del _DIRTY[self.path]
            if dirty or force:
                self._write()

    def _write(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=0)
            os.replace(tmp, self.path)

    @classmethod
    def exists(cls, folder):
        path = os.path.join(os.path.abspath(folder), FILE)
        with _DIRTY_LOCK:
            other = _DIRTY.get(path)
        if other is not None:
            other.flush()                    # created but not written yet
        if os.path.isfile(path):
            return True
        from .. import oldnames            # a job saved under the old name
        old = oldnames.job_dir_if_any(os.path.abspath(folder))
        return bool(old) and os.path.isfile(
            os.path.join(old, os.path.basename(FILE)))

    @property
    def name(self):
        return self.data["name"]

    @property
    def connected(self):
        return bool(self.data.get("hub"))

    @property
    def me(self):
        return settings.author()

    def setting(self, key, default=None):
        return self.data["settings"].get(key, default)

    def set_setting(self, key, value):
        self.data["settings"][key] = value
        self.save()

    def _changed(self, coll=None):
        self.version += 1
        for fn in list(self.listeners):
            try:
                fn(coll)
            except Exception:
                log.exception("project listener failed")

    # ---------------------------------------------------------- reads
    def coll(self, coll):
        return self.data["records"].setdefault(coll, {})

    def list(self, coll, deleted=False):
        recs = [copy.deepcopy(r) for r in self.coll(coll).values()
                if deleted or not r.get("_deleted")]
        recs.sort(key=lambda r: (r.get("_n") or 10 ** 9,
                                 r.get("_created") or ""))
        return recs

    def get(self, coll, rid):
        r = self.coll(coll).get(rid)
        return copy.deepcopy(r) if r else None

    def find(self, coll, **match):
        return [r for r in self.list(coll)
                if all(r.get(k) == v for k, v in match.items())]

    def pending_count(self):
        return len(self.data["pending"])

    # ---------------------------------------------------------- writes
    def _number(self, coll, rec):
        """Local number for a new record (replaced by the hub's when the
        project is shared, so two offline people can't both get RFI-007)."""
        t = schema.TOOLS.get(coll, {})
        n = self.data["next"].get(coll, 1)
        self.data["next"][coll] = n + 1
        rec["_n"] = n
        if self.connected:
            rec["_no"] = f"{t.get('prefix', '')}new-{n}"
            rec["_local_no"] = True
        else:
            rec["_no"] = f"{t.get('prefix', '')}{n:0{t.get('width', 3)}d}"
        sec = spec_number(rec.get("spec"))
        if t.get("number_by") == "spec" and sec:
            same = [r for r in self.list(coll)
                    if spec_number(r.get("spec")) == sec]
            rec["_no"] = f"{sec}-{len(same) + 1:03d}"
            rec.pop("_local_no", None)

    def save_record(self, coll, rec):
        """Add or update. Returns the stored record."""
        with self.lock:
            rec = copy.deepcopy(rec)
            if coll == "delay":
                # the owner contract's notice deadline (P1 tracker)
                try:
                    from .contract_terms import stamp_notice_due
                    stamp_notice_due(self, rec)
                except Exception:                         # noqa: BLE001
                    pass
            items = self.coll(coll)
            rid = rec.get("_id")
            old = items.get(rid) if rid else None
            if old is None:
                rid = rec["_id"] = rid or secrets.token_hex(8)
                rec["_coll"] = coll
                rec["_rev"] = 0
                rec["_created"] = _now()
                rec["_by"] = self.me
                self._number(coll, rec)
                changed = [k for k in rec if not k.startswith("_")]
                base = None
            else:
                why = locked_reason(coll, old, dict(old, **{
                    k: v for k, v in rec.items() if not k.startswith("_")}))
                if why:
                    raise StoreError(why)
                changed = [k for k in set(rec) | set(old)
                           if not k.startswith("_") and
                           rec.get(k) != old.get(k)]
                if not changed:
                    return copy.deepcopy(old)
                merged = dict(old)
                merged.update({k: rec.get(k) for k in changed})
                rec = merged
                base = old.get("_rev")
            rec["_updated"] = _now()
            rec["_upd_by"] = self.me
            rec["_dirty"] = True
            items[rid] = rec
            if coll == "payapp" and rec.get("status") in ("Certified",
                                                         "Paid") and \
                    not rec.get("certified_values"):
                # the numbers it was certified with, kept with it (NW-07)
                from .cost import certified_snapshot
                rec["certified_values"] = certified_snapshot(self, rid)
                rec["certified"] = rec.get("certified") or _now()
                rec["certified_by"] = rec.get("certified_by") or self.me
                changed = sorted(set(changed) | {"certified_values",
                                                 "certified",
                                                 "certified_by"})
            self._queue(coll, rid, changed, base)
            self._audit(coll, rid, rec, old, changed,
                        "create" if old is None else "change")
            self.save()
        self._changed(coll)
        return copy.deepcopy(rec)

    def delete(self, coll, rid):
        with self.lock:
            rec = self.coll(coll).get(rid)
            if not rec:
                return
            why = locked_reason(coll, rec)
            if why:
                raise StoreError(why)
            rec["_deleted"] = True
            rec["_dirty"] = True
            self._queue(coll, rid, [], rec.get("_rev"), delete=True)
            self._audit(coll, rid, rec, rec, [], "delete")
            self.save()
        self._changed(coll)

    # ---------------------------------------------------------- audit
    def _audit(self, coll, rid, rec, old, changed, action):
        """Who changed what on a money record, when, before and after (P1
        'audit trail on money records'). Append-only, each entry chained to
        the one before by a SHA-256 so a removed or edited entry shows."""
        if coll not in MONEY:
            return
        import hashlib
        import json as _j

        def val(v):
            t = _j.dumps(v, sort_keys=True, default=str)
            return t if len(t) <= 4000 else t[:4000] + "..."
        fields = [k for k in (changed or []) if not k.startswith("_")]
        if action == "create":
            fields = [k for k in rec if not k.startswith("_")]
        log = self.data.setdefault("audit", [])
        e = {"ts": _now(), "by": self.me, "coll": coll, "id": rid,
             "no": rec.get("_no") or rec.get("item") or "",
             "action": action,
             "before": {k: val((old or {}).get(k)) for k in fields}
             if action == "change" else {},
             "after": {k: val(rec.get(k)) for k in fields}}
        prev = log[-1]["hash"] if log else ""
        e["hash"] = hashlib.sha256((prev + _j.dumps(
            e, sort_keys=True)).encode("utf-8")).hexdigest()
        log.append(e)

    def audit_log(self, coll=None, rid=None):
        """The money-record history, oldest first (optionally one record)."""
        return [dict(e) for e in self.data.get("audit") or []
                if (coll is None or e["coll"] == coll) and
                (rid is None or e["id"] == rid)]

    def audit_ok(self):
        """True when no entry of the history was removed or edited."""
        import hashlib
        import json as _j
        prev = ""
        for e in self.data.get("audit") or []:
            body = {k: v for k, v in e.items() if k != "hash"}
            if hashlib.sha256((prev + _j.dumps(body, sort_keys=True))
                              .encode("utf-8")).hexdigest() != e.get("hash"):
                return False
            prev = e["hash"]
        return True

    def _queue(self, coll, rid, changed, base, delete=False):
        q = self.data["pending"]
        for p in q:                         # one queued op per record
            if p["coll"] == coll and p["id"] == rid:
                p["fields"] = sorted(set(p["fields"]) | set(changed))
                p["delete"] = p.get("delete") or delete
                return
        q.append({"coll": coll, "id": rid, "fields": sorted(changed),
                  "base": base, "delete": delete})

    # ---------------------------------------------------------- hub
    def client(self):
        from ..collab.hubclient import HubClient
        h = self.data.get("hub") or {}
        return HubClient(h.get("url"), h.get("token"))

    def connect(self, url, project, password, token=None, create=False,
                email=None):
        """Join (or create) the shared project on a hub, then send what
        this folder already has. `email`: your login, when the project uses
        logins (then `password` is your own password)."""
        from ..collab.hubclient import HubClient
        c = HubClient(url, token)
        args = dict(project=project, password=password, user=self.me)
        if email:
            args["email"] = email
        r = c.call("proj.open", **args)
        with self.lock:
            first = not self.connected
            self.data["hub"] = {"url": c.url, "token": c.token,
                                "project": r["project"], "key": r["key"],
                                "role": r.get("role", "admin"),
                                "user": r.get("user", ""),
                                "email": r.get("email", ""),
                                "logins": bool(r.get("logins"))}
            self.data["name"] = r["project"]
            if first:                       # resend everything we have
                self.data["seq"] = 0
                q = []
                for coll, items in self.data["records"].items():
                    for rid, rec in items.items():
                        rec["_dirty"] = True
                        q.append({"coll": coll, "id": rid,
                                  "fields": [k for k in rec
                                             if not k.startswith("_")],
                                  "base": None,
                                  "delete": bool(rec.get("_deleted")),
                                  "new": True})
                self.data["pending"] = q
            self.save()
        return self.sync()

    # ---------------------------------------------------------- logins
    @property
    def role(self):
        """Your role on the shared project: admin, pm, estimator, sub or
        viewer (admin for a local project)."""
        h = self.data.get("hub") or {}
        return h.get("role") or "admin"

    @property
    def can_edit(self):
        return self.role != "viewer"

    def _hub_call(self, op, **args):
        h = self.data["hub"]
        from ..collab.hubclient import HubClientError
        try:
            return self.client().call(op, project=h["project"], key=h["key"],
                                      user=self.me, **args)
        except HubClientError as e:
            raise StoreError(str(e))

    def users(self):
        return self._hub_call("user.list")["users"]

    def add_user(self, email, name, role, password):
        """Add a login. The first one turns logins on for the project: it
        must be you, as admin, and this copy switches to your login."""
        r = self._hub_call("user.add", email=email, name=name, role=role,
                           password=password)
        if r.get("key"):
            with self.lock:
                self.data["hub"].update(key=r["key"], role="admin",
                                        user=name, email=r["email"],
                                        logins=True)
                self.save()
        return r

    def set_user(self, email, **changes):
        return self._hub_call("user.set", email=email, **changes)

    def remove_user(self, email):
        return self._hub_call("user.remove", email=email)

    def change_password(self, old, new):
        r = self._hub_call("user.password", old=old, new=new)
        with self.lock:
            self.data["hub"]["key"] = r["key"]
            self.save()
        return True

    def disconnect(self):
        self.data["hub"] = None
        self.save(now=True)

    def sync(self):
        """Send queued changes, then pull everyone else's. Returns a short
        summary dict. Raises StoreError if the hub can't be reached."""
        if not self.connected:
            return {"sent": 0, "received": 0, "local": True}
        self.flush()
        from ..collab.hubclient import HubClientError
        h = self.data["hub"]
        sent = recv = conflicts = denied = 0
        try:
            with self.client().session() as s:
                while True:
                    with self.lock:
                        if not self.data["pending"]:
                            break
                        op = self.data["pending"][0]
                        rec = copy.deepcopy(self.coll(op["coll"])
                                            .get(op["id"]))
                    if rec is None:
                        with self.lock:
                            self.data["pending"].pop(0)
                        continue
                    is_new = op.get("new") or rec.get("_rev", 0) == 0
                    t = schema.TOOLS.get(op["coll"], {})
                    args = dict(project=h["project"], key=h["key"],
                                coll=op["coll"], user=self.me,
                                prefix=t.get("prefix", ""),
                                width=t.get("width", 3),
                                delete=op.get("delete", False))
                    if is_new:
                        body = {k: v for k, v in rec.items()
                                if not k.startswith("_")}
                        if t.get("number_by") == "spec":
                            args["group"] = spec_number(rec.get("spec"))
                    else:                     # only what we changed
                        body = {k: rec[k] for k in op["fields"] if k in rec}
                        args["unset"] = [k for k in op["fields"]
                                         if k not in rec]
                        args["base_rev"] = op.get("base")
                    body["_id"] = rec["_id"]
                    r = s.call("rec.put", record=body, **args)
                    if r.get("denied"):       # your role can't: undo it here
                        denied += 1
                        fields = sorted(k for k in body if k != "_id")
                        what = rec.get("_no") or op["coll"]
                        self.last_denied = (
                            f"{what} ({', '.join(fields[:6])}"
                            f"{'…' if len(fields) > 6 else ''}): "
                            f"{r['denied']}")
                        with self.lock:
                            # keep what was typed, so it isn't just lost
                            # (review 3 #30); newest 200
                            rej = self.data.setdefault("rejected", [])
                            rej.append({"coll": op["coll"], "id": op["id"],
                                        "no": rec.get("_no", ""),
                                        "values": {k: body[k]
                                                   for k in fields},
                                        "reason": r["denied"],
                                        "at": _now()})
                            del rej[:-200]
                            items = self.coll(op["coll"])
                            if r.get("current"):
                                items[op["id"]] = r["current"]
                            else:
                                items.pop(op["id"], None)
                            if self.data["pending"] and \
                                    self.data["pending"][0] is op:
                                self.data["pending"].pop(0)
                            self.save()
                        continue
                    if r.get("conflict"):     # someone else saved first:
                        conflicts += 1        # our fields go on top
                        args["base_rev"] = r["current"]["_rev"]
                        r = s.call("rec.put", record=body, **args)
                        if r.get("conflict"):
                            raise StoreError("Someone keeps changing "
                                             f"{rec.get('_no')}; try again.")
                    with self.lock:
                        self._accept(r["record"])
                        if self.data["pending"] and \
                                self.data["pending"][0] is op:
                            self.data["pending"].pop(0)
                        self.save()
                    sent += 1
                r = s.call("rec.changes", project=h["project"], key=h["key"],
                           since=self.data["seq"])
                with self.lock:
                    for rec in r["records"]:
                        if self._accept(rec, incoming=True):
                            recv += 1
                    self.data["seq"] = max(self.data["seq"], r["seq"])
                    self.save()
        except HubClientError as e:
            self.last_error = str(e)
            raise StoreError(str(e))
        self.last_sync = time.time()
        self.last_error = ""
        if sent or recv or denied:
            self._changed(None)
        return {"sent": sent, "received": recv, "conflicts": conflicts,
                "denied": denied}

    def _accept(self, rec, incoming=False):
        """Take the hub's copy of a record, unless we have unsent edits to
        it (those go out on the next sync and merge there)."""
        items = self.coll(rec["_coll"])
        mine = items.get(rec["_id"])
        ops = [p for p in self.data["pending"] if p["id"] == rec["_id"]]
        if incoming and mine is not None and mine.get("_dirty") and ops:
            merged = dict(rec)              # theirs, with our edits on top
            for p in ops:
                for k in p["fields"]:
                    if k in mine:
                        merged[k] = mine[k]
                    else:
                        merged.pop(k, None)
                p["base"] = rec["_rev"]
                p.pop("new", None)
            merged["_dirty"] = True
            items[rec["_id"]] = merged
            return True
        if mine is not None and mine.get("_rev", 0) >= rec["_rev"] and \
                not mine.get("_dirty"):
            return False
        items[rec["_id"]] = rec
        n = rec.get("_n") or 0
        if n >= self.data["next"].get(rec["_coll"], 1):
            self.data["next"][rec["_coll"]] = n + 1
        return True

    # ---------------------------------------------------------- files
    def att_dir(self):
        d = os.path.join(os.path.dirname(self.path), "attachments")
        os.makedirs(d, exist_ok=True)
        return d

    def attach(self, path, defer=False):
        """Copy a file into the project and (when shared) upload it.
        Returns the reference to keep in a record. defer=True only queues
        the upload (push_attachments sends it, off the GUI thread)."""
        import base64
        import hashlib
        import shutil
        with open(path, "rb") as f:
            data = f.read()
        sha = hashlib.sha256(data).hexdigest()
        ext = os.path.splitext(path)[1].lower()
        local = os.path.join(self.att_dir(), sha + ext)
        if not os.path.exists(local):
            shutil.copyfile(path, local)
        ref = {"name": os.path.basename(path), "sha256": sha,
               "size": len(data), "ext": ext, "by": self.me,
               "at": _now()}
        if self.connected and defer:
            with self.lock:
                q = self.data.setdefault("att_pending", [])
                if local not in q:
                    q.append(local)
            self.save()
        elif self.connected:
            h = self.data["hub"]
            try:
                self.client().call("att.put", project=h["project"],
                                   key=h["key"], name=ref["name"],
                                   data=base64.b64encode(data)
                                   .decode("ascii"))
            except Exception as e:                # sent on next sync
                log.info("attachment upload deferred: %s", e)
                self.data.setdefault("att_pending", []).append(local)
                self.save()
        return ref

    def attachment_path(self, ref):
        """Local file for an attachment, fetching it from the hub when this
        PC hasn't got it yet."""
        import base64
        local = os.path.join(self.att_dir(), ref["sha256"] +
                             (ref.get("ext") or ""))
        if os.path.exists(local):
            return local
        if not self.connected:
            raise StoreError("This attachment isn't on this PC.")
        h = self.data["hub"]
        r = self.client().call("att.get", project=h["project"],
                               key=h["key"], sha256=ref["sha256"])
        tmp = local + ".tmp"
        with open(tmp, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        os.replace(tmp, local)           # never a half-written attachment
        return local

    def push_attachments(self):
        """Upload attachments added while offline."""
        import base64
        h = self.data.get("hub")
        with self.lock:
            todo = list(self.data.get("att_pending", []))
        if not h or not todo:
            return
        done = set()
        for local in todo:
            try:
                with open(local, "rb") as f:
                    data = f.read()
                self.client().call("att.put", project=h["project"],
                                   key=h["key"],
                                   name=os.path.basename(local),
                                   data=base64.b64encode(data)
                                   .decode("ascii"))
            except FileNotFoundError:
                done.add(local)
            except Exception:
                continue
            else:
                done.add(local)
        with self.lock:              # files queued meanwhile stay queued
            self.data["att_pending"] = [
                x for x in self.data.get("att_pending", []) if x not in done]
        self.save()

    # ---------------------------------------------------------- people
    def people(self):
        """Directory names, with email and company, for pickers."""
        out = []
        for m in self.list("member"):
            out.append({"name": m.get("name", ""),
                        "email": m.get("email", ""),
                        "company": m.get("company", ""),
                        "role": m.get("role", "")})
        return out

    def email_of(self, who):
        """Email for a directory name (or the text itself if it is one)."""
        from ..mail import valid
        who = (who or "").strip()
        if valid(who):
            return who
        for m in self.list("member"):
            if m.get("name", "").strip().lower() == who.lower():
                return m.get("email") or ""
        for d in self.list("distlist"):
            if d.get("name", "").strip().lower() == who.lower():
                return "; ".join(filter(None, (self.email_of(p)
                                               for p in d.get("people") or
                                               [])))
        return ""


_OPEN = {}


def open_store(folder):
    folder = os.path.abspath(folder)
    if folder not in _OPEN:
        _OPEN[folder] = ProjectStore(folder)
    return _OPEN[folder]
