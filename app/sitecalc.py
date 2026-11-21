"""Earthwork, aggregate / asphalt, drywall and paint calculators (Nov 20).

Plain arithmetic with the usual estimating rules of thumb as editable
defaults - swell and shrink of soil, tons per cubic yard of stone and
hot mix, tape and joint compound per 1,000 SF of board, paint coverage
per gallon. Check the geotech report, the supplier's numbers and the
product data before ordering; every default is a field in the window.
No Qt here (calculators_ui.py).
"""
import math

CY = 27.0
SWELL_PCT = 25.0          # common earth, bank to loose
SHRINK_PCT = 10.0         # bank to compacted
TRUCK_CY = 12.0           # loose CY a tandem dump carries
TONS_PER_CY = {"Crushed stone / gravel": 1.40, "Sand": 1.35,
               "Topsoil": 1.10, "Asphalt (hot mix)": 2.00,
               "Recycled concrete": 1.25}
BOARD_SF = {"4 x 8": 32.0, "4 x 10": 40.0, "4 x 12": 48.0}
TAPE_LF_PER_1000 = 370.0
COMPOUND_LB_PER_1000 = 140.0
SCREWS_PER_1000 = 1000.0
PAINT_SF_PER_GAL = 350.0


def _pos(v, name, zero_ok=True):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: not a number")
    if not math.isfinite(f) or f < 0 or (f == 0 and not zero_ok):
        raise ValueError(f"{name}: must be more than 0" if not zero_ok
                         else f"{name}: must be 0 or more")
    return f


def _up(x, step=1.0):
    return math.ceil(round(x / step, 9)) * step if x else 0


# --------------------------------------------------------------- earthwork
def excavation(length_ft=0.0, width_ft=0.0, depth_ft=0.0, bank_cy=None,
               swell_pct=SWELL_PCT, shrink_pct=SHRINK_PCT,
               truck_cy=TRUCK_CY):
    """Bank (in place), loose (hauled) and compacted CY and truck loads
    for a cut L x W x D, or a bank volume already worked out."""
    bank = _pos(bank_cy, "bank CY") if bank_cy is not None else \
        _pos(length_ft, "length") * _pos(width_ft, "width") * \
        _pos(depth_ft, "depth") / CY
    loose = bank * (1 + _pos(swell_pct, "swell") / 100)
    compacted = bank * (1 - _pos(shrink_pct, "shrink") / 100)
    return {"bank_cy": bank, "loose_cy": loose, "compacted_cy": compacted,
            "loads": int(_up(loose / _pos(truck_cy, "truck CY",
                                           zero_ok=False)))}


def trench(length_ft, depth_ft, bottom_w_ft, side_slope=0.0, pipe_in=0.0,
           bedding_in=6.0, swell_pct=SWELL_PCT, truck_cy=TRUCK_CY):
    """A trench with sloped sides (`side_slope` horizontal per 1 vertical,
    0 for vertical walls): excavation; bedding as the bottom width x
    `bedding_in`; backfill as the rest less the pipe's own volume."""
    L = _pos(length_ft, "length")
    D = _pos(depth_ft, "depth")
    B = _pos(bottom_w_ft, "bottom width")
    z = _pos(side_slope, "side slope")
    top = B + 2 * z * D
    area = (B + top) / 2 * D
    exc = area * L / CY
    pipe = math.pi * (_pos(pipe_in, "pipe size") / 24) ** 2 * L / CY
    bed = B * _pos(bedding_in, "bedding") / 12 * L / CY
    back = max(0.0, exc - pipe - bed)
    loose = exc * (1 + _pos(swell_pct, "swell") / 100)
    return {"top_width_ft": top, "excavation_cy": exc, "bedding_cy": bed,
            "backfill_cy": back, "pipe_cy": pipe, "loose_cy": loose,
            "loads": int(_up(loose / _pos(truck_cy, "truck CY",
                                           zero_ok=False)))}


# -------------------------------------------------------- aggregate/asphalt
def material_tons(area_sf, thick_in, tons_per_cy, waste_pct=5.0):
    """CY and tons for a layer of stone, sand or hot mix over an area."""
    cy = _pos(area_sf, "area") * _pos(thick_in, "thickness") / 12 / CY
    w = 1 + _pos(waste_pct, "waste") / 100
    t = cy * w * _pos(tons_per_cy, "tons per CY", zero_ok=False)
    return {"cy": cy, "cy_with_waste": cy * w, "tons": t}


# ------------------------------------------------------------------ drywall
def drywall(wall_sf=0.0, ceiling_sf=0.0, openings_sf=0.0, board="4 x 8",
            layers=1, waste_pct=10.0, tape_per_1000=TAPE_LF_PER_1000,
            compound_per_1000=COMPOUND_LB_PER_1000,
            screws_per_1000=SCREWS_PER_1000):
    """Boards, tape, joint compound and screws for walls and ceilings."""
    net = max(0.0, _pos(wall_sf, "wall area") + _pos(ceiling_sf,
              "ceiling area") - _pos(openings_sf, "openings"))
    net *= max(1, int(_pos(layers, "layers")))
    if board not in BOARD_SF:
        raise ValueError(f"board: one of {', '.join(BOARD_SF)}")
    w = 1 + _pos(waste_pct, "waste") / 100
    k = net / 1000
    return {"net_sf": net,
            "boards": int(_up(net * w / BOARD_SF[board])),
            "tape_lf": _up(k * _pos(tape_per_1000, "tape")),
            "compound_lb": _up(k * _pos(compound_per_1000, "compound")),
            "screws": int(_up(k * _pos(screws_per_1000, "screws")))}


# -------------------------------------------------------------------- paint
def paint(area_sf, coats=2, sf_per_gal=PAINT_SF_PER_GAL, primer_coats=0,
          primer_sf_per_gal=300.0, waste_pct=10.0):
    """Gallons of finish and primer, and the same as 5-gallon pails plus
    gallons."""
    A = _pos(area_sf, "area")
    w = 1 + _pos(waste_pct, "waste") / 100
    fin = A * int(_pos(coats, "coats")) * w / _pos(sf_per_gal, "coverage",
                                                   zero_ok=False)
    pri = A * int(_pos(primer_coats, "primer coats")) * w / \
        _pos(primer_sf_per_gal, "primer coverage", zero_ok=False)

    def pails(g):
        g = int(_up(g))
        return g, g // 5, g % 5
    f, p = pails(fin), pails(pri)
    return {"finish_gal": f[0], "finish_pails": f[1], "finish_extra": f[2],
            "primer_gal": p[0], "primer_pails": p[1], "primer_extra": p[2]}
