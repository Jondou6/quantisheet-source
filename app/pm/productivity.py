"""Production rates for "Build Schedule From Plans": activity duration =
quantity / (rate x crews), clamped to the activity family's minimum and
maximum.

The table is the GC's: every number below is an ASSUMED STARTING VALUE -
checked against public production figures (state DOT production tables,
trade / manufacturer guides, the Census house build time; the source of
each is in the comment above it), never copied from licensed estimating
data, and where nothing public was found our own judgement, which the
comment says. The person edits it in the Build From Plans dialog
(Production Rates...); the edits are saved to productivity.json in the
settings folder and win over these defaults.

Crews: the Crews column is the fewest; on a large job the floor-wide
trades get more by an area band (CREW_BAND, band_crews(): crews =
(area / crew_band_sf)^0.5 up to max_crews, both editable assumptions).
A warehouse bay's MEP rough-in / trim counts at bay_rough_share of its
area (BAY_ROUGH).

Quantities come from the job read: the floor area and levels (room tags),
the footprint (area / levels), a perimeter for a 2:1 rectangle of that
footprint, roof area = footprint, wall area = perimeter x story height x
levels - and quantities taken off in the drawings (annotate.takeoff_items)
beat all of those estimates. A set made by Generate Set brings its own
quantities (the .genset.json / .quantities.csv beside the PDF, or the
rows embedded in it): set_quantities() turns them into the same
quantities, and they beat the floor-area estimates (BASIS "genset: ...").

The interior finishes (drywall, paint, ceilings, flooring, doors,
casework) are sized from the FINISHED area - the set's room finishes, the
finished rooms among the room tags, or for a warehouse an assumed office
share - and from the whole floor only as the fallback, which the BASIS
then says ("floor area (fallback)").

Pure Python (no Qt, no PyMuPDF).
"""
import copy
import json
import logging
import math
import os
import re
from collections import OrderedDict

log = logging.getLogger(__name__)

FILE = "productivity.json"
FIELDS = ("rate", "crews", "min", "max", "note")

ASSUMED = "rate assumed"
YOURS = "rate from your production table"


def _f(name, unit, of, rate, crews, mn, mx, qty, note, takeoff=None,
       measure="area", per_each=None):
    """One family: `unit` and `of` name the quantity ("SF", "slab"), `rate`
    is units per crew-day, `qty` the estimate it falls back to, `takeoff`
    a regex for takeoff group names (with the takeoff `measure` it reads),
    `per_each` how many counted items make one unit (1.125 block per SF)."""
    return {"name": name, "unit": unit, "of": of, "rate": rate,
            "crews": crews, "min": mn, "max": mx, "qty": qty, "note": note,
            "takeoff": takeoff, "measure": measure, "per_each": per_each}


# ------------------------------------------------------------- the table
# Every rate is an assumed starting value - the GC overrides.
#
# Review 0.12.39 (production norms): each rate below was checked against
# PUBLIC production figures for US commercial / light-commercial work and
# its basis is in the comment above it. No licensed estimating-guide data
# (RSMeans, NECA, PDCA cost guides...) was copied; where no public number
# was found the rate is our own judgement and the comment says so. The
# public sources used:
#   [NCDOT]  NCDOT "Contract Time Guidelines" - production rates per
#            working day by project size (small urban / small rural /
#            major), connect.ncdot.gov
#   [TXDOT]  TxDOT "CST production rates" (low / median / high),
#            ftp.txdot.gov/pub/txdot/cst/cst-production-rates.pdf
#   [WISDOT] WisDOT estimating "Production rate table" (interquartile
#            range and median), wisconsindot.gov
#   [CENSUS] US Census Survey of Construction: a built-for-sale
#            single-family house averages 6.9 months start to completion
#            (2017, as reported by GreenBuildingAdvisor) - the house
#            sanity check
#   [TILT]   tilt-up practice: 8-15 panels set per day by an experienced
#            crew, a 50,000 SF warehouse's panels standing 3-5 days after
#            erection starts, panels cast in 2-3 rounds (Projul tilt-up
#            guide); up to 40 panels a day (tiltwall.ca); walls of a
#            34,000 SF footprint building in place 8 weeks after the
#            foundation started (Tilt-Up Concrete Association,
#            Tilt-Up Today)
#   [PEMB]   a 5,000-10,000 SF pre-engineered metal building erects in 2-4
#            weeks with 4-6 ironworkers, foundations 2-4 weeks before
#            (Projul steel joist / metal building erection guide)
#   [SJI]    Steel Joist Institute project profile: 301,458 SF of joist
#            girders / joists / deck placed in 42 days (~7,000 SF a day,
#            several crews, panelized deck)
#   [FHB]    Fine Homebuilding framers' forum: crews of 4-8 frame about
#            1,000 SF of house a week including sheathing, windows and
#            roof paper; a 4-person crew stands a 1,600 SF floor's walls
#            and deck in about 2 days
#   [ROOF]   Roofing Contractor project profile (243,000 SF warehouse
#            TPO): about 10 squares per worker-day with 10-12 ft rolls,
#            200 squares a day for a 15-person crew with 16 ft rolls
#   [CMU]    Norlite "Estimating Production" (masonry): about 180 block
#            per mason-day on average, 200 lightweight block cited, less
#            for heavy / special units
#   [GWB]    Walls & Ceilings (via BuilderMuse): a good hanger hangs about
#            40 sheets (4x12) a day
#   [PAINT]  EstimateRocket painting estimating guide: about 140-155 SF
#            of wall per painter-hour to prep, cut in and roll one coat
#   [ELEC]   electricians' estimating forum (Mike Holt): about 0.07-0.10
#            labor-hours per SF for a whole office electrical job (rough
#            in is roughly 60% of it)
#
# Large jobs (review 0.12.39): the trades that work across the floor
# (MEP rough-ins and trim, interior finishes, roofing, cleaning) put more
# than one crew on a big building - see CREW_BAND below and the
# "crew_band_sf" / "max_crews" assumptions. The Crews column is the
# fewest crews; the area band can add more.
FAMILIES = OrderedDict([
    # [NCDOT] small urban 1/4-1 acre/day, [TXDOT] 1-6 acres/day: ~0.9 ac
    ("clearing", _f("Clearing & grubbing", "SF", "site", 40000, 1, 2, 20,
                    "site_sf", "about 1 acre per crew-day (dozer, loader, "
                    "trucks); NCDOT small urban 1/4-1 ac/day",
                    r"clearing|grubbing")),
    # no DOT rate for silt fence; a 2-3 person crew with a slicing
    # machine sets 1,000-2,000 LF/day - our judgement, low end kept for
    # inlet protection and the entrance
    ("erosion", _f("Erosion control (silt fence)", "LF", "silt fence",
                   1000, 1, 2, 10, "site_perimeter", "silt fence, inlet "
                   "protection and the construction entrance",
                   r"silt fence|erosion", "length")),
    # [NCDOT] small urban grading 100-500 CY/day: 15,000 SF at about a
    # foot of cut / fill is ~550 CY, plus compaction and the pad
    ("site_grading", _f("Mass grading & building pad", "SF", "site",
                        15000, 1, 5, 45, "site_sf", "cut / fill, compaction"
                        ", building pad to subgrade; ~550 CY/day (NCDOT "
                        "small urban 100-500 CY/day)",
                        r"\bgrading\b|site area|disturbed")),
    # [NCDOT] pipe 50-200 LF/day small urban, [TXDOT] RCP 80-212 (median
    # 119) LF/day: building services have taps and tie-ins - low end
    ("utility", _f("Underground utilities", "LF", "pipe", 80, 1, 8, 60,
                   "pipe_lf", "trench, bed, lay and backfill 4-12 in pipe "
                   "(excavator crew); NCDOT 50-200 LF/day", None, "length")),
    # was 50 LF/day, min 10: a 5-7 person crew trench-pours (or forms)
    # 2 ft x 1 ft continuous footings with rebar at 80-120 LF/day - our
    # judgement, consistent with [PEMB] 2-4 weeks of foundations for a
    # 5-10k SF building incl. piers / anchor bolts; min 6 d (dig, form,
    # inspection, pour) - a house's footings are not two weeks of work
    ("footings", _f("Footings & foundations", "LF", "footing", 80, 1, 6,
                    25, "perimeter", "form, rebar, place and strip "
                    "continuous footings / stem walls (crew of 5-7)",
                    r"footing|foundation|grade beam", "length")),
    # under-slab rough: trenching across an open pad; a warehouse bay's
    # share is weighted down (bay_rough_share - review 0.12.39)
    ("underslab", _f("Under-slab plumbing & electrical", "SF", "slab",
                     4000, 1, 3, 12, "footprint", "trench, pipe / conduit "
                     "and inspection under the slab")),
    # was 3,000: a laser screed places up to ~5,000 SF an hour (Somero
    # S-485 brochure) - placement isn't the limit, the fine grade, vapor
    # barrier, rebar / mesh and finishing cycle is: 4,000 SF a crew-day
    # net over the activity (pours of 8-15k SF every 2-3 days)
    ("slab", _f("Slab on grade", "SF", "slab", 4000, 1, 5, 20,
                "footprint", "fine grade, vapor barrier, rebar, place & "
                "finish (pours of 8-15k SF; laser screed on large slabs)",
                r"\bslab|\bS\.?O\.?G\b|concrete floor")),
    # the mixed rate when the structure isn't known: between wood framing
    # (~300) and steel / tilt-up (1,500-2,000) - kept
    ("structure", _f("Structure (mixed framing / masonry / steel)", "SF",
                     "floor", 1000, 1, 15, 45, "floor", "used when the set "
                     "doesn't say which structure it is")),
    # was 600 SF/day, min 15: [FHB] ~1,000 SF of house a week for a crew
    # of 4-8 INCLUDING the roof, sheathing and windows -> ~300 SF/day for
    # the walls and floors (the roof framing is its own row, roof_deck);
    # min 8 d: a 1,600 SF house's walls, sheathing and blocking
    ("wood_framing", _f("Wood framing", "SF", "floor", 300, 1, 8, 60,
                        "floor", "walls, floors and sheathing; crew of "
                        "4-5 (the roof framing is its own row)",
                        r"wood fram|\bframing\b|\bstuds?\b")),
    # [PEMB] 5-10k SF erected (frames, secondary and sheeting) in 2-4
    # weeks: the frames and girts / purlins are about half of that; the
    # wall panels and roof are their own rows - 2,000 SF/day kept
    ("steel_erection", _f("Structural steel / PEMB erection", "SF",
                          "floor", 2000, 1, 10, 40, "floor", "erect, plumb "
                          "and bolt frames and secondary; crane and 4-6 "
                          "ironworkers",
                          r"structural steel|\bsteel\b|\bPEMB\b|metal "
                          r"building")),
    # NEW (review 0.12.39): a tilt-up building's structure is its wall
    # panels. [TILT] erection is days (8-40 panels a day; a 50k SF
    # warehouse's panels standing in 3-5 days), the forming / rebar /
    # embeds / casting in 2-3 rounds on the slab, curing to lift strength
    # and bracing are the weeks - per round ~3-4 d forming, 2-3 d rebar /
    # embeds, the pour, ~5-7 d to lift strength, then 3-5 d of erection
    # and a week of bracing / patching: 1,200 SF of panel a crew-day over
    # the whole sequence (~28 d, 5-6 weeks, for 33,000 SF of panels;
    # [TILT]: walls in place ~8 weeks after the foundation started)
    ("tilt_up", _f("Tilt-up wall panels (form, cast, erect)", "SF",
                   "wall panels", 1200, 1, 15, 45, "wall_sf", "form, rebar,"
                   " embeds and cast on the slab in 2-3 rounds, cure, erect "
                   "(8-15+ panels/day) and brace",
                   r"tilt.?up|tilt.?wall|concrete wall panel")),
    # was 300 SF/day (340 block): [CMU] ~180 block per mason-day -> 3
    # masons + 2 tenders lay ~500 block = ~450 SF of wall a day
    # NEW (review 0.12.39): a tilt-up building's "Exterior walls &
    # finishes" is not cladding - the panels are the wall: joint sealant
    # both faces (~300-400 LF a caulker-day), patching and a sprayed
    # elastomeric / paint finish (~4,000+ SF a rig-day): ~2,000 SF of
    # panel a crew-day net (our judgement). Was the 500 SF/day cladding
    # rate, capped at 40 d on a 38,000 SF warehouse.
    ("panel_finish", _f("Tilt-up panel finishes (caulk, patch, paint)",
                        "SF", "wall panels", 2000, 1, 5, 30, "wall_sf",
                        "panel joint sealant, patching and paint / "
                        "coating", r"panel (?:joint|finish|seal)|"
                        r"elastomeric")),
    ("cmu", _f("CMU block walls", "SF", "wall", 450, 1, 10, 50, "wall_sf",
               "about 500 block per crew-day (3 masons + 2 tenders, ~170 "
               "block a mason), 1.125 block per SF",
               r"\bCMU\b|\bblock\b|masonry", "area", 1.125)),
    # was 2,500: one crane crew sets joists at 40-60 a day and decks
    # ~4,000-6,000 SF a day ([SJI] ~7,000 SF/day with several crews):
    # 4,000 SF/day; trusses on a house are at the 5 d minimum
    ("roof_deck", _f("Roof structure & deck", "SF", "roof", 4000, 1, 5,
                     20, "footprint", "joists / trusses and deck (one "
                     "crane / erection crew)",
                     r"roof deck|\bdeck\b|joist|truss")),
    # was 20 SQ/day: [ROOF] ~10 SQ per worker-day on open low-slope TPO;
    # a 4-5 person crew at ~6-7 SQ each with insulation and flashings ->
    # 30 SQ/day; a shingle crew does a 20-25 SQ house in 1-2 days.
    # Big roofs get more crews (CREW_BAND, by the roof area).
    ("roofing", _f("Roofing", "SQ", "roof", 30, 1, 6, 30, "roof_sq",
                   "membrane or shingles; crew of 4-5 (1 SQ = 100 SF)",
                   r"roof(?!\s*deck)")),
    # sheathing / WRB / siding ~1,000 SF/day, brick or stone veneer
    # ~200-250, EIFS / metal panels 300-800: a 500 SF/day mix - kept
    # (our judgement)
    ("exterior_walls", _f("Exterior walls & finishes", "SF", "wall", 500,
                          1, 10, 40, "wall_sf", "sheathing, WRB and "
                          "cladding (siding / veneer / panels)",
                          r"exterior wall|siding|veneer|stucco|\bEIFS\b|"
                          r"cladding")),
    # 2-3 glaziers set ~150-250 SF of storefront / windows a day - kept
    # (our judgement)
    ("windows", _f("Windows & storefront", "SF", "glazing", 200, 1, 3, 20,
                   "glazing_sf", "set, anchor and seal (2-3 glaziers)",
                   r"window|storefront|glazing|curtain ?wall")),
    # a batt installer does 2,000-3,000 SF a day - kept
    ("insulation", _f("Insulation", "SF", "wall", 2000, 1, 3, 12,
                      "wall_sf", "batt / board at the exterior walls",
                      r"insulation")),
    # MEP rough-ins by floor area (review 0.12.39): [ELEC] an office's
    # electrical runs ~0.07-0.10 labor-h/SF, ~60% of it rough-in -> ~0.05
    # labor-h/SF; a 3-person crew (24 h/day) roughs ~500-550 SF a day.
    # Plumbing and HVAC set relative to it (fewer hours per SF in offices
    # and retail; more in a restaurant - edit for kitchens / labs). Were
    # 1,000 / 900 / 800 SF/day at 1 crew on any floor. Now: more crews on
    # a large floor (CREW_BAND) and a warehouse bay counted at
    # bay_rough_share of its area (lights, unit heaters, a few hose
    # bibbs - not office density).
    ("plumbing_rough", _f("Plumbing rough-in", "SF", "floor", 700, 1, 10,
                          30, "floor", "crew of 2-3; = 1.4 crew-days per "
                          "1,000 SF of office-density floor")),
    ("hvac_rough", _f("HVAC rough-in & ductwork", "SF", "floor", 650, 1, 10,
                      30, "floor", "crew of 3-4; = 1.5 crew-days per 1,000 "
                      "SF of office-density floor")),
    ("elec_rough", _f("Electrical rough-in", "SF", "floor", 550, 1, 10, 35,
                      "floor", "crew of 3; ~0.05 labor-h/SF; = 1.8 "
                      "crew-days per 1,000 SF of office-density floor")),
    # a 2-3 fitter crew installs ~20-25 heads of mains / branches a day at
    # ~100 SF a head (light hazard / ESFR spacing) - kept
    ("sprinkler_rough", _f("Fire sprinkler rough-in", "SF", "floor", 2000,
                           1, 5, 20, "floor",
                           "= 0.5 crew-days per 1,000 SF (~20 heads/day)")),
    ("low_voltage", _f("Fire alarm & low voltage rough-in", "SF", "floor",
                       2500, 1, 4, 15, "floor",
                       "= 0.4 crew-days per 1,000 SF")),
    # an interior demo crew of 4-5 with a dumpster: 1,000-1,500 SF a day
    # - kept
    ("selective_demo", _f("Selective demolition", "SF", "floor", 1000, 1,
                          3, 40, "floor", "interior demolition and haul-off",
                          r"\bdemo")),
    # a framer runs ~30-50 LF of full-height partition a day: crew of 3-4
    # ~100-150 LF - kept at the low end (to deck, with bracing)
    ("interior_framing", _f("Interior framing (metal stud partitions)",
                            "LF", "partition", 100, 1, 3, 40,
                            "partition_lf", "layout, track and studs to "
                            "deck; crew of 3-4", r"partition|metal stud",
                            "length")),
    # was 3,000 SF/day, min 12: [GWB] a hanger hangs ~40 sheets (~1,900
    # SF) a day, but the tape / 3 coats / sand to level 4 with drying is
    # the pace: 2 hangers + 2 finishers net ~2,500 SF of board a day;
    # min 10 d (hang, tape, coats, dry, sand on even a small job)
    ("drywall", _f("Drywall hang, tape & finish", "SF", "board", 2500, 1,
                   10, 35, "board_sf", "hang, tape and finish (level 4); 2 "
                   "hangers + 2 finishers",
                   r"drywall|\bgyp|gypsum|\bGWB\b|sheetrock")),
    # 2 installers each ~1,000-1,500 SF of grid and tile a day - kept
    ("ceilings", _f("Ceilings (ACT)", "SF", "ceiling", 2000, 1, 5, 20,
                    "ceiling_sf", "grid and tile (2 installers)",
                    r"ceiling|\bACT\b")),
    # was 4,000 SF/day: [PAINT] ~150 SF per painter-hour per rolled coat;
    # prime (sprayed, ~3x faster) + 2 rolled coats on new board -> ~800
    # SF of surface a painter-day: crew of 3 ~2,500 SF/day
    ("paint", _f("Painting", "SF", "paint", 2500, 1, 8, 25, "paint_sf",
                 "prime (spray) + 2 rolled coats; crew of 3", r"paint")),
    # was 2,000: carpet tile ~1,000-1,500 SF per installer-day, LVT
    # ~500-800, ceramic tile ~100-200 per setter: a mixed crew of 3-4
    # ~1,500 SF a day (our judgement)
    ("flooring", _f("Flooring", "SF", "floor", 1500, 1, 6, 25, "floor",
                    "mix of carpet, VCT / LVT and tile; crew of 3-4",
                    r"flooring|carpet|\bVCT\b|\bLVT\b|floor tile|"
                    r"floor finish")),
    # 2 carpenters hang a pre-hung or HM-frame door with hardware in
    # ~1.5-2 h: ~10 a day - kept
    ("doors", _f("Doors, frames & hardware", "EA", "doors", 10, 1, 3, 15,
                 "doors", "frame, hang and hardware (2 carpenters)",
                 r"^(?!.*(?:overhead|dock|sectional|coiling|roll-?up|"
                 r"drive-in)).*\bdoors?\b",
                 "count")),
    # a 2-person crew sets a sectional door and operator in 4-8 h (the
    # dock leveler, bumpers and seal with it) - kept
    ("overhead_doors", _f("Overhead doors & dock equipment", "EA",
                          "overhead doors", 2, 1, 2, 15, "overhead_doors",
                          "set tracks, door and operator (and the dock "
                          "leveler, bumpers and seal at a dock door)",
                          r"overhead door|dock door|sectional door|coiling "
                          r"door|roll-?up door|drive-in door", "count")),
    ("specialties", _f("Casework, specialties & accessories", "SF",
                       "floor", 3000, 1, 4, 15, "floor", "casework, toilet "
                       "accessories, signage")),
    # was 2,000: [ELEC] trim is ~40% of an office's electrical hours
    # (~0.03-0.04 labor-h/SF): a 3-person crew per trade ~1,200 SF of
    # devices / fixtures / lights a day, the trades in parallel
    ("mep_trim", _f("Plumbing & electrical trim", "SF", "floor", 1200, 1,
                    6, 20, "floor", "fixtures, devices and lights; a crew "
                    "of 3 per trade")),
    ("hvac_trim", _f("HVAC trim", "SF", "floor", 2500, 1, 2, 20, "floor",
                     "grilles, diffusers and connections")),
    ("sprinkler_trim", _f("Fire sprinkler trim", "SF", "floor", 3000, 1, 2,
                          15, "floor", "heads at the finished ceilings")),
    # [NCDOT] small urban: HMA 200-500 tons/day (2 in. HMA ~0.11 ton/SY
    # -> 2,000-4,500 SY), aggregate base 200-500 tons/day, curb & gutter
    # 50-300 LF/day; [TXDOT] sidewalk median 132 SY/day: the operations
    # in sequence net ~400 SY/day over the activity - kept
    ("paving", _f("Curb, paving & sidewalks", "SY", "paving", 400, 1, 5,
                  25, "paving_sy", "subgrade, base, curb, asphalt / "
                  "concrete and walks (1 SY = 9 SF); NCDOT / TxDOT "
                  "small-job rates in sequence",
                  r"paving|pavement|asphalt|parking|\bdrives?\b|sidewalk")),
    # [WISDOT] seeding median 3,900 SY/day, sod 1,100 SY/day (~9,900 SF),
    # topsoil 280 CY/day: with planting beds ~5,000 SF a day - kept
    ("landscape", _f("Landscaping & seeding", "SF", "landscape", 5000, 1,
                     3, 20, "landscape_sf", "topsoil, seed / sod and "
                     "planting (WisDOT sod ~1,100 SY/day)",
                     r"landscap|\bsod\b|\bseed|planting|lawn")),
    # a crew of 4 cleans ~5,000-8,000 SF of new finished space a day
    ("final_clean", _f("Final cleaning", "SF", "floor", 5000, 1, 2, 8,
                       "floor", "final clean before turnover (crew of 4)")),
    # tear-off of BUR / single-ply with a chute and dumpster ~20-30 SQ a
    # crew-day - kept at 20 (wet insulation, deck repairs)
    ("roof_tearoff", _f("Roof tear-off", "SQ", "roof", 20, 1, 2, 40,
                        "roof_sq", "remove and haul existing roofing",
                        r"roof")),
    ("roof_insulation", _f("Roof insulation & cover board", "SQ", "roof",
                           25, 1, 2, 30, "roof_sq", "board insulation and "
                           "cover board", r"roof")),
    ("sheet_metal", _f("Roof sheet metal", "LF", "edge", 100, 1, 2, 20,
                       "perimeter", "edge, coping, gutters and "
                       "downspouts", r"coping|gutter|sheet ?metal|"
                       r"roof edge", "length")),
])

# how the quantities are estimated when nothing was taken off - also
# assumed starting values, also editable
ASSUMPTIONS = OrderedDict([
    ("story_height_ft", (14.0, "Story height (ft): wall area = perimeter "
                               "x height x levels")),
    ("footprint_ratio", (2.0, "Footprint shape L:W (perimeter of a "
                              "rectangle this shape)")),
    ("site_factor", (3.0, "Site area = footprint x this")),
    ("paving_factor", (1.0, "Paved area = footprint x this")),
    ("landscape_factor", (0.5, "Landscaped area = footprint x this")),
    ("board_factor", (2.5, "SF of drywall per SF of floor")),
    ("paint_factor", (2.5, "SF painted per SF of floor")),
    ("ceiling_factor", (0.9, "SF of ceiling per SF of floor")),
    ("glazing_share", (0.15, "Share of the exterior wall that is glazing")),
    ("sf_per_door", (300.0, "SF of floor per door")),
    ("partition_lf_per_sf", (0.1, "LF of partition per SF of floor")),
    ("warehouse_office_share", (0.10, "Warehouse with no finish data: share "
                                      "of the floor that is office / "
                                      "finished")),
    # review 0.12.39: crews by area band, and the warehouse bay's MEP
    ("crew_band_sf", (10000.0, "Crews by area band: the floor-wide trades "
                               "(MEP rough-in / trim, finishes, roofing, "
                               "cleaning) get (area they work / this SF)"
                               "^0.5 crews - 4x this area: 2 crews (at "
                               "least the Crews column)")),
    ("max_crews", (3.0, "Crews by area band: the most crews the band gives "
                        "one trade (1 = always the Crews column)")),
    ("bay_rough_share", (0.5, "Warehouse bay: its MEP rough-in / trim and "
                               "under-slab work per SF as a share of "
                               "office density (high-bay lights, unit "
                               "heaters, a few hose bibbs)")),
])

# Crews by area band (review 0.12.39): the families whose crews grow with
# the job, and the area each one's band is counted on - the floor, the
# FINISHED area (an office in a warehouse is one crew's work) or the roof.
# crews = (area / crew_band_sf) ^ 0.5 to 0.1 crew, between the Crews
# column and max_crews (band_crews()): a floor 4x the band gets 2 crews,
# 9x gets 3. Integer bands were tried first: a 16,500 SF strip came out
# 36 days SHORTER than a 14,000 SF one (one crew -> two at the edge);
# the square root grows smoothly and matches crews / crew sizes growing
# slower than the floor.
# The structure, foundations, slab and sitework stay at the Crews column:
# they are paced by one crane, one pour sequence or one spread of
# equipment, and their rates already are the whole crew's.
CREW_BAND = {
    "plumbing_rough": "floor", "hvac_rough": "floor", "elec_rough": "floor",
    "sprinkler_rough": "floor", "low_voltage": "floor",
    "selective_demo": "floor", "final_clean": "floor",
    "hvac_trim": "floor", "sprinkler_trim": "floor",
    "interior_framing": "finished", "drywall": "finished",
    "ceilings": "finished", "paint": "finished", "flooring": "finished",
    "specialties": "finished", "mep_trim": "finished",
    "roofing": "roof", "roof_tearoff": "roof", "roof_insulation": "roof",
}

# families whose "floor" quantity is the FINISHED floor (the interior
# finishes): the finished area when the job read gives one, else the floor
FINISHED_QTY = {"flooring": "finish_floor_sf", "specialties": "finished_sf"}
# families sized by the footprint that take the set's measured roof area
# instead when it has one (roof structure & deck)
ROOF_AREA_QTY = ("roof_deck",)

# the activities each template sizes by a family (key -> family); the
# rest keep their fixed duration, or scale by area^0.5 (see autoschedule)
ACTIVITY_FAMILIES = {
    "new_building": {
        "clearing": "clearing", "erosion": "erosion",
        "grading": "site_grading", "utilities": "utility",
        "footings": "footings", "underslab": "underslab", "slab": "slab",
        "structure": "@structure", "roofstruct": "roof_deck",
        "roofing": "roofing", "exterior": "@exterior",
        "windows": "windows", "insulation": "insulation",
        "plumb_rough": "plumbing_rough", "hvac_rough": "hvac_rough",
        "elec_rough": "elec_rough", "fs_rough": "sprinkler_rough",
        "fa_rough": "low_voltage", "drywall": "drywall",
        "ceilings": "ceilings", "paint": "paint", "flooring": "flooring",
        "doors": "doors", "oh_doors": "overhead_doors",
        "casework": "specialties",
        "mep_trim": "mep_trim", "bay_trim": "mep_trim", "paving": "paving",
        "landscape": "landscape", "clean": "final_clean"},
    "renovation": {
        "demo": "selective_demo", "framing": "interior_framing",
        "plumb_rough": "plumbing_rough", "hvac_rough": "hvac_rough",
        "elec_rough": "elec_rough", "fs_rough": "sprinkler_rough",
        "fa_rough": "low_voltage", "drywall": "drywall",
        "ceilings": "ceilings", "paint": "paint", "flooring": "flooring",
        "doors": "doors", "casework": "specialties",
        "mep_trim": "mep_trim", "hvac_trim": "hvac_trim",
        "fs_trim": "sprinkler_trim", "clean": "final_clean"},
    "reroof": {"tearoff": "roof_tearoff", "insul": "roof_insulation",
               "membrane": "roofing", "sheetmetal": "sheet_metal"},
    "sitework_only": {"utilities": "utility"},
}


# ------------------------------------------------------------- load / save
def path():
    from .. import settings
    return os.path.join(settings.DIR, FILE)


def defaults():
    """A fresh copy of the built-in table: {"families", "assumptions"}."""
    return {"families": copy.deepcopy(FAMILIES),
            "assumptions": OrderedDict((k, v) for k, (v, _n) in
                                       ASSUMPTIONS.items()),
            "edited": set()}


def _num(v, lo=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x) or (lo is not None and x < lo):
        return None
    return x


def merge(table, data):
    """Put the person's values (`data`, as saved) over `table`; values that
    aren't usable numbers are ignored. Returns the table."""
    fams = (data or {}).get("families") or {}
    for key, vals in fams.items() if isinstance(fams, dict) else ():
        fam = table["families"].get(key)
        if fam is None or not isinstance(vals, dict):
            continue
        for field in FIELDS:
            if field not in vals:
                continue
            if field == "note":
                fam["note"] = str(vals["note"])
                continue
            x = _num(vals[field], 0)
            if x is None or (field in ("rate", "crews") and x <= 0):
                continue
            fam[field] = x
            if field in ("rate", "crews", "min", "max") and \
                    x != FAMILIES[key][field]:
                table["edited"].add(key)
        if fam["max"] < fam["min"]:
            fam["max"] = fam["min"]
    asum = (data or {}).get("assumptions") or {}
    for key, v in asum.items() if isinstance(asum, dict) else ():
        x = _num(v, 0)
        if key in table["assumptions"] and x is not None and x > 0:
            table["assumptions"][key] = x
    return table


def load():
    """The table: the defaults with the saved edits over them."""
    table = defaults()
    try:
        with open(path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return table
    except (OSError, ValueError):
        log.warning("production rates file unreadable; using the defaults")
        return table
    return merge(table, data if isinstance(data, dict) else {})


def diff(table):
    """What differs from the defaults (what gets saved)."""
    out = {"families": {}, "assumptions": {}}
    for key, fam in table["families"].items():
        base = FAMILIES.get(key)
        if base is None:
            continue
        ch = {f: fam[f] for f in FIELDS if fam.get(f) != base[f]}
        if ch:
            out["families"][key] = ch
    for key, v in table["assumptions"].items():
        if key in ASSUMPTIONS and v != ASSUMPTIONS[key][0]:
            out["assumptions"][key] = v
    return out


def save(table):
    """Save the person's table (only what differs from the defaults, so
    a later default change still reaches the families nobody edited)."""
    from .. import settings
    os.makedirs(settings.DIR, exist_ok=True)
    data = diff(table)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path())
    return data


def reset():
    """Back to the built-in table (the saved edits are removed)."""
    try:
        os.remove(path())
    except FileNotFoundError:
        pass
    return defaults()


# ------------------------------------------------------------- quantities
_EXISTING = re.compile(r"\bexist", re.I)
_M_TO_FT = 3.28084


def _to_base(item):
    """A takeoff item's value in SF (area), LF (length) or EA (count)."""
    v = float(item.get("value") or 0)
    unit = str(item.get("unit") or "").strip().lower()
    t = item.get("type")
    k = 1.0
    if unit in ("m", "meter", "meters", "m2", "sm", "sq m"):
        k = _M_TO_FT
    elif unit in ("yd", "yard", "yards", "sy", "sq yd"):
        k = 3.0
    elif unit in ("in", "inch", "inches"):
        k = 1 / 12.0
    if t == "area":
        return v * k * k
    if t == "length":
        return v * k
    return v


def takeoff_quantity(key, fam, items, table):
    """(quantity in the family's unit, how) from the takeoff items whose
    group name matches the family, or None."""
    rx = fam.get("takeoff")
    if not rx or not items:
        return None
    pat = re.compile(rx, re.I)
    h = table["assumptions"]["story_height_ft"]
    total, groups = 0.0, []
    for it in items:
        g = str(it.get("group") or "")
        if not g or not pat.search(g) or _EXISTING.search(g):
            continue
        t = it.get("type")
        base = _to_base(it)
        q = None
        if fam["measure"] == t:
            q = base
        elif fam["measure"] == "area" and fam["of"] == "wall" and \
                t == "length":
            q = base * h                     # wall LF x story height
        elif fam["measure"] == "area" and t == "count" and \
                fam.get("per_each"):
            q = base / fam["per_each"]       # blocks -> SF of wall
        if q is None or q <= 0:
            continue
        if fam["unit"] == "SQ":
            q /= 100.0
        elif fam["unit"] == "SY":
            q /= 9.0
        total += q
        if g not in groups:
            groups.append(g)
    if total <= 0:
        return None
    return total, "takeoff: " + ", ".join(f'"{g}"' for g in groups[:3]) + \
        (" ..." if len(groups) > 3 else "")


# the finishes Generate Set writes that are no finish work: sealed or
# exposed concrete, exposed structure, nothing
_UNFINISHED = {"SC", "EXP", "-", "TBD", "", "NONE", "N/A", "CONC", "EC",
               "UNF", "OPEN", "MFR"}
# room names of unfinished space (a warehouse's bay, a shop floor)
_UNFINISHED_ROOM = re.compile(
    r"WAREHOUSE|\bBAYS?\b|HIGH[- ]?BAY|\bDOCKS?\b|LOADING|SHIPPING|"
    r"RECEIVING|MANUFACTUR|PRODUCTION|FABRICATION|INDUSTRIAL|\bSHOP\b|"
    r"DISTRIBUTION|APPARATUS|VEHICLE|STORAGE (?:AREA|YARD|BAY)|"
    r"\bRACKING\b|FREEZER|COOLER", re.I)
UNFINISHED_SHARE = 0.4     # unfinished rooms this share of the area: only
                           # the rest is finished


def _code(item, head):
    return item[len(head):].strip().split(" ")[0].upper()


def _ftin(text):
    """Feet from a fmt_ftin dimension ("3'-0\"", "12'-6\"")."""
    m = re.match(r"\s*(\d+)'(?:-(\d+(?:\.\d+)?)\")?", text or "")
    return int(m.group(1)) + float(m.group(2) or 0) / 12.0 if m else 0.0


def _rows_of(rows):
    """Generate Set quantity rows (tuples, CSV rows or set_items() dicts)
    as [(group, item, qty, unit, how)]; unusable rows are skipped."""
    out = []
    for r in rows or ():
        if isinstance(r, dict):
            r = (r.get("group"), r.get("item"), r.get("quantity"),
                 r.get("unit"), r.get("how"))
        try:
            g, item, q, unit = (list(r) + [None] * 4)[:4]
            how = r[4] if len(r) > 4 else ""
            if isinstance(q, bool):
                continue
            q = float(str(q).replace(",", ""))
        except (TypeError, ValueError, IndexError):
            continue
        if not item or not math.isfinite(q) or q <= 0:
            continue
        out.append((str(g or ""), str(item).strip(), q,
                    str(unit or "").strip().upper(), str(how or "")))
    return out


def _plan_rooms(plan):
    """[(room, level plan)] of a Generate Set plan, every level."""
    if not isinstance(plan, dict):
        return []
    lvls = [plan] + ([plan["upper"]] if isinstance(plan.get("upper"), dict)
                     else []) + [f for f in plan.get("floors") or ()
                                 if isinstance(f, dict)]
    out = []
    for lp in lvls:
        for r in lp.get("rooms") or ():
            if isinstance(r, dict) and isinstance(r.get("rect"),
                                                  (list, tuple)) and \
                    len(r["rect"]) == 4:
                out.append((r, lp))
    return out


def set_quantities(rows=(), plan=None, source="genset"):
    """{quantity name: (value, how)} from a Generate Set set: its quantity
    rows (group, item, qty, unit, how - the .quantities.csv or the rows
    embedded in the PDF) and, when there is one, its plan (.genset.json:
    rooms with their finishes and ceiling heights). Only what the set
    gives; the rest stays estimated."""
    rows = _rows_of(rows)
    out = {}

    def tot(pred, unit=None):
        got = [(i, q) for _g, i, q, u, _h in rows if pred(i) and
               (unit is None or u == unit)]
        return sum(q for _i, q in got), [i for i, _q in got]

    def put(key, val, what):
        if val and val > 0:
            out[key] = (val, f"{source}: {what}")
    floor_by, ceil_by = {}, {}
    for _g, i, q, u, _h in rows:
        if i.startswith("Floor finish") and u == "SF":
            c = _code(i, "Floor finish")
            floor_by[c] = floor_by.get(c, 0) + q
        elif i.startswith("Ceiling") and u == "SF":
            c = _code(i, "Ceiling")
            ceil_by[c] = ceil_by.get(c, 0) + q
    put("floor", sum(floor_by.values()), "room areas")
    v, _n = tot(lambda i: i.startswith("Slab on grade"), "SF")
    put("footprint", v, "slab on grade")
    v, _n = tot(lambda i: i.startswith("Perimeter footing"), "LF")
    put("perimeter", v, "perimeter footing")
    v, _n = tot(lambda i: i == "Roofing squares", "SQ")
    roof_how = "roof area (pitched roof, roofing squares)"
    if not v:
        v, _n = tot(lambda i: re.match(r"(?:Roof,|Low-slope roof|Metal "
                                       r"roof)", i), "SF")
        v /= 100.0
        roof_how = "roof area (low-slope)" if any(
            i.startswith("Low-slope roof") for _g, i, _q, _u, _h in rows) \
            else "roof area"
    put("roof_sq", v, roof_how)
    v, _n = tot(lambda i: re.search(r"Exterior wall area, net|wall "
                                    r"panels, net", i), "SF")
    put("wall_sf", v, "exterior wall area, net")
    # what the structure is, when the set says (review 0.12.39): tilt-up
    # wall panels, or PEMB frames - structure_family() picks its rate
    v, _n = tot(lambda i: re.match(r"Tilt-?up wall panels, net", i, re.I),
                "SF")
    put("tilt_up_sf", v, "tilt-up wall panels, net")
    v, _n = tot(lambda i: re.match(r"PEMB\b", i), "EA")
    put("pemb_frames", v, "PEMB frames")
    gl = 0.0
    for _g, i, q, u, h in rows:
        if i.startswith("Window") and u == "EA":
            m = re.search(r"(\d+'(?:-[\d.]+\")?)\s*x\s*(\d+'(?:-[\d.]+"
                          r"\")?)", h or i)
            gl += q * (_ftin(m.group(1)) * _ftin(m.group(2)) if m else 12.0)
    put("glazing_sf", gl, "windows by type and size")
    part, _n = tot(lambda i: re.search(r"(?:Interior|Office) partitions",
                                       i), "LF")
    put("partition_lf", part, "partitions")
    v, _n = tot(lambda i: re.match(r"Door\b", i), "EA")
    put("doors", v, "door schedule (overhead doors apart)")
    v, _n = tot(lambda i: re.match(r"Overhead door", i), "EA")
    put("overhead_doors", v, "overhead doors in the door schedule")
    v, _n = tot(lambda i: re.match(r"Dock levelers?", i), "EA")
    put("dock_levelers", v, "dock levelers")
    v, _n = tot(lambda i: re.search(r"\bstorefront\b", i, re.I), "SF")
    if not v:
        v, _n = tot(lambda i: re.search(r"\bstorefront\b", i, re.I), "EA")
    put("storefront", v, "storefront in the window / door schedule")
    v, _n = tot(lambda i: re.search(r"paving|\bwalk\b", i, re.I), "SF")
    put("paving_sy", v / 9.0, "paving")
    fin_floor = sum(a for c, a in floor_by.items() if c not in _UNFINISHED)
    fin_ceil = sum(a for c, a in ceil_by.items() if c not in _UNFINISHED)
    gwb_ceil = sum(a for c, a in ceil_by.items() if c.startswith("GWB"))
    put("finish_floor_sf", fin_floor, "floor finishes (" + ", ".join(
        sorted(c for c in floor_by if c not in _UNFINISHED)) + ")")
    put("ceiling_sf", fin_ceil, "ceiling finishes (" + ", ".join(
        sorted(c for c in ceil_by if c not in _UNFINISHED)) + ")")
    board, _n = tot(lambda i: i.startswith(("Gypsum board", "L1 Gypsum",
                                            "L2 Gypsum", "L3 Gypsum")) or
                    re.match(r"L\d+ Gypsum board", i), "SF")
    rooms = _plan_rooms(plan)
    finished = max(fin_floor, fin_ceil)
    paint = board + gwb_ceil if board else 0.0
    how_b = "gypsum board, walls + GWB ceilings"
    if rooms:                     # the plan: room by room
        board_r = paint_r = fin_r = 0.0
        for r, lp in rooms:
            x0, y0, x1, y1 = (float(x) for x in r["rect"])
            area = abs((x1 - x0) * (y1 - y0))
            f = r.get("finishes") or {}
            walls = str(f.get("walls") or "").upper()
            fl = str(f.get("floor") or "").upper()
            ce = str(f.get("ceiling") or "").upper()
            if walls in _UNFINISHED and fl in _UNFINISHED and \
                    ce in _UNFINISHED:
                continue                       # warehouse bay, shop floor
            fin_r += area
            h = r.get("ceiling_ht") or (lp.get("level") or {}).get(
                "ceiling_ht") or 9.0
            try:
                h = float(h)
            except (TypeError, ValueError):
                h = 9.0
            wall = 2 * (abs(x1 - x0) + abs(y1 - y0)) * h
            if "GWB" in walls:
                board_r += wall
                if walls != "GWB":             # GWB-PT, GWB-MR: painted
                    paint_r += wall
            if ce.startswith("GWB"):
                board_r += area
                paint_r += area
        if fin_r:
            finished = fin_r
        if not board and board_r:
            board, paint = board_r, paint_r
            how_b = "finished rooms' walls x ceiling height + GWB ceilings"
    elif not board and part:
        board = part * 2 * 10.0 + gwb_ceil
        paint = board
        how_b = "partitions both sides x 10 ft + GWB ceilings"
    elif board:
        board += gwb_ceil
    put("board_sf", board, how_b)
    put("paint_sf", paint, how_b.replace("gypsum board", "painted board"))
    put("finished_sf", finished, "finished rooms (office / finished "
        "zones)")
    return out


def finished_area(sc, table=None):
    """(finished SF, how, share) of the floor: Generate Set's finished rooms
    (set quantities), the finished rooms among the room tags when part of
    the building is unfinished space (a warehouse bay), an assumed office
    share for a warehouse with no finish data, else the whole floor - the
    fallback."""
    table = table or load()
    floor = max(1.0, float(sc.get("area_sf") or 5000.0))
    setq = sc.get("set_quantities") or {}
    if setq.get("finished_sf"):
        return min(floor, setq["finished_sf"][0]), setq["finished_sf"][1], \
            None
    rooms = [r for r in sc.get("rooms") or () if isinstance(r, dict) and
             float(r.get("sf") or 0) > 0]
    tagged = sum(float(r["sf"]) for r in rooms)
    unfin = sum(float(r["sf"]) for r in rooms
                if _UNFINISHED_ROOM.search(str(r.get("name") or "")))
    if tagged and unfin >= UNFINISHED_SHARE * tagged and unfin < tagged:
        fin = (tagged - unfin) * floor / tagged
        return fin, (f"room tags (takeoff) - finished rooms {fin:,.0f} SF, "
                     f"the {unfin:,.0f} SF of warehouse / bay rooms left "
                     "out"), None
    if sc.get("warehouse") and not tagged:
        share = table["assumptions"].get("warehouse_office_share", 0.10)
        return floor * share, (f"warehouse: office / finished area "
                               f"assumed {share:.0%} of the floor - floor "
                               "area (fallback)"), share
    return floor, "floor area (fallback)", None


def estimates(sc, table=None):
    """{quantity name: (value, how)} from the floor area and levels - and
    from the Generate Set quantities when the set has them (and its floor
    area is within SET_AREA_TOLERANCE of the job's - set_area_check)."""
    table = table or load()
    a = table["assumptions"]
    floor = max(1.0, float(sc.get("area_sf") or 5000.0))
    stories = max(1, int(sc.get("stories") or 1))
    fp = floor / stories
    r = max(1.0, a["footprint_ratio"])
    w = math.sqrt(fp / r)
    per = 2 * (r * w + w)
    site = fp * a["site_factor"]
    sw = math.sqrt(site / r)
    src = "floor area" if sc.get("area_found", True) else \
        "assumed 5,000 SF floor area"
    fps = f"footprint = {floor:,.0f} SF / {stories} level" + \
        ("s" if stories > 1 else "")
    pers = f"perimeter of a {r:g}:1 rectangle of the footprint, est."
    fin, fin_how, _share = finished_area(sc, table)
    fin = min(fin, floor)
    if fin_how == "floor area (fallback)":
        fin_s = "floor area (fallback)"
    else:
        fin_s = f"{fin:,.0f} SF finished area ({fin_how})"
    out = {
        "floor": (floor, src),
        "footprint": (fp, fps),
        "perimeter": (per, pers),
        "roof_sq": (fp / 100.0, "roof = footprint"),
        "wall_sf": (per * a["story_height_ft"] * stories,
                    f"perimeter {per:,.0f} LF x {a['story_height_ft']:g} ft"
                    f" x {stories} level" + ("s" if stories > 1 else "")),
        "site_sf": (site, f"site = footprint x {a['site_factor']:g}, est."),
        "site_perimeter": (2 * (r * sw + sw), "site perimeter, est."),
        "board_sf": (fin * a["board_factor"],
                     f"{a['board_factor']:g} SF per SF of {fin_s}, est."),
        "paint_sf": (fin * a["paint_factor"],
                     f"{a['paint_factor']:g} SF per SF of {fin_s}, est."),
        "ceiling_sf": (fin * a["ceiling_factor"],
                       f"{a['ceiling_factor']:g} x {fin_s}, est."),
        "glazing_sf": (per * a["story_height_ft"] * stories *
                       a["glazing_share"],
                       f"{a['glazing_share'] * 100:g}% of the wall area, "
                       "est."),
        "doors": (fin / max(1.0, a["sf_per_door"]),
                  f"1 per {a['sf_per_door']:,.0f} SF of {fin_s}, est."),
        "partition_lf": (fin * a["partition_lf_per_sf"],
                         f"{a['partition_lf_per_sf']:g} LF per SF of "
                         f"{fin_s}, est."),
        "finish_floor_sf": (fin, fin_s),
        "finished_sf": (fin, fin_s),
        "overhead_doors": (0.0, "no overhead doors counted"),
        "paving_sy": (fp * a["paving_factor"] / 9.0,
                      f"paved area = footprint x {a['paving_factor']:g}, "
                      "est."),
        "landscape_sf": (fp * a["landscape_factor"],
                         f"footprint x {a['landscape_factor']:g}, est."),
    }
    pipe = float(sc.get("pipe_lf") or 0)
    out["pipe_lf"] = (pipe, "takeoff: pipe") if pipe > 0 else \
        (per, "about one building perimeter of service runs, est.")
    setq = sc.get("set_quantities") or {}
    use, set_floor, gap = set_area_check(sc)
    for k, v in setq.items():          # the set's own numbers win
        if k in out and v and v[0] > 0 and (use or k in SET_COUNTS):
            how = str(v[1])
            if k == "floor" and use and gap > SET_AREA_NOTE:
                how += (f" {set_floor:,.0f} SF; the drawing text reads "
                        f"{floor:,.0f} SF ({gap:.1%} apart) - the set's "
                        "quantities used")
            out[k] = (float(v[0]), how)
    return out


# Generate Set quantities vs the floor area read from the drawing text:
# the set's own numbers win (its rooms are measured; the area on the sheet
# is a gross figure read from text) unless the areas are so far apart the
# area was changed by hand or the set is another building's. Counts that
# don't scale with the area (overhead doors, dock levelers) are kept even
# then.
SET_AREA_TOLERANCE = 0.15
SET_AREA_NOTE = 0.05
SET_COUNTS = ("overhead_doors", "dock_levelers")


def set_area_check(sc):
    """(use the set's quantities?, the set's floor area, share apart) for a
    scope with Generate Set quantities - share apart is |set - read| /
    read, 0.0 when the set gives no floor area."""
    setq = sc.get("set_quantities") or {}
    floor = max(1.0, float(sc.get("area_sf") or 5000.0))
    set_floor = float((setq.get("floor") or (0,))[0] or 0)
    if not setq:
        return False, set_floor, 0.0
    if not set_floor:
        return True, 0.0, 0.0
    gap = abs(set_floor - floor) / floor
    return gap <= SET_AREA_TOLERANCE, set_floor, gap


def structure_family(sc, table=None):
    """Which structure family the "Structure" row uses: what was taken off
    (tilt-up / CMU / steel / wood), else what a Generate Set set says it
    is (tilt-up panels, PEMB frames), else the one structure division the
    specs name, else wood framing for a house (residential words, no
    steel, no warehouse), else the mixed rate."""
    table = table or load()
    items = sc.get("takeoff") or ()
    for key in ("tilt_up", "cmu", "steel_erection", "wood_framing"):
        if key in table["families"] and takeoff_quantity(
                key, table["families"][key], items, table):
            return key
    setq = sc.get("set_quantities") or {}
    if setq.get("tilt_up_sf") and "tilt_up" in table["families"]:
        return "tilt_up"
    if setq.get("pemb_frames"):
        return "steel_erection"
    flags = set(sc.get("building_flags") or ()) | set(sc.get("flags") or ())
    named = [k for flag, k in (("masonry", "cmu"),
                               ("steel", "steel_erection"),
                               ("wood", "wood_framing")) if flag in flags]
    if len(named) == 1:
        return named[0]
    if not named and sc.get("residential") and not sc.get("warehouse") \
            and not sc.get("joists_named"):
        return "wood_framing"
    return "structure"


def exterior_family(sc, table=None):
    """The "Exterior walls & finishes" row's family: the tilt-up panel
    finishes when the structure is tilt-up panels (the panels are the
    wall), else the cladding rate."""
    table = table or load()
    if structure_family(sc, table) == "tilt_up" and \
            "panel_finish" in table["families"]:
        return "panel_finish"
    return "exterior_walls"


def family_for(type_key, act_key, sc, table=None):
    fam = ACTIVITY_FAMILIES.get(type_key or "new_building", {}).get(act_key)
    if fam == "@structure":
        fam = structure_family(sc, table)
    elif fam == "@exterior":
        fam = exterior_family(sc, table)
    return fam


def quantity(key, sc, table=None, est=None):
    """(value, how, from_takeoff) of a family's quantity for the scope."""
    table = table or load()
    fam = table["families"][key]
    got = takeoff_quantity(key, fam, sc.get("takeoff") or (), table)
    if got:
        return got[0], got[1], True
    est = est or estimates(sc, table)
    qk = FINISHED_QTY.get(key) if fam["qty"] == "floor" else None
    v, how = est[qk if qk in est else fam["qty"]]
    if key in ROOF_AREA_QTY and fam["qty"] == "footprint" and \
            fam["unit"] == "SF":
        # the roof framing covers the roof the set measures, not its slab
        # (review 0.12.39 #3: "38,295 SF roof (genset: slab on grade)")
        rv, rhow = est.get("roof_sq") or (0, "")
        if rv and rv > 0 and str(rhow).startswith(("takeoff", "genset")):
            v, how = rv * 100.0, rhow
    if how.startswith(("takeoff", "genset")):      # measured, not estimated
        return v, how, True
    return v, how, False


def _num_text(v):
    return f"{v:,.0f}" if v >= 10 else f"{v:,.1f}".rstrip("0").rstrip(".")


def band_crews(key, area, table=None):
    """(crews, band text) for a family on a job whose band area (floor,
    finished area or roof - CREW_BAND) is `area` SF: the Crews column, or
    more on a large job - (area / crew_band_sf) ^ 0.5, to 0.1 crew,
    between the Crews column and max_crews (a job 4x the band: 2 crews;
    9x: 3). The square root keeps the durations growing with the job
    (crews and crew sizes grow slower than the floor) with no jump at a
    band edge. The text is "" when the band adds nothing."""
    table = table or load()
    fam = table["families"][key]
    base = max(1e-9, float(fam["crews"]))
    a = table["assumptions"]
    band = float(a.get("crew_band_sf") or 0)
    most = float(a.get("max_crews") or 1)
    if key not in CREW_BAND or band <= 0 or not area or area <= 0:
        return base, ""
    n = min(max(1.0, most), round(math.sqrt(area / band), 1))
    if n <= base:
        return base, ""
    what = {"floor": "floor", "finished": "finished area",
            "roof": "roof"}[CREW_BAND[key]]
    return n, (f"{n:g} crews by area band: ({area:,.0f} SF {what} / "
               f"{band:,.0f} SF)^0.5, at most {most:g}")


def duration(key, q, table=None, crews=None, band=""):
    """(days, basis text) = ceil(q / (rate x crews)) within min..max.
    `crews`: the crews to use (band_crews()), else the Crews column;
    `band`: what the area band says about them, added to the text."""
    table = table or load()
    fam = table["families"][key]
    rate = max(1e-9, float(fam["rate"]))
    crews = max(1e-9, float(crews if crews else fam["crews"]))
    raw = int(math.ceil(q / (rate * crews) - 1e-9)) if q > 0 else 0
    mn, mx = int(round(fam["min"])), int(round(fam["max"]))
    d = min(max(raw, mn), mx)
    unit = fam["unit"]
    crew_s = f"{crews:g} crew" + ("s" if crews != 1 else "")
    text = (f"{_num_text(q)} {unit} {fam['of']} / ({rate:,g} {unit}/day x "
            f"{crew_s}) = {raw} d")
    if d > raw:
        text += f", raised to the {mn} d minimum"
    elif d < raw:
        text += f", capped at the {mx} d maximum"
    if band:
        text += f"; {band}"
    text += f" ({YOURS if key in table.get('edited', ()) else ASSUMED})"
    return d, text


# A warehouse with an office (review 0.12.38 T8): the interior insulation
# and the trim after painting are the office's - the bay's walls are
# insulated with the exterior wall panels, and the bay's lights and
# devices are trimmed out after the rough-in inspections ("bay_trim"),
# not after the office is painted.
BAY_SHARE = 0.6        # finished area at most this share of the floor


def has_bay(sc, table=None):
    """(finished SF, floor SF) when the building is a warehouse whose
    finished (office) area is a small part of the floor, else None."""
    if not sc.get("warehouse"):
        return None
    table = table or load()
    floor = max(1.0, float(sc.get("area_sf") or 5000.0))
    fin = min(floor, finished_area(sc, table)[0])
    return (fin, floor) if fin <= BAY_SHARE * floor else None


# the warehouse bay's MEP is lighter than the office's (review 0.12.39):
# these activities count the bay at bay_rough_share of its area
BAY_ROUGH = ("plumb_rough", "hvac_rough", "elec_rough", "underslab",
             "bay_trim")


def _bay_quantity(act_key, sc, table, est):
    """(value, how, measured) for the activities a warehouse bay splits
    (insulation, mep_trim, bay_trim) or weights (the MEP rough-ins and
    the under-slab work - BAY_ROUGH), else None."""
    if act_key not in ("insulation", "mep_trim") + BAY_ROUGH:
        return None
    bay = has_bay(sc, table)
    if not bay:
        return None
    fin, floor = bay
    measured = ("takeoff", "genset")
    share = float(table["assumptions"].get("bay_rough_share", 1.0))
    if act_key == "insulation":
        v, how = est["board_sf"]
        return v, (how + "; the warehouse bay's walls are insulated with "
                   "the exterior wall panels"), how.startswith(measured)
    v, how = est["finished_sf"]
    if act_key == "mep_trim":
        return v, how + " - the office; the bay has its own trim row", \
            how.startswith(measured)
    fl, fl_how = est["floor"]
    bay_sf = max(0.0, max(fl, floor) - v)
    if act_key == "bay_trim":
        return bay_sf * share, (
            f"warehouse bay: floor less the {v:,.0f} SF finished "
            f"({fl_how}), x {share:g} bay MEP density"), \
            fl_how.startswith(measured)
    # the rough-ins / under-slab: the office at full density, the bay at
    # `share` of it (the bay's lights, unit heaters, a few hose bibbs)
    eff = v + bay_sf * share
    weights = (f"office {v:,.0f} SF + warehouse bay {bay_sf:,.0f} SF x "
               f"{share:g} bay MEP density")
    if act_key == "underslab":
        fp, fp_how = est["footprint"]
        tot = max(1.0, v + bay_sf)
        return fp * eff / tot, f"{fp_how}; {weights}", \
            fp_how.startswith(measured)
    return eff, f"{fl_how}; {weights}", fl_how.startswith(measured)


def _band_area(key, act_key, sc, est):
    """The area (SF) a family's crews are banded on (CREW_BAND)."""
    kind = CREW_BAND.get(key)
    if kind == "floor":
        return float(est["floor"][0])
    if kind == "finished":
        return float(est["finished_sf"][0])
    if kind == "roof":
        return float(est["roof_sq"][0]) * 100.0
    return 0.0


def size(type_key, act_key, sc, table=None, est=None):
    """For an activity the table sizes: {"family", "duration", "basis",
    "quantity", "unit", "from_takeoff"}; None when no family applies."""
    table = table or load()
    key = family_for(type_key, act_key, sc, table)
    if not key or key not in table["families"]:
        return None
    est = est or estimates(sc, table)
    q, how, tk = _bay_quantity(act_key, sc, table, est) or \
        quantity(key, sc, table, est)
    crews, band = band_crews(key, _band_area(key, act_key, sc, est), table)
    d, text = duration(key, q, table, crews, band)
    fam = table["families"][key]
    return {"family": key, "duration": d, "quantity": q, "crews": crews,
            "unit": fam["unit"], "from_takeoff": tk,
            "basis": text.replace(f"{fam['of']} /", f"{fam['of']} ({how}) /",
                                  1)}
