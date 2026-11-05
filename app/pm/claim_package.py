"""Schedule claim package (Gantt Chart > More > Claim Package…).

One PDF that puts the schedule record in front of an insurer, a claims
consultant or the owner's reviewer, in the order they look for it:

  1. Where the job stands - the completion date used (the contract
     completion date from Project settings, else the baseline finish -
     labelled which; the DCMA CPLI uses the same one), forecast, workdays
     behind, the notice period, and whether the update record is intact
     (schedule_record.verify: every saved update is fingerprinted and
     chained, and the chain's head is anchored, so a later edit shows).
  2. Schedule updates - each saved update (baseline, monthly updates,
     recovery plans) with its data date and forecast finish, and what
     changed between updates: finish movement, logic and duration changes,
     critical path changes and - flagged - actual dates changed after the
     fact (schedule_record.compare).
  3. Delay events - the Delay Log with cause, responsibility, notice
     (late notice flagged; the contract governs), days requested / granted
     and each event's time impact analysis (schedule_record.tia).
  4. Concurrency - owner and contractor delays whose windows overlap.
  5. Windows analysis - forecast finish movement per update window and
     the delay events that fall in each.
  6. Recovery plans applied - from the Recovery Schedule history.
  7. Schedule quality - the DCMA 14-point check (schedule_check).
  8. Planned vs actual for the critical work.
  9. Fingerprints - every update's hash and the recorded head (count +
     last hash), so a copy can be checked.

Nothing here decides entitlement: the package presents the record and the
analysis; the contract and the reviewer decide. Letter portrait, built
with report._Doc.
"""
import datetime as _dt

from . import recovery, schedule, schedule_check, schedule_record

DISCLAIMER = ("Prepared from the project's schedule records in QuantiSheet. "
              "The analysis shows the schedule effect of each event on the "
              "update before it; entitlement to time or money is decided "
              "under the contract.")


def _d(v):
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _when(v):
    d = _d(v)
    return f"{d:%m/%d/%Y}" if d else "-"


def _short(v):
    d = _d(v)
    return f"{d.month}/{d.day}/{d:%y}" if d else "-"


def _days(n, unit="workday"):
    if n is None:
        return "-"
    return f"{n:+d} {unit}{'s' if abs(n) != 1 else ''}"


def completion_text(g):
    """'12/31/2026 (contract)' - the date section 1 and the CPLI measure
    against, and which one it is."""
    t = g.get("completion")
    if not t:
        return "Not set - enter the contract completion date in Project " \
            "settings"
    return f"{_when(t)} ({g.get('completion_source') or 'target'})"


def record_text(g):
    if g["intact"]:
        return "CHECK: " + "; ".join(g["intact"][:3])
    text = "Intact - every saved update matches its fingerprint"
    if g.get("intact_notes"):
        text += ". " + " ".join(g["intact_notes"])
    return text


def quality_measure(q, it):
    """The DCMA table's measure; CPLI also names its date and source."""
    m = str(it.get("metric") or "")
    if it.get("key") == "cpli" and q.get("target"):
        m += (f" (against {_when(q['target'])}, "
              f"{q.get('target_kind') or 'target'})")
    return m


def gather(store, today=None):
    """Everything the package prints, as data (tests read this)."""
    today = _d(today) or _dt.date.today()
    cpm = schedule.compute(store, schedule.data_date(store))
    stand = recovery.standing(store, None, cpm)
    log = schedule_record.updates(store)
    changes = [schedule_record.compare(a, b) for a, b in zip(log, log[1:])]
    delays = [r for r in store.list("delay")
              if r.get("status") != "Withdrawn"]
    delays.sort(key=lambda r: str(r.get("event_start") or ""))
    tias = {}
    for r in delays:
        try:
            tias[r["_id"]] = schedule_record.tia(store, r)
        except Exception as e:                      # noqa: BLE001
            tias[r["_id"]] = {"error": str(e)}
    notices = {r["_id"]: schedule_record.notice_late(store, r, today)
               for r in delays}
    terms = recovery.contract_terms(store)
    return {
        "today": today, "cpm": cpm, "standing": stand, "updates": log,
        "completion": stand.get("target"),
        "completion_source": stand.get("target_source") or "",
        "notice_days": terms["notice_days"],
        "intact": schedule_record.verify(store),
        "intact_notes": schedule_record.verify_notes(store),
        "anchor": schedule_record.anchor(store), "changes": changes,
        "delays": delays, "tia": tias, "notice": notices,
        "concurrency": schedule_record.concurrency(store),
        "windows": schedule_record.windows(store),
        "recovery": [h for h in store.setting(recovery.HISTORY) or []],
        "quality": schedule_check.check(store, today),
    }


def export_pdf(store, path, today=None):
    from . import report
    g = gather(store, today)
    st, cpm = g["standing"], g["cpm"]
    d = report._Doc("Schedule Claim Package", store.name,
                    f"Data date {_when(schedule.data_date(store))}  |  "
                    f"Prepared {_when(g['today'])}")
    d.text(DISCLAIMER, size=8.5, color=report.MUTED)
    # 1. standing
    d.heading("1. Where the job stands")
    behind = st.get("behind")
    d.grid([("Completion date used", completion_text(g)),
            ("Forecast completion", _when(st.get("forecast"))),
            ("Behind / ahead", "No target date set" if behind is None else
             ("On time" if behind <= 0 else f"{behind} workday(s) behind")),
            ("Notice period", f"{g['notice_days']} calendar days"),
            ("Update record", record_text(g))], cols=2)
    # 2. updates
    d.heading("2. Schedule updates")
    if g["updates"]:
        d.table(["No.", "Kind", "Saved", "By", "Data date", "Forecast "
                 "finish", "Note"],
                [[str(u.get("n")), u.get("kind", ""),
                  str(u.get("taken", ""))[:16].replace("T", " "),
                  str(u.get("by") or ""), _when(u.get("data_date")),
                  _when(u.get("finish")), (u.get("note") or "")[:60]]
                 for u in g["updates"]],
                [0.5, 0.9, 1.4, 1.1, 1.0, 1.1, 2.6])
    else:
        d.text("No schedule updates saved yet. Use Gantt Chart > More > "
               "Save Schedule Update at each monthly update - a claim "
               "relies on the updates made at the time.",
               color=report.MUTED)
    for c in g["changes"]:
        line = (f"Update {c['from']} to {c['to']}: finish "
                f"{_when(c['finish_before'])} to {_when(c['finish_after'])}"
                f" ({_days(c.get('finish_workdays'))})")
        bits = []
        if c.get("added"):
            bits.append(f"{len(c['added'])} added")
        if c.get("removed"):
            bits.append(f"{len(c['removed'])} removed")
        if c.get("durations"):
            bits.append(f"{len(c['durations'])} duration change(s)")
        if c.get("logic"):
            bits.append(f"{len(c['logic'])} logic change(s)")
        if c.get("critical_entered") or c.get("critical_left"):
            bits.append("critical path changed")
        d.text(line + (" - " + ", ".join(bits) if bits else ""), size=8.5)
        for flag in c.get("red_flags") or []:
            d.text("FLAG: " + str(flag), size=8.5, color=(0.75, 0.1, 0.1))
    # 3. delays
    d.heading("3. Delay events and time impact")
    if g["delays"]:
        rows = []
        for r in g["delays"]:
            t = g["tia"].get(r["_id"]) or {}
            n = g["notice"].get(r["_id"]) or {}
            rows.append([
                r.get("_no", ""), (r.get("title") or "")[:40],
                r.get("cause", ""), r.get("responsibility", ""),
                f"{_short(r.get('event_start'))} - "
                f"{_short(r.get('event_end'))}",
                (_short(r.get("notice_date")) +
                 (" LATE" if n.get("late") else "")),
                "err" if t.get("error") else
                _days(t.get("impact_workdays")),
                f"{r.get('days_requested') or '-'} / "
                f"{r.get('days_granted') or '-'}",
                r.get("status", "")])
        d.table(["No.", "Event", "Cause", "Party", "Dates",
                 "Notice", "Impact", "Days asked / got", "Status"], rows,
                [0.6, 1.6, 1.4, 1.0, 1.5, 1.1, 0.9, 1.4, 0.9])
        for r in g["delays"]:
            t = g["tia"].get(r["_id"]) or {}
            if t.get("error"):
                d.text(f"{r.get('_no')}: analysis could not run - "
                       f"{t['error']}", size=8.5, color=(0.75, 0.1, 0.1))
                continue
            d.text(f"{r.get('_no')} {r.get('title', '')}: finish "
                   f"{_when(t.get('finish_before'))} to "
                   f"{_when(t.get('finish_after'))} "
                   f"({_days(t.get('impact_workdays'))}, "
                   f"{_days(t.get('impact_calendar_days'), 'calendar day')})"
                   + ("; the event's work is on the critical path" if
                      t.get("fragnet_on_critical") else "")
                   + ". " + " ".join(t.get("notes") or [])[:300],
                   size=8.5)
        late = [r for r in g["delays"]
                if (g["notice"].get(r["_id"]) or {}).get("late")]
        if late:
            d.text("Notice given later than the setting's "
                   f"{(g['notice'][late[0]['_id']] or {}).get('limit')} "
                   "days for: " + ", ".join(r.get("_no", "") for r in late)
                   + ". The contract's notice clause governs.",
                   size=8.5, color=(0.75, 0.1, 0.1))
    else:
        d.text("No delay events in the Delay Log.", color=report.MUTED)
    # 4. concurrency
    d.heading("4. Concurrent delays")
    if g["concurrency"]:
        d.table(["Owner event", "Contractor event", "Overlap",
                 "Days"],
                [[str(c.get("owner")), str(c.get("contractor")),
                  f"{_when(c.get('start'))}-{_when(c.get('end'))}",
                  str(c.get("days"))] for c in g["concurrency"]],
                [1.5, 1.5, 2.0, 0.6])
    else:
        d.text("No overlapping owner and contractor delays.",
               color=report.MUTED)
    # 5. windows
    d.heading("5. Windows analysis")
    if g["windows"]:
        d.table(["Window", "From", "To", "Finish before", "Finish after",
                 "Change", "Events in window"],
                [[f"{w['from']}-{w['to']}", _when(w["start"]),
                  _when(w["end"]), _when(w["finish_before"]),
                  _when(w["finish_after"]), _days(w.get("workdays")),
                  ", ".join(w.get("events") or []) or "-"]
                 for w in g["windows"]],
                [0.8, 1.0, 1.0, 1.1, 1.1, 1.1, 2.0])
    else:
        d.text("Needs at least two saved updates.", color=report.MUTED)
    # 6. recovery
    d.heading("6. Recovery plans")
    if g["recovery"]:
        d.table(["Applied", "Cause", "Target", "Steps", "Reverted"],
                [[_when(h.get("applied")),
                  recovery.CAUSE_LABEL.get(h.get("cause"), "") or "-",
                  _when(h.get("target")), str(len(h.get("steps") or [])),
                  "yes" if h.get("reverted") else ""]
                 for h in g["recovery"]], [1.0, 2.0, 1.0, 0.6, 0.8])
    else:
        d.text("No recovery plan applied.", color=report.MUTED)
    # 7. quality
    q = g["quality"]
    d.heading("7. Schedule quality (DCMA 14-point)")
    d.text(q.get("summary", ""), size=8.5)
    d.table(["#", "Point", "Result", "Measure"],
            [[str(i + 1), it["name"],
              {True: "Pass", False: "FAIL", None: "n/a"}[it["passed"]],
              quality_measure(q, it)]
             for i, it in enumerate(q["items"])], [0.4, 2.2, 0.7, 3.0])
    # 8. planned vs actual
    d.heading("8. Planned vs actual - critical work")
    rows = []
    for r in cpm["rows"]:
        if r.get("summary") or not r.get("critical"):
            continue
        var = schedule.variance(r, cpm.get("cal"))
        rows.append([r.get("_no", ""), (r.get("name") or "")[:40],
                     _when(r.get("baseline_start")),
                     _when(r.get("baseline_finish")),
                     _when(r.get("actual_start") or r["es"]),
                     _when(r.get("actual_finish") or r["ef"]),
                     "-" if var is None else _days(var)])
    if rows:
        d.table(["No.", "Activity", "Baseline start", "Baseline finish",
                 "Start (act./fcst)", "Finish (act./fcst)",
                 "Variance"], rows[:80], [0.6, 2.0, 1.0, 1.0, 1.2, 1.2,
                                          0.9])
    else:
        d.text("No critical activities.", color=report.MUTED)
    # 9. fingerprints
    d.heading("9. Update fingerprints (SHA-256)")
    if g["updates"]:
        for u in g["updates"]:
            d.text(f"Update {u.get('n')}  {u.get('hash', '')}", size=7.5,
                   font="cour")
        a = g.get("anchor")
        if a:
            n = a.get("count")
            d.text(f"Recorded head: {n} update{'' if n == 1 else 's'}, "
                   f"last {a.get('head', '')}", size=7.5, font="cour")
            d.text(f"Keep this page: any later copy of the record must "
                   f"still hold update {n} with this hash.", size=8,
                   color=report.MUTED)
        else:
            d.text("Recorded head: not anchored yet - the next saved "
                   "update anchors the record.", size=8,
                   color=report.MUTED)
    else:
        d.text("None saved.", color=report.MUTED)
    return d.finish(path)
