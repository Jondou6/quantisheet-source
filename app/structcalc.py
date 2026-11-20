"""Rebar, beam, column and footing calculators (Nov 19, Jon: "build
calculators like these for QuantiSheet - build legally").

Written here from public engineering math (statics, beam formulas from
any mechanics text, Euler / Ylinen column buckling, the standard steel
column curve), plus published sizes that are facts: ASTM A615 bar
weights and diameters, sawn lumber dressed sizes. No code tables are
copied in: the user types the allowable stresses, the soil pressure and
the steel section properties from the drawings, the structural notes or
the supplier.

These are PRELIMINARY checks for estimating (is a 4x10 header in the
right range, how much rebar, about how big is the pad) - never an
engineering design. The drawings and the engineer of record govern.

Units: feet, inches, pounds, psi. No Qt here (calculators_ui.py).
"""
import math

DISCLAIMER = ("Preliminary - for estimating only, not an engineering "
              "design. The drawings and the engineer of record govern.")

# ASTM A615 / A706 bars: size -> (nominal diameter in, weight lb per ft)
BARS = {3: (0.375, 0.376), 4: (0.500, 0.668), 5: (0.625, 1.043),
        6: (0.750, 1.502), 7: (0.875, 2.044), 8: (1.000, 2.670),
        9: (1.128, 3.400), 10: (1.270, 4.303), 11: (1.410, 5.313),
        14: (1.693, 7.650), 18: (2.257, 13.600)}
STOCK_FT = 20.0                    # stock bar length
LAP_DIAMETERS = 40                 # a common rule of thumb; the drawings govern
CONCRETE_PCF = 150.0


def _pos(v, name, zero_ok=True):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: not a number")
    if not math.isfinite(f) or f < 0 or (f == 0 and not zero_ok):
        raise ValueError(f"{name}: must be more than 0" if not zero_ok
                         else f"{name}: must be 0 or more")
    return f


# ------------------------------------------------------------------ rebar
def lap_in(bar, diameters=LAP_DIAMETERS):
    """A lap splice as a number of bar diameters (40 by default)."""
    return BARS[int(bar)][0] * _pos(diameters, "lap diameters")


def run_lf(length_ft, bar, stock_ft=STOCK_FT, diameters=LAP_DIAMETERS):
    """Bar length for one continuous run of `length_ft`, with a lap at
    every stock-length joint: (lf, laps)."""
    L = _pos(length_ft, "length")
    stock = _pos(stock_ft, "stock length", zero_ok=False)
    lap = lap_in(bar, diameters) / 12
    if L <= stock:
        return L, 0
    if lap >= stock:
        raise ValueError("the lap is longer than a stock bar")
    laps = math.ceil(round((L - stock) / (stock - lap), 9))
    return L + laps * lap, laps


def rebar_grid(length_ft, width_ft, spacing_in, bar=4, cover_in=3.0,
               each_way=True, waste_pct=5.0, stock_ft=STOCK_FT,
               diameters=LAP_DIAMETERS):
    """Bars for a slab or mat: bars across the width at the spacing, each
    the length less cover (and the same the other way when `each_way`).
    {bars, lf, laps, lb, tons, lb_with_waste}."""
    L, W = _pos(length_ft, "length"), _pos(width_ft, "width")
    s = _pos(spacing_in, "spacing", zero_ok=False) / 12
    c = _pos(cover_in, "cover") / 12
    out = {"bars": 0, "lf": 0.0, "laps": 0}
    runs = [(L, W)] + ([(W, L)] if each_way else [])
    for run, across in runs:
        if run <= 2 * c or across <= 2 * c:
            continue
        n = int(math.floor(round((across - 2 * c) / s, 9))) + 1
        lf, laps = run_lf(run - 2 * c, bar, stock_ft, diameters)
        out["bars"] += n
        out["lf"] += n * lf
        out["laps"] += n * laps
    return _weigh(out, bar, waste_pct, stock_ft)


def rebar_linear(length_ft, count=1, bar=5, waste_pct=5.0,
                 stock_ft=STOCK_FT, diameters=LAP_DIAMETERS):
    """Continuous bars along a footing or wall (`count` bars side by
    side), lapped at stock lengths."""
    lf, laps = run_lf(length_ft, bar, stock_ft, diameters)
    n = int(_pos(count, "bars"))
    return _weigh({"bars": n, "lf": lf * n, "laps": laps * n}, bar,
                  waste_pct, stock_ft)


def rebar_area(area_sf, spacing_in, bar=4, each_way=True, waste_pct=5.0,
               stock_ft=STOCK_FT, diameters=LAP_DIAMETERS):
    """Bars for a slab from its takeoff area alone (no length and width):
    area x 12 / spacing feet of bar each way, plus laps as the share a
    lap takes of a stock bar."""
    A = _pos(area_sf, "area")
    s = _pos(spacing_in, "spacing", zero_ok=False)
    stock = _pos(stock_ft, "stock length", zero_ok=False)
    lap = lap_in(bar, diameters) / 12
    if lap >= stock:
        raise ValueError("the lap is longer than a stock bar")
    lf = A * 12 / s * (2 if each_way else 1)
    lapped = lf * stock / (stock - lap)
    return _weigh({"bars": 0, "lf": lapped,
                   "laps": int(round(lapped - lf) / lap) if lap else 0},
                  bar, waste_pct, stock)


def _weigh(out, bar, waste_pct, stock_ft=STOCK_FT):
    w = BARS[int(bar)][1]
    waste = _pos(waste_pct, "waste")
    out["lb"] = out["lf"] * w
    out["lb_with_waste"] = out["lb"] * (1 + waste / 100)
    out["tons"] = out["lb_with_waste"] / 2000
    out["sticks"] = int(math.ceil(round(out["lf"] * (1 + waste / 100)
                                        / stock_ft, 9))) if out["lf"] else 0
    return out


# ------------------------------------------------------------- sections
def dressed(nominal):
    """Sawn lumber dressed (actual) size in inches from the nominal:
    2 -> 1.5, 4 -> 3.5, 6 -> 5.5, 8 -> 7.25, 10 -> 9.25, 12 -> 11.25."""
    n = _pos(nominal, "nominal size", zero_ok=False)
    if n < 2:
        return n
    return n - 0.5 if n <= 6 else n - 0.75


def rect_section(b_in, d_in, plies=1):
    """A, S, I of a solid rectangle (or plies side by side)."""
    b = _pos(b_in, "width", zero_ok=False) * int(_pos(plies, "plies",
                                                      zero_ok=False))
    d = _pos(d_in, "depth", zero_ok=False)
    return {"A": b * d, "S": b * d * d / 6, "I": b * d ** 3 / 12, "b": b,
            "d": d}


# ------------------------------------------------------------------ beam
def beam(span_ft, w_plf=0.0, p_lb=0.0, a_ft=None, section=None, E_psi=None,
         Fb_psi=None, Fv_psi=None, defl_limit=360, rect=True, steps=400):
    """A simple span: uniform load w (plf, include the beam's weight) and
    one point load P at a (ft from the left; mid-span when None).
    {R1, R2, Vmax, Mmax (ft-lb), x_Mmax, defl_in, allow_defl_in, fb, fv,
    checks: [(name, actual, allowed, ok)]}. Bending fb = M/S; shear
    fv = 1.5 V / A for a rectangle (else V / A, the web area typed as A);
    deflection by superposition of the textbook formulas."""
    L = _pos(span_ft, "span", zero_ok=False)
    w = _pos(w_plf, "uniform load")
    P = _pos(p_lb, "point load")
    a = L / 2 if a_ft is None else _pos(a_ft, "load position")
    if a > L:
        raise ValueError("load position: past the end of the span")
    b = L - a
    R1 = w * L / 2 + P * b / L
    R2 = w * L / 2 + P * a / L
    # largest moment: check every point along the span and the load point
    best = (0.0, 0.0)
    for i in range(steps + 1):
        x = L * i / steps
        m = R1 * x - w * x * x / 2 - (P * (x - a) if x > a else 0.0)
        if m > best[0]:
            best = (m, x)
    m_at_a = R1 * a - w * a * a / 2
    if m_at_a > best[0]:
        best = (m_at_a, a)
    out = {"R1": R1, "R2": R2, "Vmax": max(R1, R2), "Mmax": best[0],
           "x_Mmax": best[1], "checks": []}
    if section and E_psi:
        E = _pos(E_psi, "E", zero_ok=False)
        I = section["I"]
        Lin = L * 12
        d_w = 5 * (w / 12) * Lin ** 4 / (384 * E * I)
        # point load: deflection at mid-span (near the largest for a
        # simple span), the textbook formula with the load at a
        ai, bi = min(a, b) * 12, max(a, b) * 12
        d_p = P * ai * (3 * Lin ** 2 - 4 * ai ** 2) / (48 * E * I)
        out["defl_in"] = d_w + d_p
        out["allow_defl_in"] = Lin / _pos(defl_limit, "deflection limit",
                                          zero_ok=False)
        out["checks"].append(("Deflection (in)", out["defl_in"],
                              out["allow_defl_in"],
                              out["defl_in"] <= out["allow_defl_in"]))
    if section and Fb_psi:
        out["fb"] = out["Mmax"] * 12 / section["S"]
        out["checks"].append(("Bending fb (psi)", out["fb"],
                              _pos(Fb_psi, "Fb"), out["fb"] <= Fb_psi))
    if section and Fv_psi:
        k = 1.5 if rect else 1.0
        out["fv"] = k * out["Vmax"] / section["A"]
        out["checks"].append(("Shear fv (psi)", out["fv"],
                              _pos(Fv_psi, "Fv"), out["fv"] <= Fv_psi))
    return out


# ---------------------------------------------------------------- columns
def wood_column(height_ft, b_in, d_in, Fc_psi, Emin_psi, K=1.0, c=0.8,
                plies=1):
    """Axial capacity of a solid rectangular wood post: the Ylinen column
    curve on the weak axis, with Fc and Emin as typed (already adjusted
    for the job). {le_d, FcE, Cp, Fc_star, P_allow_lb, slender_ok}."""
    sec = rect_section(b_in, d_in, plies)
    least = min(sec["b"], sec["d"])
    le = _pos(K, "K", zero_ok=False) * _pos(height_ft, "height",
                                             zero_ok=False) * 12
    le_d = le / least
    Fc = _pos(Fc_psi, "Fc", zero_ok=False)
    FcE = 0.822 * _pos(Emin_psi, "Emin", zero_ok=False) / le_d ** 2
    r = FcE / Fc
    c = _pos(c, "c", zero_ok=False)
    q = (1 + r) / (2 * c)
    Cp = q - math.sqrt(q * q - r / c)
    return {"le_d": le_d, "FcE": FcE, "Cp": Cp, "Fc_star": Fc * Cp,
            "P_allow_lb": Fc * Cp * sec["A"], "slender_ok": le_d <= 50,
            "A": sec["A"]}


def steel_column(height_ft, A_in2, r_in, Fy_psi=50000.0, E_psi=29e6, K=1.0,
                 method="ASD"):
    """Axial capacity of a steel column by the standard column curve:
    Fe = pi^2 E / (KL/r)^2; Fcr = 0.658^(Fy/Fe) Fy up to KL/r = 4.71
    sqrt(E/Fy), else 0.877 Fe; Pn = Fcr A. ASD allows Pn / 1.67, LRFD
    0.9 Pn. A and r (least radius of gyration) typed from the section."""
    A = _pos(A_in2, "area", zero_ok=False)
    r = _pos(r_in, "r", zero_ok=False)
    Fy = _pos(Fy_psi, "Fy", zero_ok=False)
    E = _pos(E_psi, "E", zero_ok=False)
    KLr = _pos(K, "K", zero_ok=False) * _pos(height_ft, "height",
                                              zero_ok=False) * 12 / r
    Fe = math.pi ** 2 * E / KLr ** 2
    Fcr = (0.658 ** (Fy / Fe)) * Fy if KLr <= 4.71 * math.sqrt(E / Fy) \
        else 0.877 * Fe
    Pn = Fcr * A
    allow = Pn / 1.67 if method == "ASD" else 0.9 * Pn
    return {"KLr": KLr, "Fe": Fe, "Fcr": Fcr, "Pn_lb": Pn,
            "P_allow_lb": allow, "slender_ok": KLr <= 200}


# ---------------------------------------------------------------- footings
def footing_size(load_lb, soil_psf, thick_in=12.0, kind="pad",
                 round_in=2.0):
    """Footing size for a column (pad, square) or a wall (continuous, per
    foot of wall: load in plf) from the allowable soil pressure, counting
    the footing's own weight. {side_ft or width_ft, bearing_psf, cy
    (pad each, or per 100 LF of wall)}."""
    P = _pos(load_lb, "load", zero_ok=False)
    q = _pos(soil_psf, "soil pressure", zero_ok=False)
    t = _pos(thick_in, "thickness", zero_ok=False) / 12
    net = q - CONCRETE_PCF * t
    if net <= 0:
        raise ValueError("the footing's own weight uses up the soil "
                         "pressure - make it thinner or check the soil")
    step = _pos(round_in, "round to", zero_ok=False) / 12
    if kind == "pad":
        side = math.ceil(round(math.sqrt(P / net) / step, 9)) * step
        return {"side_ft": side, "bearing_psf": P / side ** 2 +
                CONCRETE_PCF * t, "cy": side * side * t / 27}
    if kind == "continuous":
        width = math.ceil(round(P / net / step, 9)) * step
        return {"width_ft": width, "bearing_psf": P / width +
                CONCRETE_PCF * t, "cy": width * t * 100 / 27}
    raise ValueError("kind: pad or continuous")


# ------------------------------------------------- cold-formed steel framing
STEEL_PCF = 490.0
LB_FT_PER_IN2 = STEEL_PCF / 144.0          # 3.40 lb/ft per sq in
# the industry member name: depth (1/100 in), style, flange (1/100 in) -
# thickness (mils): 362S162-54 = 3-5/8" stud, 1-5/8" flange, 54 mil
_CFS = __import__("re").compile(r"^\s*(\d{3,4})\s*([STUF])\s*(\d{2,3})\s*-\s*"
                                r"(\d{2,3})\s*$", __import__("re").I)
CFS_STYLES = {"S": "stud / joist (with lips)", "T": "track",
              "U": "channel", "F": "furring channel"}


def cfs_member(name):
    """{depth_in, flange_in, lip_in, t_in, style, lb_ft} from a member name
    like 362S162-54. Weight from the shape's centerline length x base
    metal thickness x 490 pcf (corners not rounded off) - close to the
    makers' published figures, not one of them."""
    m = _CFS.match(str(name or ""))
    if not m:
        raise ValueError(f"{name!r}: write it like 362S162-54 (depth, S/T/U/"
                         "F, flange, mils)")
    depth = int(m.group(1)) / 100
    style = m.group(2).upper()
    flange = int(m.group(3)) / 100
    t = int(m.group(4)) / 1000
    lip = 0.0
    if style == "S":
        lip = 0.188 if flange < 1.4 else 0.5 if flange < 1.9 else 0.625
    length = depth + 2 * flange + 2 * lip
    return {"name": m.group(0).strip().upper(), "depth_in": depth,
            "flange_in": flange, "lip_in": lip, "t_in": t, "style": style,
            "lb_ft": length * t * LB_FT_PER_IN2}


def cfs_wall(length_ft, height_ft, spacing_in=16, openings=0, corners=0,
             per_opening=4, per_corner=2, bridging_ft=4.0, stud="362S162-33",
             track="362T125-33", waste_pct=5.0, track_piece_ft=10.0):
    """Metal stud wall quantities: studs at the spacing plus the ends,
    `per_opening` extra (jambs and cripples) and `per_corner` extra;
    top and bottom track; rows of bridging every `bridging_ft` up the
    wall. {studs, stud_lf, track_lf, track_pieces, bridging_lf, lb}."""
    L = _pos(length_ft, "wall length")
    H = _pos(height_ft, "wall height")
    s = _pos(spacing_in, "spacing", zero_ok=False) / 12
    w = 1 + _pos(waste_pct, "waste") / 100
    if L == 0 or H == 0:
        return {"studs": 0, "stud_lf": 0.0, "track_lf": 0.0,
                "track_pieces": 0, "bridging_lf": 0.0, "lb": 0.0}
    studs = math.ceil(round(L / s, 9)) + 1 + \
        int(_pos(openings, "openings")) * int(_pos(per_opening, "studs per "
                                                   "opening")) + \
        int(_pos(corners, "corners")) * int(_pos(per_corner, "studs per "
                                                 "corner"))
    studs = int(math.ceil(round(studs * w, 9)))
    track_lf = 2 * L * w
    rows = max(0, math.ceil(round(H / _pos(bridging_ft, "bridging",
                                            zero_ok=False), 9)) - 1)
    bridging_lf = rows * L * w
    st, tr = cfs_member(stud), cfs_member(track)
    return {"studs": studs, "stud_lf": studs * H, "track_lf": track_lf,
            "track_pieces": int(math.ceil(round(track_lf / _pos(
                track_piece_ft, "track piece", zero_ok=False), 9))),
            "bridging_lf": bridging_lf, "bridging_rows": rows,
            "stud_lb": studs * H * st["lb_ft"],
            "track_lb": track_lf * tr["lb_ft"],
            "lb": studs * H * st["lb_ft"] + track_lf * tr["lb_ft"]}


def cfs_joists(span_ft, width_ft, spacing_in=24, joist="800S200-54",
               rim="800T200-54", waste_pct=5.0):
    """Floor or roof joists across `width_ft`, each `span_ft` long, rim
    track both ends of the joists. {joists, joist_lf, rim_lf, lb}."""
    S = _pos(span_ft, "span")
    W = _pos(width_ft, "width")
    s = _pos(spacing_in, "spacing", zero_ok=False) / 12
    w = 1 + _pos(waste_pct, "waste") / 100
    if S == 0 or W == 0:
        return {"joists": 0, "joist_lf": 0.0, "rim_lf": 0.0, "lb": 0.0}
    n = int(math.ceil(round((math.ceil(round(W / s, 9)) + 1) * w, 9)))
    rim_lf = 2 * W * w
    j, r = cfs_member(joist), cfs_member(rim)
    return {"joists": n, "joist_lf": n * S, "rim_lf": rim_lf,
            "lb": n * S * j["lb_ft"] + rim_lf * r["lb_ft"]}


# ------------------------------------------------- structural steel weight
_RE = __import__("re")
_FRAC = r"(\d+(?:\.\d+)?(?:-\d+/\d+)?|\d+/\d+)"


def _num(t):
    """'1/4' 0.25, '1-1/2' 1.5, '0.375' 0.375."""
    t = t.strip()
    if "-" in t and "/" in t:
        whole, frac = t.split("-", 1)
        return float(whole) + _num(frac)
    if "/" in t:
        a, b = t.split("/")
        return float(a) / float(b)
    return float(t)


def shape_lb_ft(shape):
    """Weight per foot of a steel shape from its name:
    W, M, S, HP, C, MC, WT, MT, ST: the number after the x is the weight
    (W12x26 = 26 lb/ft); HSS6x4x1/4 (rectangular, corners rounded) and
    HSS6.625x0.280 or PIPE6.625x0.280 (round) from their size and
    nominal wall; L4x4x1/4 angles; PL1/2x12 plate (per foot of length);
    a round bar RD1 or square bar SQ1. Others raise ValueError."""
    s = str(shape or "").upper().replace(" ", "")
    m = _RE.match(r"^(W|M|S|HP|C|MC|WT|MT|ST)\d+(?:\.\d+)?X(\d+(?:\.\d+)?)$",
                  s)
    if m:
        return float(m.group(2))
    m = _RE.match(r"^HSS" + _FRAC + "X" + _FRAC + "X" + _FRAC + "$", s)
    if m:
        h, b, t = (_num(g) for g in m.groups())
        # nominal wall, corners rounded at 2t outside / t inside
        return LB_FT_PER_IN2 * (2 * t * (h + b - 2 * t) -
                                (4 - math.pi) * 3 * t * t)
    m = _RE.match(r"^(?:HSS|PIPE)" + _FRAC + "X" + _FRAC + "$", s)
    if m:
        d, t = (_num(g) for g in m.groups())
        return LB_FT_PER_IN2 * math.pi * t * (d - t)
    m = _RE.match(r"^L" + _FRAC + "X" + _FRAC + "X" + _FRAC + "$", s)
    if m:
        a, b, t = (_num(g) for g in m.groups())
        return LB_FT_PER_IN2 * t * (a + b - t)
    m = _RE.match(r"^PL" + _FRAC + "X" + _FRAC + "$", s)
    if m:
        t, w = (_num(g) for g in m.groups())
        return LB_FT_PER_IN2 * t * w
    m = _RE.match(r"^(RD|SQ)" + _FRAC + "$", s)
    if m:
        d = _num(m.group(2))
        return LB_FT_PER_IN2 * (math.pi * d * d / 4 if m.group(1) == "RD"
                                else d * d)
    raise ValueError(f"{shape!r}: not a shape this knows (W12x26, "
                     "HSS6x4x1/4, HSS6.625x0.280, L4x4x1/4, PL1/2x12, "
                     "C10x15.3, RD1)")


def steel_list(text, extra_pct=10.0):
    """A member list, one per line: shape, length in feet, count (count
    optional): 'W12x26, 24, 6'. {rows: [{shape, length, count, lb_ft,
    lb}], bad: [line], lb, lb_with_extra, tons}; `extra_pct` covers
    connections, plates and bolts."""
    rows, bad = [], []
    for line in str(text or "").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        parts = [p for p in _RE.split(r"[,\t;]+|\s{2,}", t) if p.strip()]
        if len(parts) == 1:
            parts = t.split()
        try:
            shape = parts[0]
            length = _pos(parts[1].lower().replace("ft", "").replace("'", ""),
                          "length")
            count = int(_pos(parts[2], "count")) if len(parts) > 2 else 1
            w = shape_lb_ft(shape)
        except (ValueError, IndexError):
            bad.append(t)
            continue
        rows.append({"shape": shape.upper(), "length": length,
                     "count": count, "lb_ft": w, "lb": w * length * count})
    lb = sum(r["lb"] for r in rows)
    lbx = lb * (1 + _pos(extra_pct, "connections allowance") / 100)
    return {"rows": rows, "bad": bad, "lb": lb, "lb_with_extra": lbx,
            "tons": lbx / 2000}
