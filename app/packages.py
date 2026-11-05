"""Package Tracker (Nov 3, Jon): keep the tracking numbers for material
and deliveries in one list, see which carrier each one is, and open the
carrier's own tracking page with a click. No carrier accounts, nothing
looked up in the background: the status is read on the carrier's site.

Tracking numbers are recognised by their pattern (and check digit where
the carrier publishes one). When a pattern could belong to more than one
carrier the most likely one is picked and the person can change it.
The list lives in this person's data folder (packages.json). No Qt here.
"""
import datetime
import json
import os
import re
import uuid
from urllib.parse import quote

CARRIERS = ("UPS", "FedEx", "USPS", "DHL")

URLS = {
    "UPS": "https://www.ups.com/track?tracknum={n}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={n}",
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={n}",
    "DHL": "https://www.dhl.com/us-en/home/tracking/tracking-express.html"
           "?submit=1&tracking-id={n}",
}


def clean(number):
    """Spaces, dashes and lower case taken out."""
    return re.sub(r"[\s\-]", "", str(number or "")).upper()


# ---- check digits --------------------------------------------------------------

def _s10_ok(n):
    """International (UPU S10) like RA123456785US."""
    w = [8, 6, 4, 2, 3, 5, 9, 7]
    d = [int(c) for c in n[2:10]]
    s = 11 - sum(a * b for a, b in zip(d, w)) % 11
    s = 0 if s == 10 else 5 if s == 11 else s
    return s == int(n[10])


# ---- recognising a number ------------------------------------------------------

def detect(number):
    """Carriers this tracking number could be, most likely first ([] =
    doesn't look like a tracking number)."""
    n = clean(number)
    if not n or len(n) < 9 or len(n) > 40:
        return []
    out = []
    if re.fullmatch(r"1Z[0-9A-Z]{16}", n):
        return ["UPS"]
    if re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", n):
        if n.endswith("US"):
            return ["USPS"]
        return ["USPS", "DHL"] if _s10_ok(n) else ["DHL", "USPS"]
    if re.fullmatch(r"(JJD|JVGL|JD)\d{8,22}|GM\d{16,20}|LX\d{9}[A-Z]{2}|"
                    r"[0-9]{3}-?[0-9]{8}", n) and not n.isdigit():
        return ["DHL"]
    if re.fullmatch(r"T\d{10}|H\d{10}", n):
        return ["UPS"]
    if not n.isdigit():
        return []
    L = len(n)
    if L == 30 and n.startswith("420"):          # ZIP + USPS barcode
        return ["USPS"]
    if L in (20, 22) and n[:2] in ("91", "92", "93", "94", "95"):
        # 92 is also used by FedEx Ground Economy (handed to USPS)
        return ["USPS", "FedEx"] if n.startswith("92") else ["USPS"]
    if L == 26 and n.startswith("420"):
        return ["USPS"]
    if L == 10:
        return ["DHL"]
    if L == 12:
        return ["FedEx"]
    if L == 15:
        return ["FedEx"]
    if L == 20 and n.startswith("96"):
        return ["FedEx"]
    if L == 22 and n.startswith("96"):
        return ["FedEx"]
    if L == 34 and n.startswith("96"):
        return ["FedEx"]
    if L == 9 or L == 11:
        return ["UPS", "DHL"] if L == 9 else ["DHL"]
    if L == 18 and n.startswith("00"):
        return ["DHL", "FedEx"]
    return []


def carrier(number):
    c = detect(number)
    return c[0] if c else None


def url(number, carrier_name=None):
    """The carrier's own tracking page for this number (None = unknown)."""
    c = carrier_name or carrier(number)
    if c not in URLS:
        return None
    return URLS[c].format(n=quote(clean(number)))


# plain digit lengths that are also phone, order or invoice numbers: only
# taken from pasted text when that carrier is named in it
_AMBIGUOUS = {9, 10, 11, 12, 15, 18}


def find_numbers(text):
    """Tracking numbers in pasted text (a shipping email, a packing slip):
    [(number, carrier)], in order, each once."""
    up = (text or "").upper()
    named = {c for c in CARRIERS if c.upper() in up} | \
        ({"FedEx"} if "FEDEX" in up else set())
    toks = re.findall(r"[0-9A-Z]+", re.sub(r"(?<=[0-9A-Z])-(?=[0-9A-Z])",
                                           " ", up))
    seen, out = set(), []

    def ok(n):
        if not any(ch.isdigit() for ch in n):
            return None
        c = carrier(n)
        if not c:
            return None
        if n.isdigit() and len(n) in _AMBIGUOUS and c not in named:
            return None
        return c
    i = 0
    while i < len(toks):
        hit = None
        if any(ch.isdigit() for ch in toks[i]) or toks[i].startswith("1Z"):
            j_max = i
            while j_max < len(toks) and j_max - i < 10 and (
                    any(ch.isdigit() for ch in toks[j_max]) or
                    (j_max == i and toks[j_max].startswith("1Z")) or
                    (j_max > i and toks[i].startswith("1Z") and
                     len(toks[j_max]) <= 4)):
                j_max += 1
            for j in range(j_max, i, -1):
                n = "".join(toks[i:j])
                c = ok(n)
                if c:
                    hit = (n, c, j)
                    break
        if hit:
            n, c, j = hit
            if n not in seen:
                seen.add(n)
                out.append((n, c))
            i = j
        else:
            i += 1
    return out


# ---- the list ------------------------------------------------------------------

def path():
    from . import settings
    return os.path.join(settings.DIR, "packages.json")


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data if isinstance(p, dict) and p.get("number")]
    except (OSError, ValueError):
        return []


def save(items):
    from . import safeio
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    safeio.atomic_write(path(), json.dumps(items, indent=2))


def parse_date(text, today=None):
    """'11/6', '11/6/2026', '2026-11-06' -> date (None if not a date).
    A month/day with no year is the next one coming."""
    t = (text or "").strip()
    if not t:
        return None
    today = today or datetime.date.today()
    try:
        return datetime.date.fromisoformat(t)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?", t)
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
    try:
        if y:
            y = int(y)
            return datetime.date(y + 2000 if y < 100 else y, mo, d)
        dt = datetime.date(today.year, mo, d)
        if (today - dt).days > 180:              # Jan date typed in Dec
            dt = datetime.date(today.year + 1, mo, d)
        return dt
    except ValueError:
        return None


def is_late(p, today=None):
    """Not delivered and its expected day has passed."""
    if p.get("delivered"):
        return False
    d = parse_date(p.get("expected", ""))
    return bool(d and d < (today or datetime.date.today()))


def jobs(items):
    return sorted({p.get("job", "") for p in items if p.get("job")},
                  key=str.lower)


def new(number, what="", vendor="", job="", carrier_name=None, note="",
        expected=""):
    n = clean(number)
    d = parse_date(expected)
    return {"id": uuid.uuid4().hex[:12], "number": n,
            "carrier": carrier_name or carrier(n) or "",
            "what": what.strip(), "vendor": vendor.strip(),
            "job": job.strip(), "note": note.strip(),
            "expected": d.isoformat() if d else "",
            "added": datetime.date.today().isoformat(),
            "delivered": False}


def add(items, number, **kw):
    """Add one (not twice). Returns the entry (the existing one if the
    number is already on the list)."""
    n = clean(number)
    for p in items:
        if p["number"] == n:
            return p
    p = new(n, **kw)
    items.append(p)
    return p
