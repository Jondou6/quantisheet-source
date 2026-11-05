"""Dispatch board for open work orders.

Unassigned tickets sit in one list. Each technician has the tickets
scheduled on the chosen day. Assigning sets the technician and the day.
The day sheet is a printable PDF. Dragging a ticket calls assign(); the
window does that on drop.

No network calls.
"""
import datetime as dt

from . import files


def add_tech(store, name):
    from . import workorder
    name = files.txt(name)
    if not name:
        raise workorder.WorkOrderError("Name the technician.")
    if name not in store["techs"]:
        store["techs"].append(name)
    return name


def board(store, day):
    """Unassigned open tickets, and each technician's tickets that day."""
    try:
        day = files.iso_date(day, "Day", blank_ok=False)
    except files.FileError as e:
        from . import workorder
        raise workorder.WorkOrderError(str(e)) from e
    by_tech = {t: [] for t in store.get("techs") or []}
    unassigned = []
    for wo in store["orders"]:
        if wo.get("scheduled") == day and wo.get("tech"):
            by_tech.setdefault(wo["tech"], []).append(wo)
        elif wo["status"] == "open" and (
                not wo.get("tech") or not wo.get("scheduled")):
            unassigned.append(wo)
    return {"day": day, "unassigned": unassigned, "by_tech": by_tech}


def assign(store, wo_id, tech, day):
    """Put the ticket on a technician's day, or clear both to unassign."""
    from . import workorder
    wo = workorder.get(store, wo_id)
    if wo["status"] != "open":
        raise workorder.WorkOrderError(
            "A closed ticket stays on the day it was closed.")
    tech = files.txt(tech)
    if not tech:
        wo["tech"] = ""
        wo["scheduled"] = ""
        return wo
    try:
        wo["scheduled"] = files.iso_date(day, "Day", blank_ok=False)
    except files.FileError as e:
        raise workorder.WorkOrderError(str(e)) from e
    wo["tech"] = tech
    if tech not in store["techs"]:
        store["techs"].append(tech)
    return wo


def day_sheet(store, day, path, comp=None, tech=None):
    """Print the day's tickets, one section per technician."""
    from .pdfdoc import Sheet
    info = board(store, day)
    sheet = Sheet("Day sheet", comp, subtitle=info["day"])
    names = [tech] if tech else list(info["by_tech"])
    any_row = False
    for i, name in enumerate(names, start=1):
        rows = info["by_tech"].get(name) or []
        if tech and not rows:
            continue
        any_row = any_row or bool(rows)
        sheet.section(f"{i:02d}", name or "Technician")
        if not rows:
            sheet.y += 14
            sheet.text(36, sheet.y, "Nothing scheduled.", 9)
            continue
        for wo in rows:
            sheet.need(28)
            sheet.y += 14
            sheet.text(36, sheet.y,
                       f"{wo['number']}  {wo['customer']}", 10, True)
            sheet.y += 12
            sheet.text(36, sheet.y,
                       f"{wo['site']}    {wo['complaint'][:80]}", 8)
    if info["unassigned"] and not tech:
        sheet.section("00", "Not assigned")
        for wo in info["unassigned"]:
            sheet.need(16)
            sheet.y += 14
            sheet.text(36, sheet.y,
                       f"{wo['number']}  {wo['customer']}  {wo['complaint'][:60]}",
                       9)
    if not any_row and not info["unassigned"]:
        sheet.y += 16
        sheet.text(36, sheet.y, "Nothing scheduled for this day.", 9)
    return sheet.save(path)


def today():
    return dt.date.today().isoformat()
