"""Workflow buttons for each tool (Send RFI, Ready for Review, Close...).

Each action is (label, icon, available(rec) -> bool, run(ctx, rec) -> rec).
``ctx`` gives the store and a way to email: run() changes the record and
returns it (the form saves it), and may send mail with the item's PDF.
Actions that need a choice (a review response) ask through ctx.ask().
"""
import logging
import os
from datetime import date

from . import schema
from .schema import workdays_from


def _today():
    return date.today().isoformat()


class Ctx:
    """What actions may use. The UI passes one in; tests use a stub."""

    def __init__(self, store, ask=None, notify=None, mail=True,
                 ask_text=None, open_file=None, pick_file=None,
                 takeoff_doc=None, level=None):
        self.store = store
        self.ask = ask or (lambda title, options: options[0])
        self.ask_text = ask_text or (lambda title, default="": default)
        self.open_file = open_file or (lambda path: None)
        self.notify = notify or (lambda text: None)
        self.mail = mail
        # pick_file(title, filter) -> path or None
        self.pick_file = pick_file or (lambda title, filt="": None)
        # the PDF open in QuantiSheet (for quantities), or None
        self.takeoff_doc = takeoff_doc or (lambda: None)
        # level(bids, title, plugs=, on_plugs=): show bid leveling
        self.level = level or (lambda bids, title="", **kw: None)

    def emails(self, *who):
        out = []
        for w in who:
            if not w:
                continue
            if isinstance(w, (list, tuple)):
                out += self.emails(*w)
                continue
            e = self.store.email_of(w)
            out += [x.strip() for x in e.split(";") if x.strip()]
        seen, uniq = set(), []
        for e in out:
            if e.lower() not in seen:
                seen.add(e.lower())
                uniq.append(e)
        return uniq

    def send(self, key, rec, to, cc=(), subject=None, body="",
             extra_files=()):
        """Email rec's PDF (plus its attachments when small)."""
        if not self.mail:
            return None
        from .. import mail
        from .report import temp_pdf
        to_list = self.emails(to)
        if not to_list:
            self.notify("No email address for " +
                        (", ".join(to) if isinstance(to, (list, tuple))
                         else str(to or "the recipient")) +
                        " - add them in the Directory. The change was "
                        "saved; nothing was sent.")
            return None
        t = schema.TOOLS[key]
        tf = t.get("title_field", "title")
        subject = subject or (f"{self.store.name}: {t['one']} "
                              f"{rec.get('_no', '')} - "
                              f"{rec.get(tf, '')}")
        files = [temp_pdf(self.store, key, rec)]
        total = 0
        for f in t["fields"]:
            if f["type"] != "attachments":
                continue
            for a in rec.get(f["key"]) or []:
                total += a.get("size", 0)
                if total > 15 * 1024 * 1024:
                    break
                try:
                    files.append(self.store.attachment_path(a))
                except Exception:
                    logging.getLogger(__name__).debug("ignored error", exc_info=True)
        files += list(extra_files)
        body = (body or "") + f"\n\nSent from QuantiSheet for " \
            f"{self.store.name}."
        how = mail.send(to_list, subject, body.strip(),
                        cc=[c for c in self.emails(cc) if c not in to_list],
                        attachments=files)
        self.notify(mail.describe(how))
        return how


# ------------------------------------------------------------------ RFIs
def rfi_send(ctx, r):
    r["status"] = "Open"
    r.setdefault("submitted", _today())
    r["submitted"] = r.get("submitted") or _today()
    ctx.send("rfi", r, r.get("to"), r.get("cc"),
             body=f"Please answer {r.get('_no')} by "
                  f"{r.get('due') or 'the due date'}.\n\n"
                  f"{r.get('question', '')}")
    return r


def rfi_close(ctx, r):
    r["status"] = "Closed"
    r["answered"] = r.get("answered") or _today()
    r["answered_by"] = r.get("answered_by") or r.get("to") or ctx.store.me
    ctx.send("rfi", r, r.get("from") or r.get("_by"),
             [r.get("to")] + list(r.get("cc") or []),
             body=f"{r.get('_no')} is answered:\n\n{r.get('answer', '')}")
    return r


def reopen(ctx, r):
    r["status"] = "Open"
    return r


# ------------------------------------------------------------ submittals
def _next_step(r):
    for i, s in enumerate(r.get("workflow") or []):
        if not s.get("returned"):
            return i
    return None


def sub_send(ctx, r):
    steps = r.get("workflow") or []
    if not steps:
        rev = ctx.store.setting("default_reviewer") or ""
        steps = [{"reviewer": rev, "days": r.get("review_days") or 10}]
    i = _next_step({"workflow": steps})
    if i is None:
        i = 0
    s = steps[i]
    s["sent"] = _today()
    s["due"] = workdays_from(date.today(),
                             int(s.get("days") or 10)).isoformat()
    r["workflow"] = steps
    r["status"] = "In Review"
    r["received"] = r.get("received") or _today()
    ctx.send("submittal", r, s.get("reviewer"), r.get("cc"),
             body=f"Please review submittal {r.get('_no')} "
                  f"(revision {r.get('revision') or 0}) and respond by "
                  f"{s['due']}.")
    return r


def sub_respond(ctx, r):
    i = _next_step(r)
    if i is None:
        return r
    res = ctx.ask("Reviewer's response", schema.REVIEW_RESULTS[1:])
    if not res:
        return None
    s = r["workflow"][i]
    s["returned"] = _today()
    s["result"] = res
    if res in ("Revise and Resubmit", "Rejected"):
        r["status"] = res
        ctx.send("submittal", r, r.get("responsible"), r.get("cc"),
                 body=f"Submittal {r.get('_no')} was returned: {res}.")
        return r
    j = _next_step(r)
    if j is not None:                       # on to the next reviewer
        return sub_send(ctx, r)
    r["status"] = res if res != "For Record Only" else "Closed"
    ctx.send("submittal", r, r.get("responsible"), r.get("cc"),
             body=f"Submittal {r.get('_no')} is {r['status'].lower()}.")
    return r


def sub_package(ctx, r):
    """The submittal as one PDF for the architect and engineers: cover
    sheet with the CSI section, review stamps, then the attachments
    (app/pm/submittals.py). Kept on the record so Send for Review mails
    it."""
    from . import submittals
    path = submittals.package_pdf(ctx.store, r)
    r = submittals.attach_package(ctx.store, r, path)
    ctx.notify(f"Saved {os.path.basename(path)} in the Submittals folder.")
    ctx.open_file(path)
    return r


def sub_resubmit(ctx, r):
    r["revision"] = int(r.get("revision") or 0) + 1
    for s in r.get("workflow") or []:
        for k in ("sent", "due", "returned", "result"):
            s[k] = ""
    r["status"] = "Not Submitted"
    return r


# ----------------------------------------------------------------- punch
def punch_assign(ctx, r):
    r["status"] = "Work Required"
    ctx.send("punch", r, r.get("assignee"),
             body=f"Punch item {r.get('_no')} at "
                  f"{r.get('location') or 'the site'} needs work by "
                  f"{r.get('due') or 'the due date'}.")
    return r


def punch_ready(ctx, r):
    r["status"] = "Ready for Review"
    ctx.send("punch", r, r.get("manager") or r.get("_by"),
             body=f"{r.get('_no')} is ready for your review.")
    return r


def punch_accept(ctx, r):
    if r.get("final_approver") and r.get("status") == "Ready for Review":
        r["status"] = "Ready to Close"
        ctx.send("punch", r, r.get("final_approver"),
                 body=f"{r.get('_no')} is ready to close.")
    else:
        r["status"] = "Closed"
    return r


def punch_reject(ctx, r):
    r["status"] = "Not Accepted"
    ctx.send("punch", r, r.get("assignee"),
             body=f"{r.get('_no')} was not accepted - please fix and mark "
                  "it ready again.")
    return r


def close(ctx, r):
    r["status"] = "Closed"
    if "closed_on" in {f["key"] for f in schema.TOOLS.get(
            r.get("_coll"), {}).get("fields", [])}:
        r["closed_on"] = _today()
    return r


def obs_ready(ctx, r):
    r["status"] = "Ready for Review"
    ctx.send("observation", r, r.get("_by"),
             body=f"{r.get('_no')} is ready for review.")
    return r


def obs_assign(ctx, r):
    ctx.send("observation", r, r.get("assignee"),
             body=f"Observation {r.get('_no')} ({r.get('type')}) needs "
                  "your attention.")
    return r


def obs_reject(ctx, r):
    r["status"] = "Not Accepted"
    ctx.send("observation", r, r.get("assignee"),
             body=f"{r.get('_no')} was not accepted.")
    return r


def issue_email(ctx, r):
    ctx.send("issue", r, r.get("assignee"))
    return r


# ----------------------------------------------------------- transmittal
def tr_send(ctx, r):
    r["status"] = "Sent"
    r["sent"] = _today()
    ctx.send("transmittal", r, r.get("to"), r.get("cc"),
             body=f"Transmittal {r.get('_no')}: {r.get('purpose', '')}."
                  f"\n\n{r.get('notes', '')}")
    return r


def tr_ack(ctx, r):
    r["status"] = "Acknowledged"
    r["acknowledged"] = _today()
    return r


# ---------------------------------------------------------------- meetings
def meet_distribute(ctx, r):
    r["status"] = "Distributed"
    people = [a.get("name") for a in r.get("attendees") or []]
    ctx.send("meeting", r, people + list(r.get("cc") or []),
             subject=f"{ctx.store.name}: minutes of {r.get('title')} "
                     f"({r.get('date')})",
             body="Minutes attached. Please send corrections within "
                  "3 working days.")
    return r


def meet_next(ctx, r):
    """A new meeting carrying forward open topics and the attendee list
    (returns the new meeting, which the UI opens)."""
    topics = [dict(t, discussion=t.get("discussion", ""))
              for t in r.get("topics") or []
              if (t.get("status") or "Open") != "Closed"]
    new = {"title": r.get("title"), "type": r.get("type"),
           "time": r.get("time"), "location": r.get("location"),
           "status": "Agenda", "date": "",
           "attendees": [{"name": a.get("name"),
                          "company": a.get("company"), "present": ""}
                         for a in r.get("attendees") or []],
           "topics": topics, "cc": r.get("cc") or []}
    try:
        from datetime import datetime
        d = datetime.fromisoformat(r.get("date") or "").date()
        from datetime import timedelta
        new["date"] = (d + timedelta(days=7)).isoformat()
    except ValueError:
        new["date"] = _today()
    saved = ctx.store.save_record("meeting", new)
    ctx.notify(f"Created {saved.get('_no')} with {len(topics)} open "
               "topic(s) carried forward.")
    return {"_open": ("meeting", saved["_id"])}


def meet_issues(ctx, r):
    n = 0
    for t in r.get("topics") or []:
        if (t.get("status") or "Open") == "Open" and t.get("owner") and \
                not t.get("issue"):
            iss = ctx.store.save_record("issue", {
                "title": t.get("topic") or "Meeting item",
                "assignee": t.get("owner"), "due": t.get("due") or "",
                "description": t.get("discussion", ""),
                "meeting": r["_id"], "status": "Open"})
            t["issue"] = iss.get("_no")
            n += 1
    ctx.notify(f"Created {n} issue(s) from open topics with an owner.")
    return r


# ----------------------------------------------------------------- daily
def daily_copy(ctx, r):
    prev = [x for x in ctx.store.list("daily")
            if x.get("date", "") < (r.get("date") or "9999") and
            x["_id"] != r.get("_id")]
    if not prev:
        ctx.notify("No earlier log to copy from.")
        return r
    p = max(prev, key=lambda x: x.get("date", ""))
    r["manpower"] = [dict(m) for m in p.get("manpower") or []]
    r["equipment"] = [dict(e) for e in p.get("equipment") or []]
    ctx.notify(f"Copied crews and equipment from {p.get('date')}.")
    return r


def daily_submit(ctx, r):
    r["status"] = "Submitted"
    return r


# ------------------------------------------------------------- inspection
def insp_fill(ctx, r):
    from .templates import items_for
    if r.get("template") and not r.get("items"):
        r["items"] = items_for(r["template"])
    return r


def insp_finish(ctx, r):
    items = r.get("items") or []
    failed = [i for i in items if i.get("result") == "No"]
    r["status"] = "Failed" if failed else "Passed"
    r["signed_by"] = r.get("signed_by") or ctx.store.me
    if failed:
        for i in failed:
            ctx.store.save_record("observation", {
                "title": i.get("item"), "type": "Quality",
                "location": r.get("location", ""),
                "description": f"Failed on {r.get('_no')}: "
                               f"{i.get('note', '')}".strip(),
                "status": "Initiated"})
        ctx.notify(f"{len(failed)} failed item(s) became observations.")
    return r


def exp_delivered(ctx, r):
    r["status"] = "Delivered"
    r["delivered"] = _today()
    return r


# ------------------------------------------------------------------ cost
def ev_send(ctx, r):
    from . import cost
    r["status"] = "Pending"
    r["submitted"] = _today()
    owner = ctx.store.setting("owner_contact") or ctx.store.setting("owner")
    ctx.send("event", r, owner,
             subject=f"{ctx.store.name}: change order request "
                     f"{r.get('_no')} - {r.get('title')}",
             body=f"Please review and approve {r.get('_no')} for "
                  f"{cost.money_fmt(cost.event_price(r))}"
                  + (f" and {r.get('days')} day(s)" if r.get("days")
                     else "") + ".")
    return r


def ev_approve(ctx, r):
    r["status"] = "Approved"
    r["approved"] = r.get("approved") or _today()
    if not r.get("co_no"):
        # next number after the highest one, compared as numbers: a count
        # repeats a number once a CO is deleted (review 3 #10)
        import re
        nums = [int(m.group(1)) for e in ctx.store.list("event")
                if e.get("co_no") and e["_id"] != r.get("_id")
                for m in [re.search(r"(\d+)\s*$", str(e["co_no"]))] if m]
        r["co_no"] = f"CO-{max(nums, default=0) + 1:03d}"
    return r


def ev_reject(ctx, r):
    r["status"] = "Rejected"
    return r


def cm_send(ctx, r):
    r["status"] = "Out for Signature"
    ctx.send("commitment", r, r.get("vendor"),
             body=f"Please sign and return {r.get('_no')} "
                  f"({r.get('title')}).")
    return r


def cm_execute(ctx, r):
    r["status"] = "Executed"
    r["executed"] = r.get("executed") or _today()
    return r


def cost_approve(ctx, r):
    r["status"] = "Approved"
    r["approved_by"] = ctx.store.me
    return r


def cost_paid(ctx, r):
    from . import cost
    issues = cost.compliance(ctx.store, r, "cost")
    if issues:
        pick = ctx.ask("Compliance: " + "; ".join(issues),
                       ["Don't pay yet", "Pay anyway"])
        if pick != "Pay anyway":
            return None
        r["compliance_override"] = f"{ctx.store.me}: " + "; ".join(issues)
    r["status"] = "Paid"
    r["paid"] = r.get("paid") or _today()
    return r


def pa_fill(ctx, r):
    from . import cost
    r["lines"] = cost.fill_payapp(ctx.store, r)
    ctx.notify(f"{len(r['lines'])} line(s) from the contract and approved "
               "change orders - type this period's work.")
    return r


def sp_fill(ctx, r):
    from . import subpay
    try:
        r["lines"] = subpay.fill(ctx.store, r)
    except subpay.SubPayError as e:
        ctx.notify(str(e))
        return None
    ctx.notify(f"{len(r['lines'])} line(s) from the subcontract - type "
               "this period's work.")
    return r


def sp_submit(ctx, r):
    r["status"] = "Submitted"
    return r


def sp_approve(ctx, r):
    from . import subpay
    note = r.get("review_note") or ""
    issues = subpay.problems(r)
    if issues and not note:
        note = ctx.ask_text("It bills past the schedule of values (" +
                            "; ".join(issues) + "). Why approve it?", "")
        if not note:
            return None
    r["status"] = "Approved"
    r["reviewed_by"] = ctx.store.me
    r["review_note"] = note
    return r


def sp_reject(ctx, r):
    note = ctx.ask_text("Why is it going back to the sub?", "")
    if not note:
        return None
    r["status"] = "Rejected"
    r["reviewed_by"] = ctx.store.me
    r["review_note"] = note
    return r


def pa_subs(ctx, r):
    from . import subpay
    try:
        rep = subpay.feed_owner(ctx.store, r)
    except subpay.SubPayError as e:
        ctx.notify(str(e))
        return None
    msg = (f"{len(rep['subs'])} approved sub pay app(s) rolled in: "
           f"${rep['work']:,.2f} work, ${rep['stored']:,.2f} stored, on "
           f"{len(rep['fed'])} line(s).")
    if rep["kept"]:
        msg += " Kept what you'd typed on: " + ", ".join(rep["kept"]) + "."
    ctx.notify(msg)
    return rep["payapp"]


def _pa_pdf(ctx, r):
    import os
    from . import cost
    folder = os.path.join(ctx.store.folder, "Pay Applications")
    os.makedirs(folder, exist_ok=True)
    from ..reportname import report_file_name
    path = os.path.join(folder, report_file_name(
        "Pay Application", ctx.store.name, cost.app_no(ctx.store, r),
        r.get("period_to")))
    return cost.payapp_pdf(ctx.store, r, path)


def pa_print(ctx, r):
    path = _pa_pdf(ctx, r)
    ctx.notify(f"Saved {path}")
    ctx.open_file(path)
    return r


def pa_submit(ctx, r):
    ctx.store.save_record("payapp", r)
    path = _pa_pdf(ctx, r)
    r["status"] = "Submitted"
    owner = ctx.store.setting("owner_contact") or ctx.store.setting(
        "architect_contact") or ctx.store.setting("owner")
    ctx.send("payapp", r, owner,
             subject=f"{ctx.store.name}: pay application for the period "
                     f"to {r.get('period_to')}",
             body="Our application for payment is attached.",
             extra_files=[path])
    return r


def pa_certify(ctx, r):
    r["status"] = "Certified"
    return r


def pa_paid(ctx, r):
    from . import cost
    try:
        due = cost.payapp_values(ctx.store, r)["g702"]["8"]
    except Exception:
        due = 0.0
    amt = ctx.ask_text("Amount received", f"{due:.2f}")
    if amt in (None, ""):
        return None
    try:
        r["received"] = round(float(str(amt).replace("$", "")
                                    .replace(",", "")), 2)
    except ValueError:
        ctx.notify("Not an amount.")
        return None
    r["received_on"] = _today()
    r["status"] = "Paid"
    return r


# --------------------------------------------------------------- bidding
def _bid_link(ctx, path):
    from ..collab.hubclient import web_base
    h = ctx.store.data.get("hub") or {}
    return web_base(h.get("url")) + path


def _sheet_numbers(ctx):
    """Sheet numbers of the drawing set open in QuantiSheet (its bookmarks
    or drawing register), for "Sheets to start with". [] if none."""
    try:
        doc = ctx.takeoff_doc()
    except Exception:
        doc = None
    if doc is None:
        return []
    import re
    out = []
    try:
        for _lvl, title, _p in doc.get_toc(simple=True):
            m = re.match(r"^\s*([A-Z]{1,3}-?\d+[A-Z]?)\b", str(title))
            if m and m.group(1) not in out:
                out.append(m.group(1))
    except Exception:
        return []
    return out


def bid_invite(ctx, r):
    from .. import mail
    rows = r.get("bidders") or []
    new = [b for b in rows if not b.get("token") and
           (b.get("email") or ctx.store.email_of(b.get("company")) or
            ctx.store.email_of(b.get("contact")))]
    if not rows:
        ctx.notify("Add bidders first (company and email).")
        return None
    links = {}
    if ctx.store.connected and new:
        saved = ctx.store.save_record("bidpkg", r)
        ctx.store.sync()
        h = ctx.store.data["hub"]
        res = ctx.store.client().call(
            "bid.invite", project=h["project"], key=h["key"],
            record_id=saved["_id"], user=ctx.store.me,
            bidders=[{"company": b.get("company"),
                      "email": b.get("email")} for b in new])
        r = ctx.store.get("bidpkg", saved["_id"])
        rows = r.get("bidders") or []
        new = [b for b in rows if not b.get("token") and
               (b.get("email") or ctx.store.email_of(b.get("company")))]
        for b, inv in zip(new, res["invites"]):
            b["token"] = inv["token"]
            links[inv["token"]] = _bid_link(ctx, inv["link"])
    # the personal invitation (Chief's v18): "Hi Steve,", the package,
    # the sheets to start with, key dates, and Yes / Unsure / No buttons;
    # sent from the "Bid invites send as" mailbox (Bids@...), never from
    # someone's own mailbox instead
    from .. import bid_followup as invite_boost   # invitations live here
    sender = invite_boost.live_sender()
    project = {"name": ctx.store.name,
               "number": ctx.store.data.get("number") or "",
               "owner": ctx.store.data.get("owner") or "",
               "location": ctx.store.data.get("location") or ""}
    sheets = _sheet_numbers(ctx)
    sent = 0
    for b in new:
        to = b.get("email") or ctx.store.email_of(b.get("company")) or \
            ctx.store.email_of(b.get("contact"))
        if not to or not mail.valid(to.split(";")[0].strip()):
            continue
        link = links.get(b.get("token"))
        m = invite_boost.build_invite(r, dict(b, email=to), project, sender,
                                      link or "", sheets)
        body = m["text"]
        if not link:
            body += "\n\nThe bid documents are attached."
        if ctx.mail:
            files = []
            if not link:
                for a in r.get("documents") or []:
                    try:
                        files.append(ctx.store.attachment_path(a))
                    except Exception:
                        logging.getLogger(__name__).debug("ignored error", exc_info=True)
            try:
                how = mail.send([to], m["subject"], body,
                                attachments=files,
                                html=m["html"] if link else None,
                                send_as=sender["email"])
            except mail.MailError as e:
                ctx.notify(str(e))
                break
            if how:
                sent += 1
        b["status"] = b.get("status") or "Invited"
        if b["status"] == "":
            b["status"] = "Invited"
        b["invited"] = _today()
    r["status"] = "Open"
    ctx.notify(f"Invited {sent} bidder(s)." + ("" if ctx.store.connected
                                               else " Share the project to "
                                               "give bidders a response "
                                               "page."))
    return r


def bid_remind(ctx, r):
    from .. import mail
    n = 0
    for b in r.get("bidders") or []:
        if b.get("status") in ("Won't Bid", "Bid Received", "Awarded"):
            continue
        to = b.get("email") or ctx.store.email_of(b.get("company"))
        if not to or not ctx.mail:
            continue
        link = _bid_link(ctx, f"/bid.html?t={b['token']}") \
            if b.get("token") and ctx.store.connected else ""
        mail.send([to], f"Reminder: bids due {r.get('due')} - "
                        f"{ctx.store.name} {r.get('title')}",
                  f"A reminder that bids for {r.get('title')} are due "
                  f"{r.get('due')} {r.get('due_time') or ''}.\n\n{link}")
        n += 1
    ctx.notify(f"Reminded {n} bidder(s).")
    return r


def bid_close(ctx, r):
    r["status"] = "Closed"
    return r


def bid_award(ctx, r):
    bids = [b for b in r.get("bidders") or [] if b.get("amount")]
    if not bids:
        ctx.notify("No bid amounts yet - enter them in the Bidders table.")
        return None
    bids.sort(key=lambda b: float(b.get("amount") or 0))
    labels = [f"{b.get('company')}  ${float(b['amount']):,.0f}"
              for b in bids]
    pick = ctx.ask("Award to", labels)
    if not pick:
        return None
    b = bids[labels.index(pick)]
    b["status"] = "Awarded"
    r["status"] = "Awarded"
    r["awarded_to"] = b.get("company")
    r["award_amount"] = float(b["amount"])
    c = ctx.store.save_record("commitment", {
        "title": r.get("title"), "vendor": b.get("company"),
        "type": "Subcontract", "status": "Draft",
        "lines": [{"cost_code": r.get("trades") or "",
                   "description": r.get("title"),
                   "amount": float(b["amount"])}],
        "scope": r.get("scope", "")})
    # remember who bid and who won (Company Directory bid history)
    try:
        from .. import subdir
        for x in r.get("bidders") or []:
            if x.get("amount") in (None, "") and x.get("status") != \
                    "Won't Bid":
                continue
            subdir.record_bid(x.get("company"), ctx.store.name,
                              r.get("title"), x.get("amount"),
                              "Awarded" if x is b else
                              ("Declined" if x.get("status") == "Won't Bid"
                               else "Not awarded"))
    except Exception:
        logging.getLogger(__name__).debug("bid history skipped",
                                          exc_info=True)
    # award and regret letters, attached for review before sending
    how = ctx.ask("Award letters", ["Make award and regret letters",
                                    "Award letter only", "No letters"])
    made = 0
    if how and how != "No letters":
        from . import bidletters
        refs = bidletters.make_letters(ctx.store, r, b, b["amount"],
                                       regrets=how.startswith("Make award"))
        r["letters"] = list(r.get("letters") or []) + refs
        r.pop("letters_sent", None)
        made = len(refs)
    ctx.notify(f"Awarded to {b.get('company')} - draft subcontract "
               f"{c.get('_no')} created." +
               (f" {made} letter(s) attached - open them to check, then "
                "Send Award Letters." if made else ""))
    return r


def bid_send_letters(ctx, r):
    """Email each attached award / regret letter to its bidder."""
    from .. import mail
    sent = 0
    for ref in r.get("letters") or []:
        if ref.get("sent") or not ref.get("letter"):
            continue
        to = ref.get("email") or ctx.store.email_of(ref.get("company"))
        if not to or not mail.valid(to.split(";")[0].strip()):
            continue
        try:
            path = ctx.store.attachment_path(ref)
        except Exception as e:
            ctx.notify(f"{ref.get('name')}: {e}")
            continue
        subj = (f"Notice of intent to award - {ctx.store.name} "
                f"{r.get('title')}" if ref["letter"] == "award" else
                f"Bid results - {ctx.store.name} {r.get('title')}")
        body = ("Please see the attached letter." if ref["letter"] ==
                "award" else "Thank you for your bid - please see the "
                "attached letter.")
        if ctx.mail and mail.send([to], subj, body, attachments=[path]):
            ref["sent"] = _today()
            sent += 1
    r["letters_sent"] = _today() if sent else r.get("letters_sent")
    ctx.notify(f"Sent {sent} letter(s).")
    return r


# ------------------------------------------------------------ bid forms
def bid_form(ctx, r):
    """Fill the package's bid form from a template, the takeoff of the
    open drawing, a spreadsheet or another package."""
    from . import bidforms
    lib = bidforms.library()
    opts = [f"Template: {n}" for n in lib]
    opts += ["Quantities from the takeoff in the open drawing",
             "Import from Excel or CSV…", "Copy from another bid package"]
    pick = ctx.ask("Bid form from", opts)
    if not pick:
        return None
    if pick.startswith("Template: "):
        lines = lib[pick[len("Template: "):]]
    elif pick.startswith("Quantities"):
        doc = ctx.takeoff_doc()
        lines = bidforms.from_takeoff(doc) if doc is not None else []
        if not lines:
            ctx.notify("Open a drawing with takeoff in QuantiSheet first.")
            return None
    elif pick.startswith("Import"):
        path = ctx.pick_file("Bid form lines", "Spreadsheets (*.xlsx *.csv)")
        if not path:
            return None
        try:
            lines = bidforms.import_lines(path)
        except Exception as e:
            ctx.notify(f"Couldn't read that file ({e}).")
            return None
    else:
        others = [o for o in ctx.store.list("bidpkg")
                  if o.get("_id") != r.get("_id") and o.get("form")]
        if not others:
            ctx.notify("No other package has a bid form yet.")
            return None
        labels = [f"{o.get('_no', '')} {o.get('title', '')}" for o in others]
        got = ctx.ask("Copy the form of", labels)
        if not got:
            return None
        lines = bidforms.clean(others[labels.index(got)]["form"])
    if not lines:
        ctx.notify("No lines found.")
        return None
    if r.get("form"):
        how = ctx.ask("This package already has a bid form",
                      ["Replace it", "Add these lines"])
        if not how:
            return None
        if how.startswith("Add"):
            lines = bidforms.clean(list(r["form"]) + list(lines))
            for i, ln in enumerate(lines, 1):
                ln["item"] = str(i)
    r["form"] = bidforms.clean(lines)
    ctx.notify(f"Bid form has {len(r['form'])} line(s). Bidders price them "
               "on their bid page.")
    return r


def bid_save_template(ctx, r):
    from . import bidforms
    name = ctx.ask_text("Save bid form as template named",
                        r.get("title") or "My bid form")
    if not name:
        return None
    bidforms.save_template(name, r.get("form") or [])
    ctx.notify(f"Saved template \"{name}\".")
    return None


def _add_bidders(r, new):
    have = {(b.get("email") or "").lower() for b in r.get("bidders") or []
            if b.get("email")}
    have |= {(b.get("company") or "").lower() for b in r.get("bidders")
             or [] if b.get("company") and not b.get("email")}
    n = 0
    for b in new:
        key = (b.get("email") or b.get("company") or "").lower()
        if not key or key in have:
            continue
        have.add(key)
        r.setdefault("bidders", []).append(
            {"company": b.get("company", ""), "contact": b.get("contact",
                                                               ""),
             "email": b.get("email", ""), "status": "", "amount": None,
             "note": b.get("note", "")})
        n += 1
    return n


def bid_import_bidders(ctx, r):
    """Bidders from a spreadsheet: Company, Contact, Email (and Phone,
    Trade) columns."""
    from .bidforms import import_rows
    path = ctx.pick_file("Bidder list", "Spreadsheets (*.xlsx *.csv)")
    if not path:
        return None
    try:
        rows = import_rows(path)
    except Exception as e:
        ctx.notify(f"Couldn't read that file ({e}).")
        return None
    n = _add_bidders(r, rows)
    ctx.notify(f"Added {n} bidder(s)" + (f" ({len(rows) - n} already on "
                                         "the list)" if len(rows) > n else
                                         "") + ".")
    return r


def bid_from_directory(ctx, r):
    """Subcontractors in the project Directory whose trade matches."""
    subs = [m for m in ctx.store.list("member")
            if (m.get("role") or "") in ("Subcontractor", "Supplier",
                                          "Vendor") or m.get("trade")]
    if not subs:
        ctx.notify("No subcontractors in the Directory yet.")
        return None
    words = {w for w in __import__("re").findall(
        r"[a-z]{4,}", f"{r.get('title', '')} {r.get('trades', '')}".lower())}
    match = [m for m in subs if words & set(__import__("re").findall(
        r"[a-z]{4,}", (m.get("trade") or "").lower()))]
    opts = []
    if match:
        opts.append(f"Add the {len(match)} matching this trade")
    opts.append(f"Add all {len(subs)} subcontractors")
    pick = ctx.ask("Add bidders from the Directory", opts)
    if not pick:
        return None
    use = match if pick.startswith("Add the") else subs
    n = _add_bidders(r, [{"company": m.get("company") or m.get("name"),
                          "contact": m.get("name"),
                          "email": m.get("email")} for m in use])
    ctx.notify(f"Added {n} bidder(s).")
    return r


def bid_from_company(ctx, r):
    """Bidders from your Company Directory: the subs in this package's CSI
    division (or trade), with an email."""
    from .. import subdir
    allc = subdir.load()
    if not allc:
        ctx.notify("Your Company Directory is empty - import your contacts "
                   "(Project Center > Company Directory > Import).")
        return None
    match = subdir.for_package(r, allc)
    if not match:
        ctx.notify("No contacts in the Company Directory match this "
                   "package's division or trade.")
        return None
    states = sorted({c.get("state") for c in match if c.get("state")})
    opts = [f"Add all {len(match)} matching subs"]
    pq = [c for c in match if subdir.prequal_ok(c)]
    fav = [c for c in match if c.get("favorite")]
    if pq:
        opts.append(f"Only prequalified ({len(pq)})")
    if fav:
        opts.append(f"Only favorites ({len(fav)})")
    opts += [f"Only {s} ({sum(1 for c in match if c.get('state') == s)})"
             for s in states]
    pick = ctx.ask("Add bidders from the Company Directory", opts)
    if not pick:
        return None
    if pick.startswith("Only prequalified"):
        match = pq
    elif pick.startswith("Only favorites"):
        match = fav
    elif pick.startswith("Only "):
        st = pick.split()[1]
        match = [c for c in match if c.get("state") == st]
    # flag what the GC should know before inviting
    late = {c.get("company") for c, what, _d, ex in subdir.alerts(match)
            if ex}
    for c in match:
        c["_flag"] = "; ".join(x for x in (
            "" if subdir.prequal_ok(c) else
            f"prequal: {subdir.prequal_status(c).lower()}",
            "insurance expired" if c.get("company") in late else "") if x)
    n = _add_bidders(r, [{"company": c.get("company"),
                          "contact": c.get("contact"),
                          "email": c.get("email"),
                          "note": c.get("_flag", "")} for c in match])
    ctx.notify(f"Added {n} bidder(s) from the Company Directory.")
    return r


def _addendum_draft(ctx, r, path, no):
    """"What changed" written for you (Chief's v20): the revised PDF is
    compared sheet by sheet with the set open in QuantiSheet - changed
    sheets (with the takeoff they touch), new and removed sheets - for
    this package's sheets. "" when there's nothing to compare."""
    if not path or not str(path).lower().endswith(".pdf"):
        return ""
    try:
        cur = ctx.takeoff_doc()
    except Exception:
        cur = None
    if cur is None:
        return ""
    try:
        import fitz
        from .. import addendum_summary as asum
        new = fitz.open(path)
        try:
            summ = asum.summarize(cur, new)
        finally:
            new.close()
        label = f"Addendum {no}"
        if asum.sheets_for_package(r, summ):
            return asum.draft(r, summ, label)
        return asum.text(summ, label)
    except Exception:
        logging.getLogger(__name__).warning("addendum summary",
                                            exc_info=True)
        return ""


def bid_addendum(ctx, r):
    """Issue an addendum: number it, attach it, and tell every bidder who
    hasn't declined (they must acknowledge it to submit)."""
    from datetime import date as _d
    from .. import mail
    from . import bidforms
    no = str(bidforms.next_addendum(r))
    path = ctx.pick_file(f"Addendum {no} document (optional)",
                         "Documents (*.pdf *.docx *.xlsx *.dwg *.zip)")
    desc = ctx.ask_text("Addendum - what changed?",
                        _addendum_draft(ctx, r, path, no))
    if not desc:
        return None
    if path:
        try:
            ref = ctx.store.attach(path)
            ref["name"] = f"Addendum {no} - {ref['name']}"
            r.setdefault("documents", []).append(ref)
        except Exception as e:
            ctx.notify(f"Couldn't attach the file ({e}).")
    r.setdefault("addenda", []).append(
        {"number": no, "date": _d.today().isoformat(), "description": desc})
    sent = 0
    for b in r.get("bidders") or []:
        if b.get("status") in ("Won't Bid",):
            continue
        b["acks"] = ", ".join(x for x in (b.get("ack_list") or []))
        to = b.get("email") or ctx.store.email_of(b.get("company"))
        if not to or not ctx.mail or not (b.get("token") or
                                          b.get("invited")):
            continue
        link = _bid_link(ctx, f"/bid.html?t={b['token']}") \
            if b.get("token") and ctx.store.connected else ""
        how = mail.send([to], f"Addendum {no}: {ctx.store.name} - "
                              f"{r.get('title')}",
                        f"Addendum {no} has been issued for "
                        f"{r.get('title')}:\n\n{desc}\n\n" +
                        (f"See it and acknowledge it on your bid page:\n"
                         f"{link}\n\n" if link else "") +
                        f"Bids are still due {r.get('due')} "
                        f"{r.get('due_time') or ''}. Please acknowledge "
                        "this addendum with your bid.",
                        attachments=[path] if path and not link else [])
        if how:
            sent += 1
    ctx.notify(f"Addendum {no} issued" + (f"; {sent} bidder(s) told." if
                                         sent else "."))
    return r


def bid_followups(ctx, r, today=None):
    """Follow-ups due today (Chief's v19 sequence): day 3 not opened, day 5
    opened with no click, day 7 viewed with no answer, and a due-date
    reminder to bidders who said yes or maybe. Each goes out once, from the
    Bids@ mailbox, review first; the sequence stops when a bidder replies,
    declines or bids. Also lists who to phone and low coverage."""
    from .. import bid_followup as fu, mail
    invite_boost = fu                       # invitations live here too
    due = fu.due(r, today)
    calls = fu.call_list(r, today)
    cov = fu.coverage(r, today)
    extra = []
    if calls:
        extra.append("Call: " + ", ".join(
            f"{c['company']} ({c['stage']})" for c in calls))
    if cov["alert"]:
        extra.append(f"Coverage: only {cov['likely']} bidding on "
                     f"{cov['trade']}.")
    if not due:
        ctx.notify("No follow-ups due today." +
                   (" " + " ".join(extra) if extra else ""))
        return r if extra else None
    names = ", ".join(f"{d['company']} ({d['step'].replace('_', ' ')})"
                      for d in due)
    if ctx.ask(f"Send {len(due)} follow-up(s)? {names}",
               ["Send (review each in Outlook)", "Cancel"]) != \
            "Send (review each in Outlook)":
        return None
    sender = invite_boost.live_sender()
    project = {"name": ctx.store.name}
    n = 0
    for d in due:
        b = next((x for x in r.get("bidders") or []
                  if (d["token"] and x.get("token") == d["token"]) or
                  (not d["token"] and x.get("company") == d["company"])),
                 None)
        if b is None:
            continue
        to = b.get("email") or ctx.store.email_of(b.get("company"))
        if not to or not ctx.mail:
            continue
        link = _bid_link(ctx, f"/bid.html?t={b['token']}") \
            if b.get("token") and ctx.store.connected else ""
        m = fu.message(r, dict(b, email=to), d["step"], project, sender,
                       link)
        try:
            how = mail.send([to], m["subject"], m["text"],
                            send_as=sender["email"])
        except mail.MailError as e:
            ctx.notify(str(e))
            break
        if how:
            b.setdefault("followups", []).append(d["step"])
            n += 1
    ctx.notify(f"Sent {n} follow-up(s)." +
               (" " + " ".join(extra) if extra else ""))
    return r


def _sealed_shut(r):
    return str(r.get("sealed") or "").lower() in ("yes", "true", "1") and \
        not r.get("unsealed")


def bid_unseal(ctx, r):
    """Open the sealed bids (the hub allows it only after the due time)."""
    from ..collab.hubclient import HubClientError
    if not ctx.store.connected:
        ctx.notify("Sealed bids are kept on your relay - share the project "
                   "first.")
        return None
    saved = ctx.store.save_record("bidpkg", r)
    h = ctx.store.data["hub"]
    try:
        ctx.store.sync()
        res = ctx.store.client().call(
            "bid.unseal", project=h["project"], key=h["key"],
            record_id=saved["_id"], user=ctx.store.me)
        ctx.store.sync()
    except HubClientError as e:
        ctx.notify(str(e))
        return None
    except Exception as e:                     # StoreError: offline
        ctx.notify(f"Couldn't reach the relay: {e}")
        return None
    ctx.notify(f"Opened {res.get('opened', 0)} sealed bid(s)." if
               not res.get("already") else "The bids were already opened.")
    return ctx.store.get("bidpkg", saved["_id"])


def bid_level(ctx, r):
    from . import bidforms
    bids = bidforms.to_leveling(r)
    if len(bids) < 2:
        ctx.notify("Leveling needs bids from at least two bidders.")
        return None
    rid = r.get("_id")

    def on_plugs(lines):                 # plugs are kept on the package
        cur = ctx.store.get("bidpkg", rid) if rid else None
        if cur is not None:
            cur["plugs"] = lines
            ctx.store.save_record("bidpkg", cur)
    ctx.level(bids, f"{r.get('_no', '')} {r.get('title', '')}",
              plugs=r.get("plugs") or [], on_plugs=on_plugs)
    return None


# ------------------------------------------------------------ schedule
def act_start(ctx, r):
    r["status"] = "In Progress"
    r["actual_start"] = r.get("actual_start") or _today()
    return r


def act_finish(ctx, r):
    r["status"] = "Complete"
    r["actual_start"] = r.get("actual_start") or _today()
    r["actual_finish"] = _today()
    r["percent"] = 100
    return r


def act_tia(ctx, r):
    """Delay event: time impact on the schedule update before it."""
    from . import schedule_record
    try:
        t = schedule_record.tia(ctx.store, r)
    except ValueError as e:              # a negative impact is refused
        ctx.notify(f"{r.get('_no')}: {e}")
        return None                      # nothing changed, nothing saved
    n = t.get("impact_workdays")
    ctx.notify(f"{r.get('_no')}: completion {t.get('finish_before')} -> "
               f"{t.get('finish_after')} ({n:+d} workdays)." if n is not None
               else "Time impact could not be worked out: " +
               " ".join(t.get("notes") or []))
    if n is not None and r.get("status") in ("Open", "Notice Given"):
        r["status"] = "Analyzed"
    return r


def act_meeting_lookahead(ctx, r):
    from . import activity_lookahead
    import os
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),
                        "2-Week Look-Ahead.pdf")
    activity_lookahead.export_pdf(ctx.store, path, 2)
    ctx.open_file(path)
    return None


def act_lookahead(ctx, r):
    from . import schedule
    import os
    import tempfile
    path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),
                        "Lookahead.pdf")
    schedule.lookahead_pdf(ctx.store, path)
    ctx.open_file(path)
    return None


def st(*names):
    return lambda r: r.get("status") in names


ACTIONS = {
    "rfi": [("Send RFI", "mail", st("Draft"), rfi_send),
            ("Close with Response", "close",
             lambda r: r.get("status") == "Open" and bool(r.get("answer")),
             rfi_close),
            ("Reopen", "undo", st("Closed"), reopen)],
    "submittal": [
        ("Send for Review", "mail",
         st("Draft", "Not Submitted", "Submitted"), sub_send),
        ("Record Response", "gavel", st("In Review"), sub_respond),
        ("Resubmit as Next Revision", "redo",
         st("Revise and Resubmit", "Rejected"), sub_resubmit),
        ("Make Submittal Package (PDF)", "print",
         lambda r: bool(r.get("_id")), sub_package)],
    "punch": [("Send to Assignee", "mail", st("Draft", "Initiated"),
               punch_assign),
              ("Ready for Review", "inbox",
               st("Work Required", "Not Accepted", "Initiated"),
               punch_ready),
              ("Accept", "close", st("Ready for Review", "Ready to Close"),
               punch_accept),
              ("Not Accepted", "undo", st("Ready for Review"),
               punch_reject)],
    "observation": [("Email Assignee", "mail", st("Initiated"), obs_assign),
                    ("Ready for Review", "inbox",
                     st("Initiated", "Not Accepted"), obs_ready),
                    ("Close", "close", st("Ready for Review"), close),
                    ("Not Accepted", "undo", st("Ready for Review"),
                     obs_reject)],
    "issue": [("Email Responsible", "mail", st("Open"), issue_email),
              ("Close", "close", st("Open"), close),
              ("Reopen", "undo", st("Closed"), reopen)],
    "transmittal": [("Send", "mail", st("Draft"), tr_send),
                    ("Mark Acknowledged", "close", st("Sent"), tr_ack)],
    "meeting": [("Topics to Issues", "flag", lambda r: True, meet_issues),
                ("Distribute Minutes", "mail", st("Agenda", "Minutes"),
                 meet_distribute),
                ("Create Next Meeting", "new", lambda r: True, meet_next)],
    "daily": [("Copy Yesterday's Crews", "duplicate", st("Draft"),
               daily_copy),
              ("Submit", "close", st("Draft"), daily_submit)],
    "inspection": [("Load Checklist", "checklist",
                    lambda r: bool(r.get("template")) and
                    not r.get("items"), insp_fill),
                   ("Finish Inspection", "close",
                    st("Scheduled", "In Progress"), insp_finish)],
    "event": [("Send to Owner", "mail", st("Open"), ev_send),
              ("Owner Approved", "close", st("Open", "Pending"),
               ev_approve),
              ("Rejected", "undo", st("Open", "Pending"), ev_reject)],
    "commitment": [("Send for Signature", "mail", st("Draft"), cm_send),
                   ("Mark Executed", "close",
                    st("Draft", "Out for Signature"), cm_execute)],
    "cost": [("Approve", "close", st("Pending"), cost_approve),
             ("Mark Paid", "dollar", st("Pending", "Approved"), cost_paid)],
    "subpay": [("Fill from Subcontract", "sov", st("Draft"), sp_fill),
               ("Submit to GC", "mail",
                lambda r: r.get("status") == "Draft" and
                bool(r.get("lines")), sp_submit),
               ("Approve", "close", st("Submitted"), sp_approve),
               ("Send Back", "undo", st("Submitted"), sp_reject)],
    "payapp": [("Fill from Contract", "sov", st("Draft"), pa_fill),
               ("Roll In Sub Pay Apps", "import", st("Draft"), pa_subs),
               ("Print Application", "print", lambda r: bool(r.get("lines")),
                pa_print),
               ("Submit to Owner", "mail",
                lambda r: r.get("status") == "Draft" and
                bool(r.get("lines")), pa_submit),
               ("Mark Certified", "close", st("Submitted"), pa_certify),
               ("Record Payment", "dollar", st("Submitted", "Certified"),
                pa_paid)],
    "bidpkg": [("Send Invitations", "mail",
                lambda r: r.get("status") in ("Draft", "Open") and any(
                    not b.get("token") and not b.get("invited")
                    for b in r.get("bidders") or []), bid_invite),
               ("Bid Form…", "form", st("Draft", "Open"), bid_form),
               ("Save Form as Template", "save",
                lambda r: bool(r.get("form")), bid_save_template),
               ("Import Bidders…", "import", st("Draft", "Open"),
                bid_import_bidders),
               ("Add Bidders from Company Directory", "people",
                st("Draft", "Open"), bid_from_company),
               ("Add Bidders from Project Team", "people",
                st("Draft", "Open"), bid_from_directory),
               ("Issue Addendum…", "addenda", st("Draft", "Open"),
                bid_addendum),
               ("Remind Bidders", "history", st("Open"), bid_remind),
               ("Follow-ups Due…", "flag", st("Open"), bid_followups),
               ("Open Sealed Bids", "lock", lambda r: _sealed_shut(r) and
                r.get("status") in ("Open", "Closed"), bid_unseal),
               ("Level Bids", "leveling", lambda r: not _sealed_shut(r)
                and sum(1 for b in r.get("bidders") or []
                        if b.get("amount") not in (None, "") or
                        b.get("form_values")) >= 2, bid_level),
               ("Close Bidding", "lock", st("Open"), bid_close),
               ("Award", "gavel", lambda r: r.get("status") in
                ("Open", "Closed") and not _sealed_shut(r), bid_award),
               ("Send Award Letters", "mail", lambda r: r.get("status") ==
                "Awarded" and bool(r.get("letters")) and
                not r.get("letters_sent"), bid_send_letters)],
    "activity": [("Started Today", "history", st("Not Started"), act_start),
                 ("Finished Today", "close",
                  st("Not Started", "In Progress"), act_finish),
                 ("2-Week Look-Ahead", "print", lambda r: True,
                  act_meeting_lookahead),
                 ("3-Week Lookahead", "print", lambda r: True,
                  act_lookahead)],
    "delay": [("Time Impact Analysis", "gantt", lambda r: True, act_tia)],
    "expedite": [("Mark Delivered", "close",
                  lambda r: r.get("status") != "Delivered", exp_delivered)],
}


def available(key, rec):
    return [a for a in ACTIONS.get(key, []) if a[2](rec)]


def run(ctx, key, rec, label):
    for a in ACTIONS.get(key, []):
        if a[0] == label:
            out = a[3](ctx, dict(rec))
            if out is None:
                return None
            if "_open" in out:
                return out
            return ctx.store.save_record(key, out)
    raise KeyError(label)
