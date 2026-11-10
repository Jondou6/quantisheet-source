"""A permanent practice job for a first 10-minute takeoff.

The plan set, the sample estimate, and the export stay in one sandbox
folder. Job files are written only there. The step the user reached is
the one record kept in settings, so the walkthrough can resume.

The sheets are the made-up clinic in app/practice.py. This module does
not draw a second set.
"""
import json
import os

from . import practice
from . import settings
from .dmoney import c2 as _c2

SANDBOX_NAME = "practice-job"
PLAN_NAME = "practice-plan.pdf"
ESTIMATE_NAME = "practice-estimate.json"
EXPORT_NAME = "practice-estimate.csv"
SETTINGS_KEY = "practice_job_step"

# Sheet A-101 in practice.floor_plan. The south exterior wall's outside
# face runs from x=0 to x=60 feet. practice._p places that origin at
# (120, 120) points.
SOUTH_WALL_FT = 60.0
_PLAN_ORIGIN = (120.0, 120.0)
SCALE_NAME = '1/4" = 1\'-0"'
SCALE_UNIT = "ft"
# Made-up unit price for the walkthrough. Not a real bid number.
UNIT_COST = 18.75
WALL_NAME = "South Exterior Wall"

_USER_FOLDERS = {"documents", "desktop", "downloads", "onedrive",
                 "pictures", "videos", "music"}


class SandboxError(ValueError):
    """A practice-job path was outside the sandbox folder."""


def known_scale():
    """The scale practice.make stores on the drawing sheets."""
    return {"name": SCALE_NAME, "ppu": practice.PPU, "unit": SCALE_UNIT,
            "pages": [0, 1, 2]}


def wall_points():
    """PDF points of the south wall's outside face on sheet A-101."""
    ox, oy = _PLAN_ORIGIN
    ppu = practice.PPU
    return {"start": [ox, oy],
            "end": [ox + SOUTH_WALL_FT * ppu, oy]}


def line_total(price=None):
    """quantity x (1 + waste%) x multiplier x unit cost, in dollars."""
    p = price if price is not None else sample_estimate()["price"]
    qty = (float(p["quantity"]) * (1 + float(p["waste"]) / 100.0)
           * float(p["multiplier"]))
    return _c2(qty * float(p["unit_cost"]))


def sample_estimate():
    """Made-up estimate for the one wall in the walkthrough."""
    price = {
        "name": WALL_NAME,
        "type": "length",
        "unit": "ft",
        "quantity": SOUTH_WALL_FT,
        "waste": 0.0,
        "multiplier": 1.0,
        "unit_cost": UNIT_COST,
        "code": "PRACTICE",
        "cost_type": "Material",
    }
    return {
        "made_up": True,
        "job": "Practice Clinic",
        "note": "Made-up numbers for the first-job walkthrough. "
                "Not a real bid.",
        "sheet": "A-101",
        "page": 0,
        "scale": known_scale(),
        "wall": {
            "name": WALL_NAME,
            "where": "Sheet A-101, outside face of the south wall, "
                     "from the left corner to the right corner.",
            "length_ft": SOUTH_WALL_FT,
            "thickness_in": 8,
            "pdf_points": wall_points(),
        },
        "price": price,
        "total": line_total(price),
    }


def sandbox_dir(root=None):
    """The only folder this module writes job files into."""
    if root is None:
        path = os.path.abspath(os.path.join(settings.DIR, SANDBOX_NAME))
    else:
        path = os.path.abspath(root)
    _reject_user_folder(path)
    if os.path.normcase(path) == os.path.normcase(
            os.path.abspath(settings.DIR)):
        raise SandboxError(
            "The practice job uses its own sandbox folder, "
            "not the settings folder.")
    return path


def _reject_user_folder(path):
    home = os.path.abspath(os.path.expanduser("~"))
    try:
        rel = os.path.relpath(os.path.abspath(path), home)
    except ValueError:
        return
    if rel.startswith(".."):
        return
    first = rel.split(os.sep)[0]
    if first == ".":
        raise SandboxError(
            "The practice job uses its own sandbox folder, "
            "not the home folder.")
    if first.lower() in _USER_FOLDERS:
        raise SandboxError(
            "The practice job stays in its sandbox folder.")


def _require_inside(path, root):
    root = os.path.abspath(root)
    path = os.path.abspath(path)
    try:
        common = os.path.commonpath([root, path])
    except ValueError:
        raise SandboxError(
            "The practice job only writes inside its sandbox folder."
        ) from None
    if os.path.normcase(common) != os.path.normcase(root):
        raise SandboxError(
            "The practice job only writes inside its sandbox folder.")
    if os.path.normcase(path) == os.path.normcase(root):
        raise SandboxError(
            "The practice job writes files inside the sandbox folder.")
    return path


def plan_path(root=None):
    root = sandbox_dir(root)
    return _require_inside(os.path.join(root, PLAN_NAME), root)


def estimate_path(root=None):
    root = sandbox_dir(root)
    return _require_inside(os.path.join(root, ESTIMATE_NAME), root)


def export_path(root=None):
    root = sandbox_dir(root)
    return _require_inside(os.path.join(root, EXPORT_NAME), root)


def _ensure_root(root):
    path = sandbox_dir(root)
    os.makedirs(path, exist_ok=True)
    return path


def _write_text(path, root, text):
    path = _require_inside(path, root)
    tmp = _require_inside(path + ".tmp", root)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path


def generate_plan_set(root=None):
    """Write the practice sheets (known scale) into the sandbox.

    The pages come from practice.make: floor plan, plumbing and power,
    a detail, and a spec page. Drawing sheets carry 1/4\" = 1'-0\".
    """
    path = plan_path(root)
    _ensure_root(root)
    # practice.make creates the parent folder and writes only `path`.
    return practice.make(path)


def write_estimate(root=None):
    """Write the made-up estimate JSON into the sandbox."""
    path = estimate_path(root)
    root = _ensure_root(root)
    _write_text(path, root, json.dumps(sample_estimate(), indent=2) + "\n")
    return path


def prepare(root=None, refresh=False):
    """Make sure the sandbox holds the plan and the sample estimate.

    An existing plan is left as it is, so markups from a previous try
    stay. Pass refresh=True to write a fresh plan.
    """
    root = _ensure_root(root)
    pdf = plan_path(root)
    est = estimate_path(root)
    if refresh or not os.path.isfile(pdf):
        generate_plan_set(root)
    if refresh or not os.path.isfile(est):
        write_estimate(root)
    return {"sandbox": root, "plan": pdf, "estimate": est}


def place_sample_wall(doc):
    """Draw the known 60 ft south wall on sheet A-101.

    The line sits on the outside face of the wall in the practice plan.
    Its name matches the sample price, so the Estimate panel can price it.
    """
    from . import annotate
    pts = wall_points()
    op = annotate.new_op(
        "add_line", 0,
        pts=[pts["start"], pts["end"]],
        color=[0.1, 0.35, 0.8],
        label="South Exterior Wall  60 ft",
        measure={"type": "length", "value": SOUTH_WALL_FT,
                 "unit": "ft", "group": WALL_NAME})
    annotate.apply_op(doc, op, fresh=True)
    return op


def apply_sample_price(doc):
    """Store the made-up wall price inside `doc` (the open plan)."""
    from . import estimate
    p = sample_estimate()["price"]
    estimate.set_price(
        doc, p["name"], p["type"], p["unit"],
        waste=p["waste"], multiplier=p["multiplier"],
        unit_cost=p["unit_cost"], code=p["code"],
        cost_type=p["cost_type"])
    return estimate.read_prices(doc)


def save_plan(doc, root=None):
    """Save `doc` to the sandbox plan path."""
    path = plan_path(root)
    root = _ensure_root(root)
    if doc.name and os.path.normcase(os.path.abspath(doc.name)) == \
            os.path.normcase(os.path.abspath(path)):
        # the plan itself is open: Windows won't replace an open file,
        # so save it in place (Nov 4, found on Jon's PC)
        doc.saveIncr()
        return path
    tmp = _require_inside(path + ".writing", root)
    doc.save(tmp, garbage=3, deflate=True)
    os.replace(tmp, path)
    return path


def export_csv(doc, root=None):
    """Export the estimate CSV into the sandbox."""
    from . import estimate
    path = export_path(root)
    root = _ensure_root(root)
    tmp = _require_inside(path + ".writing", root)
    estimate.export_csv(doc, tmp)
    os.replace(tmp, path)
    return path


# About 10 minutes: open, set the scale, measure one wall, price it, export.
STEPS = [
    {
        "id": "open",
        "title": "Open the practice plan",
        "minutes": 2,
        "what": "Open the made-up clinic plan. It lives in the practice "
                "sandbox, and you can mark it up.",
        "how": "Call prepare(), then open the plan path it returns.",
        "call": "prepare",
    },
    {
        "id": "scale",
        "title": "Set the scale",
        "minutes": 2,
        "what": "Sheet A-101 is drawn at 1/4 inch = 1 foot. Confirm that "
                "scale before you measure.",
        "how": "Read the scale on the status bar. When it is blank, use "
               "Calibrate (Set Scale) and choose 1/4\" = 1'-0\".",
        "call": "known_scale",
        "sheet": "A-101",
        "page": 0,
    },
    {
        "id": "measure",
        "title": "Measure one wall",
        "minutes": 3,
        "what": "Measure the outside face of the south wall on sheet "
                "A-101, from the left corner to the right corner.",
        "how": "Use Length and name it South Exterior Wall. The wall is "
               "60 feet at the practice scale.",
        "call": "place_sample_wall",
        "sheet": "A-101",
        "page": 0,
        "length_ft": SOUTH_WALL_FT,
    },
    {
        "id": "price",
        "title": "Price the wall",
        "minutes": 2,
        "what": "Give the south wall the made-up practice price.",
        "how": "In the Estimate panel, price South Exterior Wall at "
               "$18.75 per foot. Waste is 0 and the multiplier is 1. "
               "The line comes to $1,125.00.",
        "call": "apply_sample_price",
    },
    {
        "id": "export",
        "title": "Export the estimate",
        "minutes": 1,
        "what": "Save the estimate as a CSV in the practice sandbox.",
        "how": "Call export_csv() with the open plan. The file stays in "
               "the sandbox.",
        "call": "export_csv",
    },
]


def step(step_id):
    """The walkthrough step with this id."""
    for item in STEPS:
        if item["id"] == step_id:
            return item
    names = ", ".join(item["id"] for item in STEPS)
    raise ValueError(f"Unknown practice step. Expected one of: {names}")


def record_step(step_id):
    """Remember which step the user reached. Stored in settings."""
    found = step(step_id)
    settings.set(SETTINGS_KEY, found["id"])
    return found


def reset_progress():
    """Clear the remembered step so the walkthrough starts over."""
    settings.set(SETTINGS_KEY, None)


def progress():
    """The id of the step the user reached, or None if they are new."""
    value = settings.get(SETTINGS_KEY)
    if isinstance(value, str) and any(item["id"] == value for item in STEPS):
        return value
    return None


def resume():
    """The step the user reached, or the first step if they are new."""
    reached = progress()
    if reached is None:
        return STEPS[0]
    return step(reached)
