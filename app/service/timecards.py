"""Service tech hours -> Back Office time cards (Nov 5).

Every hour a tech logs on a work order becomes a time card line for the
service job in Back Office, through the same read-only interface v1
snapshot the rest of QuantiSheet uses (app/backoffice_hook.py): one card
per logged time entry (id "svc:<entry id>"), so Back Office's own rule -
a card brought in before adds nothing - means each hour goes in once,
however often this is sent.

The service job's number and the labor cost code are settings
(service_job_number, default "SERVICE"; service_labor_code, default
blank) - Back Office then codes the lines like any time card.
"""
import datetime as dt

from .. import __version__, dmoney


def _setting(key, default):
    from .. import settings
    return settings.get(key) or default


def cards(orders, since=None, until=None, tech=None):
    """Time cards from work-order time between since and until (ISO
    dates, inclusive)."""
    code = _setting("service_labor_code", "")
    out = []
    for wo in orders.get("orders", []):
        for t in wo.get("time", []):
            d = str(t.get("date") or "")[:10]
            if not d or (since and d < since) or (until and d > until):
                continue
            if tech and t.get("tech") != tech:
                continue
            hrs = str(dmoney.D(t.get("hours") or 0))
            out.append({
                "id": f"svc:{t['id']}", "date": d,
                "foreman": t.get("tech", ""),
                "crew": [{"name": t.get("tech", ""), "class": "Service Tech",
                          "hours": hrs}],
                "equipment": [],
                "production": [{"cost_code": code, "qty": "1", "unit": "ea",
                                "hours": hrs}] if code else [],
                "note": f"{wo['number']} {wo.get('customer', '')}".strip()})
    out.sort(key=lambda c: (c["date"], c["foreman"]))
    return out


def snapshot(orders, since=None, until=None, tech=None):
    """An interface v1 snapshot holding only the service job's cards."""
    number = _setting("service_job_number", "SERVICE")
    return {"interface_version": 1,
            "source": {"app": f"QuantiSheet {__version__}",
                       "file": "service work orders", "folder": "",
                       "taken_at": dt.datetime.now().isoformat(
                           timespec="minutes")},
            "project": {"name": "Service Department", "number": number,
                        "address": "", "owner": "", "contractor": "",
                        "architect": "", "contract_no": "",
                        "contract_date": "", "state": ""},
            "cost_codes": [], "budget": [], "estimate": [], "activities": [],
            "contract": {"retainage_work": "0", "retainage_stored": "0",
                         "sov": []},
            "changes": [], "payapps": [], "commitments": [],
            "direct_costs": [], "timecards": cards(orders, since, until, tech),
            "directory": [], "daily_logs": []}


def summary(snap):
    by = {}
    for c in snap["timecards"]:
        by[c["foreman"]] = by.get(c["foreman"], dmoney.D(0)) + \
            dmoney.D(c["crew"][0]["hours"])
    return {"cards": len(snap["timecards"]),
            "hours": {k: str(v) for k, v in sorted(by.items())}}


# ---- hh2 (QuantiSheet 1.2, Nov 5) -------------------------------------------
# hh2 publishes no import format for time, so this is a mapped CSV the
# client sets up once (service_hh2_time_columns): one row per logged entry,
# each entry once (orders["hh2_time_sent"]), and a reverse file with the
# hours negated. Offline.

HH2_TIME_COLUMNS = ["Employee", "Date", "Job", "Cost Code", "Hours",
                    "Pay Type", "Note", "Entry ID"]
TIME_ROUTES = {"backoffice": "QuantiSheet Back Office",
               "hh2": "hh2 (mapped CSV)"}


def time_route():
    r = _setting("service_time_route", "backoffice")
    return r if r in TIME_ROUTES else "backoffice"


def hh2_time_columns():
    cols = _setting("service_hh2_time_columns", None) or HH2_TIME_COLUMNS
    cols = [c for c in cols if c in HH2_TIME_COLUMNS]
    return cols or list(HH2_TIME_COLUMNS)


def hh2_rows(orders, since=None, until=None, again=False):
    """(rows, held). Entries already in an hh2 file are left out unless
    again; an entry with no tech or no hours is held back."""
    done = set(orders.get("hh2_time_sent") or [])
    job = _setting("service_job_number", "SERVICE")
    code = _setting("service_labor_code", "")
    rows, held = [], []
    for c in cards(orders, since, until):
        eid = c["id"][4:]
        if eid in done and not again:
            continue
        hrs = dmoney.D(c["crew"][0]["hours"] or 0)
        if not c["foreman"] or hrs <= 0:
            held.append((c["date"], c["foreman"] or "(no tech)",
                         "no tech or no hours"))
            continue
        rows.append({"Employee": c["foreman"], "Date": c["date"],
                     "Job": job, "Cost Code": code, "Hours": str(hrs),
                     "Pay Type": "Regular", "Note": c.get("note", ""),
                     "Entry ID": eid})
    return rows, held


def hh2_csv(orders, path, since=None, until=None, again=False):
    """Write the mapped CSV and its reverse; mark the entries sent. The
    caller saves the work orders."""
    import csv
    import os
    from . import sage_ar
    rows, held = hh2_rows(orders, since, until, again)
    if not rows:
        raise ValueError("Nothing to send to hh2: " + ("; ".join(
            f"{d} {t}: {w}" for d, t, w in held) or "every hour in that "
            "week is already in an hh2 file."))
    cols = hh2_time_columns()
    base, ext = os.path.splitext(path)
    rev = f"{base} (reverse){ext or '.csv'}"
    for p, sign in ((path, 1), (rev, -1)):
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(cols)
            for r in rows:
                vals = []
                for c in cols:
                    v = r[c]
                    if c == "Hours" and sign < 0:
                        v = str(-dmoney.D(v))
                    vals.append(sage_ar._clean(v))
                w.writerow(vals)
    orders.setdefault("hh2_time_sent", []).extend(r["Entry ID"]
                                                   for r in rows)
    return {"file": path, "reverse": rev, "entries": len(rows),
            "held": held}
