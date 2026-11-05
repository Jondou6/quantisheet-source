"""Send email through the Outlook on this PC (RFIs, transmittals, signature
requests, punch assignments, reminders).

Outlook is driven through COM (pywin32), so mail goes out from the user's
own account and lands in Sent Items. With "Review emails before sending"
on (the default) Outlook opens each message for a last look instead of
sending it straight away.

Without Outlook the message is written as an .eml file and opened, so the
default mail program shows it ready to send.

Tests set ``mail.OUTBOX = []`` to capture messages instead of sending.
"""
import logging
import os
import re
import tempfile
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from . import settings

log = logging.getLogger(__name__)
OUTBOX = None               # a list here captures mail (tests)
_EMAIL = re.compile(r"^[^@\s;,<>]+@[^@\s;,<>]+\.[^@\s;,<>]+$")


class MailError(RuntimeError):
    pass


def split_addresses(text):
    """'a@x.com; Bob <b@y.com>, c@z.org' -> ['a@x.com', 'b@y.com', ...]"""
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        out = []
        for t in text:
            out += split_addresses(t)
        return out
    out = []
    for part in re.split(r"[;,\n]+", str(text)):
        part = part.strip()
        m = re.search(r"<([^>]+)>", part)
        if m:
            part = m.group(1).strip()
        if part:
            out.append(part)
    return out


def valid(addr):
    return bool(_EMAIL.match(addr or ""))


def review_first():
    return bool(settings.get("mail_review", True))


def outlook_available():
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID")
    except OSError:
        return False
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def _outlook(msg, display):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("Outlook.Application")
        item = app.CreateItem(0)                       # olMailItem
        if msg.get("send_as"):
            _use_account(app, item, msg["send_as"])
        item.To = "; ".join(msg["to"])
        if msg["cc"]:
            item.CC = "; ".join(msg["cc"])
        item.Subject = msg["subject"]
        if msg.get("html"):
            item.HTMLBody = msg["html"]
        else:
            item.Body = msg["body"]
        for path in msg["attachments"]:
            item.Attachments.Add(os.path.abspath(path))
        if display:
            item.Display(False)
        else:
            item.Send()
    finally:
        pythoncom.CoUninitialize()


def outlook_account(accounts, address):
    """The Outlook account whose SMTP address is `address`, or None."""
    want = (address or "").strip().lower()
    for acc in accounts:
        try:
            if str(acc.SmtpAddress).strip().lower() == want:
                return acc
        except Exception:
            continue
    return None


def _use_account(app, item, address):
    acc = outlook_account(app.Session.Accounts, address)
    if acc is None:
        raise MailError(f"{address} isn't set up in Outlook on this "
                        "computer. Add that mailbox to Outlook (File > "
                        "Add Account) and try again. Nothing was sent.")
    try:
        item.SendUsingAccount = acc
    except Exception:
        # older pywin32 can't set it as an attribute: PROPERTYPUTREF
        item._oleobj_.Invoke(*(64209, 0, 8, 0, acc))


def to_eml(msg, path=None):
    """Write msg as an .eml draft (X-Unsent so mail apps open it to send)."""
    em = EmailMessage()
    em["To"] = ", ".join(msg["to"])
    if msg["cc"]:
        em["Cc"] = ", ".join(msg["cc"])
    em["Subject"] = msg["subject"]
    em["Date"] = formatdate(localtime=True)
    em["Message-ID"] = make_msgid(domain="quantisheet.local")
    em["X-Unsent"] = "1"
    em.set_content(msg["body"] or "")
    if msg.get("html"):
        em.add_alternative(msg["html"], subtype="html")
    for p in msg["attachments"]:
        with open(p, "rb") as f:
            data = f.read()
        sub = "pdf" if p.lower().endswith(".pdf") else "octet-stream"
        em.add_attachment(data, maintype="application", subtype=sub,
                          filename=os.path.basename(p))
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".eml", prefix="quantisheet-")
        os.close(fd)
    with open(path, "wb") as f:
        f.write(bytes(em))
    return path


def send(to, subject, body="", cc=(), attachments=(), html=None,
         display=None, send_as=None):
    """Send (or open for review) one email. Returns how it went out:
    'outlook', 'outlook-review', 'eml' or 'captured'.

    `send_as`: the mailbox it must go out from (bid invites go from
    Bids@...). It is sent through that Outlook account, so replies and
    bounces land there; if Outlook or that account isn't available it is
    NOT sent (MailError) - never from someone's own mailbox instead."""
    msg = {"to": [a for a in split_addresses(to)],
           "cc": [a for a in split_addresses(cc)],
           "subject": subject or "", "body": body or "", "html": html,
           "attachments": [p for p in attachments if p],
           "send_as": (send_as or "").strip() or None}
    if not msg["to"]:
        raise MailError("No recipient email address.")
    bad = [a for a in msg["to"] + msg["cc"] if not valid(a)]
    if bad:
        raise MailError("Not an email address: " + ", ".join(bad))
    for p in msg["attachments"]:
        if not os.path.isfile(p):
            raise MailError(f"Attachment not found: {p}")
    if OUTBOX is not None:
        OUTBOX.append(msg)
        return "captured"
    display = review_first() if display is None else display
    if msg["send_as"] and not outlook_available():
        raise MailError(f"This has to go out from {msg['send_as']}, and "
                        "that needs Outlook with that mailbox set up on "
                        "this computer. Nothing was sent.")
    if outlook_available():
        try:
            _outlook(msg, display)
            return "outlook-review" if display else "outlook"
        except MailError:
            raise
        except Exception as e:
            if msg["send_as"]:
                raise MailError(f"Outlook couldn't send from "
                                f"{msg['send_as']} ({e}). Nothing was "
                                "sent.")
            log.warning("Outlook send failed, falling back to .eml: %s", e)
    path = to_eml(msg)
    try:
        os.startfile(path)                      # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    return "eml"


def describe(how):
    return {"outlook": "Sent through Outlook.",
            "outlook-review": "Opened in Outlook for you to review and send.",
            "eml": "Opened in your mail program, ready to send.",
            "captured": "Captured (test)."}.get(how, how)
