"""Read an invitation to bid from a saved email (Nov 11) into a draft for
the Bid Board.

Only reads: a .eml file (or pasted text) is opened and parsed; nothing is
sent, answered or marked read, and no link in it is opened. The result is
a *draft* - the Bid Board shows it for the user to check and confirm, and
says which fields were found.

Pure Python, no Qt.
"""
import email
import email.policy
import html as _html
import os
import re

from . import bidboard

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_DATE = (r"(?:(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
         r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|"
         r"[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)")
_TIME = r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)(?:\s+(?:E|C|M|P)[SD]?T)?"
_SUBJECT_JUNK = re.compile(
    r"^\s*(?:(?:re|fw|fwd)\s*:\s*)*(?:invitation\s+to\s+bid|bid\s+invit"
    r"ation|bid\s+invite|itb|request\s+for\s+(?:proposal|quote|bid)|rfp|"
    r"rfq|now\s+bidding|bidding)\s*[:\-–|]*\s*", re.I)


def _text_of(msg):
    """The message's text: the plain part, else the HTML with tags off."""
    if not hasattr(msg, "get_body"):
        return ""
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    text = body.get_content()
    if body.get_content_type() == "text/plain" and len(text.strip()) < 80:
        # a stub ("view this in HTML"): the HTML part has the invitation
        alt = msg.get_body(preferencelist=("html",))
        if alt is not None:
            body, text = alt, alt.get_content()
    if body.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text)
        text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    return text


def read_eml(path):
    """(subject, sender name, sender address, text) of a saved .eml."""
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)
    sender = msg.get("From", "")
    name, addr = email.utils.parseaddr(str(sender))
    return str(msg.get("Subject", "")), name, addr, _text_of(msg)


def _field(text, labels, pattern=r"(.+)"):
    """The value after one of the labels ("Bid date: ..."), first hit."""
    for lab in labels:
        m = re.search(rf"(?im)^\s*(?:[-*•]\s*)?{lab}\s*(?:is|are)?\s*[:\-–]"
                      rf"\s*{pattern}", text)
        if m:
            return m.group(1).strip(" .\t")
    return ""


def _date_time(text, labels):
    v = _field(text, labels)
    if not v:
        for lab in labels:               # "... bids are due Dec 4 at 2 PM"
            m = re.search(rf"(?i){lab}\s+(?:is|are|by|on)?\s*(?:due\s+)?"
                          rf"(?:by|on)?\s*({_DATE}[^\n.]*)", text)
            if m:
                v = m.group(1)
                break
    if not v:
        return "", ""
    d = re.search(_DATE, v, re.I)
    t = re.search(_TIME, v, re.I)
    day = bidboard.parse_day(re.sub(
        r"^(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+", "",
        d.group(0), flags=re.I)) if d else ""
    return day, (t.group(0).strip() if t else "")


def _company_from(addr, name):
    """A company name guessed from the sender: the signature isn't
    reliable, so this is only a start for the user to correct."""
    dom = addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""
    if dom and not re.match(r"^(gmail|yahoo|outlook|hotmail|aol|icloud|"
                            r"proton(?:mail)?|live|msn)\.", dom):
        base = dom.split(".")[0]
        return re.sub(r"[-_]+", " ", base).title()
    return ""


def parse(subject="", sender_name="", sender_addr="", text="", source=""):
    """(draft, found): a Bid Board opportunity from an invitation, and
    the names of the fields that were read from it. Fields not found are
    left blank for the user."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    project = _field(text, [r"project(?:\s+name)?", r"job(?:\s+name)?",
                            r"re"])
    if not project:
        project = _SUBJECT_JUNK.sub("", subject).strip(" -–|:")
    gc = _field(text, [r"general\s+contractor", r"gc", r"contractor",
                       r"construction\s+manager", r"cm"]) or \
        _company_from(sender_addr, sender_name)
    due, due_time = _date_time(text, [r"bids?\s+(?:are\s+)?due(?:\s+date)?",
                                      r"bid\s+date", r"due\s+date",
                                      r"proposals?\s+(?:are\s+)?due",
                                      r"quotes?\s+(?:are\s+)?due"])
    walk_day, walk_time = _date_time(text, [
        r"(?:mandatory\s+)?pre-?bid(?:\s+(?:meeting|conference|walk))?",
        r"job\s+walk", r"site\s+(?:visit|walk)", r"walk-?through"])
    rfi, _t = _date_time(text, [r"rfis?(?:\s+(?:are\s+)?due|\s+deadline|"
                                r"\s+cutoff)?", r"questions?(?:\s+(?:are\s+)"
                                r"?due(?:\s+by)?|\s+deadline)?",
                                r"last\s+day\s+for\s+questions"])
    address = _field(text, [r"(?:project\s+|site\s+|job\s+)?address",
                            r"(?:project\s+)?location", r"site"])
    location = ""
    m = re.search(r",\s*([A-Za-z .]+),\s*([A-Z]{2})\b(?:\s+\d{5})?", address)
    if m:
        location = f"{m.group(1).strip()}, {m.group(2)}"
    trade = _field(text, [r"trades?", r"scope", r"bid\s+package",
                          r"division"])
    links = []
    for u in _URL.findall(text):
        u = u.rstrip(".,;")
        if u not in links:
            links.append(u)
    draft = {"project": project[:200], "gc": gc[:120],
             "address": address[:200], "location": location,
             "trade": trade[:120], "due": due, "due_time": due_time,
             "job_walk": (walk_day + (" " + walk_time if walk_time else ""))
             if walk_day else "",
             "rfi_due": rfi, "estimator": "", "amount": "",
             "status": "Undecided", "plan_links": "\n".join(links[:10]),
             "notes": (f"From {sender_name or sender_addr}"
                       if sender_name or sender_addr else ""),
             "source": os.path.basename(source) if source else "pasted text"}
    found = [k for k in ("project", "gc", "due", "due_time", "job_walk",
                         "rfi_due", "address", "trade", "plan_links")
             if draft[k]]
    return draft, found


def from_file(path):
    """(draft, found) from a saved email. .eml is read here; an Outlook
    .msg file needs to be saved as .eml (or its text pasted) - it is a
    different format this program doesn't open."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".eml":
        subject, name, addr, text = read_eml(path)
        return parse(subject, name, addr, text, path)
    if ext in (".txt", ""):
        with open(path, encoding="utf-8", errors="replace") as f:
            return parse(text=f.read(), source=path)
    raise bidboard.BoardError(
        "That file type can't be read here. In Outlook, drag the email to "
        "a folder and save it as .eml (or copy its text and use Paste "
        "Text).")
