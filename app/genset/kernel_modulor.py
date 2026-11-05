"""Plan JSON -> Modulor: the drafting kernel for the floor plan and the
elevations (v1, locked by Jon, Oct 19 2026).

Modulor builds every wall (thickness, height), cuts every door and window
into it, and adds the rooms. From it we take:
  * the floor plan's wall outlines (all walls merged, openings cut);
  * each face's elevation outline - that face's walls projected on their
    own, so the openings come through as holes (projecting the whole
    building at once fills them in with the wall behind).

Modulor's own room labels print m2; we never use them - room tags are
drawn from the plan's ft2 (workaround 1 in the plan).
"""
import logging

log = logging.getLogger(__name__)


class KernelMissing(RuntimeError):
    """Modulor isn't installed - Generate Set can't run without it."""


def _modulor():
    try:
        import modulor                                    # noqa: F401
        from modulor import Cad, shapes                   # noqa: F401
        return modulor
    except Exception as e:                                # noqa: BLE001
        raise KernelMissing(
            "Generate Set requires Modulor (the drawing engine). It isn't "
            "installed in this copy of QuantiSheet; reinstall QuantiSheet to "
            f"get it back. ({e})")


def version():
    return _modulor().__version__


def ops(plan):
    """The Modulor op list for the plan (also saved in the sidecar)."""
    lv = plan["level"]
    out = [{"op": "set_units", "units": "ft"}]
    for w in plan["walls"]:
        if w.get("kind") == "open":      # one space: nothing is built
            continue
        out.append({"op": "add_wall", "path": [w["a"], w["b"]],
                    "thickness": w["thickness"], "height": lv["plate_height"],
                    "tag": "face_" + w["face"] if w.get("face") else
                    "interior", "_id": w["id"]})
    for o in plan["openings"]:
        if o["kind"] in ("door", "overhead"):
            sill, head = 0.0, o["height"]
        else:
            sill, head = o["sill"], o["sill"] + o["height"]
        # an overhead door is a door opening to Modulor
        out.append({"op": "add_opening", "_wall": o["wall"],
                    "along": o["along"], "width": o["width"],
                    "type": "door" if o["kind"] == "overhead" else
                    o["kind"], "sill": sill, "head": head})
    for r in plan["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        out.append({"op": "add_room", "name": r["name"],
                    "level": lv.get("name", "L1"),
                    "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]})
    return out


class Model:
    """The building in Modulor, with the outlines the sheets need."""

    def __init__(self, plan):
        mod = _modulor()
        from modulor import Cad
        self.plan = plan
        self.version = mod.__version__
        self.cad = Cad(units="ft")
        self.wall_ids = {}
        for cmd in ops(plan):
            cmd = dict(cmd)
            wid = cmd.pop("_id", None)
            wall = cmd.pop("_wall", None)
            if wall is not None:
                cmd["wall"] = self.wall_ids[wall]
            op = cmd.pop("op")
            res = self.cad(op, **cmd)
            if wid:
                self.wall_ids[wid] = res["created"][0]

    def _ent(self, wid):
        return self.cad.doc.entities[self.wall_ids[wid]]

    def plan_outline(self):
        """The walls in plan, merged, openings cut: polygons (outer
        boundaries and holes - fill even-odd) in plan feet."""
        from modulor import shapes
        total = None
        for w in self.plan["walls"]:
            if w["id"] not in self.wall_ids:          # an open wall
                continue
            cs = shapes.wall_footprint(self.cad.doc, self._ent(w["id"]))
            total = cs if total is None else total + cs
        return [[(float(x), float(y)) for x, y in poly]
                for poly in total.to_polygons()] if total is not None else []

    def elevation(self, face):
        """The face's walls as seen from outside: polygons in (across, up)
        feet, `across` running left to right as you face the building."""
        W = self.plan["footprint"]["width"]
        D = self.plan["footprint"]["depth"]
        axis = "y" if face in ("S", "N") else "x"
        res = self.cad("project", select={"tags": ["face_" + face]},
                       axis=axis, layer="elevation")
        polys = []
        for eid in res.get("created", []):
            for c in self.cad.doc.entities[eid].get("contours", []):
                pts = []
                for u, z in c:
                    u = float(u)
                    if face == "N":
                        u = W - u          # seen from the north
                    elif face == "W":
                        u = D - u          # seen from the west
                    pts.append((u, float(z)))
                polys.append(pts)
            self.cad("delete", select=eid) if "delete" in _registry() \
                else None
        return polys


def _registry():
    try:
        from modulor.ops import REGISTRY
        return REGISTRY
    except Exception:                                     # noqa: BLE001
        return {}
