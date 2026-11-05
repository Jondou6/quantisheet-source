"""Single-family house (R-3): one or two stories, 400 - 8,000 SF. A thin
adapter - the zoned layout, two-story rules, garage, porch and deck in
layout.py / twostory.py / garage.py / outdoor.py do the work, unchanged."""
from .base import BuildingType

TYPE = BuildingType(
    key="single_family", label="Single-family house",
    occupancies=("R-3",), default_occ="R-3",
    sf_range=(400, 8000), stories_range=(1, 2), ratio=1.6,
    plate_height=9.0, floor_to_floor=10.0, ceiling_ht=9.0,
    ext_wall="Wood frame", cover_label="Single-family residence",
    roof_default={"type": "gable", "pitch": 6, "overhang": 1.5,
                  "parapet": 0},
    setbacks={"front": 25.0, "side": 10.0, "rear": 25.0},
    ada_use="residential",
    needs=(("bed", "bath"), "Has a bedroom and a bath"))
