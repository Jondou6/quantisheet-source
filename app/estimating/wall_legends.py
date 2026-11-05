"""Wall-type assemblies (r36 v2 step 7, G1.2): one QuantiSheet assembly
per wall type in the drawing set's wall-type legend, named after the AI
Takeoff's group ("Wall Type 2A"), so the group is priced by it.

The parts are what 0.13.9's wall_assembly reads from the legend text -
studs, top & bottom track, type X board, sealant, sheets, tape, compound,
screws, and batt, furring, rigid, sheathing, vapor barrier, CMU, siding
when the legend names them - written as formulas over the measured
Length and the type's Height with 0.13.9's own take-off factors
(wall_assembly.SHEET_SF, TAPE_FT_PER_SF, COMPOUND_LB_PER_SF,
SCREWS_PER_SF, CMU_PER_SF). With every Waste % at 0 the quantities are
the ones the AI Takeoff lists for the type.

Every part costs $0 (QuantiSheet ships no prices) and carries the cost
code 0.13.9 gives the line (09 21 16, CMU 04 22 00), so a cost book of
YOUR rates prices it (Takeoff > Cost Books...). Each part has its own
Waste_<part> property, 0 until you set it.

How sure each type is:
  VERIFIED      the legend names the parts and the type's height;
  INFERRED      the height comes from the top-of-wall mark on the
                elevations (as the AI Takeoff does) or a general
                wall-height note, or a part is inferred (masonry drawn
                but CMU not named);
  NEEDS HEIGHT  no height for the type - Height is 0 until you set it.

    from_doc(doc) -> build(...) for the open drawing set's legend
    build(legend, heights, general_height) -> {"types", "unreadable",
                                               "message"}
    apply(doc, built) -> {"bound", "priced_already", "no_group"}
"""
import logging

from .. import wall_assembly as WA

log = logging.getLogger(__name__)

CODE = "09 21 16"
CMU_CODE = "04 22 00"


def _w(key):
    return f"(1+Waste_{key}/100)"


def _parts(comps):
    """[(waste key, name, unit, formula)] in wall_assembly.lines order."""
    out = []
    gwb = None
    for c in comps:
        k = c["kind"]
        if k == "studs":
            out.append(("Studs", f"{WA._frac(c['size_in'])} metal studs @ "
                        f"{c['oc_in']:g}\" OC", "LF",
                        f"(ceil(Length/(Spacing/12))+1)*Height*{_w('Studs')}"))
            out.append(("Track", f"{WA._frac(c['size_in'])} top & bottom "
                        "track", "LF", f"2*Length*{_w('Track')}"))
        elif k == "gwb":
            gwb = c
            out.append(("Board", f"{WA._frac(c['thk_in'])} type X gypsum "
                        "board", "SF", f"Length*Height*Sides*{_w('Board')}"))
            out.append(("Sealant", "sealant (top and bottom of the board)",
                        "LF", f"2*Length*Sides*{_w('Sealant')}"))
        elif k == "batt":
            out.append(("Batt", "batt insulation", "SF",
                        f"Length*Height*{_w('Batt')}"))
        elif k == "furring":
            out.append(("Furring", f"{WA._frac(c['size_in'])} metal furring "
                        "channels", "LF",
                        f"ceil(Length/2)*Height*{_w('Furring')}"))
        elif k == "rigid":
            out.append(("Rigid", f"{WA._frac(c['thk_in'])} rigid insulation",
                        "SF", f"Length*Height*{_w('Rigid')}"))
        elif k == "sheathing":
            out.append(("Sheathing", "glass mat gypsum sheathing", "SF",
                        f"Length*Height*{_w('Sheathing')}"))
        elif k == "vapor barrier":
            out.append(("Vapor_Barrier", "vapor barrier", "SF",
                        f"Length*Height*{_w('Vapor_Barrier')}"))
        elif k == "cmu":
            out.append(("CMU_Wall", f"{c['size_in']}\" CMU wall", "SF",
                        f"Length*Height*{_w('CMU_Wall')}"))
            out.append(("CMU_Block", f"{c['size_in']}\" CMU block", "EA",
                        f"ceil(Length*Height*{WA.CMU_PER_SF}*"
                        f"{_w('CMU_Block')})"))
        elif k == "siding":
            out.append(("Siding", "cement board siding", "SF",
                        f"Length*Height*{_w('Siding')}"))
    if gwb:
        sf = "Length*Height*Sides"
        out.append(("Sheets", "gypsum board 4'x8' sheets", "SHEETS",
                    f"ceil({sf}/{WA.SHEET_SF}*{_w('Sheets')})"))
        out.append(("Tape", "joint tape (500' rolls)", "ROLLS",
                    f"ceil({sf}*{WA.TAPE_FT_PER_SF}/500.0*{_w('Tape')})"))
        out.append(("Compound", "joint compound", "LB",
                    f"ceil({sf}*{WA.COMPOUND_LB_PER_SF}*{_w('Compound')})"))
        out.append(("Screws", "1-1/4\" drywall screws", "EA",
                    f"ceil({sf}*{WA.SCREWS_PER_SF}*{_w('Screws')})"))
    return out


def assembly_for(code, desc, height):
    """The assembly for wall type `code` (all prices 0, all waste 0)."""
    comps = WA.components(desc)
    props = {"Height": float(height or 0)}
    for c in comps:
        if c["kind"] == "studs":
            props["Spacing"] = float(c["oc_in"])
        if c["kind"] == "gwb":
            props["Sides"] = int(c["sides"])
    parts = []
    for key, name, unit, formula in _parts(comps):
        props[f"Waste_{key}"] = 0
        parts.append({"name": name, "unit": unit, "qty": formula,
                      "cost": 0.0, "labor": 0.0,
                      "code": CMU_CODE if "CMU" in name else CODE})
    return {"name": f"Wall Type {code}", "measure": "length",
            "trade": "Framing & Drywall", "props": props, "parts": parts,
            "source": "wall-type legend (no prices - price it from your "
                      "cost book)",
            "legend": str(desc or "")[:400]}


def build(legend, heights=None, general_height=None, plate=None):
    """Assemblies for `legend` {code: text}. Height: the type's own
    (legend / notes), else the elevations' top-of-wall mark `plate` (the
    AI Takeoff's order), else a general wall-height note."""
    heights = heights or {}
    out = {"types": [], "unreadable": [], "message": ""}
    for code in sorted(legend or {}):
        desc = legend[code]
        comps = WA.components(desc)
        if not comps:
            out["unreadable"].append(code)
            continue
        why = []
        h = heights.get(code)
        if h:
            status = "VERIFIED"
            why.append(f"height {h:g} ft from the legend")
        elif plate:
            h, status = plate, "INFERRED"
            why.append(f"height {h:.2f} ft from the top-of-wall mark on the "
                       "elevations")
        elif general_height:
            h, status = general_height, "INFERRED"
            why.append(f"height {h:g} ft from the general wall-height note")
        else:
            h, status = 0, "NEEDS HEIGHT"
            why.append("no height for this type - set Height")
        if any(c.get("inferred") for c in comps):
            if status == "VERIFIED":
                status = "INFERRED"
            why.append("masonry drawn but CMU not named - confirm the "
                       "back-up wall")
        a = assembly_for(code, desc, h)
        out["types"].append({"code": code, "name": a["name"], "desc": desc,
                             "status": status, "why": "; ".join(why),
                             "assembly": a, "parts": len(a["parts"])})
    if not out["types"]:
        out["message"] = ("no wall-type legend found in this drawing set "
                          "(a G- or A-sheet titled WALL TYPES / PARTITION "
                          "TYPES, or wall-type details)" if not legend else
                          "the wall-type legend names no studs, board or "
                          "block QuantiSheet can read")
    return out


def _read(doc, rows=None):
    """({code: legend text}, [pages], their text) with 0.13.9's reader."""
    from .. import aitakeoff
    rows = rows if rows is not None else aitakeoff.plan_set(doc)
    legend, pages = aitakeoff.wall_legend(doc, rows)
    text = "\n".join(doc[p].get_text() for p in pages)
    return legend, pages, text


def _plate(doc, rows):
    """The elevations' wall height (top-of-wall mark - floor), as the AI
    Takeoff reads it; None when there is none."""
    from .. import aitakeoff, envelope
    ep = [r["page"] for r in rows or ()
          if aitakeoff._ELEV_T.search(r.get("title") or "")]
    if not ep:
        return None
    try:
        hs = envelope.wall_heights_from_levels([doc[p] for p in ep])
    except Exception:                                     # noqa: BLE001
        log.warning("elevation wall heights unreadable", exc_info=True)
        return None
    return hs[0] if hs else None


def from_doc(doc, rows=None):
    from .. import aitakeoff
    if rows is None:
        rows = aitakeoff.plan_set(doc)
    legend, pages, text = _read(doc, rows)
    if not legend:
        out = build({})
        return dict(out, pages=[])
    hts = aitakeoff.wall_heights(legend, text)
    out = build(legend, hts.get("types") or {}, hts.get("all"),
                plate=_plate(doc, rows))
    out["pages"] = pages
    return out


def apply(doc, built, job=None):
    """Bind each type's assembly to its unpriced "Wall Type <code>"
    length group - one write (one Undo)."""
    from .. import assemblies, estimate
    from . import checks
    priced = checks.priced_groups(doc, job)
    groups = {(g["name"], g["type"], g["unit"]) for g in estimate.lines(doc)}
    ajob = assemblies.read_job(doc)
    res = {"bound": [], "priced_already": [], "no_group": []}
    for t in built.get("types") or []:
        mine = [k for k in groups if k[0] == t["name"] and k[1] == "length"]
        if not mine:
            res["no_group"].append(t["name"])
        elif all(k in priced for k in mine):
            res["priced_already"].append(t["name"])
        else:
            ajob["assemblies"][t["name"]] = t["assembly"]
            res["bound"].append(t["name"])
    if res["bound"]:
        assemblies.write_job(doc, ajob)
    return res
