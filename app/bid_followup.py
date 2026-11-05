"""Open / view / intent tracking and automatic follow-ups (v19).

What's already there: the relay marks a bidder "Viewed" when their private
link is opened, and the bid page records Will / Won't / Might Bid;
pm/actions.bid_remind sends one manual reminder to everyone.

This adds:
* stage(bidder): not opened -> opened -> viewed -> bidding / unsure /
  declined (+ bounced, bid in).
* record(pkg, token, "opened" | "viewed" | "intent" | "replied"): one place
  to feed events in - an email-open pixel (pixel_url), the intent links in
  the v18 invite, or a reply found in the mailbox.
* due(pkg, today): which follow-up each bidder needs, by the sequence
  below. Each step goes out once, and the sequence stops when the bidder
  replies, declines, bids or unsubscribes.
    day 3   not opened        "did this reach you?" (new subject)
    day 5   opened, no click  scope nudge with the link
    day 7   viewed, no intent "even 'no' helps"
    T-3     bidding / unsure  due-time reminder with the bid link
  call_list(T-2): still unknown -> phone list.
  coverage(T-1): trades with fewer than N likely bidders -> alert.
* send_due(): writes the follow-ups to the v18 DryRunOutbox. NOTHING IS
  SENT.

The timing is our own design. The spec marks it *inferred*: no source page
gives it. All the numbers are settings (STEPS).
"""

# ======================================================================
# Personal bid invitations (was invite_boost.py; folded Nov 4, 1.1.1)
#
# Personal bid invitations (v18): one email per bidder, from your own
# mailbox, with a no-login plans link and one-click bid intent.
#
# Builds on what's already there (pm/actions.bid_invite, mail.py, the relay's
# private bid links). It adds what the PreconSuite-style invite has and ours
# lacks:
# * "Hi Steve," first-name greeting (or "Hi <Company> team,"), your
#   signature, subject "ITB: <Project> - <Package> - Bids due <date>".
# * the sheets this trade should start with, picked from the set by
#   discipline (C-/U- for utilities, E- for electrical...), as ranges.
# * key dates, requirements (bond, wages, DBE goal), and
#   [View Files and Project Details] plus Yes / Unsure / Not bidding links.
# * a per-recipient log (sent / bounced / resent) and a bounce queue: fix the
#   address in place and resend.
#
# NOTHING IS SENT. Messages go to a DryRunOutbox (.eml files + log.jsonl)
# for review. Wiring a live sender is left to Claude, behind an explicit
# setting (see TO-CLAUDE-v18.md).

import datetime
import email.message
import email.utils
import html as _html
import json
import os
import re

TRADE_SHEETS = [
    (("sewer", "water", "storm", "utilit", "pipe", "force main", "33 "),
     ("C", "CU", "U")),
    (("earthwork", "grading", "paving", "sitework", "site work",
      "excavat", "asphalt", "31 ", "32 "), ("C", "CS", "CG")),
    (("concrete", "structural", "steel", "rebar", "03 ", "05 "), ("S",)),
    (("electric", "26 "), ("E",)),
    (("mechanical", "hvac", "23 "), ("M",)),
    (("plumbing", "22 "), ("P",)),
    (("landscap", "irrigation"), ("L",)),
    (("drywall", "roof", "door", "finish", "architect", "glazing",
      "painting"), ("A",)),
    (("process", "wastewater", "treatment", "40 ", "46 "), ("D", "PR")),
]
_SHEET = re.compile(r"^([A-Z]{1,3})-?(\d+)([A-Z]?)$")


def first_name(contact):
    c = re.sub(r"\(.*?\)", "", str(contact or "")).strip()
    if "," in c:                                     # "Rogers, Steve"
        c = c.split(",", 1)[1].strip()
    parts = [p for p in c.split() if p.lower().strip(".") not in
             ("mr", "mrs", "ms", "dr")]
    return parts[0] if parts else ""


def sheets_for_trade(trades, sheets):
    t = " " + str(trades or "").lower() + " "
    prefixes = set()
    for words, pre in TRADE_SHEETS:
        if any(w in t for w in words):
            prefixes.update(pre)
    out = []
    for s in sheets or []:
        m = _SHEET.match(str(s).strip().upper())
        if m and m.group(1) in prefixes:
            out.append(str(s).strip().upper())
    return out


def ranges(sheets):
    """['C-101','C-102','C-104'] -> 'C-101 to C-102, C-104'."""
    parsed = []
    for s in sheets:
        m = _SHEET.match(s)
        parsed.append((m.group(1), int(m.group(2)), s) if m and
                      not m.group(3) else (s, None, s))
    out, i = [], 0
    while i < len(parsed):
        j = i
        while j + 1 < len(parsed) and parsed[j][1] is not None and \
                parsed[j + 1][0] == parsed[j][0] and \
                parsed[j + 1][1] == parsed[j][1] + 1:
            j += 1
        out.append(parsed[i][2] if i == j else
                   f"{parsed[i][2]} to {parsed[j][2]}")
        i = j + 1
    return ", ".join(out)


def _intent(link, value):
    if not link:
        return ""
    return f"{link}{'&' if '?' in link else '?'}intent={value}"


# Default "send as" mailbox (setting; override per company/project by passing
# sender={"name": ..., "email": ...}). The live send must go out through
# this mailbox's own account so From/Reply-To are genuine.
def _default_sender():
    """The company's bid mailbox, from app/data/company_sender.json - a
    private file that ships only in the in-house tester build (never in the
    public build or the source repository). Empty when it isn't there."""
    import json
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                     "company_sender.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        return {"name": str(d.get("name") or "")[:100],
                "email": str(d.get("email") or "")[:200]}
    except (OSError, ValueError, AttributeError):
        return {"name": "", "email": ""}


DEFAULT_SENDER = _default_sender()


def live_sender():
    """The "Bid invites send as" setting (name / email / signature),
    filled in from DEFAULT_SENDER. Real mail shows no logo placeholder."""
    from . import settings
    s = settings.get("bid_invite_sender")
    s = dict(s) if isinstance(s, dict) else {}
    s.setdefault("logo_placeholder", False)
    return sender_with_defaults(s)


def sender_with_defaults(sender=None):
    s = dict(sender or {})
    if not (s.get("email") or "").strip():
        s["email"] = DEFAULT_SENDER["email"]
        s.setdefault("name", DEFAULT_SENDER["name"])
    if not (s.get("name") or "").strip():
        s["name"] = DEFAULT_SENDER["name"] if s["email"] == \
            DEFAULT_SENDER["email"] else ""
    s.setdefault("company", DEFAULT_SENDER["name"] if s["email"] ==
                 DEFAULT_SENDER["email"] else "")
    return s


def build_invite(pkg, bidder, project, sender, link="", sheets=None):
    """{from, reply_to, to, subject, text, html} for one bidder."""
    sender = sender_with_defaults(sender)
    fn = first_name(bidder.get("contact"))
    hi = f"Hi {fn}," if fn else f"Hi {bidder.get('company') or 'there'} team,"
    proj = project.get("name") or ""
    due = f"{pkg.get('due') or ''} {pkg.get('due_time') or ''}".strip()
    subject = f"ITB: {proj} - {pkg.get('title') or ''}" + \
        (f" - Bids due {due}" if due else "")
    who = [f"Job #{project['number']}" if project.get("number") else "",
           f"Owner: {project['owner']}" if project.get("owner") else ""]
    who = ", ".join(w for w in who if w)
    lines = [hi, "",
             f"We'd like your bid on {proj}" + (f" ({who})" if who else "")
             + ".", "",
             f"Your package: {pkg.get('title') or ''}" +
             (f" ({pkg['trades']})" if pkg.get("trades") else "") + "."]
    if pkg.get("scope"):
        lines.append(str(pkg["scope"]).strip())
    picked = sheets_for_trade(f"{pkg.get('trades', '')} {pkg.get('title', '')}",
                              sheets or [])
    if picked:
        lines.append(f"Sheets to start with: {ranges(picked)}")
    if pkg.get("specs"):
        lines.append(f"Spec sections: {pkg['specs']}")
    dates = [("Pre-bid meeting", pkg.get("prebid")),
             ("Site visit", pkg.get("site_visit")),
             ("RFIs due", pkg.get("rfi_due")),
             ("Bids due", due + (" (sealed, opened after the deadline)"
                                 if str(pkg.get("sealed")).lower() in
                                 ("yes", "true", "1") else ""))]
    dates = [(k, v) for k, v in dates if v]
    if dates:
        lines += ["", "Key dates"] + [f"  - {k}: {v}" for k, v in dates]
    if pkg.get("requirements"):
        lines.append(f"Requirements: {pkg['requirements']}")
    lines.append("")
    if link:
        lines += [f"View Files and Project Details (no login needed): {link}",
                  "",
                  f"Will you bid?  Yes: {_intent(link, 'yes')}",
                  f"  Unsure: {_intent(link, 'unsure')}",
                  f"  Not bidding: {_intent(link, 'no')}",
                  "Even \"no\" or \"unsure\" helps us plan coverage."]
    else:
        lines.append("Please reply to this email to let us know if you'll "
                     "bid - even \"no\" or \"unsure\" helps.")
    lines += ["", "Thanks,", sender.get("signature") or sender.get("name", ""),
              "", "Not your trade? Reply and we'll update our list."]
    text = "\n".join(lines)
    body = _invite_html(project, pkg, due, link, sender)
    frm = email.utils.formataddr((sender.get("name") or "",
                                  sender.get("email") or ""))
    return {"from": frm, "reply_to": sender.get("email") or "",
            "to": [bidder.get("email", "").split(";")[0].strip()],
            "subject": subject, "text": text, "html": body}



_FONT = "font-family:Arial,Helvetica,sans-serif;color:#222222;"


def _btn(href, label, bg, width, fg="#ffffff"):
    e = _html.escape
    return (f'<td align="center" style="padding:0 5px;width:{width}px">'
            f'<a href="{e(href)}" style="display:block;'
            f'background:{bg};color:{fg};text-decoration:none;'
            f'font-size:13px;font-weight:bold;padding:10px 0;'
            f'border-radius:3px;{_FONT.split(";")[0]}">{label}</a></td>')


def _invite_html(project, pkg, due, link, sender):
    """PreconSuite-style invite: centered logo, INVITATION TO BID, project,
    location, due date, divider, grey box with Yes/No/Unsure and a wide
    View Files button. Email-safe: tables + inline styles; URLs only in
    href/src."""
    e = _html.escape
    proj = project.get("name") or ""
    title = proj + (f": {pkg['title']}" if pkg.get("title") else "")
    loc = project.get("location") or ", ".join(
        x for x in (project.get("city"), project.get("state")) if x)
    if sender.get("logo_url"):
        w = int(sender.get("logo_width") or 220)
        logo = (f'<img src="{e(sender["logo_url"])}" alt="'
                f'{e(sender.get("company") or "Logo")}" width="{w}" '
                f'style="display:block;margin:0 auto;width:{w}px;'
                f'max-width:100%;height:auto;border:0">')
    elif sender.get("logo_placeholder", True):
        logo = ('<div style="width:140px;height:70px;margin:0 auto;'
                'border:1px dashed #b0b0b0;color:#9a9a9a;font-size:12px;'
                'line-height:70px;text-align:center">[Company Logo]</div>')
    else:
        logo = ""                      # real mail: no placeholder box
    p = 'style="margin:0 0 6px;font-size:14px;line-height:1.4"'
    head = (f'<tr><td align="center" style="padding:24px 20px 14px">{logo}'
            f'</td></tr>'
            f'<tr><td align="center" style="padding:0 20px 18px">'
            f'<p {p}><b>INVITATION TO BID</b></p>'
            f'<p {p}><b>{e(title)}</b></p>'
            + (f'<p {p}><b>{e(loc)}</b></p>' if loc else "")
            + (f'<p {p}><b>Bids are due by: {e(due)}</b></p>' if due else "")
            + '</td></tr>'
            '<tr><td style="padding:0 20px"><div style="border-top:1px solid '
            '#d0d0d0;height:1px;line-height:1px;font-size:1px">&nbsp;</div>'
            '</td></tr>')
    if link:
        box = ('<tr><td style="padding:16px 20px 24px"><table width="100%" '
               'cellpadding="0" cellspacing="0" style="background:#f4f4f4">'
               '<tr><td align="center" style="padding:20px 12px">'
               '<p style="margin:0 0 12px;font-size:13px">You have been '
               'invited to bid on this project. Will you be bidding?</p>'
               '<table width="100%" cellpadding="0" cellspacing="0" align="center" '
               'style="max-width:390px"><tr>'
               + _btn(_intent(link, "yes"), "Yes", "#28a745", 120)
               + _btn(_intent(link, "no"), "No", "#d93a2b", 120)
               + _btn(_intent(link, "unsure"), "Unsure", "#F4C430", 120,
                      "#1f1f1f")
               + '</tr></table>'
               '<table width="100%" cellpadding="0" cellspacing="0" align="center" '
               'style="max-width:390px;margin-top:18px"><tr>'
               + _btn(link, "View Files and Project Details", "#0b5cad", 380)
               + '</tr></table></td></tr></table></td></tr>')
    else:
        box = ('<tr><td align="center" style="padding:16px 20px 24px;'
               'font-size:13px">Please reply to let us know if you will be '
               'bidding.</td></tr>')
    return ('<html><body style="margin:0;padding:0;background:#ffffff">'
            '<table width="100%" cellpadding="0" cellspacing="0"><tr>'
            '<td align="center"><table width="100%" cellpadding="0" '
            f'cellspacing="0" style="max-width:600px;{_FONT}">'
            + head + box + '</table></td></tr></table></body></html>')


class DryRunOutbox:
    """Writes each message as an .eml file and a log line. Sends nothing."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    def send(self, msg, meta=None):
        m = email.message.EmailMessage()
        m["From"] = msg["from"]
        m["To"] = ", ".join(msg["to"])
        if msg.get("reply_to"):
            m["Reply-To"] = msg["reply_to"]
        m["Subject"] = msg["subject"]
        m["Date"] = email.utils.formatdate(localtime=True)
        m["X-QuantiSheet-Dry-Run"] = "yes"
        m.set_content(msg["text"])
        if msg.get("html"):
            m.add_alternative(msg["html"], subtype="html")
        n = len([f for f in os.listdir(self.folder) if f.endswith(".eml")])
        safe = re.sub(r"[^A-Za-z0-9@._-]+", "_", msg["to"][0])[:60]
        path = os.path.join(self.folder, f"{n + 1:04d}-{safe}.eml")
        with open(path, "wb") as f:
            f.write(bytes(m))
        with open(os.path.join(self.folder, "log.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(dict(meta or {}, event="dry-run",
                                    to=msg["to"][0], subject=msg["subject"],
                                    file=os.path.basename(path),
                                    at=datetime.datetime.now().isoformat(
                                        timespec="seconds"))) + "\n")
        return path


def _event(b, event, today, **kw):
    b.setdefault("events", []).append(dict(kw, event=event, date=today))


def _today(today):
    return today or datetime.date.today().isoformat()


def invite_all(pkg, project, sender, outbox, link_for=None, sheets=None,
               today=None):
    """Invite every bidder not yet invited (not declined, has an email).
    Returns {sent, skipped: {company: why}}."""
    today = _today(today)
    sent, skipped = 0, {}
    for b in pkg.get("bidders") or []:
        name = b.get("company") or b.get("email") or "?"
        if b.get("status") in ("Won't Bid",):
            skipped[name] = "declined"
            continue
        if not (b.get("email") or "").strip():
            skipped[name] = "no email"
            continue
        if b.get("invited"):
            skipped[name] = "already invited"
            continue
        link = link_for(b) if link_for else ""
        msg = build_invite(pkg, b, project, sender, link, sheets)
        outbox.send(msg, {"company": name, "kind": "invite"})
        b["invited"] = today
        b["status"] = b.get("status") or "Invited"
        _event(b, "sent", today, kind="invite", to=msg["to"][0])
        sent += 1
    return {"sent": sent, "skipped": skipped}


def record_bounce(pkg, address, reason=""):
    """Mark the bidder with this address as bounced (from a bounce notice
    found in the mailbox)."""
    a = address.strip().lower()
    for b in pkg.get("bidders") or []:
        if (b.get("email") or "").strip().lower() == a:
            b["status"] = "Bounced"
            _event(b, "bounced", _today(None), reason=reason, to=address)
            return b
    return None


def bounce_queue(pkg):
    return [b for b in pkg.get("bidders") or [] if b.get("status") ==
            "Bounced"]


def resend(pkg, bidder, project, sender, outbox, link="", sheets=None,
           today=None):
    """After the address was fixed inline: send the invite again."""
    today = _today(today)
    old = [e.get("to") for e in bidder.get("events") or []
           if e.get("event") in ("sent", "bounced") and e.get("to")]
    hist = bidder.setdefault("email_history", [])
    for o in old:
        if o and o != bidder.get("email") and o not in hist:
            hist.append(o)
    msg = build_invite(pkg, bidder, project, sender, link, sheets)
    outbox.send(msg, {"company": bidder.get("company"), "kind": "resend"})
    bidder["status"] = "Invited"
    bidder["invited"] = today
    _event(bidder, "sent", today, kind="resend", to=msg["to"][0])
    return msg


def deliverability(pkg):
    """[{company, email, sent, bounced, last}] per bidder."""
    rows = []
    for b in pkg.get("bidders") or []:
        ev = b.get("events") or []
        rows.append({"company": b.get("company"), "email": b.get("email"),
                     "sent": sum(1 for e in ev if e["event"] == "sent"),
                     "bounced": sum(1 for e in ev if e["event"] == "bounced"),
                     "last": ev[-1]["event"] if ev else ""})
    return rows


# ======================================================================
# Follow-ups (above: the invitations they follow)
STEPS = [("not_opened", 3, "not opened"),
         ("opened_no_click", 5, "opened"),
         ("viewed_no_intent", 7, "viewed")]
REMIND_DAYS = 3
CALL_DAYS = 2
COVERAGE_DAYS = 1
INTENT = {"yes": "Will Bid", "unsure": "Might Bid", "no": "Won't Bid"}
DONE = ("Won't Bid", "Bid Received", "Awarded", "Not Awarded")


def _d(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def stage(b):
    s = b.get("status") or ""
    if s == "Won't Bid":
        return "declined"
    if s in ("Bid Received", "Awarded", "Not Awarded"):
        return "bid in"
    if s == "Bounced":
        return "bounced"
    if s == "Will Bid":
        return "bidding"
    if s == "Might Bid":
        return "unsure"
    if b.get("viewed") or s == "Viewed":
        return "viewed"
    if b.get("opened"):
        return "opened"
    return "not opened"


def pixel_url(base, token):
    """1x1 image to put at the end of the invite. Needs a /bid.gif route on
    the relay that calls record(..., "opened") - see TO-CLAUDE-v19.md."""
    return f"{base.rstrip('/')}/bid.gif?t={token}"


def _bidder(pkg, token):
    return next((b for b in pkg.get("bidders") or []
                 if b.get("token") == token), None)


def record(pkg, token, event, value="", reason="", when=None):
    b = _bidder(pkg, token)
    if b is None:
        return None
    when = when or datetime.date.today().isoformat()
    if event == "opened":
        b.setdefault("opened", when)
    elif event == "viewed":
        b.setdefault("opened", when)
        b.setdefault("viewed", when)
        if b.get("status") in (None, "", "Invited"):
            b["status"] = "Viewed"
    elif event == "intent" and value in INTENT:
        b["status"] = INTENT[value]
        b["intent_date"] = when
        if value == "no" and reason:
            b["decline_reason"] = reason
    elif event == "replied":
        b["replied"] = when
    _event(b, event, when, value=value) if value else _event(b, event, when)
    return b


def _stopped(b):
    return bool(b.get("replied") or b.get("unsubscribed") or
                b.get("status") in DONE or b.get("status") == "Bounced")


def due(pkg, today=None):
    """[{company, token, step}] follow-ups due today."""
    t = _d(today) or datetime.date.today()
    due_d = _d(pkg.get("due"))
    out = []
    for b in pkg.get("bidders") or []:
        inv = _d(b.get("invited"))
        if not inv or _stopped(b):
            continue
        done = set(b.get("followups") or [])
        st = stage(b)
        days = (t - inv).days
        pick = None
        for step, after, want in STEPS:
            if st == want and days >= after and step not in done:
                pick = step
        if pick is None and due_d and st in ("bidding", "unsure") and \
                0 <= (due_d - t).days <= REMIND_DAYS and \
                "due_reminder" not in done:
            pick = "due_reminder"
        if pick:
            out.append({"company": b.get("company"), "token": b.get("token"),
                        "step": pick})
    return out


def message(pkg, b, step, project, sender, link=""):
    fn = first_name(b.get("contact"))
    hi = f"Hi {fn}," if fn else f"Hi {b.get('company') or 'there'} team,"
    title, proj = pkg.get("title") or "", project.get("name") or ""
    due = f"{pkg.get('due') or ''} {pkg.get('due_time') or ''}".strip()
    if step == "not_opened":
        subj = f"Did this reach you? {proj} - {title}, bids due {due}"
        body = (f"{hi}\n\nDid this reach you? We'd like your bid on {title} "
                f"for {proj}, due {due}.")
    elif step == "opened_no_click":
        subj = f"{proj} - {title}: plans and scope"
        body = (f"{hi}\n\nThe plans, specs and scope for {title} are one "
                "click away, no login needed.")
    elif step == "viewed_no_intent":
        subj = f"Will you bid {title}? ({proj})"
        body = (f"{hi}\n\nCan you let me know if you'll bid {title}? Even "
                "\"no\" or \"unsure\" helps us plan coverage.")
    else:
        subj = f"Reminder: {title} bids due {due} ({proj})"
        body = f"{hi}\n\nA reminder that bids for {title} are due {due}."
    if link:
        body += f"\n\n{link}"
    body += f"\n\nThanks,\n{sender.get('signature') or sender.get('name', '')}"
    return {"from": f"{sender.get('name', '')} <{sender.get('email', '')}>",
            "reply_to": sender.get("email", ""),
            "to": [(b.get("email") or "").split(";")[0].strip()],
            "subject": subj, "text": body}


def send_due(pkg, project, sender, outbox, today=None, link_for=None):
    today = today or datetime.date.today().isoformat()
    n = 0
    for d in due(pkg, today):
        b = _bidder(pkg, d["token"]) or next(
            x for x in pkg["bidders"] if x.get("company") == d["company"])
        if not (b.get("email") or "").strip():
            continue
        msg = message(pkg, b, d["step"], project, sender,
                      link_for(b) if link_for else "")
        outbox.send(msg, {"company": b.get("company"), "kind": "followup",
                          "step": d["step"]})
        b.setdefault("followups", []).append(d["step"])
        _event(b, "sent", today, kind=d["step"], to=msg["to"][0])
        n += 1
    return n


def call_list(pkg, today=None):
    """Bidders to phone CALL_DAYS before the due date: still no answer."""
    t = _d(today) or datetime.date.today()
    due_d = _d(pkg.get("due"))
    if not due_d or (due_d - t).days > CALL_DAYS:
        return []
    return [{"company": b.get("company"), "contact": b.get("contact"),
             "phone": b.get("phone", ""), "stage": stage(b)}
            for b in pkg.get("bidders") or []
            if stage(b) in ("not opened", "opened", "viewed", "bounced")
            and not b.get("unsubscribed")]


def coverage(pkg, today=None, minimum=3):
    """{trade, likely, unsure, alert}: alert when fewer than `minimum`
    bidders are bidding within COVERAGE_DAYS of the due date."""
    t = _d(today) or datetime.date.today()
    due_d = _d(pkg.get("due"))
    st = [stage(b) for b in pkg.get("bidders") or []]
    likely = sum(1 for s in st if s in ("bidding", "bid in"))
    near = bool(due_d and 0 <= (due_d - t).days <= COVERAGE_DAYS)
    return {"trade": pkg.get("trades") or pkg.get("title"), "likely": likely,
            "unsure": st.count("unsure"),
            "alert": near and likely < minimum}
