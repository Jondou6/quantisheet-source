"""Bid Board (Nov 11): the invitations to bid that come to *us*, in one
list - who asked, when it is due, who is pricing it, where it stands.

One opportunity is one invitation from one GC for one project:

    project, gc, location, address, trade, due + due_time, job_walk,
    rfi_due, estimator, notes, amount (what we bid), status, plan_links,
    source ("typed" or the email file it was read from)

Status: Undecided -> Accepted -> Submitted -> Won / Lost, or Declined.
Won, Lost, Submitted (pending) and Declined (no bid) show in the
Estimating Dashboard's hit rate, also by GC.

Kept on this PC in the settings folder (bid_board.json). Nothing here
sends anything; an invitation email is only read (never marked read,
never answered), and a draft made from one is saved only when the user
confirms it.

Pure Python, no Qt.
"""
import datetime as _dt
import difflib
import json
import os
import re
import uuid

from . import settings

FILE = "bid_board.json"
STATUSES = ("Undecided", "Accepted", "Submitted", "Won", "Lost", "Declined")
OPEN = ("Undecided", "Accepted")
FIELDS = ("project", "gc", "location", "address", "trade", "due",
          "due_time", "job_walk", "rfi_due", "estimator", "notes",
          "amount", "status", "plan_links", "source")
# the Estimating Dashboard's words for our own result
RESULT = {"Won": "Won", "Lost": "Lost", "Submitted": "Pending",
          "Declined": "No bid"}


class BoardError(ValueError):
    pass


def path():
    return os.path.join(settings.DIR, FILE)


def _read():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "items": []}


def _write(data):
    os.makedirs(settings.DIR, exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path())


def _s(v):
    return " ".join(str(v or "").split())


def parse_day(v):
    """A date typed or read ("2026-12-04", "12/4/2026", "Dec 4, 2026",
    "December 4") as ISO text, or "" when it isn't a date."""
    t = _s(v)
    if not t:
        return ""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", t)
    try:
        if m:
            return _dt.date(*(int(x) for x in m.groups())).isoformat()
        m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", t)
        if m:
            mo, d, y = (int(x) for x in m.groups())
            return _dt.date(y + 2000 if y < 100 else y, mo, d).isoformat()
        m = re.match(r"^(?:\w+,?\s+)?([A-Za-z]{3,9})\.?\s+(\d{1,2})"
                     r"(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t)
        if m and m.group(1)[:3].lower() in _MONTHS:
            today = _dt.date.today()
            y = int(m.group(3)) if m.group(3) else today.year
            d = _dt.date(y, _MONTHS[m.group(1)[:3].lower()],
                         int(m.group(2)))
            if not m.group(3) and (today - d).days > 60:
                d = d.replace(year=y + 1)    # "Jan 8" said in December
            return d.isoformat()
    except ValueError:
        return ""
    return ""


_MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def parse_amount(v):
    """Dollars typed ("$1,234,500", "1234500.50") as a 2-decimal string,
    "" for blank. Unreadable or negative: BoardError."""
    t = _s(v).replace("$", "").replace(",", "")
    if not t:
        return ""
    from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise BoardError(f"The amount isn't a number: {v!r}.") from None
    if not d.is_finite() or d < 0 or d > Decimal("1e12"):
        raise BoardError(f"The amount isn't a usable number: {v!r}.")
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def clean(o):
    """One opportunity with known fields and fixed types."""
    out = {"id": _s(o.get("id")) or uuid.uuid4().hex[:12]}
    for k in FIELDS:
        out[k] = _s(o.get(k)) if k not in ("notes", "plan_links") else \
            str(o.get(k) or "").strip()
    for k in ("due", "rfi_due"):
        out[k] = parse_day(out[k])
    # a job walk is "YYYY-MM-DD time" when it starts with a date (so it
    # goes on the calendar), else whatever was typed
    jw = _s(o.get("job_walk"))
    first, _sp, rest = jw.partition(" ")
    day = parse_day(first)
    out["job_walk"] = (day + (" " + rest if rest else "")) if day else jw
    out["amount"] = parse_amount(out["amount"])
    if out["status"] not in STATUSES:
        out["status"] = "Undecided"
    if not out["project"]:
        raise BoardError("Give the project a name.")
    for k in ("created", "decided_at"):
        if o.get(k):
            out[k] = _s(o[k])
    if isinstance(o.get("go"), dict):
        out["go"] = o["go"]
    if o.get("not_duplicate_of"):
        out["not_duplicate_of"] = [str(x) for x in o["not_duplicate_of"]]
    return out


def load():
    out = []
    for o in _read()["items"]:
        try:
            out.append(clean(o))
        except BoardError:
            continue
    return out


def get(oid, items=None):
    return next((o for o in (load() if items is None else items)
                 if o["id"] == oid), None)


def save(o):
    """Add or update one opportunity; returns the saved copy."""
    o = clean(o)
    data = _read()
    items = [x for x in data["items"] if x.get("id") != o["id"]]
    if len(items) == len(data["items"]):
        o.setdefault("created", _dt.datetime.now().isoformat(
            timespec="seconds"))
    else:
        old = next(x for x in data["items"] if x.get("id") == o["id"])
        o.setdefault("created", old.get("created", ""))
    items.append(o)
    data["items"] = items
    _write(data)
    return o


def remove(oid):
    data = _read()
    data["items"] = [x for x in data["items"] if x.get("id") != oid]
    _write(data)


def set_status(oid, status, amount=None):
    if status not in STATUSES:
        raise BoardError(f"Not a status: {status!r}.")
    o = get(oid)
    if o is None:
        raise BoardError("That opportunity isn't on the board any more.")
    o["status"] = status
    if amount is not None:
        o["amount"] = amount
    if status in ("Won", "Lost", "Declined"):
        o["decided_at"] = _dt.date.today().isoformat()
    return save(o)


def sort_key(o):
    """Open bids by due date first, then the rest, newest due first."""
    is_open = o["status"] in OPEN + ("Submitted",)
    return (not is_open, o["due"] or "9999" if is_open else "",
            "" if is_open else _neg(o["due"]), o["project"].lower())


def _neg(day):
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c
                   for c in (day or "0000-00-00"))


# ---------------------------------------------------------------- calendar
def events(items=None, statuses=OPEN + ("Submitted",)):
    """[{"date", "time", "what", "project", "gc", "id"}] for bids due,
    job walks and question cutoffs, soonest first."""
    out = []
    for o in (load() if items is None else items):
        if o["status"] not in statuses:
            continue
        who = f"{o['project']}" + (f" ({o['gc']})" if o["gc"] else "")
        if o["due"]:
            out.append({"date": o["due"], "time": o["due_time"],
                        "what": "Bid due", "title": f"Bid due: {who}",
                        "project": o["project"], "gc": o["gc"],
                        "id": o["id"]})
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*(.*)$", o["job_walk"])
        if m:
            out.append({"date": m.group(1), "time": m.group(2),
                        "what": "Job walk", "title": f"Job walk: {who}",
                        "project": o["project"], "gc": o["gc"],
                        "id": o["id"]})
        if o["rfi_due"]:
            out.append({"date": o["rfi_due"], "time": "",
                        "what": "Questions due",
                        "title": f"Questions due: {who}",
                        "project": o["project"], "gc": o["gc"],
                        "id": o["id"]})
    out.sort(key=lambda e: (e["date"], e["time"], e["title"]))
    return out


def _ics_text(s):
    return str(s).replace("\\", "\\\\").replace(";", "\\;") \
        .replace(",", "\\,").replace("\n", "\\n")


def to_ics(evts, path_):
    """Write the events as all-day entries in an .ics file to import into
    a calendar. Nothing is sent to anyone."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//QuantiSheet//Bid Board//EN"]
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in evts:
        d = _dt.date.fromisoformat(e["date"])
        lines += ["BEGIN:VEVENT",
                  f"UID:{e['id']}-{e['what'].replace(' ', '')}-{e['date']}"
                  "@quantisheet",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{d + _dt.timedelta(days=1):%Y%m%d}",
                  "SUMMARY:" + _ics_text(e["title"] + (
                      f" {e['time']}" if e["time"] else "")),
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    with open(path_, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return path_


# -------------------------------------------------------------- duplicates
_NOISE = {"the", "a", "an", "of", "at", "for", "and", "project", "phase",
          "new", "building", "bldg", "renovation", "addition", "llc", "inc",
          "co", "company", "construction", "contractors", "builders"}
_ABBR = {"st": "street", "st.": "street", "ave": "avenue", "rd": "road",
         "blvd": "boulevard", "dr": "drive", "hwy": "highway", "ln": "lane",
         "ct": "court", "pkwy": "parkway", "n": "north", "s": "south",
         "e": "east", "w": "west", "elem": "elementary", "es": "elementary",
         "hs": "high", "ms": "middle", "sch": "school", "ctr": "center",
         "bldg": "building", "med": "medical", "hosp": "hospital"}


def _words(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", str(text or "").lower()):
        w = _ABBR.get(w, w)
        if w not in _NOISE:
            out.append(w)
    return out


def _alike(a, b):
    """0..1: how alike two names or addresses are, word order ignored."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    sa, sb = set(wa), set(wb)
    overlap = len(sa & sb) / float(min(len(sa), len(sb)))
    seq = difflib.SequenceMatcher(None, " ".join(sorted(wa)),
                                  " ".join(sorted(wb))).ratio()
    return max(seq, overlap if len(sa & sb) >= 2 else 0.0)


def _days_apart(a, b):
    try:
        return abs((_dt.date.fromisoformat(a) -
                    _dt.date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return None


NAME_ALIKE, DUE_DAYS = 0.78, 10


_SUFFIX = {"street", "avenue", "road", "boulevard", "drive", "highway",
           "lane", "court", "parkway", "way", "place", "pl", "circle",
           "cir", "trail", "suite", "ste", "unit"}


def same_street(a, b):
    """Two addresses on the same street at the same number ("1200 River
    Rd" and "1200 River Road, Springfield"). The city isn't compared: an
    invitation often leaves it off."""
    def parts(addr):
        ws = _words(str(addr or "").split(",")[0])
        num = next((w for w in ws if w.isdigit()), "")
        names = {w for w in ws if not w.isdigit() and w not in _SUFFIX}
        return num, names
    (na, wa), (nb, wb) = parts(a), parts(b)
    return bool(na and na == nb and wa and wb and
                (wa <= wb or wb <= wa))


def why_same(a, b):
    """Reasons two opportunities look like the same project ([] when they
    don't): alike names with due dates close together (or one missing),
    or the same street address."""
    why = []
    name = _alike(a["project"], b["project"])
    addr = same_street(a["address"], b["address"])
    gap = _days_apart(a["due"], b["due"])
    names = name >= NAME_ALIKE and (gap is None or gap <= DUE_DAYS)
    if addr:
        why.append(f"same address ({b['address']})")
    if names:
        why.append(f"project names alike (\"{b['project']}\")")
        if gap is not None:
            why.append("due the same day" if gap == 0 else
                       f"due {gap} day(s) apart")
    if why and _s(a["gc"]).lower() != _s(b["gc"]).lower() and b["gc"]:
        why.append(f"from another GC ({b['gc']})")
    return why


def duplicates(o, items=None):
    """[(other, [reasons])] for the opportunities that look like the same
    project as `o` (itself and pairs the user dismissed left out)."""
    out = []
    skip = set(o.get("not_duplicate_of") or [])
    for x in (load() if items is None else items):
        if x["id"] == o.get("id") or x["id"] in skip or \
                o.get("id") in (x.get("not_duplicate_of") or []):
            continue
        why = why_same(o, x)
        if why:
            out.append((x, why))
    return out


def dismiss(o, other_id):
    """The user says these two are not the same project."""
    lst = list(o.get("not_duplicate_of") or [])
    if other_id not in lst:
        lst.append(other_id)
    o["not_duplicate_of"] = lst
    return o


def groups(items=None):
    """{id: (group number, "same project, 3 GCs")} for opportunities that
    are the same project from more than one invitation."""
    items = load() if items is None else items
    parent = {o["id"]: o["id"] for o in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(items):
        for x, _why in duplicates(a, items[i + 1:]):
            parent[find(a["id"])] = find(x["id"])
    members = {}
    for o in items:
        members.setdefault(find(o["id"]), []).append(o)
    out, n = {}, 0
    for root, ms in members.items():
        if len(ms) < 2:
            continue
        n += 1
        gcs = {_s(m["gc"]).lower() for m in ms if m["gc"]}
        label = f"same project, {len(gcs)} GCs" if len(gcs) > 1 else \
            f"same project, {len(ms)} invitations"
        for m in ms:
            out[m["id"]] = (n, label)
    return out


# ------------------------------------------------------------------- stats
def _rate(won, lost):
    return None if won + lost == 0 else round(1000.0 * won /
                                              (won + lost)) / 10.0


def win_rate_by_gc(items=None):
    """[{"gc", "won", "lost", "pending", "declined", "rate"}], most bids
    first. The rate counts Won and Lost only (the Dashboard's rule)."""
    by = {}
    for o in (load() if items is None else items):
        k = _s(o["gc"]) or "(no GC)"
        r = by.setdefault(k.lower(), {"gc": k, "won": 0, "lost": 0,
                                      "pending": 0, "declined": 0,
                                      "open": 0})
        r[{"Won": "won", "Lost": "lost", "Submitted": "pending",
           "Declined": "declined"}.get(o["status"], "open")] += 1
    rows = list(by.values())
    for r in rows:
        r["rate"] = _rate(r["won"], r["lost"])
    rows.sort(key=lambda r: (-(r["won"] + r["lost"] + r["pending"]),
                             r["gc"].lower()))
    return rows


def bids_per_month(items=None):
    """[{"month": "2026-11", "submitted", "won", "lost"}] by due date:
    the bids we sent in (Submitted, Won or Lost)."""
    by = {}
    for o in (load() if items is None else items):
        if o["status"] not in ("Submitted", "Won", "Lost") or not o["due"]:
            continue
        r = by.setdefault(o["due"][:7], {"month": o["due"][:7],
                                         "submitted": 0, "won": 0,
                                         "lost": 0})
        r["submitted"] += 1
        r["won"] += o["status"] == "Won"
        r["lost"] += o["status"] == "Lost"
    return [by[k] for k in sorted(by)]


def workload(items=None, today=None):
    """[{"estimator", "open", "due_7", "next_due"}]: bids each estimator
    is carrying now (Undecided or Accepted), and how many are due within
    a week."""
    today = today or _dt.date.today()
    by = {}
    for o in (load() if items is None else items):
        if o["status"] not in OPEN:
            continue
        k = _s(o["estimator"]) or "(nobody yet)"
        r = by.setdefault(k.lower(), {"estimator": k, "open": 0, "due_7": 0,
                                      "next_due": ""})
        r["open"] += 1
        gap = _days_apart(o["due"], today.isoformat()) if o["due"] else None
        if o["due"] and o["due"] >= today.isoformat() and gap is not None \
                and gap <= 7:
            r["due_7"] += 1
        if o["due"] and o["due"] >= today.isoformat() and \
                (not r["next_due"] or o["due"] < r["next_due"]):
            r["next_due"] = o["due"]
    return sorted(by.values(), key=lambda r: (-r["open"],
                                              r["estimator"].lower()))


# ---------------------------------------------------------------- go/no-go
GO_KEY = "bid_board_go"
FACTORS = (("scope", "Scope fits what we do"),
           ("location", "Location / distance works"),
           ("relationship", "Good relationship with this GC"),
           ("history", "We win with this GC"),
           ("workload", "We have the time to price it"),
           ("bonding", "Bonding needed is within our capacity"))
DEFAULT_WEIGHTS = {"scope": 25, "location": 15, "relationship": 20,
                   "history": 15, "workload": 15, "bonding": 10}
DEFAULT_GO, DEFAULT_MAYBE = 65, 45
ANSWERS = (("Yes", 1.0), ("Partly", 0.5), ("No", 0.0))


def go_settings():
    """{"weights": {factor: points}, "go": score for Go, "maybe": score
    below which it is No-go} - the user's own, else the defaults."""
    s = settings.get(GO_KEY) or {}
    w = dict(DEFAULT_WEIGHTS)
    if isinstance(s.get("weights"), dict):
        for k, _l in FACTORS:
            try:
                v = float(s["weights"].get(k, w[k]))
            except (TypeError, ValueError):
                continue
            if 0 <= v <= 1000:
                w[k] = v
    out = {"weights": w, "go": DEFAULT_GO, "maybe": DEFAULT_MAYBE}
    for k in ("go", "maybe"):
        try:
            v = float(s.get(k, out[k]))
            if 0 <= v <= 100:
                out[k] = v
        except (TypeError, ValueError):
            pass
    if out["maybe"] > out["go"]:
        out["maybe"] = out["go"]
    return out


def set_go_settings(weights=None, go=None, maybe=None):
    cur = go_settings()
    if weights is not None:
        for k, v in weights.items():
            if k in cur["weights"]:
                v = float(v)
                if not 0 <= v <= 1000:
                    raise BoardError("A weight is 0 or more.")
                cur["weights"][k] = v
    if go is not None:
        cur["go"] = float(go)
    if maybe is not None:
        cur["maybe"] = float(maybe)
    if not 0 <= cur["maybe"] <= cur["go"] <= 100:
        raise BoardError("The scores run 0 to 100, and Go is the higher "
                         "one.")
    if sum(cur["weights"].values()) <= 0:
        raise BoardError("At least one weight must be more than 0.")
    settings.set(GO_KEY, cur)
    return cur


def history_answer(gc, items=None):
    """A starting answer for "we win with this GC" from the board itself:
    Yes at 40% or better, Partly at 15%, else No; "" with fewer than 3
    decided bids (not enough to say)."""
    r = next((x for x in win_rate_by_gc(items)
              if x["gc"].lower() == _s(gc).lower()), None)
    if r is None or r["won"] + r["lost"] < 3:
        return ""
    return "Yes" if r["rate"] >= 40 else "Partly" if r["rate"] >= 15 \
        else "No"


def go_score(answers, cfg=None):
    """{"score": 0-100 or None, "recommendation": "Go" / "Look closer" /
    "No-go" / "", "answered", "of"} from {factor: "Yes" | "Partly" | "No"}.
    Factors left blank are left out of the score (it is over the weights
    answered); with nothing answered there is no score."""
    cfg = cfg or go_settings()
    val = dict(ANSWERS)
    got = pts = 0.0
    n = 0
    for k, _label in FACTORS:
        a = (answers or {}).get(k)
        if a not in val:
            continue
        w = cfg["weights"][k]
        got += w * val[a]
        pts += w
        n += 1
    if pts <= 0:
        return {"score": None, "recommendation": "", "answered": n,
                "of": len(FACTORS)}
    score = round(1000.0 * got / pts) / 10.0
    rec = "Go" if score >= cfg["go"] else "Look closer" if \
        score >= cfg["maybe"] else "No-go"
    return {"score": score, "recommendation": rec, "answered": n,
            "of": len(FACTORS)}


def record_decision(o, answers, decision, reason, by=""):
    """Keep the checklist, the score and what the person decided (the
    decision is theirs: it may differ from the recommendation)."""
    if decision not in ("Go", "No-go"):
        raise BoardError("Decide Go or No-go.")
    sc = go_score(answers)
    o["go"] = {"answers": {k: v for k, v in (answers or {}).items()
                           if v in dict(ANSWERS)},
               "score": sc["score"], "recommendation": sc["recommendation"],
               "decision": decision, "reason": _s(reason), "by": _s(by),
               "at": _dt.datetime.now().isoformat(timespec="seconds")}
    if o["status"] == "Undecided":
        o["status"] = "Accepted" if decision == "Go" else "Declined"
    return o


# ------------------------------------------------------------ the dashboard
def dashboard_jobs(items=None):
    """The board's decided and submitted bids as Estimating Dashboard
    jobs (key "bb:<id>"): Won / Lost / Pending / No bid, with the GC."""
    from decimal import Decimal
    out = []
    for o in (load() if items is None else items):
        res = RESULT.get(o["status"])
        if not res:
            continue
        out.append({"key": "bb:" + o["id"], "name": o["project"],
                    "gc": o["gc"], "estimator": o["estimator"],
                    "bid_date": _dt.date.fromisoformat(o["due"])
                    if o["due"] else None,
                    "bid": Decimal(o["amount"]) if o["amount"] else None,
                    "result": res, "result_source": "Bid Board",
                    "sources": ["Bid Board"]})
    return out
