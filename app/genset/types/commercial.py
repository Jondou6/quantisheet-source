"""Small commercial - office (B) or retail (M), one story, 400 - 8,000 SF.
A thin adapter around today's zoned layout in layout.py; the key stays
"small_commercial" so older plans and briefs read the same."""
from .base import BuildingType

TYPE = BuildingType(
    key="small_commercial", label="Small commercial",
    occupancies=("B", "M"), default_occ="B",
    sf_range=(400, 8000), stories_range=(1, 1), ratio=2.0,
    plate_height=12.0, floor_to_floor=14.0, ceiling_ht=10.0,
    ext_wall="By design professional",
    cover_label="Small commercial building",
    roof_default={"type": "flat", "pitch": 0.25, "overhang": 0,
                  "parapet": 3.0},
    setbacks={"front": 20.0, "side": 10.0, "rear": 20.0},
    ada_use="office", ada_use_by_occ={"M": "retail"},
    needs=(("restroom",), "Has a restroom"),
    code_sheet=True)                 # G-003 for office and retail too
