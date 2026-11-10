"""Tune-up planner (QuantiSheet 1.2, #7): spread the spring or fall
agreement visits of every customer over the season, by tech, at most so
many a day - sized for a small crew (works with one tech). The plan can
become planned-maintenance work orders and an .ics calendar file (saved,
never sent).

Seasons and the daily load are settings (service_season_spring /
service_season_fall as "MM-DD..MM-DD", service_tuneups_per_day)."""
import datetime as dt

from . import agreements as agr_api
from . import files

SEASONS = {"spring": "03-01..05-31", "fall": "09-01..11-30"}
PER_DAY = 4


class PlanError(ValueError):
    pass


def season_dates(name, year):
    from .. import settings
    spec = settings.get(f"service_season_{name}") or SEASONS.get(name)
    if not spec:
        raise PlanError("Spring or fall.")
    try:
        a, b = spec.split("..")
        start = dt.date.fromisoformat(f"{year}-{a}")
        end = dt.date.fromisoformat(f"{year}-{b}")
    except ValueError:
        raise PlanError(f"The {name} season setting {spec!r} isn't MM-DD.."
                        "MM-DD.") from None
    return start, end


def per_day():
    from .. import settings
    try:
        return max(1, int(settings.get("service_tuneups_per_day") or PER_DAY))
    except (TypeError, ValueError):
        return PER_DAY


def plan(store, orders, techs, start, end, today=None, cap=None):
    """[{date, tech, agreement_id, number, customer, site, planned}] -
    every visit in the window that has no work order yet, on workdays,
    earliest first, spread over the techs, at most `cap` a tech a day."""
    techs = [t.strip() for t in techs if t and t.strip()]
    if not techs:
        raise PlanError("Name at least one tech.")
    today = today or dt.date.today()
    if isinstance(today, str):
        today = dt.date.fromisoformat(today)
    cap = cap or per_day()
    todo = [v for v in agr_api.visit_calendar(
        store, orders, start.isoformat(), end.isoformat(), today=today)
        if v["state"] in ("due", "upcoming") and not v["work_order_id"]]
    todo.sort(key=lambda v: (v["planned"], v["customer"].lower()))
    load = {}
    rows = []
    first = max(start, today)
    for v in todo:
        # never before the agreement's term starts
        term = dt.date.fromisoformat(agr_api.get(store, v["agreement_id"])
                                     ["start"])
        day = max(first, term)
        while True:
            if day > end:
                raise PlanError(f"{len(todo) - len(rows)} visit(s) don't fit "
                                f"by {end} - add a tech or raise the daily "
                                "load.")
            if day.weekday() < 5:
                free = [t for t in techs if load.get((day, t), 0) < cap]
                if free:
                    t = min(free, key=lambda x: (load.get((day, x), 0),
                                                 techs.index(x)))
                    load[(day, t)] = load.get((day, t), 0) + 1
                    rows.append({"date": day.isoformat(), "tech": t,
                                 "agreement_id": v["agreement_id"],
                                 "number": v["number"],
                                 "customer": v["customer"],
                                 "site": v["site"], "planned": v["planned"]})
                    break
            day += dt.timedelta(days=1)
    return rows


def weekly_load(rows):
    """{(week starting, tech): visits}."""
    out = {}
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
        out[(wk, r["tech"])] = out.get((wk, r["tech"]), 0) + 1
    return out


def make_work_orders(store, orders, rows, records=None, today=None):
    """Planned-maintenance work orders for the plan (one per visit, never
    twice). Returns the new ids."""
    from . import workorder
    have = {(wo.get("agreement_id"), wo.get("pm_visit"))
            for wo in orders.get("orders", [])}
    made = []
    for r in rows:
        if (r["agreement_id"], r["planned"]) in have:
            continue
        agr = agr_api.get(store, r["agreement_id"])
        wid = workorder.add(
            orders, records, customer=agr["customer"], site=agr["site"],
            property_id=agr.get("property_id") or "",
            complaint=f"Planned maintenance visit ({agr['number']})",
            billing="agreement", agreement_id=agr["id"], tech=r["tech"],
            scheduled=r["date"], pm_visit=r["planned"], call_type="pm",
            when=today)
        have.add((r["agreement_id"], r["planned"]))
        made.append(wid)
    return made


def _esc(t):
    bs = chr(92)
    return (str(t).replace(bs, bs + bs).replace(";", bs + ";")
            .replace(",", bs + ",").replace("\n", bs + "n"))


def ics(rows, company="QuantiSheet"):
    """An iCalendar file (all-day events), to import into any calendar."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0",
           f"PRODID:-//{_esc(company)}//Tune-up plan//EN"]
    for r in rows:
        d = dt.date.fromisoformat(r["date"])
        out += ["BEGIN:VEVENT",
                f"UID:{r['agreement_id']}-{r['planned']}@quantisheet",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{d:%Y%m%d}",
                f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}",
                f"SUMMARY:{_esc('Tune-up ' + r['customer'] + ' (' + r['tech'] + ')')}",
                f"LOCATION:{_esc(r['site'])}",
                f"DESCRIPTION:{_esc('Agreement ' + r['number'] + ', visit planned ' + r['planned'])}",
                "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def save_ics(rows, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(ics(rows))
    return path
