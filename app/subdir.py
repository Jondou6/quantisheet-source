"""Company Directory: your subcontractor and vendor contacts, kept on this
computer only.

It lives in your own data folder (~/.quantisheet/company_directory.json),
never in the program folder, so it is never part of an installer or a copy
of QuantiSheet you give someone. Bid packages pick bidders from it by CSI
division, trade and state.

Import from Excel (an Outlook contact export or your own list): any sheet
with a company column is read; division, trade and type columns found on
other sheets (matched by company name) fill in what the main list lacks.
"""
import json
import os
import re

from . import settings

FILE = "company_directory.json"
FIELDS = ["company", "contact", "division", "trade", "type", "phone",
          "email", "address", "city", "state", "zip", "notes", "favorite",
          "source", "certs", "license", "insurance_exp", "bond_limit",
          "rating", "prequal", "prequal_exp", "prequal_limit"]
# small-business and labour certifications owners ask about
CERTS = ["MBE", "WBE", "DBE", "SBE", "VOSB", "SDVOSB", "HUBZone",
         "Section 3", "Union"]
PREQUAL = ["", "Sent", "Pending", "Approved", "Rejected"]

STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY",
    "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY"}


def path():
    return os.path.join(settings.DIR, FILE)


def _read():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load():
    cs = [c for c in _read().get("contacts", []) if isinstance(c, dict)]
    for c in cs:
        c.setdefault("id", _new_id(c))
    return cs


def _new_id(c=None):
    import secrets
    return secrets.token_hex(6)


def save(contacts, history=None):
    os.makedirs(settings.DIR, exist_ok=True)
    if history is None:
        history = _read().get("history", {})
    for c in contacts:
        c.setdefault("id", _new_id(c))
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "contacts": contacts, "history": history},
                  f, indent=0)
    try:                          # a hidden file can't be replaced on Windows
        if os.name == "nt" and os.path.exists(path()):
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path(), 0x80)
    except Exception:
        pass
    os.replace(tmp, path())
    try:                                   # private to this Windows user
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path(), 0x2)  # hidden
    except Exception:
        pass


# ------------------------------------------------------------- editing
def get(cid, contacts=None):
    return next((c for c in (load() if contacts is None else contacts)
                 if c.get("id") == cid), None)


def upsert(contact):
    """Add a contact, or update the one with the same id. Returns it."""
    cs = load()
    c = {f: contact.get(f, "") for f in FIELDS}
    c["id"] = contact.get("id") or _new_id()
    c["state"] = _state(c.get("state"))
    c["division"] = _div(c.get("division")) or ""
    if isinstance(contact.get("prequal_data"), dict):
        c["prequal_data"] = contact["prequal_data"]
    for i, old in enumerate(cs):
        if old.get("id") == c["id"]:
            keep = {k: v for k, v in old.items() if k not in c}
            cs[i] = dict(keep, **c)
            save(cs)
            return cs[i]
    cs.append(c)
    save(cs)
    return c


def remove(cid):
    cs = load()
    left = [c for c in cs if c.get("id") != cid]
    if len(left) != len(cs):
        save(left)
    return len(cs) - len(left)


def toggle_favorite(cid):
    cs = load()
    for c in cs:
        if c.get("id") == cid:
            c["favorite"] = "" if c.get("favorite") else "1"
            save(cs)
            return bool(c["favorite"])
    return False


def certs_of(c):
    return [x.strip() for x in re.split(r"[,;/]", c.get("certs") or "")
            if x.strip()]


# ------------------------------------------------- prequal / compliance
def _date(v):
    from datetime import date
    s = _s(v)
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s) or \
        re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if not m:
        return None
    try:
        if "-" in m.group(0):
            y, mo, d = (int(x) for x in m.groups())
        else:
            mo, d, y = (int(x) for x in m.groups())
            y += 2000 if y < 100 else 0
        return date(y, mo, d)
    except ValueError:
        return None


def prequal_status(c, today=None):
    """Not prequalified / Sent / Pending / Approved / Expired / Rejected."""
    from datetime import date
    today = today or date.today()
    st = c.get("prequal") or ""
    if st == "Approved":
        exp = _date(c.get("prequal_exp"))
        if exp and exp < today:
            return "Expired"
        return "Approved"
    return st or "Not prequalified"


def prequal_ok(c, amount=None, today=None):
    """Prequalified, and for this much work when a limit is set."""
    if prequal_status(c, today) != "Approved":
        return False
    lim = _money(c.get("prequal_limit"))
    return not (amount and lim and amount > lim)


def _money(v):
    try:
        return float(re.sub(r"[^0-9.]", "", str(v or "")) or "x")
    except ValueError:
        return None


def alerts(contacts=None, today=None, days=30):
    """Insurance and prequalification running out: [(contact, what, date,
    expired)] - expired first, then soonest."""
    from datetime import date, timedelta
    today = today or date.today()
    soon = today + timedelta(days=days)
    out = []
    for c in (load() if contacts is None else contacts):
        for key, what in (("insurance_exp", "Insurance"),
                          ("prequal_exp", "Prequalification")):
            if key == "prequal_exp" and c.get("prequal") != "Approved":
                continue
            d = _date(c.get(key))
            if d and d <= soon:
                out.append((c, what, d.isoformat(), d < today))
    out.sort(key=lambda t: (not t[3], t[2]))
    return out


# ------------------------------------------------------------- bid history
def record_bid(company, project, package, amount, result, when=None):
    """Remember a bid this company sent (result: Awarded / Not awarded /
    Declined)."""
    from datetime import date
    data = _read()
    hist = data.get("history") or {}
    k = _company_key(company)
    if not k:
        return
    rows = hist.setdefault(k, [])
    row = {"project": _s(project), "package": _s(package),
           "amount": amount, "result": result,
           "date": when or date.today().isoformat()}
    rows[:] = [r for r in rows if not (r.get("project") == row["project"]
                                       and r.get("package") ==
                                       row["package"])]
    rows.append(row)
    save([c for c in data.get("contacts", []) if isinstance(c, dict)],
         hist)


def history(company):
    return list((_read().get("history") or {}).get(_company_key(company),
                                                     []))


def stats(company):
    """{"bids", "wins", "win_rate", "last"} for a company."""
    rows = [r for r in history(company) if r.get("result") != "Declined"]
    wins = sum(1 for r in rows if r.get("result") == "Awarded")
    return {"bids": len(rows), "wins": wins,
            "win_rate": (wins / len(rows)) if rows else None,
            "last": max((r.get("date") or "" for r in rows), default="")}


def _s(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


def _state(v):
    s = _s(v)
    if len(s) == 2:
        return s.upper()
    return STATE_ABBR.get(s.lower(), s)


def _div(v):
    s = _s(v)
    m = re.match(r"^(\d{1,2})", s)
    return f"{int(m.group(1)):02d}" if m else ""


def _key(c):
    return (re.sub(r"[^a-z0-9]", "", (c.get("company") or "").lower()),
            (c.get("email") or "").strip().lower())


def _company_key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ------------------------------------------------------------- import
_COLS = {
    "company": ("company name", "company", "firm", "vendor", "subcontractor"),
    "contact": ("contact", "estimator", "first name"),
    "division": ("division", "div", "csi"),
    "trade": ("trade",),
    "type": ("type",),
    "phone": ("phone number", "business phone", "phone", "primary phone",
              "mobile phone", "tel"),
    "email": ("e-mail address", "e-mail adress", "e-mail", "email"),
    "address": ("company address", "business street", "address", "street"),
    "city": ("company city", "business city", "city"),
    "state": ("company state", "business state", "state"),
    "zip": ("company zip", "business postal code", "zip", "postal"),
    "notes": ("notes",),
    "certs": ("certifications", "certification", "certs", "mwbe"),
    "license": ("license no", "license number", "contractor license",
                "license"),
    "insurance_exp": ("insurance exp", "insurance expires", "coi exp",
                      "coi expires"),
}


def _header(rows):
    """(index of the header row, {field: column}) or (None, {})."""
    for i, r in enumerate(rows[:15]):
        head = [_s(c).lower() for c in r]
        if not any(h.startswith(("company", "firm", "vendor")) for h in head):
            continue
        cols = {}
        for field, names in _COLS.items():
            for n in names:
                hit = next((j for j, h in enumerate(head) if h == n), None)
                if hit is None:
                    hit = next((j for j, h in enumerate(head)
                                if h.startswith(n)), None)
                if hit is not None and hit not in cols.values():
                    cols[field] = hit
                    break
        if "company" in cols:
            return i, cols
    return None, {}


def read_xlsx(path, sheet=None):
    """Contacts from an Excel workbook: (contacts, report). The sheet named
    IMPORT (or `sheet`, or the biggest one with emails) is the list; other
    sheets with a trade or division column fill those in by company."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        i, cols = _header(rows)
        if i is not None:
            sheets[ws.title] = (rows[i + 1:], cols)
    if not sheets:
        raise ValueError("No sheet with a Company column.")
    main = sheet if sheet in sheets else next(
        (n for n in sheets if n.strip().upper() == "IMPORT"), None)
    if main is None:
        main = max(sheets, key=lambda n: (("email" in sheets[n][1]),
                                          len(sheets[n][0])))
    extra = {}
    for name, (rows, cols) in sheets.items():
        if name == main or not ({"trade", "division"} & set(cols)):
            continue
        for r in rows:
            comp = _s(r[cols["company"]]) if cols["company"] < len(r) else ""
            if not comp:
                continue
            got = {f: _s(r[cols[f]]) for f in ("division", "trade", "type")
                   if f in cols and cols[f] < len(r) and _s(r[cols[f]])}
            if got:
                extra.setdefault(_company_key(comp), {}).update(
                    {k: v for k, v in got.items()
                     if not extra.get(_company_key(comp), {}).get(k)})
    rows, cols = sheets[main]
    out = []
    for r in rows:
        c = {f: (_s(r[j]) if j < len(r) else "") for f, j in cols.items()}
        if not c.get("company"):
            continue
        if c.get("email") and "@" not in c["email"]:
            c["email"] = ""
        c["state"] = _state(c.get("state"))
        c["division"] = _div(c.get("division"))
        if c.get("zip") in ("0", "00000"):
            c["zip"] = ""
        more = extra.get(_company_key(c["company"]), {})
        for f in ("division", "trade", "type"):
            if not c.get(f) and more.get(f):
                c[f] = _div(more[f]) if f == "division" else more[f]
        if c.get("contact") == c.get("company"):
            c["contact"] = ""
        c["source"] = os.path.basename(path)
        out.append({f: c.get(f, "") for f in FIELDS if f != "favorite"})
    return out, {"sheet": main, "rows": len(out),
                 "filled_from": sorted(n for n in sheets if n != main)}


def merge(new, replace=False):
    """Add contacts (same company + email updates the old one). Returns
    (added, updated, total)."""
    cur = [] if replace else load()
    idx = {_key(c): i for i, c in enumerate(cur)}
    added = updated = 0
    for c in new:
        k = _key(c)
        if k in idx:
            old = cur[idx[k]]
            for f, v in c.items():
                if v and not old.get(f):
                    old[f] = v
            updated += 1
        else:
            idx[k] = len(cur)
            cur.append(dict(c))
            added += 1
    save(cur)
    return added, updated, len(cur)


def import_xlsx(path, sheet=None, replace=False):
    contacts, report = read_xlsx(path, sheet)
    added, updated, total = merge(contacts, replace)
    report.update(added=added, updated=updated, total=total)
    return report


# ------------------------------------------------------------- search
def search(text="", division="", state="", with_email=False,
           contacts=None, favorites=False, cert="", prequalified=False):
    cs = load() if contacts is None else contacts
    t = (text or "").lower().strip()
    div = _div(division)
    st = _state(state) if state else ""
    out = []
    for c in cs:
        if div and c.get("division") != div:
            continue
        if st and (c.get("state") or "").upper() != st:
            continue
        if with_email and not c.get("email"):
            continue
        if favorites and not c.get("favorite"):
            continue
        if cert and cert.lower() not in [x.lower() for x in certs_of(c)]:
            continue
        if prequalified and prequal_status(c) != "Approved":
            continue
        hay = " ".join(str(c.get(f) or "") for f in
                       ("company", "contact", "trade", "type", "city",
                        "email", "notes", "certs")).lower()
        if t and t not in hay:
            continue
        out.append(c)
    out.sort(key=lambda c: (not c.get("favorite"),
                            (c.get("company") or "").lower()))
    return out


def for_package(rec, contacts=None):
    """Contacts that fit a bid package: same CSI division as its trade
    (01-49), or a trade word in common."""
    trades = f"{rec.get('trades') or ''} {rec.get('specs') or ''}"
    m = re.search(r"\b(\d{2})(?:\s?\d{2}\s?\d{2})?\b", trades)
    div = m.group(1) if m else ""
    words = set(re.findall(r"[a-z]{4,}", f"{rec.get('title', '')} "
                                         f"{trades}".lower()))
    words -= {"work", "complete", "section", "trade", "package"}
    cs = load() if contacts is None else contacts
    out = []
    for c in cs:
        if not c.get("email"):
            continue
        if div and c.get("division") == div:
            out.append(c)
        elif words & set(re.findall(r"[a-z]{4,}", f"{c.get('trade', '')} "
                                                  f"{c.get('type', '')}"
                                                  .lower())):
            out.append(c)
    return out
