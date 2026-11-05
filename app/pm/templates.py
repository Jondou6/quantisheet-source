"""Inspection checklists that ship with QuantiSheet. Pick one on a new
inspection and its items fill the checklist."""
INSPECTIONS = {
    "Pre-pour concrete": [
        "Forms set to line, grade and dimensions on the drawings",
        "Forms braced, clean and oiled", "Subgrade compacted and tested",
        "Vapor retarder in place, laps taped",
        "Rebar size, spacing and laps per drawings",
        "Rebar clearance and chairs correct", "Embeds and sleeves placed",
        "Anchor bolts set and checked", "MEP rough-in below slab inspected",
        "Joints and blockouts located", "Testing lab scheduled",
        "Weather plan (hot/cold) in place"],
    "Framing": [
        "Wall layout matches plans", "Stud size and spacing correct",
        "Headers sized per schedule", "Hold-downs and straps installed",
        "Sheathing nailing per schedule", "Fire blocking installed",
        "Shear walls per drawings", "Trusses braced per manufacturer",
        "Openings sized for doors and windows"],
    "MEP rough-in": [
        "Plumbing tested and holding", "Ductwork supported and sealed",
        "Electrical boxes at correct heights", "Conduit fill acceptable",
        "Penetrations fire-stopped", "Clearances at panels maintained",
        "Low-voltage pathways in place", "Equipment pads ready"],
    "Insulation and drywall": [
        "Insulation R-value per plans", "Vapor barrier where required",
        "Backing installed for fixtures and accessories",
        "Rated assemblies labeled", "Board type correct by room",
        "Screw spacing per assembly", "Corner bead and trim straight",
        "Finish level per spec"],
    "Roofing": [
        "Deck fastened and clean", "Underlayment laps correct",
        "Flashings at walls and curbs", "Penetrations flashed",
        "Edge metal and gutters installed", "Drains clear",
        "Manufacturer inspection booked for warranty"],
    "Weekly safety walk": [
        "Fall protection at open edges", "Guardrails and covers in place",
        "Ladders in good condition, tied off",
        "Scaffold tagged and inspected", "PPE worn by all workers",
        "Housekeeping - walkways clear", "Fire extinguishers charged",
        "Electrical cords and GFCIs OK", "Excavations sloped or shored",
        "SDS binder current", "First aid kit stocked"],
    "Final / pre-punch": [
        "All rooms complete per finish schedule", "Doors swing and latch",
        "Hardware complete and working", "Paint touch-up complete",
        "Ceilings complete, tiles clean", "Fixtures and devices installed",
        "Signage installed", "Site clean, debris removed",
        "O&M manuals and warranties received", "Attic stock delivered"],
}


def items_for(name):
    return [{"item": t, "result": "", "note": ""}
            for t in INSPECTIONS.get(name, [])]
