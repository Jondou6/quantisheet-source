"""BuildingType: what Generate Set needs to know about one kind of
building - its limits, defaults and the hooks that make its plan and
sheets.

A hook left as None means "the core code does it the way it always has"
(the house and small-commercial adapters leave most hooks empty, so their
plans and sets stay exactly as before). Every hook is a plain function:

    layout(fields) -> plan            the whole plan from the brief fields
    program(fields) -> [room dicts]   the default room program
    grid(plan) -> grid dict or None   the structural grid (grid.py)
    checks(plan) -> [(status, check, detail)]   extra self-check lines
    sheets(plan) -> [SheetSpec]       the sheet list (sheets.py)
    notes(plan) -> [str]              template project notes
    quantities(plan) -> [row]         the A-701 / CSV quantity rows
    validate(plan) -> [warning]       extra plan checks (PlanError to stop)
    cover(plan, rows) -> rows         the cover's project-data rows
    read(text) -> fields              the type's own brief fields (seats,
                                      tenants...) once the type is picked
    detect(text) -> [hits] or None    a match rule regexes can't say (a
                                      count of bays AND a retail word);
                                      used with `patterns`
    `weak` patterns pick the type only when no other type's words are in
    the brief ("tilt-up" alone is a warehouse; a "tilt-up strip center"
    is strip retail).
    scoping(plan, project) -> project the ada_check project for A-801
    code_lines(plan, code) -> [[item, required, this set]]  extra G-003
                                      lines
"""
from dataclasses import dataclass, field


@dataclass
class BuildingType:
    key: str
    label: str                       # the dialog's name for it
    occupancies: tuple               # IBC groups this type may be labelled
    default_occ: str
    sf_range: tuple                  # (min, max) gross SF, the whole building
    stories_range: tuple = (1, 1)
    ratio: float = 2.0               # default width / depth
    plate_height: float = 12.0       # ft, floor to the roof bearing
    floor_to_floor: float = 14.0
    ceiling_ht: float = 10.0
    ext_wall: str = ""
    roof_default: dict = field(default_factory=dict)
    setbacks: dict = field(default_factory=dict)     # assumed, ft
    ada_use: str = "office"          # app/ada_check.py USES key
    ada_use_by_occ: dict = field(default_factory=dict)
    patterns: tuple = ()             # regexes that pick it from a brief
    weak: tuple = ()                 # of them, the ones another type beats
    max_w: float = 120.0             # ft, footprint limits
    max_d: float = 80.0
    cover_label: str = ""
    code_sheet: bool = False         # G-003 Code Summary in the set
    needs: tuple = (("restroom",), "Has a restroom")    # audit
    occ_rules: tuple = ()            # ((regex, group), ...) first match wins
    layout: object = None
    program: object = None
    grid: object = None
    checks: object = None
    sheets: object = None
    notes: object = None
    quantities: object = None
    validate: object = None
    cover: object = None
    read: object = None
    detect: object = None
    scoping: object = None
    code_lines: object = None

    def limits(self):
        """{"sf": (lo, hi), "stories": (lo, hi), "max_w", "max_d"}."""
        return {"sf": tuple(self.sf_range),
                "stories": tuple(self.stories_range),
                "max_w": self.max_w, "max_d": self.max_d}

    def ada_use_for(self, occupancy):
        return self.ada_use_by_occ.get(occupancy or "", self.ada_use)

    def run(self, hook, *args, default=None):
        """Call a hook if the type has one, else return `default`."""
        fn = getattr(self, hook)
        return default if fn is None else fn(*args)
