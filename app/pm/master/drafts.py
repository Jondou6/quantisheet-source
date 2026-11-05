"""Messages to subs - DRAFTS ONLY (design 3.7).

Nothing here sends. A draft is kept on the submission; open_draft() is
the only function that hands one to app.mail, and it always asks for the
review window (display=True: Outlook opens the message and Jon clicks
Send himself), whatever the global "review before sending" setting.
It is only ever called from Jon's click on one specific draft."""
import datetime as _dt

from . import model


def _now():
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def recipients(store, company):
    return "; ".join(sorted({m.get("email") for m in store.list("member")
                             if model.same_company(m.get("company"),
                                                   company)
                             and m.get("email")}))


def make(store, kind, company, subject, body):
    return {"kind": kind, "company": company,
            "to": recipients(store, company), "subject": subject,
            "body": body, "created": _now(), "opened": None}


def for_submission(store, sub, kind, reason=""):
    lab = model.label(sub)
    proj = store.name
    head = f"{proj} - schedule update {sub.get('cycle') or ''} " \
        f"({sub.get('file_name') or 'entry'})"
    if kind == "rejected":
        lines = [f"- {r.get('where')}: {r.get('text')}"
                 for r in sub.get("reasons") or []]
        body = ("Your schedule update could not be used, so nothing from it "
                "was applied. Please fix the following and send the whole "
                "update again:\n\n" + "\n".join(lines))
        subj = f"Not accepted: {head}"
    elif kind == "received":
        body = ("We received your schedule update. It is under review; we "
                "will let you know when it is accepted.")
        subj = f"Received: {head}"
    elif kind == "accepted":
        body = "Your schedule update was accepted into the master schedule."
        subj = f"Accepted: {head}"
    elif kind == "declined":
        body = ("Your schedule update was not accepted, so the master "
                f"schedule was not changed.\n\nReason: {reason}")
        subj = f"Not accepted: {head}"
    else:
        raise ValueError(kind)
    d = make(store, kind, sub.get("company"), subj,
             body + f"\n\nRef. {lab}")
    return d


def slip_notices(store, sub):
    """Downstream-trade notices: one draft per OTHER company whose
    activities now finish later."""
    by = {}
    for x in (sub.get("impact") or {}).get("later") or []:
        if x["owner"] == "GC" or model.same_company(x["owner"],
                                                    sub.get("company")):
            continue
        by.setdefault(x["owner"], []).append(x)
    out = []
    for co, rows in sorted(by.items()):
        lines = [f"- {r['_no']} {r['name']}: {r['before']} -> {r['after']}"
                 f" ({r['workdays']:+d} workdays)" for r in rows]
        out.append(make(store, "slip", co,
                        f"{store.name} - schedule change affecting your "
                        "work", "The master schedule was updated. These "
                        "activities of yours now finish later:\n\n" +
                        "\n".join(lines)))
    return out


def reminder(store, company, cycle, link=None):
    body = (f"Please send your schedule update for the {cycle} cycle "
            "using the attached template.")
    if link:
        body += ("\n\nUpload the filled-in file here (no Dropbox account "
                 f"needed for a file request link):\n{link}")
    return make(store, "reminder", company,
                f"{store.name} - schedule update due {cycle}", body)


def open_draft(draft, mail_module=None):
    """Jon clicked Open on this draft: Outlook (or the mail program)
    opens it for him to review and send. Never sends by itself."""
    if mail_module is None:
        from ... import mail as mail_module
    import os
    att = [p for p in draft.get("attachments") or [] if os.path.isfile(p)]
    how = mail_module.send(draft.get("to") or "", draft.get("subject"),
                           draft.get("body") or "", attachments=att,
                           display=True)
    draft["opened"] = _now()
    return how
