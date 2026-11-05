"""The building section (A-301), drawn from the plan JSON: Modulor has no
vertical section op (its slice is horizontal only) - workaround 2.

A transverse cut at mid-length (x = width / 2), looking west: the slab,
both exterior walls cut (poche), every interior wall that crosses the cut,
the ceiling line and the roof."""


def ridge_height(plan):
    """Top of the roof above the floor: plate + rise for a gable whose
    ridge runs along x (span = the depth), or plate + parapet for a flat
    roof. 50x32 ft, 6:12 -> plate + 8 ft. The roof sits on the top
    floor's plate."""
    from .model import top_level
    lv, roof = top_level(plan), plan["roof"]
    plate = lv["floor_elev"] + lv["plate_height"]
    if roof["type"] == "gable":
        span = plan["footprint"]["depth"] if roof.get("ridge_dir", "x") \
            == "x" else plan["footprint"]["width"]
        return plate + roof["pitch"] / 12.0 * span / 2.0
    return plate + float(roof.get("parapet") or 0)


def cut_x(plan):
    """Where the section is cut: mid-length, or through the middle of the
    stair in a two-story house (so the stair shows)."""
    st = plan["rooms"][0].get("stair") if plan.get("rooms") else None
    if st:
        return (st["rect"][0] + st["rect"][2]) / 2
    return plan["footprint"]["width"] / 2


def cut_walls(plan, xc=None):     # one floor (a level plan)
    """Walls the cut at x = xc (default W/2) passes through: [(y_center,
    thickness, kind)] - the exterior walls at y = 0 and y = depth, and
    interior walls running east-west that span the cut line."""
    W = plan["footprint"]["width"]
    xc = W / 2 if xc is None else xc
    out = []
    for w in plan["walls"]:
        if w.get("kind") == "open":                 # nothing built there
            continue
        (ax, ay), (bx, by) = w["a"], w["b"]
        if abs(ay - by) < 1e-6 and min(ax, bx) - 1e-6 <= xc <= \
                max(ax, bx) + 1e-6:
            out.append((ay, w["thickness"], w["kind"]))
    return sorted(out)


def _turned(plan):
    """The one-story plan mirrored about the diagonal (x <-> y), with the
    ridge back along x: its section is the cut across a deep house whose
    ridge runs north-south (0.12.22)."""
    sw = lambda p: [p[1], p[0]]                           # noqa: E731
    t = dict(plan)
    t["footprint"] = dict(plan["footprint"],
                          width=plan["footprint"]["depth"],
                          depth=plan["footprint"]["width"])
    t["roof"] = dict(plan["roof"], ridge_dir="x")
    t["walls"] = [dict(w, a=sw(w["a"]), b=sw(w["b"])) for w in plan["walls"]]
    t["rooms"] = [dict(r, rect=[r["rect"][1], r["rect"][0], r["rect"][3],
                                r["rect"][2]]) for r in plan["rooms"]]
    return t


def section_geometry(plan):
    """Everything A-301 draws, in section feet (u = north-south position
    from the south face, z = height). A one-story house whose ridge runs
    north-south is cut the other way - across it, through the ridge's
    gable profile - with u running west to east ("turned", "span")."""
    if plan["roof"]["type"] == "gable" and \
            plan["roof"].get("ridge_dir") == "y" and not plan.get("upper") \
            and not (plan.get("rooms") and plan["rooms"][0].get("stair")):
        geo = section_geometry(_turned(plan))
        geo["turned"] = True
        geo["span"] = plan["footprint"]["width"]
        return geo
    from .model import levels
    D = plan["footprint"]["depth"]
    lvls = levels(plan)
    lv, roof = plan["level"], plan["roof"]
    floor = lv["floor_elev"]
    top = ridge_height(plan)
    geo = {"slab": (0.0 - 0.25, D + 0.25, floor - lv["slab"], floor),
           "span": D,
           "walls": [], "ceilings": [], "floors": [], "top": top,
           "levels": [("T.O. SLAB", floor)]}
    xc = cut_x(plan)
    geo["cut_x"] = xc
    st = plan["rooms"][0].get("stair") if plan.get("rooms") else None
    for i, lp in enumerate(lvls):
        l_ = lp["level"]
        f0 = l_["floor_elev"]
        plate = f0 + l_["plate_height"]
        ceiling = min([r.get("ceiling_ht", l_["plate_height"])
                       for r in lp["rooms"]] or [l_["plate_height"]])
        geo["walls"] += [(y - t / 2, y + t / 2, f0, plate, kind)
                         for y, t, kind in cut_walls(lp, xc)]
        geo["ceilings"].append(f0 + ceiling)
        if i:
            # the floor framing between the floors, and the exterior
            # walls carried past it
            below = lvls[i - 1]["level"]
            pb = below["floor_elev"] + below["plate_height"]
            if st:            # the stairwell: no floor over the run
                sy0, sy1 = st["rect"][1], st["rect"][3]
                geo["floors"] += [(0.0, sy0, pb, f0), (sy1, D, pb, f0)]
            else:
                geo["floors"].append((0.0, D, pb, f0))
            geo["walls"] += [(-0.25, 0.25, pb, f0, "exterior"),
                             (D - 0.25, D + 0.25, pb, f0, "exterior")]
            geo["levels"].append((f"LEVEL {i + 1}", f0))
        geo["levels"].append(("PLATE" if len(lvls) == 1 else
                              f"PLATE L{i + 1}", plate))
    if st:
        # the stair in profile: up from the bottom, riser by riser
        sy0, sy1 = st["rect"][1], st["rect"][3]
        rise, tread = st["rise_in"] / 12.0, st["tread_in"] / 12.0
        up = st.get("dir", "N") == "N"
        u = sy0 if up else sy1
        z = floor
        pts = [(u, z)]
        for k in range(st["risers"]):
            z += rise
            pts.append((u, z))
            if k < st["risers"] - 1:
                u += tread if up else -tread
                pts.append((u, z))
        geo["stair"] = pts
    plate = geo["levels"][-1][1]
    geo["plate"] = plate
    geo["ceiling"] = geo["ceilings"][0]
    if roof["type"] == "gable" and roof.get("ridge_dir") == "y":
        # the ridge runs north-south, along the cut: the roof shows as a
        # level line at its height over the cut, from rake to rake, and
        # the gable-end walls rise to it
        ov = float(roof.get("overhang") or 0)
        W = plan["footprint"]["width"]
        zc = plate + roof["pitch"] / 12.0 * min(xc, W - xc)
        geo["roof"] = [(-ov, zc), (D + ov, zc)]
        geo["walls"] += [(-0.25, 0.25, plate, zc, "exterior"),
                         (D - 0.25, D + 0.25, plate, zc, "exterior")]
        if top - zc > 0.25:          # the ridge, seen beyond the cut
            geo["ridge_beyond"] = [(-ov, top), (D + ov, top)]
        geo["levels"].append(("RIDGE", top))
    elif roof["type"] == "gable":
        ov = float(roof.get("overhang") or 0)
        rise_ov = roof["pitch"] / 12.0 * ov
        geo["roof"] = [(-ov, plate - rise_ov), (D / 2, top),
                       (D + ov, plate - rise_ov)]
        geo["levels"].append(("RIDGE", top))
    else:
        geo["roof"] = [(0.0, plate), (D, plate)]
        geo["parapet"] = top
        geo["levels"].append(("T.O. PARAPET", top))
    return geo
