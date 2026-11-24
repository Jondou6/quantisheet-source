"""A bidder's qualification at a glance (Nov 11): insurance, license,
bonding against this bid, prequalification - read from the Company
Directory, the one place they are kept (the same data the "insurance
expired" flag on an invitation uses).

badges(contact, bid) gives one small badge per subject; award_warnings()
gives the ones that should stop an award until someone overrides them
with a reason. The bond check is the single-job limit only (Jon, Nov 11).

Pure Python, no Qt.
"""
import datetime as _dt

from . import subdir

OK, WARN, BAD, NONE = "ok", "warn", "bad", "none"
SOON_DAYS = 30
COLORS = {OK: "#cdf0cd", WARN: "#ffe1aa", BAD: "#ffcdcd", NONE: "#e6e6e6"}


def find(company, contacts=None):
    """The directory entry for a bidder's name, or None."""
    key = subdir._company_key(company)
    if not key:
        return None
    for c in (subdir.load() if contacts is None else contacts):
        if subdir._company_key(c.get("company")) == key:
            return c
    return None


def _expiry(c, key, what, today, soon):
    d = subdir._date(c.get(key))
    if d is None:
        return None
    if d < today:
        return {"key": what.lower(), "state": BAD, "short": f"{what} expired",
                "text": f"{what} expired {d.isoformat()}"}
    if d <= soon:
        return {"key": what.lower(), "state": WARN,
                "short": f"{what} expiring",
                "text": f"{what} expires {d.isoformat()}"}
    return {"key": what.lower(), "state": OK, "short": f"{what} OK",
            "text": f"{what} good until {d.isoformat()}"}


def badges(contact, bid=None, today=None):
    """[{"key", "state", "short", "text"}] for insurance, license, bond
    and prequal. `bid`: this bidder's amount in dollars (None: not
    known). A bidder who isn't in the directory gets one grey badge."""
    today = today or _dt.date.today()
    soon = today + _dt.timedelta(days=SOON_DAYS)
    if not contact:
        return [{"key": "directory", "state": NONE, "short": "Not in directory",
                 "text": "Not in the Company Directory: no insurance, "
                         "license, bonding or prequalification on file"}]
    out = []
    out.append(_expiry(contact, "insurance_exp", "Insurance", today, soon) or
               {"key": "insurance", "state": NONE, "short": "No insurance date",
                "text": "No insurance expiry date on file"})
    lic = _expiry(contact, "license_exp", "License", today, soon)
    if lic is None:
        has = str(contact.get("license") or "").strip()
        lic = {"key": "license", "state": OK if has else NONE,
               "short": "License on file" if has else "No license",
               "text": (f"License {has} on file (no expiry date entered)"
                        if has else "No license on file")}
    out.append(lic)
    lim = subdir._money(contact.get("bond_limit"))
    if not lim:
        out.append({"key": "bond", "state": NONE, "short": "No bond limit",
                    "text": "No bonding limit on file"})
    elif bid is not None and bid > lim:
        out.append({"key": "bond", "state": BAD, "short": "Over bond limit",
                    "text": f"Bid ${bid:,.0f} is over the bonding limit "
                            f"${lim:,.0f} (single job)"})
    else:
        out.append({"key": "bond", "state": OK, "short": "Bond OK",
                    "text": f"Bonding limit ${lim:,.0f} (single job)"})
    st = subdir.prequal_status(contact, today)
    plim = subdir._money(contact.get("prequal_limit"))
    if st == "Approved" and bid is not None and plim and bid > plim:
        out.append({"key": "prequal", "state": BAD, "short": "Over approved limit",
                    "text": f"Bid ${bid:,.0f} is over the prequalified "
                            f"limit ${plim:,.0f}"})
    else:
        out.append({"key": "prequal",
                    "state": {"Approved": OK, "Expired": BAD,
                              "Rejected": BAD, "Sent": WARN,
                              "Pending": WARN}.get(st, NONE),
                    "short": "Prequal " + st.lower() if st !=
                    "Not prequalified" else "Not prequalified",
                    "text": "Prequalification: " + st})
    return out


def worst(bs):
    order = [NONE, OK, WARN, BAD]
    return max((b["state"] for b in bs), key=order.index, default=NONE)


def summary(bs):
    """One line for a tooltip or a report cell."""
    return "; ".join(b["text"] for b in bs)


def short(bs):
    """What to show in a small cell: the problems, or "Qualified"."""
    bad = [b["short"] for b in bs if b["state"] in (BAD, WARN)]
    if bad:
        return ", ".join(bad)
    if all(b["state"] == NONE for b in bs):
        return bs[0]["short"] if len(bs) == 1 else "Nothing on file"
    return "Qualified"


def award_warnings(contact, bid=None, today=None):
    """What should stop an award: expired insurance or license, a bid over
    the bonding limit or the prequalified limit. [text]."""
    if not contact:
        return []
    return [b["text"] for b in badges(contact, bid, today)
            if b["state"] == BAD and (
                b["key"] in ("insurance", "license", "bond") or
                b["short"] == "Over approved limit")]


def override(company, warnings, reason, who="", when=None):
    """The record kept on an award made in spite of warnings. A reason is
    required."""
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Give a reason to award in spite of the warning.")
    return {"company": str(company or ""), "warnings": list(warnings),
            "reason": reason, "by": str(who or ""),
            "at": (when or _dt.datetime.now()).isoformat(timespec="seconds")}


def html(pairs):
    """One line of badges for a window: [(bidder name, badges)]. The text
    says the state; the colour only repeats it."""
    import html as _h
    out = []
    for name, bs in pairs:
        st = worst(bs)
        out.append(f"<span title=\"{_h.escape(summary(bs))}\">"
                   f"{_h.escape(name)}: <span style='background:"
                   f"{COLORS[st]};color:#111'>&nbsp;{_h.escape(short(bs))}"
                   "&nbsp;</span></span>")
    return "<b>Qualification:</b> " + " &nbsp; ".join(out) if out else ""
