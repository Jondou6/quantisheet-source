"""Default room programs by building type, and reconciling them to the
net floor area."""

# (name, type, share of the net area); the first room is the hub - every
# interior door opens onto it or onto a room that does
HOUSE_BASE = [("LIVING", "living", 0.20), ("KITCHEN", "kitchen", 0.11),
              ("DINING", "dining", 0.08), ("LAUNDRY", "laundry", 0.03),
              ("MECH", "mech", 0.02)]
OFFICE = [("OPEN OFFICE", "open_office", 0.38), ("CONFERENCE", "conference",
          0.10), ("OFFICE", "office", 0.07), ("OFFICE", "office", 0.07),
          ("BREAK ROOM", "break", 0.07), ("RESTROOM", "restroom", 0.04),
          ("RESTROOM", "restroom", 0.04), ("STORAGE", "storage", 0.04),
          ("MECH", "mech", 0.03)]
RETAIL = [("SALES", "sales", 0.62), ("STOCK", "storage", 0.16),
          ("OFFICE", "office", 0.06), ("RESTROOM", "restroom", 0.04),
          ("RESTROOM", "restroom", 0.04), ("MECH", "mech", 0.03)]

FINISHES = {
    "living": ("LVP", "WD", "GWB-PT", "GWB-PT"),
    "kitchen": ("LVP", "WD", "GWB-PT", "GWB-PT"),
    "dining": ("LVP", "WD", "GWB-PT", "GWB-PT"),
    "bed": ("CPT", "WD", "GWB-PT", "GWB-PT"),
    "bath": ("CT", "CT", "GWB-MR", "GWB-PT"),
    "laundry": ("LVP", "WD", "GWB-PT", "GWB-PT"),
    "mech": ("SC", "RB", "GWB", "EXP"),
    "open_office": ("CPT-T", "RB", "GWB-PT", "ACT"),
    "conference": ("CPT-T", "RB", "GWB-PT", "ACT"),
    "office": ("CPT-T", "RB", "GWB-PT", "ACT"),
    "break": ("LVT", "RB", "GWB-PT", "ACT"),
    "restroom": ("CT", "CT", "GWB-MR", "GWB-PT"),
    "storage": ("SC", "RB", "GWB-PT", "EXP"),
    "sales": ("LVT", "RB", "GWB-PT", "ACT"),
    "hall": ("LVP", "WD", "GWB-PT", "GWB-PT"),
    "stair": ("LVP", "WD", "GWB-PT", "GWB-PT"),
    # warehouse / industrial (types/warehouse.py)
    "lobby": ("LVT", "RB", "GWB-PT", "ACT"),
    "riser": ("SC", "RB", "GWB", "EXP"),
    "warehouse": ("SC", "-", "EXP", "EXP"),
    "industrial": ("SC", "-", "EXP", "EXP"),
    # restaurant (types/restaurant.py) - all assumed, health department
    # rules decide (cleanable floors, walls and ceilings in the kitchen)
    # (the dining room is type "dining", its finishes set there)
    "kitchen_comm": ("QT", "QT", "FRP", "ACT-V"),
    "prep": ("QT", "QT", "FRP", "ACT-V"),
    "dish": ("QT", "QT", "FRP", "ACT-V"),
    "drive_thru": ("QT", "QT", "FRP", "ACT-V"),
    "walkin": ("MFR", "-", "MFR", "MFR"),
    "dry_storage": ("SC", "RB", "FRP", "ACT-V"),
}


def default_program(building_type, occupancy="", beds=3, baths=2):
    """[{name, type, share}] for the building type."""
    if building_type == "single_family":
        beds = max(1, min(6, int(beds or 3)))
        baths = max(1, min(4, int(baths or 2)))
        rooms = list(HOUSE_BASE)
        rooms.insert(3, ("PRIMARY BEDROOM", "bed", 0.14))
        for i in range(2, beds + 1):
            rooms.append((f"BEDROOM {i}", "bed", 0.10))
        for i in range(1, baths + 1):
            rooms.append(("BATH" if baths == 1 else f"BATH {i}", "bath",
                          0.05))
    elif (occupancy or "").upper().startswith("M"):
        rooms = list(RETAIL)
    else:
        rooms = list(OFFICE)
    out, seen = [], {}
    for name, kind, share in rooms:
        seen[name] = seen.get(name, 0) + 1
        out.append({"name": name, "type": kind, "share": share})
    # number repeated names (OFFICE 1, OFFICE 2)
    count = {}
    for r in out:
        if seen[r["name"]] > 1:
            count[r["name"]] = count.get(r["name"], 0) + 1
            r["name"] = f"{r['name']} {count[r['name']]}"
    return out


def reconcile(program, net_sf):
    """Target SF for each room so they add up to the net area. Rooms the
    brief gave a size keep their proportion; the rest share by their
    default share. Returns (program with "target_sf", warnings)."""
    total_share = sum(r["share"] for r in program) or 1.0
    given = [r for r in program if r.get("target_sf")]
    warnings = []
    if given:                            # sizes came from the brief
        rest = [r for r in program if not r.get("target_sf")]
        for r in rest:
            r["target_sf"] = net_sf * r["share"] / total_share
        program_sf = sum(r["target_sf"] for r in program)
        f = net_sf / program_sf
        if abs(program_sf - net_sf) / net_sf > 0.03:
            given_sf = sum(r["target_sf"] for r in given)
            warnings.append(
                f"Program total {program_sf:,.0f} SF (rooms the brief "
                f"sized: {given_sf:,.0f} SF) "
                f"{'exceeds' if program_sf > net_sf else 'is under'} net "
                f"area {net_sf:,.0f} SF; rooms scaled {f:.2f}.")
        for r in program:
            r["target_sf"] = round(r["target_sf"] * f, 1)
    else:
        for r in program:
            r["target_sf"] = round(net_sf * r["share"] / total_share, 1)
    return program, warnings
