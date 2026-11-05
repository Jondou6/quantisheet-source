"""General notes (a fixed template) and project notes (from the local AI
when it's running, otherwise from the template). The AI writes words only:
no code citations and no dimensions."""
import json
import logging
import re
import threading

from . import DISCLAIMER

log = logging.getLogger(__name__)
AI_TIMEOUT = 60           # seconds for one Generate Set AI call

GENERAL = [
    "These drawings are a computer-generated starting point "
    f"{DISCLAIMER}. A licensed design professional must verify all "
    "information.",
    "Do not scale drawings. Written dimensions govern; verify all "
    "dimensions and conditions in the field before starting work.",
    "Dimensions are to the face of stud or centerline of wall as shown "
    "unless noted otherwise.",
    "The contractor shall coordinate the work of all trades and report "
    "conflicts to the design professional before proceeding.",
    "All work shall comply with the codes and standards adopted by the "
    "authority having jurisdiction. Code analysis is by the design "
    "professional.",
    "Structural, mechanical, electrical, plumbing and fire protection "
    "design are by others and are not part of this set.",
    "Provide blocking in walls for all wall-hung items.",
    "Seal all penetrations through rated assemblies and the building "
    "envelope.",
    "Door and window sizes are nominal; confirm rough openings with the "
    "manufacturer.",
    "Finishes are listed on the room finish schedule; submit samples for "
    "approval.",
    "Provide clearances at doors, fixtures and equipment as required by "
    "the accessibility standards that apply.",
    "Grade shall slope away from the building on all sides.",
    "Verify all existing conditions (existing work) before demolition.",
    "Keep the site clean and dispose of debris daily.",
    "Any change to these drawings requires review by the design "
    "professional.",
]


def template_project_notes(plan):
    from . import types
    got = types.for_plan(plan).run("notes", plan, default=None)
    if got is not None:
        return list(got)
    bt = plan["project"]["building_type"]
    if bt == "single_family" and plan.get("upper"):
        st = plan["upper"]["rooms"][0].get("stair") or {}
        return ["Two-story single-family residence on a slab on grade; "
                "floor to floor 10'-0\" (wood floor framing).",
                f"Stair: {st.get('risers', 16)} risers at about "
                f"{st.get('rise_in', 7.5):.2f}\", {st.get('tread_in', 10):g}\" "
                "treads, 3'-6\" wide; guards and handrails by the design "
                "professional.",
                "Bedrooms each have an operable window; verify egress "
                "requirements.",
                "Kitchen and bath layouts are diagrammatic; fixture "
                "layouts by the design professional.",
                "Floor framing, structure and the laundry and mechanical "
                "equipment are to be confirmed."]
    if bt == "single_family":
        return ["One-story single-family residence on a slab on grade.",
                "Wood-frame exterior walls with gable roof; roof framing "
                "by others.",
                "Bedrooms each have an operable window; verify egress "
                "requirements.",
                "Kitchen and bath layouts are diagrammatic; fixture "
                "layouts by the design professional.",
                "Mechanical room size and equipment are to be confirmed."]
    return ["One-story commercial building on a slab on grade.",
            "Flat roof with parapet; roof drainage by others.",
            "Restrooms are diagrammatic; fixture counts and accessible "
            "layouts by the design professional.",
            "Tenant finishes are as scheduled unless noted otherwise.",
            "Storefront and exterior door hardware to be confirmed."]


_NO = re.compile(r"\b(seal(?:ed|ing)?|stamp(?:ed)?|certif\w*|approved|"
                 r"permit[- ]ready)\b", re.I)


def _clean(note):
    """Words only: no code citations, no dimensions or other numbers, and
    nothing that claims the set is sealed or approved (Grok N1)."""
    note = re.sub(r"\s+", " ", str(note)).strip()
    note = re.sub(r"\b(IBC|IRC|NFPA|ADA|IECC)\b(\s*[\d.()]+)*", "", note)
    if re.search(r"\d", note) or _NO.search(note):
        return ""                        # drop it rather than half-fix it
    note = re.sub(r"\s+", " ", note).replace(" ,", ",").replace(" .", ".")
    return note.strip(" .;,") + "." if note.strip(" .;,") else ""


def project_notes(plan, ask=None, timeout=AI_TIMEOUT):
    """(notes, from_ai). `ask(prompt) -> text` defaults to the local AI;
    anything that goes wrong falls back to the template."""
    from . import brief
    if ask is None and (brief.ai_busy() or not brief.ai_up()):
        return template_project_notes(plan), False
    summary = {k: plan["project"].get(k) for k in
               ("building_type", "work", "occupancy", "gross_sf_target")}
    summary["rooms"] = [r["name"] for r in plan["rooms"]]
    summary["roof"] = plan["roof"]["type"]
    prompt = ("You write short project notes for a starter construction "
              "drawing set. Return JSON {\"notes\": [...]} with at most 8 "
              "short notes. No code citations, no dimensions, no numbers. "
              "Project: " + json.dumps(summary))
    out = {}

    def run():
        try:
            if ask is not None:
                out["raw"] = ask(prompt)
            else:
                from ..ai import review
                out["raw"] = review._ollama(prompt, json_mode=True)
        except Exception as e:                            # noqa: BLE001
            out["err"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        brief._inflight.append(th)
    if th.is_alive() or "raw" not in out:
        log.info("genset notes from the template (%s)",
                 out.get("err", "timed out"))
        return template_project_notes(plan), False
    try:
        data = json.loads(out["raw"]) if isinstance(out["raw"], str) \
            else out["raw"]
        notes = [_clean(n) for n in (data.get("notes") or [])][:8]
        notes = [n for n in notes if len(n) > 8]
    except Exception:                                     # noqa: BLE001
        notes = []
    if not notes:
        return template_project_notes(plan), False
    return notes, True
