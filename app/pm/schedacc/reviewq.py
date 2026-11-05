"""Review queue. Each activity says where it came from.

Confirming a row can write the duration back onto the company template
slot so the next job of that type starts from what the person accepted.
"""
from . import templates


def queue(doc):
    rows = []
    for a in doc.get("activities") or ():
        rows.append({
            "code": a.get("code"),
            "name": a.get("name"),
            "needs_confirm": a.get("duration_kind") != "computed"
            or bool(a.get("citations")) or not a.get("confirmed"),
            "confirmed": bool(a.get("confirmed")),
            "provenance": {
                "spec": list(a.get("citations") or []),
                "takeoff_items": list(a.get("takeoff_ids") or []),
                "template_slot": a.get("template_slot") or a.get("slot") or "",
                "duration": a.get("duration_kind") or "estimated",
                "basis": a.get("basis") or "",
                "human_edited": bool(a.get("human_edited")),
                "why": a.get("why") or "",
                "calendar": a.get("calendar") or "",
                "float_days": a.get("total_float_days"),
                "critical": bool(a.get("critical")),
                "longest_path": bool(a.get("longest_path")),
            },
        })
    doc["review"] = rows
    return rows


def confirm(doc, code, template_dir=None, changes=None):
    """Mark one activity confirmed. ``changes`` may set days or a name.

    When the activity came from a template slot and a template directory
    is given, the slot is updated so the next schedule uses the confirmed
    duration.
    """
    act = next((a for a in doc.get("activities") or () if a.get("code") == code),
               None)
    if act is None:
        raise KeyError(code)
    changes = dict(changes or {})
    if "days" in changes:
        from .durations import set_hours
        set_hours(act, changes["days"], doc)
        act["duration_kind"] = "estimated"
        act["basis"] = "edited by hand, estimated until a quantity supports it"
        act["human_edited"] = True
    if changes.get("name"):
        act["name"] = changes["name"]
        act["human_edited"] = True
    act["confirmed"] = True
    slot = act.get("template_slot") or ""
    if template_dir and slot and "days" in changes:
        templates.update_slot(template_dir, slot, {"days": changes["days"]})
    queue(doc)
    return act
