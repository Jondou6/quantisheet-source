"""Approval paths, the approvals inbox and escalation (P1-03, P1-06, P1-09).

A request walks ordered steps. Each step names principals:
  "role:Controller", "user:<id>" or "jobrole:PM" (the job's PM, else any
  Approver whose title is PM), and a mode: "any" (any one of them) or
  "all" (parallel: every principal must approve). No one approves a
record they own (their own time, an invoice they entered).
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import clock, jobs
from .security import Denied


class ApprovalError(ValueError):
    pass


def step(*principals, mode="any") -> dict:
    return {"principals": list(principals), "mode": mode}


def set_path(office, record_type, steps, job_id=None) -> int:
    office.require("routing.edit", "approval_path", job_id or "default")
    with office.db.tx():
        old = office.db.one("SELECT * FROM approval_paths WHERE record_type = ? "
                            "AND job_id IS ? AND deleted = 0",
                            (record_type, job_id))
        if old:
            office.db.soft_delete("approval_paths", old["id"])
        pid = office.db.insert("approval_paths", job_id=job_id,
                               record_type=record_type, steps=steps)
        office.audit("change", "approval_path", pid, old and old["steps"],
                     steps)
    return pid


def path_for(office, record_type, job_id=None) -> list:
    for jid in (job_id, None):
        r = office.db.one("SELECT steps FROM approval_paths WHERE record_type = ? "
                          "AND job_id IS ? AND deleted = 0 ORDER BY id DESC",
                          (record_type, jid))
        if r:
            return json.loads(r["steps"])
    return [step("jobrole:PM")]


def _users_for(office, principal, job_id) -> set[int]:
    kind, _, val = principal.partition(":")
    db = office.db
    if kind == "user":
        return {int(val)}
    if kind == "role":
        return {u["id"] for u in db.rows(
            "SELECT id FROM users WHERE role = ? AND active = 1", (val,))}
    if kind == "jobrole":
        ids = set(jobs.team(office, job_id, val)) if job_id else set()
        if not ids:
            ids = {u["id"] for u in db.rows(
                "SELECT id FROM users WHERE title = ? AND active = 1 AND "
                "role IN ('Approver','Admin','Controller')", (val,))}
        return ids
    raise ApprovalError(f"unknown principal {principal!r}")


def label(principal) -> str:
    kind, _, val = principal.partition(":")
    return val if kind in ("role", "jobrole") else f"user {val}"


def start(office, record_type, record_id, steps, job_id=None,
          escalate_days=None, escalate_to=None) -> int:
    db = office.db
    with db.tx():
        old = request(office, record_type, record_id)
        if old and old["status"] == "pending":
            db.update("approval_requests", old["id"], status="replaced")
        rid = db.insert("approval_requests", record_type=record_type,
                        record_id=record_id, job_id=job_id, steps=steps,
                        step=0, status="pending",
                        step_started=clock.iso_now(),
                        escalate_days=escalate_days, escalate_to=escalate_to,
                        approved_in_step=[], reassigned={})
        office.audit("submit", record_type, record_id, None,
                     {"path": [" / ".join(label(p) for p in s["principals"])
                               for s in steps]})
    return rid


def request(office, record_type, record_id) -> dict | None:
    r = office.db.one("SELECT * FROM approval_requests WHERE record_type = ? "
                      "AND record_id = ? AND status != 'replaced' "
                      "ORDER BY id DESC LIMIT 1", (record_type, record_id))
    if r:
        r["steps"] = json.loads(r["steps"])
        r["approved_in_step"] = json.loads(r["approved_in_step"] or "[]")
        r["reassigned"] = json.loads(r["reassigned"] or "{}")
    return r


def current_approvers(office, req) -> set[int]:
    if req["status"] != "pending":
        return set()
    s = req["steps"][req["step"]]
    ids = set()
    for p in s["principals"]:
        ids |= _users_for(office, p, req["job_id"])
    re_ = req["reassigned"].get(str(req["step"]))
    if re_:
        ids = {int(re_)}
    if s.get("mode") == "all":
        ids -= set(req["approved_in_step"])
    return ids


def waiting_on(office, req) -> str:
    if req is None or req["status"] != "pending":
        return ""
    s = req["steps"][req["step"]]
    return "waiting on " + " and ".join(label(p) for p in s["principals"])


def escalated(office, req) -> bool:
    """Waiting on the current step for more than escalate_days days."""
    if req["status"] != "pending" or not req["escalate_days"]:
        return False
    waited = (clock.today() - clock.d(req["step_started"])).days
    return waited > req["escalate_days"]


def can_act(office, req, user_id, owner_id=None) -> bool:
    if req is None or req["status"] != "pending":
        return False
    if owner_id is not None and owner_id == user_id:
        return False
    if user_id in current_approvers(office, req):
        return True
    if escalated(office, req) and req["escalate_to"]:
        return user_id in _users_for(office, req["escalate_to"], req["job_id"])
    return False


def decide(office, record_type, record_id, decision, reason="",
           owner_id=None) -> dict:
    """approve / reject the current step as the signed-in user. Returns the
    request; status 'approved' once the last step is done."""
    req = precheck(office, record_type, record_id, decision, reason, owner_id)
    uid = office.user["id"] if office.user else None
    db = office.db
    with db.tx():
        db.insert("approval_actions", record_type=record_type,
                  record_id=record_id, step=req["step"], user_id=uid,
                  decision=decision, reason=reason, ts=clock.iso_now())
        if decision == "reject":
            db.update("approval_requests", req["id"], status="rejected")
        else:
            s = req["steps"][req["step"]]
            done = req["approved_in_step"] + [uid]
            left = set()
            if s.get("mode") == "all":
                for p in s["principals"]:
                    us = _users_for(office, p, req["job_id"])
                    if not us & set(done):
                        left.add(p)
            if left:
                db.update("approval_requests", req["id"], approved_in_step=done)
            elif req["step"] + 1 >= len(req["steps"]):
                db.update("approval_requests", req["id"], status="approved",
                          approved_in_step=done)
            else:
                db.update("approval_requests", req["id"], step=req["step"] + 1,
                          approved_in_step=[], step_started=clock.iso_now())
        office.audit(decision, record_type, record_id,
                     {"step": req["step"]}, {"reason": reason} if reason else None)
    return request(office, record_type, record_id)


def precheck(office, record_type, record_id, decision="approve", reason="",
             owner_id=None) -> dict:
    """The checks decide() makes, run before the caller opens its
    transaction so a refusal is still written to the audit log."""
    if decision not in ("approve", "reject"):
        raise ApprovalError("decision must be approve or reject")
    req = request(office, record_type, record_id)
    if req is None or req["status"] != "pending":
        raise ApprovalError("nothing is waiting for approval")
    uid = office.user["id"] if office.user else None
    from .r111.duties import guard
    guard(office, record_type, record_id, decision, owner_id)
    if not can_act(office, req, uid):
        office.audit("denied", record_type, record_id, None,
                     {"reason": "not an approver for this step"})
        raise Denied(f"{office.who} is not an approver for this step "
                     f"({waiting_on(office, req)}).")
    if decision == "reject" and not (reason or "").strip():
        raise ApprovalError("A reason is required to reject.")
    return req


def reassign(office, record_type, record_id, to_user_id, reason="") -> None:
    req = request(office, record_type, record_id)
    uid = office.user["id"]
    if not (can_act(office, req, uid) or office.role in ("Admin", "Controller")):
        raise Denied("Only a current approver, Controller or Admin can reassign.")
    with office.db.tx():
        r = dict(req["reassigned"])
        r[str(req["step"])] = to_user_id
        office.db.update("approval_requests", req["id"], reassigned=r)
        office.audit("reassign", record_type, record_id, None,
                     {"to": to_user_id, "reason": reason})


def inbox(office, user_id=None, record_type=None) -> list[dict]:
    uid = user_id or office.user["id"]
    q = "SELECT * FROM approval_requests WHERE status = 'pending'"
    p = []
    if record_type:
        q += " AND record_type = ?"
        p.append(record_type)
    out = []
    for r in office.db.rows(q + " ORDER BY id", p):
        req = request(office, r["record_type"], r["record_id"])
        if req["id"] != r["id"]:
            continue
        mine = uid in current_approvers(office, req)
        esc = escalated(office, req) and req["escalate_to"] and \
            uid in _users_for(office, req["escalate_to"], req["job_id"])
        if mine or esc:
            out.append({"record_type": req["record_type"],
                        "record_id": req["record_id"],
                        "waiting": waiting_on(office, req),
                        "escalated": bool(escalated(office, req)),
                        "via_escalation": bool(esc and not mine)})
    return out


def overdue(office) -> list[dict]:
    out = []
    for r in office.db.rows("SELECT * FROM approval_requests WHERE "
                            "status = 'pending'"):
        req = request(office, r["record_type"], r["record_id"])
        if req and req["id"] == r["id"] and escalated(office, req):
            out.append(req)
    return out
