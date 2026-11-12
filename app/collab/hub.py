"""QuantiSheet hub: the storage side of the relay.

Runs inside both relays (Live Collaboration's own relay and the hostable
server/relay_server.py). Edit this file only: server/hub.py is generated
from it by tools/sync_server.py, and a test fails if they differ. It keeps, in a data folder:

* signature envelopes - pages to sign, the fields each signer fills, and an
  audit trail (who, when, from which address);
* project files - every version of every file, check-out locks and an
  activity feed;
* the project database - RFIs, submittals, punch items, daily logs,
  meetings, budget and cost records - with attachments (photos, PDFs),
  shared by QuantiSheet and the phone page.

Clients talk to it over the same WebSocket port as the relay: they send
``{"type": "api"}`` as their hello, then ``{"id", "op", "args"}`` requests,
each answered by ``{"type": "api_reply", "id", "ok", "result"|"error"}``.
Page images and photos are fetched with plain HTTP GETs under /hub/.

Standard library only, so the server image needs nothing extra.
"""
import logging
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

MAX_CHUNK = 4 * 1024 * 1024
MAX_IMAGE = 2 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024 * 1024
FIELD_KINDS = ("signature", "initials", "date", "name", "text", "checkbox")
SIGNER_OPS = ("sign.open", "sign.submit", "sign.decline", "bid.open",
              "bid.respond")
OPEN_OPS = SIGNER_OPS + ("proj.open",)
# what a phone (project password, no relay token) may do
PHONE_OPS = ("proj.files", "proj.get_chunk", "proj.activity", "rec.changes",
             "rec.put", "att.put", "att.get")


# ---------------------------------------------------------------- logins
# A project can have its own user accounts (email + password) with roles.
# Until the first account is made, the shared project password works as
# before and everyone is treated as an admin.
ROLES = ("admin", "pm", "accountant", "super", "estimator", "sub",
         "viewer")
ROLE_NAMES = {"admin": "Admin", "pm": "Project manager",
              "accountant": "Accountant", "super": "Superintendent",
              "estimator": "Estimator", "sub": "Subcontractor",
              "viewer": "Viewer (read only)"}
READ_OPS = ("proj.files", "proj.get_chunk", "proj.activity", "rec.changes",
            "att.get", "user.me", "user.password")
STAFF_OPS = ("proj.lock", "proj.unlock", "proj.put_begin", "proj.put_chunk",
             "proj.put_end", "bid.invite", "bid.unseal")
# what a sub may add or change (their own, or ones assigned to them)
SUB_COLLS = ("rfi", "submittal", "punch", "observation", "daily", "issue",
             "timecard", "subpay")
# P1 roles (0.13.14): the accountant keeps the money records and is one
# who may certify an owner pay app; the superintendent runs the field
# records and can't touch pay apps or other money records
MONEY_COLLS = ("budget", "contract", "commitment", "event", "cost",
               "payapp", "subpay")
SUPER_COLLS = SUB_COLLS + ("inspection", "meeting", "delay", "permit",
                           "activity", "expedite")
SUBPAY_REVIEWED = ("Approved", "Rejected", "Billed")
ESTIMATOR_COLLS = ("bidpkg", "budget", "event", "rfi", "issue", "meeting",
                   "member", "distlist", "transmittal", "submittal",
                   "subpkg", "activity", "timecard", "scopesheet")


class HubError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _unb64(text, limit=None):
    if not isinstance(text, str):
        raise HubError("Expected base64 data.")
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    try:
        data = base64.b64decode(text, validate=True)
    except Exception:
        raise HubError("Bad base64 data.")
    if limit and len(data) > limit:
        raise HubError("Data too large.")
    return data


def _slug(name, what="name"):
    name = str(name or "").strip()
    if not name or len(name) > 120:
        raise HubError(f"Bad {what}.")
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    if not s:
        raise HubError(f"Bad {what}.")
    return s


def _pw_hash(salt, password):
    return hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"),
                               salt, 100_000)


def _text(v, n=500):
    return str(v if v is not None else "")[:n]


class Hub:
    def __init__(self, data_dir):
        self.dir = os.path.abspath(data_dir)
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.RLock()
        sp = os.path.join(self.dir, "secret")
        if not os.path.exists(sp):
            with open(sp, "wb") as f:
                f.write(secrets.token_bytes(32))
        with open(sp, "rb") as f:
            self.secret = f.read()
        self.uploads = {}
        self._op = ""
        self._caller = None

    # ---------------------------------------------------------- storage
    def _p(self, *parts):
        base = os.path.realpath(self.dir)
        full = os.path.realpath(os.path.join(base, *parts))
        try:
            inside = os.path.commonpath([full, base]) == base
        except ValueError:                 # another drive on Windows
            inside = False
        if not inside:
            raise HubError("Bad path.")
        return full

    def _load(self, path, default=None):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except ValueError:
            raise HubError("Stored data is damaged.")

    def _save(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)

    def _mac(self, *parts):
        return hmac.new(self.secret, "\x1f".join(parts).encode("utf-8"),
                        hashlib.sha256).hexdigest()[:40]

    # ---------------------------------------------------------- dispatch
    def call(self, op, args=None, ctx=None, authed=True):
        """Run one request. ``authed`` = the caller gave the relay token
        (or none is required); without it only signer and phone operations
        are allowed."""
        args = args if isinstance(args, dict) else {}
        ctx = ctx or {}
        fn = getattr(self, "op_" + str(op).replace(".", "_"), None)
        if fn is None:
            raise HubError(f"Unknown operation: {op}")
        if not authed and op not in OPEN_OPS and op not in PHONE_OPS:
            raise HubError("Bad relay token.")
        with self.lock:
            self._op = str(op)
            self._caller = None
            self._authed = bool(authed)
            try:
                return fn(args, ctx, authed) if op == "proj.open" else \
                    fn(args, ctx)
            finally:
                self._caller = None
                self._authed = False

    # ======================================================== envelopes
    def _env_dir(self, env_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", str(env_id or "")):
            raise HubError("Bad envelope id.")
        return self._p("envelopes", env_id)

    def _env(self, env_id):
        meta = self._load(os.path.join(self._env_dir(env_id), "meta.json"))
        if meta is None:
            raise HubError("No such envelope.")
        return meta

    def _env_save(self, meta):
        self._save(os.path.join(self._env_dir(meta["id"]), "meta.json"), meta)

    @staticmethod
    def _event(meta, action, who, ctx=None, detail=""):
        ctx = ctx or {}
        meta["events"].append({"at": now_iso(), "action": action,
                               "who": who, "ip": _text(ctx.get("ip"), 64),
                               "agent": _text(ctx.get("agent"), 200),
                               "detail": _text(detail, 500)})

    @staticmethod
    def _expired(meta):
        exp = meta.get("expires")
        return bool(exp) and now_iso() > exp

    @staticmethod
    def _env_status(meta):
        if meta.get("voided"):
            return "voided"
        sts = [s["status"] for s in meta["signers"]]
        if any(s == "declined" for s in sts):
            return "declined"
        if all(s == "signed" for s in sts):
            return "completed"
        if Hub._expired(meta):
            return "expired"
        return "sent"

    @staticmethod
    def _ready(meta, idx):
        """Signer idx may sign: everyone in an earlier order has signed."""
        me = meta["signers"][idx]
        return all(s["status"] == "signed" for s in meta["signers"]
                   if s["order"] < me["order"])

    def op_env_create(self, a, ctx):
        signers = a.get("signers") or []
        pages = a.get("pages") or []
        fields = a.get("fields") or []
        if not signers or len(signers) > 50:
            raise HubError("Add between 1 and 50 signers.")
        if not pages or len(pages) > 500:
            raise HubError("No pages to sign.")
        env_id = secrets.token_urlsafe(12)
        d = self._env_dir(env_id)
        os.makedirs(d)
        out_signers = []
        for i, s in enumerate(signers):
            name = _text(s.get("name"), 120).strip()
            if not name:
                raise HubError(f"Signer {i + 1} has no name.")
            out_signers.append({
                "name": name, "email": _text(s.get("email"), 200).strip(),
                "order": int(s.get("order") or 1),
                "token": secrets.token_urlsafe(24), "status": "sent",
                "viewed": None, "signed": None, "ip": "", "values": {},
                "decline_reason": ""})
        out_pages = []
        for n, pg in enumerate(pages):
            png = _unb64(pg.get("png"), 8 * 1024 * 1024)
            if not png.startswith(b"\x89PNG"):
                raise HubError("Page images must be PNG.")
            with open(os.path.join(d, f"p{n}.png"), "wb") as f:
                f.write(png)
            out_pages.append({"w": float(pg.get("w") or 612),
                              "h": float(pg.get("h") or 792)})
        out_fields = []
        for k, fd in enumerate(fields):
            kind = fd.get("kind")
            if kind not in FIELD_KINDS:
                raise HubError(f"Unknown field kind: {kind}")
            si = int(fd.get("signer", 0))
            pno = int(fd.get("page", 0))
            if not (0 <= si < len(out_signers)) or \
                    not (0 <= pno < len(out_pages)):
                raise HubError("Field points at a missing signer or page.")
            r = [float(v) for v in fd.get("rect")][:4]
            if len(r) != 4 or r[2] <= r[0] or r[3] <= r[1]:
                raise HubError("Bad field rectangle.")
            out_fields.append({"id": _text(fd.get("id") or f"f{k}", 40),
                               "signer": si, "page": pno, "rect": r,
                               "kind": kind,
                               "required": bool(fd.get("required", True)),
                               "label": _text(fd.get("label"), 80)})
        for i, s in enumerate(out_signers):
            if not any(f["signer"] == i and f["kind"] in
                       ("signature", "initials") for f in out_fields):
                raise HubError(f"{s['name']} has nowhere to sign.")
        days = max(1, min(365, int(a.get("expires_days") or 30)))
        sender = a.get("sender") or {}
        meta = {"id": env_id, "title": _text(a.get("title"), 200) or
                "Signature request", "message": _text(a.get("message"), 4000),
                "sender": {"name": _text(sender.get("name"), 120),
                           "email": _text(sender.get("email"), 200)},
                "doc_sha256": _text(a.get("doc_sha256"), 64),
                "file_name": _text(a.get("file_name"), 200),
                "created": now_iso(),
                "expires": (datetime.now(timezone.utc) + timedelta(days=days))
                .replace(microsecond=0).isoformat(),
                "sender_key": secrets.token_urlsafe(24),
                "signers": out_signers, "pages": out_pages,
                "fields": out_fields, "events": [], "voided": False}
        self._event(meta, "created", meta["sender"]["name"] or "sender", ctx,
                    f"{len(out_signers)} signer(s), {len(out_fields)} "
                    f"field(s), document SHA-256 {meta['doc_sha256']}")
        self._env_save(meta)
        return {"env_id": env_id, "sender_key": meta["sender_key"],
                "expires": meta["expires"],
                "signers": [{"name": s["name"], "email": s["email"],
                             "order": s["order"], "token": s["token"],
                             "link": f"/sign.html?t={s['token']}"}
                            for s in out_signers]}

    def _sender(self, a):
        meta = self._env(a.get("env_id"))
        if not hmac.compare_digest(str(a.get("sender_key") or ""),
                                   meta["sender_key"]):
            raise HubError("Wrong envelope key.")
        return meta

    def op_env_status(self, a, ctx):
        meta = self._sender(a)
        signers = []
        for i, s in enumerate(meta["signers"]):
            st = s["status"]
            if st in ("sent", "viewed") and not self._ready(meta, i):
                st = "waiting"
            signers.append({"name": s["name"], "email": s["email"],
                            "order": s["order"], "status": st,
                            "viewed": s["viewed"], "signed": s["signed"],
                            "ip": s["ip"], "token": s["token"],
                            "decline_reason": s["decline_reason"],
                            "values": s["values"] if s["status"] == "signed"
                            else {}})
        return {"env_id": meta["id"], "title": meta["title"],
                "status": self._env_status(meta), "created": meta["created"],
                "expires": meta["expires"], "signers": signers,
                "fields": meta["fields"], "events": meta["events"],
                "doc_sha256": meta["doc_sha256"]}

    def op_env_void(self, a, ctx):
        meta = self._sender(a)
        if self._env_status(meta) == "completed":
            raise HubError("Everyone has already signed.")
        meta["voided"] = True
        self._event(meta, "voided", meta["sender"]["name"] or "sender", ctx,
                    _text(a.get("reason"), 300))
        self._env_save(meta)
        return {"status": "voided"}

    def op_env_note(self, a, ctx):
        meta = self._sender(a)
        self._event(meta, _text(a.get("action") or "note", 40),
                    meta["sender"]["name"] or "sender", ctx,
                    _text(a.get("detail"), 500))
        self._env_save(meta)
        return {"ok": True}

    def _signer(self, token):
        token = str(token or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token):
            raise HubError("This signing link is not valid.")
        root = self._p("envelopes")
        index = self._load(os.path.join(root, "tokens.json"), {})
        env_id = index.get(token)
        meta = None
        if env_id:
            try:
                meta = self._env(env_id)
            except HubError:
                meta = None
        if meta is None and os.path.isdir(root):
            for name in os.listdir(root):
                p = os.path.join(root, name, "meta.json")
                m = self._load(p) if os.path.isfile(p) else None
                if m and any(s["token"] == token for s in m["signers"]):
                    meta = m
                    index[token] = m["id"]
                    self._save(os.path.join(root, "tokens.json"), index)
                    break
        if meta is None:
            raise HubError("This signing link is not valid.")
        idx = next(i for i, s in enumerate(meta["signers"])
                   if hmac.compare_digest(s["token"], token))
        return meta, idx

    def op_sign_open(self, a, ctx):
        meta, i = self._signer(a.get("token"))
        me = meta["signers"][i]
        status = self._env_status(meta)
        if me["viewed"] is None and status == "sent":
            me["viewed"] = now_iso()
            if me["status"] == "sent":
                me["status"] = "viewed"
            self._event(meta, "viewed", me["name"], ctx)
            self._env_save(meta)
        ready = self._ready(meta, i)
        can = status == "sent" and ready and me["status"] != "signed"
        why = ""
        if me["status"] == "signed":
            why = "You have already signed. Thank you."
        elif status in ("voided", "declined", "expired", "completed"):
            why = {"voided": "The sender cancelled this request.",
                   "declined": "Someone declined, so signing has stopped.",
                   "expired": "This request has expired.",
                   "completed": "Everyone has signed."}[status]
        elif not ready:
            why = "Someone before you still needs to sign. You'll get an " \
                  "email when it's your turn."
        return {"env_id": meta["id"], "title": meta["title"],
                "message": meta["message"],
                "sender": meta["sender"], "signer": me["name"],
                "email": me["email"], "pages": meta["pages"],
                "fields": [f for f in meta["fields"] if f["signer"] == i],
                "can_sign": can, "why": why, "status": me["status"],
                "others": [{"name": s["name"], "status": s["status"]}
                           for k, s in enumerate(meta["signers"]) if k != i]}

    def op_sign_submit(self, a, ctx):
        meta, i = self._signer(a.get("token"))
        me = meta["signers"][i]
        if self._env_status(meta) != "sent" or me["status"] == "signed" or \
                not self._ready(meta, i):
            raise HubError("This document can't be signed right now.")
        if a.get("consent") is not True:
            raise HubError("Please agree to sign electronically first.")
        values = a.get("values") or {}
        out = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for f in meta["fields"]:
            if f["signer"] != i:
                continue
            v = values.get(f["id"])
            if f["kind"] in ("signature", "initials"):
                if not v:
                    if f["required"]:
                        raise HubError("Please sign every signature box.")
                    continue
                png = _unb64(v, MAX_IMAGE)
                if not png.startswith(b"\x89PNG"):
                    raise HubError("Signatures must be PNG images.")
                out[f["id"]] = {"kind": f["kind"], "png": _b64(png),
                                "sha256": hashlib.sha256(png).hexdigest()}
            elif f["kind"] == "date":
                out[f["id"]] = {"kind": "date", "text": today}
            elif f["kind"] == "name":
                out[f["id"]] = {"kind": "name", "text": me["name"]}
            elif f["kind"] == "checkbox":
                out[f["id"]] = {"kind": "checkbox", "checked": bool(v)}
            else:
                t = _text(v, 500).strip()
                if not t and f["required"]:
                    raise HubError(f"Please fill in {f['label'] or 'every box'}.")
                out[f["id"]] = {"kind": "text", "text": t}
        me["values"] = out
        me["status"] = "signed"
        me["signed"] = now_iso()
        me["ip"] = _text(ctx.get("ip"), 64)
        digest = hashlib.sha256(json.dumps(out, sort_keys=True)
                                .encode("utf-8")).hexdigest()
        self._event(meta, "signed", me["name"], ctx,
                    f"agreed to sign electronically; values SHA-256 {digest}")
        if self._env_status(meta) == "completed":
            self._event(meta, "completed", "QuantiSheet hub", ctx)
        self._env_save(meta)
        return {"status": "signed"}

    def op_sign_decline(self, a, ctx):
        meta, i = self._signer(a.get("token"))
        me = meta["signers"][i]
        if self._env_status(meta) != "sent" or me["status"] == "signed":
            raise HubError("This request is no longer open.")
        me["status"] = "declined"
        me["decline_reason"] = _text(a.get("reason"), 500)
        self._event(meta, "declined", me["name"], ctx, me["decline_reason"])
        self._env_save(meta)
        return {"status": "declined"}

    # ========================================================= projects
    def _proj_dir(self, project):
        return self._p("projects", _slug(project, "project name"))

    def _key_for(self, slug, meta):
        return self._mac("proj", slug, meta["pw"])

    def _session_key(self, slug, email, u):
        tag = base64.urlsafe_b64encode(email.encode("utf-8")).decode() \
            .rstrip("=")
        return f"u.{tag}.{self._mac('sess', slug, email, u['pw'])}"

    def _proj(self, a):
        slug = _slug(a.get("project"), "project name")
        meta = self._load(self._p("projects", slug, "meta.json"))
        if meta is None:
            raise HubError("No such project.")
        key = str(a.get("key") or "")
        users = meta.get("users") or {}
        if key.startswith("u."):
            try:
                tag, mac = key[2:].rsplit(".", 1)
                email = base64.urlsafe_b64decode(
                    tag + "=" * (-len(tag) % 4)).decode("utf-8")
            except Exception:
                raise HubError("Your login has expired - open the project "
                               "again.")
            u = users.get(email)
            if u is None or u.get("disabled") or not hmac.compare_digest(
                    key, self._session_key(slug, email, u)):
                raise HubError("Your login has expired - open the project "
                               "again.")
            who = {"email": email, "name": u.get("name") or email,
                   "role": u.get("role", "viewer")}
        else:
            if not hmac.compare_digest(key, self._key_for(slug, meta)):
                raise HubError("Wrong project key - open the project again.")
            if users:
                raise HubError("This project now uses logins - open it "
                               "again with your email and password.")
            who = {"email": "", "name": _text(a.get("user"), 80) or
                   "someone", "role": "admin"}
        self._caller = who
        self._allow(getattr(self, "_op", ""), who)
        return slug, meta

    @staticmethod
    def _allow(op, who):
        role = who["role"]
        if op in READ_OPS or role in ("admin",) or op == "rec.put":
            return                 # record writes: checked per record
        if op.startswith("user."):
            raise HubError("Only a project admin can manage logins.")
        if role == "viewer":
            raise HubError("You have view-only access to this project.")
        # a sub submits its pay app; only the GC's PM or accountant
        # approves, rejects or bills it (P1 sub pay apps)
        if coll == "subpay" and role != "accountant" and (
                (rec or {}).get("status") in SUBPAY_REVIEWED or
                (cur or {}).get("status") in SUBPAY_REVIEWED):
            raise HubError("Only the PM or accountant can review a sub pay "
                           "app.")
        if role == "accountant":
            if coll not in MONEY_COLLS:
                raise HubError(f"Accountants can change money records "
                               f"only, not {coll}.")
            return
        if role == "super":
            if coll in MONEY_COLLS:
                raise HubError("Superintendents can't change pay apps or "
                               "other money records.")
            if coll not in SUPER_COLLS:
                raise HubError(f"Superintendents can't change {coll} "
                               "records.")
            return
        if op in STAFF_OPS and role == "sub":
            raise HubError("Your role can't do that on this project.")

    def _who(self, a):
        c = getattr(self, "_caller", None)
        if c:
            return c["name"]
        return _text(a.get("user"), 80) or "someone"

    def _can_write(self, coll, cur, delete, rec=None):
        """Raise unless the caller's role may write this record."""
        who = getattr(self, "_caller", None)
        if not who:
            return
        role = who["role"]
        if role in ("admin", "pm"):
            return
        # only the office approves time cards, and an approved card is
        # final for everyone else (it feeds job cost and production)
        if coll == "timecard" and ((cur or {}).get("status") == "Approved"
                                   or (rec or {}).get("status") ==
                                   "Approved"):
            raise HubError("Only a PM or admin can approve or change an "
                           "approved time card.")
        if role == "viewer":
            raise HubError("You have view-only access to this project.")
        # a sub submits its pay app; only the GC's PM or accountant
        # approves, rejects or bills it (P1 sub pay apps)
        if coll == "subpay" and role != "accountant" and (
                (rec or {}).get("status") in SUBPAY_REVIEWED or
                (cur or {}).get("status") in SUBPAY_REVIEWED):
            raise HubError("Only the PM or accountant can review a sub pay "
                           "app.")
        if role == "accountant":
            if coll not in MONEY_COLLS:
                raise HubError(f"Accountants can change money records "
                               f"only, not {coll}.")
            return
        if role == "super":
            if coll in MONEY_COLLS:
                raise HubError("Superintendents can't change pay apps or "
                               "other money records.")
            if coll not in SUPER_COLLS:
                raise HubError(f"Superintendents can't change {coll} "
                               "records.")
            return
        if role == "estimator":
            if coll not in ESTIMATOR_COLLS:
                raise HubError(f"Estimators can't change {coll} records.")
            return
        # a sub: their own items, or ones that name them
        if coll not in SUB_COLLS:
            raise HubError(f"Subcontractors can't change {coll} records.")
        if delete:
            raise HubError("Subcontractors can't delete records.")
        if cur is None:
            return
        mine = {who["email"].lower(), who["name"].lower()} - {""}

        def names(v):
            if isinstance(v, str):
                return {v.strip().lower()}
            if isinstance(v, list):
                out = set()
                for x in v:
                    out |= names(x)
                return out
            return set()
        if cur.get("_by_id", "").lower() in mine or \
                cur.get("_by", "").lower() in mine:
            return
        if any(names(v) & mine for k, v in cur.items()
               if not k.startswith("_")):
            return
        raise HubError("You can only change items you made or that are "
                       "assigned to you.")

    def _activity(self, slug, user, action, detail=""):
        p = self._p("projects", slug, "activity.jsonl")
        c = getattr(self, "_caller", None)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_iso(), "user": _text(user, 80),
                                "uid": c["email"] if c else "",
                                "role": c["role"] if c else "",
                                "action": action,
                                "detail": _text(detail, 300)}) + "\n")

    def op_proj_open(self, a, ctx, authed=True):
        slug = _slug(a.get("project"), "project name")
        d = self._p("projects", slug)
        mp = os.path.join(d, "meta.json")
        meta = self._load(mp)
        user = _text(a.get("user") or "someone", 80)
        want = _text(a.get("project"), 120).strip().casefold()
        if meta is not None and meta.get("name") and \
                meta["name"].strip().casefold() != want:
            # "Job/A" and "Job?A" share the folder "Job_A": don't let one
            # land in the other (nit: slug collisions)
            raise HubError("Another project already uses a name like that; "
                           "choose a different name.")
        if meta is None:
            if not authed:
                raise HubError("No such project.")
            if len(str(a.get("password") or "")) < 8:
                raise HubError("Choose a project password of 8 or more "
                               "characters.")
            salt = secrets.token_bytes(16)
            meta = {"name": _text(a.get("project"), 120),
                    "salt": salt.hex(),
                    "pw": _pw_hash(salt, a.get("password")).hex(),
                    "created": now_iso(), "created_by": user}
            os.makedirs(os.path.join(d, "files"), exist_ok=True)
            self._save(mp, meta)
            self._activity(slug, user, "created the project")
        elif meta.get("users"):
            email = _text(a.get("email"), 200).strip().lower()
            if not email:
                raise HubError("This project uses logins - enter your email "
                               "and password.")
            u = meta["users"].get(email)
            if u is None or u.get("disabled") or not hmac.compare_digest(
                    _pw_hash(bytes.fromhex(u["salt"]),
                             a.get("password")).hex(), u["pw"]):
                time.sleep(0.2)
                raise HubError("Wrong email or password.")
            self._caller = {"email": email, "name": u.get("name") or email,
                            "role": u.get("role", "viewer")}
            self._activity(slug, self._caller["name"], "signed in")
            return {"project": meta["name"], "slug": slug,
                    "key": self._session_key(slug, email, u),
                    "role": u.get("role"), "user": u.get("name") or email,
                    "email": email, "logins": True}
        elif not hmac.compare_digest(
                _pw_hash(bytes.fromhex(meta["salt"]),
                         a.get("password")).hex(), meta["pw"]):
            raise HubError("Wrong project password.")
        return {"project": meta["name"], "slug": slug,
                "key": self._key_for(slug, meta), "role": "admin",
                "logins": False}

    # ---------------------------------------------------------- logins
    def _meta_save(self, slug, meta):
        self._save(self._p("projects", slug, "meta.json"), meta)

    def op_user_me(self, a, ctx):
        slug, meta = self._proj(a)
        c = self._caller
        return {"email": c["email"], "name": c["name"], "role": c["role"],
                "logins": bool(meta.get("users"))}

    def op_user_list(self, a, ctx):
        slug, meta = self._proj(a)
        return {"users": [{"email": e, "name": u.get("name", ""),
                           "role": u.get("role"),
                           "disabled": bool(u.get("disabled")),
                           "created": u.get("created", "")}
                          for e, u in sorted((meta.get("users") or {})
                                             .items())]}

    @staticmethod
    def _new_user(name, role, password):
        if role not in ROLES:
            raise HubError("Unknown role.")
        if len(str(password or "")) < 8:
            raise HubError("Passwords need 8 or more characters.")
        salt = secrets.token_bytes(16)
        return {"name": _text(name, 80).strip(), "role": role,
                "salt": salt.hex(), "pw": _pw_hash(salt, password).hex(),
                "created": now_iso(), "disabled": False}

    def op_user_add(self, a, ctx):
        """Add a login. The first one turns logins on and must be an
        admin; it answers with that admin's new key."""
        slug, meta = self._proj(a)
        email = _text(a.get("email"), 200).strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise HubError("Enter a valid email address.")
        users = meta.setdefault("users", {})
        if email in users:
            raise HubError(f"{email} already has a login.")
        role = str(a.get("role") or "viewer")
        first = not users
        if first and role != "admin":
            raise HubError("The first login must be an admin (you).")
        users[email] = self._new_user(a.get("name") or email, role,
                                      a.get("password"))
        self._meta_save(slug, meta)
        self._activity(slug, self._who(a), "added a login",
                       f"{email} ({ROLE_NAMES.get(role, role)})")
        out = {"email": email, "role": role, "logins": True}
        if first:
            out["key"] = self._session_key(slug, email, users[email])
        return out

    def _admins(self, meta, but=None):
        return [e for e, u in (meta.get("users") or {}).items()
                if u.get("role") == "admin" and not u.get("disabled")
                and e != but]

    def op_user_set(self, a, ctx):
        slug, meta = self._proj(a)
        email = _text(a.get("email"), 200).strip().lower()
        u = (meta.get("users") or {}).get(email)
        if u is None:
            raise HubError("No such login.")
        demote = (a.get("role") not in (None, "admin") or
                  a.get("disabled") is True)
        if demote and u.get("role") == "admin" and \
                not self._admins(meta, but=email):
            raise HubError("Keep at least one admin.")
        changed = []
        if a.get("role") is not None:
            if a["role"] not in ROLES:
                raise HubError("Unknown role.")
            u["role"] = a["role"]
            changed.append(f"role {a['role']}")
        if a.get("name") is not None:
            u["name"] = _text(a["name"], 80).strip()
        if a.get("disabled") is not None:
            u["disabled"] = bool(a["disabled"])
            changed.append("disabled" if u["disabled"] else "enabled")
        if a.get("password"):
            n = self._new_user(u.get("name"), u["role"], a["password"])
            u["salt"], u["pw"] = n["salt"], n["pw"]
            changed.append("password reset")
        self._meta_save(slug, meta)
        self._activity(slug, self._who(a), "changed a login",
                       f"{email}: {', '.join(changed)}")
        return {"email": email, "role": u["role"],
                "disabled": bool(u.get("disabled"))}

    def op_user_remove(self, a, ctx):
        slug, meta = self._proj(a)
        email = _text(a.get("email"), 200).strip().lower()
        users = meta.get("users") or {}
        if email not in users:
            raise HubError("No such login.")
        if users[email].get("role") == "admin" and \
                not self._admins(meta, but=email):
            raise HubError("Keep at least one admin.")
        del users[email]
        self._meta_save(slug, meta)
        self._activity(slug, self._who(a), "removed a login", email)
        return {"removed": email}

    def op_user_password(self, a, ctx):
        """Change your own password; answers with your new key."""
        slug, meta = self._proj(a)
        c = self._caller
        if not c["email"]:
            raise HubError("This project doesn't use logins.")
        u = meta["users"][c["email"]]
        if not hmac.compare_digest(_pw_hash(bytes.fromhex(u["salt"]),
                                            a.get("old")).hex(), u["pw"]):
            raise HubError("Your current password is wrong.")
        n = self._new_user(u.get("name"), u["role"], a.get("new"))
        u["salt"], u["pw"] = n["salt"], n["pw"]
        self._meta_save(slug, meta)
        return {"key": self._session_key(slug, c["email"], u)}

    def _index(self, slug):
        return self._load(self._p("projects", slug, "files.json"), {})

    def op_proj_files(self, a, ctx):
        slug, _ = self._proj(a)
        idx = self._index(slug)
        return {"files": [dict(name=k, **v) for k, v in sorted(idx.items())]}

    def op_proj_activity(self, a, ctx):
        slug, _ = self._proj(a)
        p = self._p("projects", slug, "activity.jsonl")
        out = []
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
        since = str(a.get("since") or "")
        out = [e for e in out if e["at"] > since]
        return {"events": out[-int(a.get("limit") or 200):]}

    def op_proj_lock(self, a, ctx):
        slug, _ = self._proj(a)
        idx = self._index(slug)
        name = _slug(a.get("name"), "file name")
        user = self._who(a)
        ent = idx.get(name)
        if ent is None:
            raise HubError("No such file.")
        lk = ent.get("lock")
        if lk and lk["user"] != user:
            raise HubError(f"{lk['user']} has it checked out since "
                           f"{lk['at'][:16].replace('T', ' ')}.")
        ent["lock"] = {"user": user, "at": now_iso()}
        self._save(self._p("projects", slug, "files.json"), idx)
        self._activity(slug, user, "checked out", name)
        return {"lock": ent["lock"]}

    def op_proj_unlock(self, a, ctx):
        slug, _ = self._proj(a)
        idx = self._index(slug)
        name = _slug(a.get("name"), "file name")
        user = self._who(a)
        ent = idx.get(name)
        if ent is None:
            raise HubError("No such file.")
        lk = ent.get("lock")
        if lk and lk["user"] != user and not a.get("force"):
            raise HubError(f"{lk['user']} has it checked out.")
        ent["lock"] = None
        self._save(self._p("projects", slug, "files.json"), idx)
        self._activity(slug, user, "checked in" if not a.get("force") else
                       "broke the check-out on", name)
        return {"lock": None}

    def op_proj_put_begin(self, a, ctx):
        slug, _ = self._proj(a)
        name = _slug(a.get("name"), "file name")
        size = int(a.get("size") or 0)
        if size < 0 or size > MAX_FILE:
            raise HubError("File too large.")
        user = self._who(a)
        ent = self._index(slug).get(name)
        if ent:
            lk = ent.get("lock")
            if lk and lk["user"] != user:
                raise HubError(f"{lk['user']} has {name} checked out.")
            base = a.get("base_version")
            latest = ent["versions"][-1]["v"]
            if base is not None and int(base) != latest and \
                    not a.get("force"):
                raise HubError(f"CONFLICT: {name} changed on the server "
                               f"(version {latest}) since you got version "
                               f"{base}.")
        uid = secrets.token_urlsafe(12)
        tmp = self._p("uploads", uid)
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        open(tmp, "wb").close()
        self.uploads[uid] = {"slug": slug, "name": name, "size": size,
                             "sha256": _text(a.get("sha256"), 64),
                             "user": user, "uid": (self._caller or {})
                             .get("email", ""), "note": _text(a.get("note"), 300),
                             "path": tmp, "at": time.time()}
        return {"upload": uid}

    def op_proj_put_chunk(self, a, ctx):
        up = self.uploads.get(str(a.get("upload")))
        if up is None:
            raise HubError("Upload not found.")
        self._proj(dict(a, project=up["slug"]))
        data = _unb64(a.get("data"), MAX_CHUNK)
        off = int(a.get("offset") or 0)
        if off != os.path.getsize(up["path"]):
            raise HubError("Chunk out of order.")
        with open(up["path"], "ab") as f:
            f.write(data)
        return {"received": off + len(data)}

    def op_proj_put_end(self, a, ctx):
        up = self.uploads.pop(str(a.get("upload")), None)
        if up is None:
            raise HubError("Upload not found.")
        slug, _ = self._proj(dict(a, project=up["slug"]))
        h = hashlib.sha256()
        with open(up["path"], "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        size = os.path.getsize(up["path"])
        if size != up["size"] or (up["sha256"] and
                                  h.hexdigest() != up["sha256"]):
            os.remove(up["path"])
            raise HubError("Upload damaged in transit - try again.")
        idx = self._index(slug)
        ent = idx.setdefault(up["name"], {"versions": [], "lock": None})
        v = (ent["versions"][-1]["v"] + 1) if ent["versions"] else 1
        dest = self._p("projects", slug, "files", up["name"], f"v{v}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.replace(up["path"], dest)
        ent["versions"].append({"v": v, "size": size,
                                "sha256": h.hexdigest(), "by": up["user"],
                                "by_id": up.get("uid", ""),
                                "at": now_iso(), "note": up["note"]})
        self._save(self._p("projects", slug, "files.json"), idx)
        self._activity(slug, up["user"], "uploaded",
                       f"{up['name']} v{v}" +
                       (f" - {up['note']}" if up["note"] else ""))
        return {"name": up["name"], "version": v, "sha256": h.hexdigest()}

    def op_proj_get_chunk(self, a, ctx):
        slug, _ = self._proj(a)
        name = _slug(a.get("name"), "file name")
        ent = self._index(slug).get(name)
        if ent is None:
            raise HubError("No such file.")
        v = int(a.get("version") or ent["versions"][-1]["v"])
        p = self._p("projects", slug, "files", name, f"v{v}")
        if not os.path.isfile(p):
            raise HubError("No such version.")
        off = int(a.get("offset") or 0)
        size = min(int(a.get("size") or MAX_CHUNK), MAX_CHUNK)
        with open(p, "rb") as f:
            f.seek(off)
            data = f.read(size)
        return {"data": _b64(data), "offset": off,
                "total": os.path.getsize(p), "version": v}

    # ========================================================== records
    # A project's shared database: RFIs, submittals, punch items, daily
    # logs, budget lines... Each record lives in a collection, has a stable
    # id, a display number (RFI-007) and a revision. Writes name the
    # revision they started from; a mismatch is a conflict the client
    # resolves (it merges the fields it changed and tries again). Every
    # write gets a project-wide sequence number, so clients sync with
    # "everything after seq N".

    def _coll(self, coll):
        coll = str(coll or "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", coll):
            raise HubError("Bad collection name.")
        return coll

    def _records(self, slug, coll):
        return self._load(self._p("projects", slug, "records",
                                  coll + ".json"), {"next": 1, "items": {}})

    def _next_seq(self, slug):
        p = self._p("projects", slug, "seq")
        try:
            with open(p) as f:
                n = int(f.read().strip() or 0)
        except (OSError, ValueError):
            n = 0
        n += 1
        with open(p, "w") as f:
            f.write(str(n))
        return n

    def op_rec_changes(self, a, ctx):
        slug, _ = self._proj(a)
        since = int(a.get("since") or 0)
        d = self._p("projects", slug, "records")
        out = []
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if not name.endswith(".json"):
                    continue
                data = self._load(os.path.join(d, name), {"items": {}})
                out += [self._rec_out(slug, r) for r in
                        data["items"].values() if r.get("_seq", 0) > since]
        out.sort(key=lambda r: r["_seq"])
        seq = 0
        p = self._p("projects", slug, "seq")
        if os.path.exists(p):
            with open(p) as f:
                seq = int(f.read().strip() or 0)
        return {"seq": seq, "records": out}

    def op_rec_put(self, a, ctx):
        slug, _ = self._proj(a)
        coll = self._coll(a.get("coll"))
        rec = a.get("record")
        if not isinstance(rec, dict):
            raise HubError("Bad record.")
        if len(json.dumps(rec)) > 512 * 1024:
            raise HubError("Record too large - attach files instead.")
        user = self._who(a)
        uid = (self._caller or {}).get("email", "")
        data = self._records(slug, coll)
        rid = rec.get("_id")
        cur = data["items"].get(rid) if rid else None
        try:
            self._can_write(coll, cur, bool(a.get("delete")), rec)
        except HubError as e:
            # every refusal is kept in the project's activity (P1 roles)
            try:
                self._activity(slug, user, "denied",
                               f"{coll} {(cur or rec).get('_no') or ''}: "
                               f"{e}")
            except Exception:                             # noqa: BLE001
                pass
            return {"conflict": False, "denied": str(e),
                    "current": self._rec_out(slug, cur)}
        fields = {k: v for k, v in rec.items() if not k.startswith("_")}
        if cur is not None:
            base = a.get("base_rev")
            if base is not None and int(base) != cur["_rev"]:
                return {"conflict": True,
                        "current": self._rec_out(slug, cur)}
            new = dict(cur)                 # a partial update
            new.update(fields)
            for k in a.get("unset") or []:
                if not str(k).startswith("_"):
                    new.pop(k, None)
            new["_rev"] = cur["_rev"] + 1
            action = "edited"
        else:
            if rid and not re.fullmatch(r"[A-Za-z0-9_-]{6,40}", str(rid)):
                raise HubError("Bad record id.")
            prefix = _text(a.get("prefix"), 12)
            width = max(1, min(6, int(a.get("width") or 3)))
            no = data["next"]
            data["next"] += 1
            new = dict(fields)
            label = f"{prefix}{no:0{width}d}"
            group = _text(a.get("group"), 20).strip()
            if group:                 # numbered within a spec section
                k = 1 + sum(1 for r in data["items"].values()
                            if r.get("_group") == group)
                label = f"{group}-{k:03d}"
                new["_group"] = group
            new.update({"_id": rid or secrets.token_hex(8), "_coll": coll,
                        "_n": no, "_no": label,
                        "_rev": 1, "_created": now_iso(), "_by": user,
                        "_by_id": uid})
            action = "added"
        new["_updated"] = now_iso()
        new["_upd_by"] = user
        new["_upd_by_id"] = uid
        new["_deleted"] = bool(a.get("delete")) if cur is not None else False
        if new["_deleted"]:
            action = "deleted"
        new["_seq"] = self._next_seq(slug)
        if coll == "bidpkg":
            self._scrub_bid_tokens(slug, new["_id"], new)
        data["items"][new["_id"]] = new
        self._save(self._p("projects", slug, "records", coll + ".json"),
                   data)
        title = fields.get("title") or fields.get("subject") or \
            fields.get("name") or ""
        self._activity(slug, user, f"{action} {coll}",
                       f"{new['_no']} {title}".strip())
        return {"conflict": False, "record": self._rec_out(slug, new)}

    def op_att_put(self, a, ctx):
        """One-shot attachment upload (photos, PDFs up to 16 MB). Stored by
        content hash, so the same file twice is kept once."""
        slug, _ = self._proj(a)
        data = _unb64(a.get("data"), 16 * 1024 * 1024)
        sha = hashlib.sha256(data).hexdigest()
        p = self._p("projects", slug, "att", sha)
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        return {"sha256": sha, "size": len(data),
                "name": _text(a.get("name"), 200) or sha[:12]}

    def op_att_get(self, a, ctx):
        slug, _ = self._proj(a)
        sha = str(a.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise HubError("Bad attachment id.")
        p = self._p("projects", slug, "att", sha)
        if not os.path.isfile(p):
            raise HubError("Attachment not found.")
        with open(p, "rb") as f:
            return {"data": _b64(f.read())}

    # ============================================================= bids
    # A bid package invites subs; each bidder gets a private link to a page
    # with the scope and documents where they say will / won't / might bid
    # and can upload their number. Answers land in the package record.

    def op_bid_invite(self, a, ctx):
        slug, _ = self._proj(a)
        rid = str(a.get("record_id") or "")
        data = self._records(slug, "bidpkg")
        if rid not in data["items"]:
            raise HubError("Sync the bid package first.")
        out = []
        for b in a.get("bidders") or []:
            tok = secrets.token_urlsafe(18)
            inv = {"token": tok, "project": slug, "record": rid,
                   "company": _text(b.get("company"), 120),
                   "email": _text(b.get("email"), 200),
                   "created": now_iso(), "viewed": None}
            self._save(self._p("invites", tok + ".json"), inv)
            self._bid_index_add(slug, rid, tok)
            out.append({"company": inv["company"], "token": tok,
                        "link": f"/bid.html?t={tok}"})
        self._activity(slug, self._who(a), "invited bidders", f"{len(out)} on "
                       f"{data['items'][rid].get('_no', '')}")
        # "features": what this hub's bid page can show, so the sender
        # is told when a bid form needs a newer hub (Nov 11)
        return {"invites": out, "features": list(BID_FEATURES)}

    def _invite(self, token):
        token = str(token or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
            raise HubError("This invitation link is not valid.")
        inv = self._load(self._p("invites", token + ".json"))
        if inv is None:
            raise HubError("This invitation link is not valid.")
        data = self._records(inv["project"], "bidpkg")
        rec = data["items"].get(inv["record"])
        if rec is None or rec.get("_deleted"):
            raise HubError("This bid package was withdrawn.")
        return inv, data, rec

    def _bidder_row(self, rec, inv):
        """This invitation's row in the package. Rows carry only the
        invite_ref (a MAC of the token), never the token itself."""
        ref = self._bid_index_add(inv["project"], inv["record"],
                                  inv["token"])
        rows = [r for r in rec.get("bidders") or [] if isinstance(r, dict)]
        for row in rows:
            if row.get("invite_ref") == ref:
                return row
        for row in rows:                      # a record from before 0.13.5
            if row.get("token") and hmac.compare_digest(
                    str(row["token"]), inv["token"]):
                row.pop("token", None)
                row["invite_ref"] = ref
                return row
        # the GC's copy with the invitation may not have synced yet: the
        # same bidder by email (or company) is this one
        for row in rows:
            if row.get("token") or row.get("invite_ref"):
                continue
            if (inv["email"] and (row.get("email") or "").lower() ==
                    inv["email"].lower()) or (not inv["email"] and
                                              row.get("company") ==
                                              inv["company"]):
                row["invite_ref"] = ref
                return row
        row = {"company": inv["company"], "email": inv["email"],
               "invite_ref": ref}
        rec.setdefault("bidders", []).append(row)
        return row

    # ---- invitation tokens stay out of the shared record (0.13.5 fix)
    # Every project reader gets the bid package record, so a token on a
    # bidder row let anyone answer (or read) as that bidder. The tokens
    # live in invites/<token>.json plus a per-package index the hub keeps
    # for itself; rows carry a non-secret invite_ref. Only office staff
    # who could send the invitation themselves (relay-token callers with
    # an admin, PM or estimator role) get the token back on their copy,
    # for the reminder and follow-up links.

    def _bid_ref(self, token):
        return self._mac("bidref", str(token or ""))[:20]

    def _bid_index_path(self, slug, rid):
        rid = str(rid or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
            raise HubError("Bad record id.")
        return self._p("bidrefs", _slug(slug, "project name"), rid + ".json")

    def _bid_index(self, slug, rid):
        try:
            return self._load(self._bid_index_path(slug, rid), {}) or {}
        except HubError:
            return {}

    def _bid_index_add(self, slug, rid, token):
        idx = self._bid_index(slug, rid)
        ref = self._bid_ref(token)
        if idx.get(ref) != token:
            idx[ref] = token
            p = self._bid_index_path(slug, rid)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            self._save(p, idx)
        return ref

    def _bid_token_valid(self, slug, rid, token):
        token = str(token or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
            return False
        inv = self._load(self._p("invites", token + ".json"))
        return bool(inv) and inv.get("project") == slug and \
            str(inv.get("record")) == str(rid)

    def _scrub_bid_tokens(self, slug, rid, rec):
        """Take every token off the bidder rows before the record is
        saved; a real one (this package's invitation) becomes its ref."""
        for row in rec.get("bidders") or []:
            if not isinstance(row, dict) or "token" not in row:
                continue
            tok = row.pop("token")
            if tok and self._bid_token_valid(slug, rid, tok):
                row["invite_ref"] = self._bid_index_add(slug, rid, tok)
        return rec

    def _bid_staff(self):
        c = getattr(self, "_caller", None)
        return bool(getattr(self, "_authed", False)) and bool(c) and \
            c.get("role") in ("admin", "pm", "estimator")

    def _rec_out(self, slug, rec):
        """A record as it goes to a client: bid package rows never carry
        an invitation token, except on the office staff's own copy."""
        if not isinstance(rec, dict) or rec.get("_coll") != "bidpkg" or \
                not rec.get("bidders"):
            return rec
        staff = self._bid_staff()
        idx = self._bid_index(slug, rec.get("_id")) if staff else {}
        out = dict(rec)
        rows = []
        for row in rec.get("bidders") or []:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            row = dict(row)
            row.pop("token", None)
            if staff and row.get("invite_ref") in idx:
                row["token"] = idx[row["invite_ref"]]
            rows.append(row)
        out["bidders"] = rows
        return out

    def _row_token(self, slug, rid, row):
        """The invitation token behind a bidder row (hub side only)."""
        ref = row.get("invite_ref")
        if ref:
            tok = self._bid_index(slug, rid).get(ref)
            if tok:
                return tok
        return row.get("token")               # a record from before 0.13.5

    def _touch(self, slug, coll, data, rec, user, action):
        if coll == "bidpkg":
            self._scrub_bid_tokens(slug, rec.get("_id"), rec)
        rec["_rev"] = rec.get("_rev", 0) + 1
        rec["_updated"] = now_iso()
        rec["_upd_by"] = user
        rec["_seq"] = self._next_seq(slug)
        self._save(self._p("projects", slug, "records", coll + ".json"),
                   data)
        self._activity(slug, user, action, f"{rec.get('_no', '')} "
                                           f"{rec.get('title', '')}")

    def op_bid_open(self, a, ctx):
        inv, data, rec = self._invite(a.get("token"))
        row = self._bidder_row(rec, inv)
        if not inv.get("viewed"):
            inv["viewed"] = now_iso()
            self._save(self._p("invites", inv["token"] + ".json"), inv)
            if row.get("status") in (None, "", "Invited"):
                row["status"] = "Viewed"
            row["viewed"] = inv["viewed"]
            self._touch(inv["project"], "bidpkg", data, rec,
                        inv["company"], "viewed bid package")
        meta = self._load(self._p("projects", inv["project"], "meta.json"),
                          {})
        docs = [{"name": f.get("name"), "sha256": f.get("sha256"),
                 "size": f.get("size", 0)}
                for f in rec.get("documents") or []]
        form = [{"item": _text(ln.get("item"), 12),
                 "description": _text(ln.get("description"), 300),
                 "type": ln.get("type") or "Lump sum",
                 "qty": ln.get("qty"), "unit": _text(ln.get("unit"), 12),
                 "note": _text(ln.get("note"), 300)}
                for ln in rec.get("form") or [] if isinstance(ln, dict)]
        addenda = [{"number": _text(a.get("number"), 12),
                    "date": _text(a.get("date"), 20),
                    "description": _text(a.get("description"), 300)}
                   for a in rec.get("addenda") or [] if isinstance(a, dict)]
        # A sealed bid is never read back, not even with its own link (a
        # forwarded or leaked link must not show the number): the bidder
        # sees that it was received, and may send a new one until the
        # deadline (0.13.5 security fix).
        sealed = self._sealed(rec)
        mine = {} if sealed else row
        dl = _deadline(rec)
        return {"project": meta.get("name", ""), "title": rec.get("title"),
                "sealed": sealed,
                "sealed_received": row.get("sealed") if sealed else None,
                "deadline": dl.isoformat() if dl else "",
                "past_due": bool(dl and _now_local() > dl),
                "number": rec.get("_no"), "due": rec.get("due"),
                "due_time": rec.get("due_time"),
                "prebid": rec.get("prebid"), "scope": rec.get("scope"),
                "site_visit": rec.get("site_visit"),
                "rfi_due": rec.get("rfi_due"), "specs": rec.get("specs"),
                "sheets": rec.get("sheets"),
                "trades": rec.get("trades"), "contact": rec.get("contact"),
                "company": inv["company"], "status": row.get("status"),
                "amount": mine.get("amount"), "note": row.get("note"),
                "form": form, "values": mine.get("form_values") or {},
                "addenda": addenda, "acks": row.get("ack_list") or [],
                "inclusions": mine.get("inclusions") or "",
                "exclusions": mine.get("exclusions") or "",
                "clarifications": mine.get("clarifications") or "",
                "documents": docs,
                "closed": rec.get("status") in ("Closed", "Awarded")}

    # sealed bids: the numbers stay in the hub, out of the package record,
    # until someone opens them after the bid deadline
    SEALED_KEYS = ("amount", "form_values", "form_missing", "alternates",
                   "inclusions", "exclusions", "clarifications",
                   "bid_file")

    @staticmethod
    def _sealed(rec):
        return _yes(rec.get("sealed")) and not rec.get("unsealed")

    def _sealed_path(self, inv, rec):
        return self._p("sealed", inv["project"], str(rec.get("_id") or
                                                     inv["record"]),
                       inv["token"] + ".json")

    def op_bid_respond(self, a, ctx):
        inv, data, rec = self._invite(a.get("token"))
        if rec.get("status") in ("Closed", "Awarded"):
            raise HubError("Bidding on this package has closed.")
        dl = _deadline(rec)
        late = bool(dl and _now_local() > dl)
        if late and self._sealed(rec) and a.get("intent") == "Bid Received":
            raise HubError("Sealed bids closed at the bid deadline.")
        intent = a.get("intent")
        if intent not in ("Will Bid", "Won't Bid", "Might Bid",
                          "Bid Received"):
            raise HubError("Choose will bid, won't bid or might bid.")
        row = self._bidder_row(rec, inv)
        lines = [ln for ln in rec.get("form") or [] if isinstance(ln, dict)]
        values = a.get("form") if isinstance(a.get("form"), dict) else None
        if values is not None:
            values = {str(k): _text(v, 120) for k, v in values.items()
                      if str(k).isdigit() and int(k) < len(lines)}
        addenda = [str(x.get("number") or "") for x in rec.get("addenda")
                   or [] if isinstance(x, dict)]
        acks = [str(x) for x in (a.get("acks") or []) if str(x) in addenda]
        bidding = intent == "Bid Received" or bool(a.get("file")) or \
            a.get("amount") not in (None, "") or bool(values and any(
                v not in ("", None) for v in values.values()))
        if bidding and addenda and set(acks) != set(addenda):
            raise HubError("Acknowledge every addendum before you send your "
                           "bid.")
        row["status"] = intent
        row["note"] = _text(a.get("note"), 1000)
        row["responded"] = now_iso()
        if values is not None:
            row["form_values"] = values
            tot = bid_totals(lines, values)
            row["form_missing"] = tot["missing"]
            row["alternates"] = tot["alternates"]
            if any(v not in ("", None) for v in values.values()):
                row["amount"] = tot["base"]
                row["status"] = "Bid Received"
        if addenda:
            row["ack_list"] = acks
            row["acks"] = ", ".join(acks) if acks else ""
        for k in ("inclusions", "exclusions", "clarifications"):
            if a.get(k) is not None:
                row[k] = _text(a.get(k), 2000)
        has_form = bool(values and any(v not in ("", None)
                                       for v in values.values()))
        if a.get("amount") not in (None, "") and not has_form:
            try:
                row["amount"] = _c2(float(str(a["amount"]).replace(
                    "$", "").replace(",", "")))
            except ValueError:
                raise HubError("The bid amount isn't a number.")
        if a.get("file"):
            fdata = _unb64(a.get("file"), 32 * 1024 * 1024)
            sha = hashlib.sha256(fdata).hexdigest()
            p = self._p("projects", inv["project"], "att", sha)
            if not os.path.exists(p):
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(fdata)
            name = _text(a.get("file_name"), 120) or "bid.pdf"
            row["bid_file"] = {"name": name, "sha256": sha,
                               "size": len(fdata),
                               "ext": os.path.splitext(name)[1].lower(),
                               "by": inv["company"], "at": now_iso()}
            row["status"] = "Bid Received"
        if late and row["status"] == "Bid Received":
            row["late"] = now_iso()
        if self._sealed(rec):
            if late and any(row.get(k) not in (None, "", [], {})
                            for k in self.SEALED_KEYS):
                raise HubError("Sealed bids closed at the bid deadline.")
            sp = self._sealed_path(inv, rec)
            box = self._load(sp, {}) or {}
            # the page can't show a sealed number back, so a click that
            # only changes the answer (blank form) must not wipe the bid
            # already in the box; a new number replaces it
            empty = (None, "", [], {})
            new_bid = any(row.get(k) not in empty
                          for k in ("amount", "bid_file")) or any(
                v not in ("", None)
                for v in (row.get("form_values") or {}).values())
            for k in self.SEALED_KEYS:
                if k in row:
                    v = row.pop(k)
                    if new_bid or v not in empty:
                        box[k] = v
            if box:
                box["sealed_at"] = now_iso()
                self._save(sp, box)
                row["sealed"] = box["sealed_at"]
                row["sealed_hash"] = hashlib.sha256(json.dumps(
                    box, sort_keys=True).encode()).hexdigest()[:16]
                row["status"] = "Bid Received"
        self._touch(inv["project"], "bidpkg", data, rec, inv["company"],
                    f"bid response: {row['status']}" +
                    (" (sealed)" if row.get("sealed") and
                     self._sealed(rec) else ""))
        return {"status": row["status"], "sealed": self._sealed(rec)}

    def op_bid_unseal(self, a, ctx):
        """Open the sealed bids of a package - only after its deadline."""
        slug, _ = self._proj(a)
        rid = str(a.get("record_id") or "")
        data = self._records(slug, "bidpkg")
        rec = data["items"].get(rid)
        if rec is None:
            raise HubError("Sync the bid package first.")
        if not _yes(rec.get("sealed")):
            raise HubError("This package doesn't take sealed bids.")
        if rec.get("unsealed"):
            return {"opened": 0, "already": rec["unsealed"]}
        dl = _deadline(rec)
        if dl is None and rec.get("status") not in ("Closed", "Awarded"):
            raise HubError("Set the bid due date first.")
        if dl is not None and _now_local() < dl:
            raise HubError(f"Sealed bids can't be opened before the "
                           f"deadline ({dl.strftime('%Y-%m-%d %I:%M %p')}).")
        n = 0
        for row in rec.get("bidders") or []:
            if not isinstance(row, dict):
                continue
            tok = self._row_token(slug, rid, row)
            if not tok or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}",
                                           str(tok)):
                continue
            sp = self._p("sealed", slug, rid, tok + ".json")
            box = self._load(sp)
            if not box:
                continue
            for k in self.SEALED_KEYS:
                if k in box:
                    row[k] = box[k]
            n += 1
        user = self._who(a)
        rec["unsealed"] = now_iso()
        rec["unsealed_by"] = user
        self._touch(slug, "bidpkg", data, rec, user,
                    f"opened {n} sealed bid(s)")
        return {"opened": n, "at": rec["unsealed"]}

    # ============================================================== GET
    def get(self, path, headers=None):
        """(status, content type, body) for GET /hub/...

        `headers` are the request's headers. A project attachment needs
        the session key as "Authorization: Bearer <key>"; a key in the
        address ("?k=") is refused (Nov 6 security fix: it ended up in
        browser history, proxy logs and Referer)."""
        path, _, query = path.partition("?")
        q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        m = re.fullmatch(r"/hub/env/([A-Za-z0-9_-]+)/p(\d+)\.png", path)
        try:
            with self.lock:
                # the role check in _proj reads _op: never let the last
                # call's operation decide a GET (review 3 #1)
                self._op = "att.get"
                self._caller = None
                if m:
                    meta = self._env(m.group(1))
                    t = q.get("t", "")
                    ok = hmac.compare_digest(t, meta["sender_key"]) or any(
                        hmac.compare_digest(t, s["token"])
                        for s in meta["signers"])
                    if not ok or meta.get("voided"):
                        return 403, "text/plain", b"forbidden"
                    p = os.path.join(self._env_dir(meta["id"]),
                                     f"p{int(m.group(2))}.png")
                    if not os.path.isfile(p):
                        return 404, "text/plain", b"not found"
                    with open(p, "rb") as f:
                        return 200, "image/png", f.read()
                m = re.fullmatch(r"/hub/bid/([A-Za-z0-9_-]{16,64})/"
                                 r"([0-9a-f]{64})", path)
                if m:
                    inv, _d, rec = self._invite(m.group(1))
                    shas = {f.get("sha256") for f in rec.get("documents")
                            or []}
                    if m.group(2) not in shas:
                        return 403, "text/plain", b"forbidden"
                    p = self._p("projects", inv["project"], "att",
                                m.group(2))
                    if not os.path.isfile(p):
                        return 404, "text/plain", b"not found"
                    with open(p, "rb") as f:
                        body = f.read()
                    return 200, ("application/pdf" if body[:4] == b"%PDF"
                                 else "application/octet-stream"), body
                m = re.fullmatch(r"/hub/att/([^/]+)/([0-9a-f]{64})", path)
                if m:
                    from urllib.parse import unquote
                    key = bearer(headers)
                    if not key:
                        return 401, "text/plain", (
                            b"sign in again" if "k" not in q else
                            b"keys in the address are no longer accepted")
                    slug, _ = self._proj({"project": unquote(m.group(1)),
                                          "key": key})
                    p = self._p("projects", slug, "att", m.group(2))
                    if not os.path.isfile(p):
                        return 404, "text/plain", b"not found"
                    with open(p, "rb") as f:
                        body = f.read()
                    ctype = ("image/jpeg" if body[:2] == b"\xff\xd8" else
                             "image/png" if body[:4] == b"\x89PNG" else
                             "application/pdf" if body[:4] == b"%PDF" else
                             "application/octet-stream")
                    return 200, ctype, body
        except HubError:
            return 403, "text/plain", b"forbidden"
        return 404, "text/plain", b"not found"


def bearer(headers):
    """The token in an "Authorization: Bearer ..." header, or ""."""
    if not headers:
        return ""
    try:
        v = headers.get("Authorization") or headers.get("authorization")
    except AttributeError:
        v = None
    v = str(v or "").strip()
    if v[:7].lower() != "bearer ":
        return ""
    return v[7:].strip()


def _yes(v):
    return v is True or str(v or "").strip().lower() in ("yes", "true", "1",
                                                         "y")


def _now_local():
    return datetime.now()


def _deadline(rec):
    """The bid due date and time as a local datetime (None without a
    date). The time defaults to 2:00 PM."""
    d = str(rec.get("due") or "").strip()[:10]
    try:
        day = datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        return None
    t = str(rec.get("due_time") or "2:00 PM").strip().upper()
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*([AP]\.?M\.?)?", t)
    if not m:
        return day.replace(hour=14)
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").replace(".", "")
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    try:
        return day.replace(hour=min(h, 23), minute=min(mi, 59))
    except ValueError:
        return day.replace(hour=14)


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _c2(v):
    """A float to the cent, half up - the same rule as app/dmoney.c2
    (Chief's round 7, Nov 9: round() here made 1.25 x 0.5 into 0.62 while
    the desktop's bid form total said 0.63). Kept here, not imported: this
    file runs on its own on a server."""
    from decimal import ROUND_HALF_UP, Decimal
    v = float(v)
    if v != v or abs(v) >= 1e15:
        return v
    v = round(v, 8 if abs(v) < 1e6 else 6 if abs(v) < 1e8 else 4)
    return float(Decimal(repr(v)).quantize(Decimal("0.01"),
                                           rounding=ROUND_HALF_UP))


# what the bid page of this hub understands beyond prices: "Scope item"
# lines (Included / Excluded) and a Clarifications list
BID_FEATURES = ("scope_items", "clarifications")


def bid_totals(lines, values):
    """Base bid, alternates and blank priced lines of a bid form (the same
    sums as app/pm/bidforms.totals - this file runs on its own on a
    server)."""
    base, alts, missing = 0.0, {}, []
    for i, ln in enumerate(lines or []):
        v = _num((values or {}).get(str(i)))
        t = ln.get("type")
        if t in ("Lump sum", "Unit price", "Allowance"):
            if t != "Allowance" and v is None:
                missing.append(ln.get("item") or str(i + 1))
            if t == "Lump sum":
                base += v or 0.0
            elif t == "Unit price":
                base += (v or 0.0) * (_num(ln.get("qty")) or 0.0)
            else:
                q = _num(ln.get("qty"))
                base += q if q is not None else (v or 0.0)
        elif t == "Alternate" and v is not None:
            alts[ln.get("item") or str(i + 1)] = v
    return {"base": _c2(base), "alternates": alts, "missing": missing}


# wrong passwords / keys per address: 5 a minute, then a minute's lockout
_FAILS = {}
_LOCKED = {}


def _blocked(ip, now=None):
    import time
    now = time.monotonic() if now is None else now
    until = _LOCKED.get(ip)
    if until is None:
        return False
    if now >= until:
        _LOCKED.pop(ip, None)
        _FAILS.pop(ip, None)
        return False
    return True


def _note_fail(ip, now=None):
    import time
    now = time.monotonic() if now is None else now
    q = [t for t in _FAILS.get(ip, []) if now - t <= 60] + [now]
    _FAILS[ip] = q
    if len(q) >= 5:
        _LOCKED[ip] = now + 60
    if len(_FAILS) > 10000:
        _FAILS.clear()


async def api_session(hub, ws, hello, ctx, relay_token=None):
    """Serve hub requests on an open WebSocket after an api hello."""
    import asyncio
    ip = (ctx or {}).get("ip", "")
    given = str((ctx or {}).get("bearer") or hello.get("token") or "")
    authed = not relay_token or hmac.compare_digest(given, relay_token)
    if relay_token and not authed and given:
        _note_fail(ip)
    await ws.send(json.dumps({"type": "api_ready", "authed": authed}))
    loop = asyncio.get_running_loop()
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        rid = msg.get("id")
        if _blocked(ip):
            await ws.send(json.dumps({
                "type": "api_reply", "id": rid, "ok": False,
                "error": "Too many wrong passwords. Wait a minute and try "
                         "again."}))
            continue
        try:
            res = await loop.run_in_executor(
                None, hub.call, str(msg.get("op")), msg.get("args"), ctx,
                authed)
            reply = {"type": "api_reply", "id": rid, "ok": True,
                     "result": res}
        except HubError as e:
            if str(e).startswith("Wrong"):
                _note_fail(ip)
            reply = {"type": "api_reply", "id": rid, "ok": False,
                     "error": str(e)}
        except Exception as e:                     # never kill the socket
            reply = {"type": "api_reply", "id": rid, "ok": False,
                     "error": f"Server error: {type(e).__name__}"}
        await ws.send(json.dumps(reply))


def _forwarded_ip(peer, xff):
    try:
        from .relaycore import forwarded_ip
    except ImportError:                 # server/hub.py run on its own
        from relaycore import forwarded_ip
    return forwarded_ip(peer, xff)


def ws_context(ws, headers=None):
    """Caller's address and browser, for the audit trail. Behind a proxy
    the address the proxy added is used (relaycore.forwarded_ip)."""
    from_header = ""
    agent = ""
    bearer = ""
    try:
        peer = str(ws.remote_address[0])
    except Exception:
        peer = ""
    try:
        h = headers if headers is not None else (
            getattr(getattr(ws, "request", None), "headers", None) or
            getattr(ws, "request_headers", None))
        if h is not None:
            from_header = h.get("X-Forwarded-For") or ""
            agent = h.get("User-Agent") or ""
            auth = str(h.get("Authorization") or "")
            if auth[:7].lower() == "bearer ":
                bearer = auth[7:].strip()
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    out = {"ip": _forwarded_ip(peer, from_header), "agent": agent}
    if bearer:
        out["bearer"] = bearer          # relay token from the handshake
    return out
