"""Walls by role: sort the walls Auto Walls finds into what they do.

Roles (each its own takeoff group, so each gets a length total and can be
bound to an assembly like any group):

  Exterior   on the outer boundary of the building footprint
  Shaft      bounds a space labelled SHAFT / ELEV / STAIR / CHASE
  Restroom   bounds a space labelled TOILET / RESTROOM / MEN / WOMEN ...
  Corridor   bounds a space labelled CORRIDOR / CORR / HALL / HALLWAY
  Demising   between two different tenant spaces (TENANT A / SUITE 101 /
             UNIT 2B)
  Interior   any other wall

How the spaces are found (our own method, all on this computer):

1. The walls (centerlines with thickness, from autowalls.walls) are drawn
   into a coarse grid (about 3" cells). Door openings are closed off:
   from each wall end, a short "bridge" is run straight on to the next
   wall it would meet within 6'-6" - so each room becomes a closed pocket
   of the grid.
2. The open cells are flood-filled into spaces. Spaces touching the edge
   of the grid are outside the building.
3. Text lines on the sheet are read as space labels and dropped into the
   space they sit in. A tenant's name usually sits in one of its rooms,
   so tenants are spread to the rooms joined to that one through doors
   (flooding again without the door bridges, not passing through
   corridors, shafts, restrooms or the outside).
4. Each wall is looked at every 2 ft along its length, on both faces: the
   two spaces it separates decide its role there, best first: Exterior,
   Shaft, Restroom, Corridor, Demising, Interior. A wall that changes role
   part way is split; runs shorter than 3 ft take their neighbour's role.
   When a named space turns out to be open to the outside (a storefront
   wider than the door bridges), "outside" must also be outside the
   footprint with openings up to 12 ft closed (the walls drawn 6 ft
   fatter on a 1 ft grid), so the rooms behind the storefront are not
   taken as outside.

Coordinates are page points as autowalls gives them (unrotated, the same
as page.get_text("words")).
"""
import math
import re
from array import array

ROLES = ("Exterior", "Shaft", "Restroom", "Corridor", "Demising", "Interior",
         "Freestanding")
ROLE_COLORS = {"Exterior": (0.80, 0.15, 0.15), "Shaft": (0.45, 0.25, 0.70),
               "Restroom": (0.00, 0.55, 0.60), "Corridor": (0.95, 0.55, 0.0),
               "Demising": (0.15, 0.40, 0.85), "Interior": (0.35, 0.55, 0.20),
               "Freestanding": (0.55, 0.55, 0.55)}
GROUP_SUFFIX = " Walls"

FT_PER = {"ft": 1.0, "in": 12.0, "m": 0.3048, "yd": 1 / 3.0}
CELL_FT = 0.25              # grid cell: 3"
MAX_CELLS = 1_200_000
DOOR_FT = 6.5               # openings up to this wide are closed off
SAMPLE_FT = 2.0             # look at each wall this often
MIN_RUN_FT = 3.0            # shorter role changes are smoothed away
MARGIN_FT = 3.0

_CORRIDOR = {"CORRIDOR", "CORRIDORS", "CORR", "HALL", "HALLWAY", "HALLWAYS"}
_RESTROOM = {"TOILET", "TOILETS", "RESTROOM", "RESTROOMS", "MEN", "WOMEN",
             "MENS", "WOMENS", "LAV", "LAVATORY", "WC", "BATHROOM"}
_SHAFT = {"SHAFT", "SHAFTS", "ELEV", "ELEVATOR", "ELEVATORS", "STAIR",
          "STAIRS", "STAIRWELL", "STAIRWAY", "CHASE"}
_TENANT = {"TENANT", "SUITE", "UNIT"}
# spaces that are outside the building though drawn like rooms: a covered
# porch's columns and beam lines are not exterior walls
_OUTSIDE = {"PORCH", "PATIO", "CANOPY", "DECK", "BREEZEWAY", "VERANDA",
            "LOGGIA", "TERRACE", "COURTYARD", "CARPORT", "PORTICO",
            # unconditioned / covered exterior spaces (Oct 31, round 2):
            # not gross floor area
            "COVERED", "DUMPSTER", "RECYCLING", "SCREENED", "PAVILION",
            "GAZEBO", "AWNING", "UNCONDITIONED"}
# ...unless the label names a room ('RECYCLING ROOM' is inside)
_OUTSIDE_NOT = {"ROOM", "RM"}
_TENANT_ID = re.compile(r"^(?:[A-Z]|[A-Z]?\d{1,5}[A-Z]?)$")
_NOT_SHAFT = {"LOBBY", "MACHINE", "EQUIP", "EQUIPMENT", "ROOM", "RM"}


def group_name(role):
    return f"{role}{GROUP_SUFFIX}"


def role_of_group(group):
    for r in ROLES:
        if group == group_name(r):
            return r
    return None


# ---- labels ------------------------------------------------------------------
def classify_label(text):
    """(kind, tenant id) for a space label. kind: "corridor", "restroom",
    "shaft", "tenant", "outside" (a porch, patio, canopy...) or None (any
    other room name)."""
    toks = re.findall(r"[A-Z0-9]+", (text or "").upper().replace("'", "")
                      .replace("’", ""))
    words = set(toks)
    tenant = None
    for i, t in enumerate(toks[:-1]):
        if t in _TENANT and _TENANT_ID.match(toks[i + 1]):
            tenant = f"{t} {toks[i + 1]}"
            break
    if words & _OUTSIDE and not words & _OUTSIDE_NOT:
        return "outside", None
    if words & _CORRIDOR:
        return "corridor", tenant
    if words & _RESTROOM:
        return "restroom", tenant
    if words & _SHAFT and not words & _NOT_SHAFT:
        return "shaft", tenant
    if tenant:
        return "tenant", tenant
    return None, None


def labels_from_words(words):
    """Space labels from page.get_text("words") output: [{"text", "pt",
    "kind", "tenant"}] for the text lines that name a role or tenant."""
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    out = []
    for ws in lines.values():
        if len(ws) > 6:
            continue                       # a note, not a label
        ws.sort(key=lambda w: w[0])
        text = " ".join(str(w[4]) for w in ws)
        if len(text) > 40:
            continue
        kind, tenant = classify_label(text)
        if kind is None:
            continue
        x0 = min(w[0] for w in ws)
        y0 = min(w[1] for w in ws)
        x1 = max(w[2] for w in ws)
        y1 = max(w[3] for w in ws)
        out.append({"text": text, "pt": ((x0 + x1) / 2, (y0 + y1) / 2),
                    "kind": kind, "tenant": tenant})
    return out


# ---- geometry helpers ------------------------------------------------------------
class _W:
    __slots__ = ("i", "a", "b", "ux", "uy", "nx", "ny", "L", "hw")

    def __init__(self, i, w, per_ft):
        self.i = i
        self.a = (float(w["p0"][0]), float(w["p0"][1]))
        self.b = (float(w["p1"][0]), float(w["p1"][1]))
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        self.L = math.hypot(dx, dy) or 1e-9
        self.ux, self.uy = dx / self.L, dy / self.L
        self.nx, self.ny = -self.uy, self.ux
        self.hw = max(0.5, float(w.get("thickness", 6.0)) / 12.0 * per_ft / 2)

    def at(self, t):
        return (self.a[0] + self.ux * t, self.a[1] + self.uy * t)


def _bridges(ws, max_gap):
    """Short segments closing door openings: from each wall end straight
    on to the first wall it meets within max_gap. [(p, q, half width)]."""
    out = []
    for w in ws:
        for E, dx, dy in ((w.a, -w.ux, -w.uy), (w.b, w.ux, w.uy)):
            best = None
            for o in ws:
                if o is w:
                    continue
                cross = dx * o.uy - dy * o.ux
                if abs(cross) < 0.09:                 # parallel (5 deg)
                    ox, oy = o.a[0] - E[0], o.a[1] - E[1]
                    off = abs(ox * dy - oy * dx)
                    if off > max(w.hw, o.hw) + 0.5:
                        continue                      # not in line
                    s0 = ox * dx + oy * dy
                    s1 = (o.b[0] - E[0]) * dx + (o.b[1] - E[1]) * dy
                    s = min(s0, s1)
                    if s <= 0.01 or s > max_gap:
                        continue
                    t = s
                else:
                    # ray E + t*d against o's centerline a + s*u
                    ex, ey = o.a[0] - E[0], o.a[1] - E[1]
                    t = (ex * o.uy - ey * o.ux) / cross
                    s = (ex * dy - ey * dx) / cross
                    if not (-(o.hw + w.hw) <= s <= o.L + o.hw + w.hw):
                        continue
                    if t < -w.hw or t - o.hw > max_gap:
                        continue
                if best is None or t < best:
                    best = t
            if best is not None and best > 0.5:
                out.append((E, (E[0] + dx * best, E[1] + dy * best), w.hw))
    return out


class Grid:
    """The walls drawn into cells: 0 open, 1 wall, 2 door bridge."""

    def __init__(self, x0, y0, cell, nx, ny):
        self.x0, self.y0, self.cell, self.nx, self.ny = x0, y0, cell, nx, ny
        self.v = bytearray(nx * ny)

    def cell_of(self, p):
        i = int((p[0] - self.x0) // self.cell)
        j = int((p[1] - self.y0) // self.cell)
        if 0 <= i < self.nx and 0 <= j < self.ny:
            return i, j
        return None

    def draw(self, a, b, hw, val):
        c = self.cell
        reach = hw + 0.75 * c
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        i0 = max(0, int((min(a[0], b[0]) - reach - self.x0) // c))
        i1 = min(self.nx - 1, int((max(a[0], b[0]) + reach - self.x0) // c))
        j0 = max(0, int((min(a[1], b[1]) - reach - self.y0) // c))
        j1 = min(self.ny - 1, int((max(a[1], b[1]) + reach - self.y0) // c))
        v, nx = self.v, self.nx
        r2 = reach * reach
        for j in range(j0, j1 + 1):
            py = self.y0 + (j + 0.5) * c
            row = j * nx
            for i in range(i0, i1 + 1):
                k = row + i
                if v[k] == 1:
                    continue
                px = self.x0 + (i + 0.5) * c
                t = 0.0 if L2 == 0 else ((px - a[0]) * dx +
                                         (py - a[1]) * dy) / L2
                t = 0.0 if t < 0 else 1.0 if t > 1 else t
                qx, qy = a[0] + t * dx - px, a[1] + t * dy - py
                if qx * qx + qy * qy <= r2:
                    v[k] = val

    def label(self, blocked=None, walls_only=False):
        """Flood-fill the open cells: (region per cell (-1 = wall or
        blocked), number of regions, regions touching the edge)."""
        n = self.nx * self.ny
        reg = array("i", [-1]) * n
        v, nx, ny = self.v, self.nx, self.ny
        edge = set()
        count = 0
        for start in range(n):
            if reg[start] != -1 or (v[start] == 1 or
                                    (v[start] == 2 and not walls_only)):
                continue
            if blocked is not None and blocked[start]:
                continue
            rid = count
            count += 1
            reg[start] = rid
            stack = [start]
            while stack:
                k = stack.pop()
                i, j = k % nx, k // nx
                if i == 0 or j == 0 or i == nx - 1 or j == ny - 1:
                    edge.add(rid)
                for q, ok in ((k - 1, i > 0), (k + 1, i < nx - 1),
                              (k - nx, j > 0), (k + nx, j < ny - 1)):
                    if not ok or reg[q] != -1:
                        continue
                    vq = v[q]
                    if vq == 1 or (vq == 2 and not walls_only):
                        continue
                    if blocked is not None and blocked[q]:
                        continue
                    reg[q] = rid
                    stack.append(q)
        return reg, count, edge

    def open_near(self, p, reg, dirx=0.0, diry=0.0, steps=6):
        """Region at p, stepping on along (dirx, diry) past wall cells."""
        x, y = p
        for _ in range(steps + 1):
            c = self.cell_of((x, y))
            if c is None:
                return None
            r = reg[c[1] * self.nx + c[0]]
            if r != -1:
                return r
            if not (dirx or diry):
                return None
            x += dirx * self.cell
            y += diry * self.cell
        return None


LEAK_FT = 6.0
LEAK_NEAR_FT = 8.0


def _footprint_test(ws, x0, y0, x1, y1, per_ft):
    """p -> True when p is outside the building with openings up to
    2 x LEAK_FT wide closed: the walls are drawn LEAK_FT fatter into a
    1 ft grid, the outside is flooded in from the edge, and p counts as
    outside when it is within LEAK_NEAR_FT of that flood."""
    cell = per_ft
    m = (LEAK_FT + 2) * per_ft
    gx0, gy0 = x0 - m, y0 - m
    nx = int((x1 - x0 + 2 * m) / cell) + 1
    ny = int((y1 - y0 + 2 * m) / cell) + 1
    if nx * ny > MAX_CELLS:
        return lambda p: True
    g = Grid(gx0, gy0, cell, nx, ny)
    for w in ws:
        g.draw(w.a, w.b, w.hw + LEAK_FT * per_ft, 1)
    reg, _n, edge = g.label()
    k = int(math.ceil(LEAK_NEAR_FT * per_ft / cell))
    memo = {}

    def near(p):
        c = g.cell_of(p)
        if c is None:
            return True
        if c in memo:
            return memo[c]
        i, j = c
        hit = False
        for jj in range(max(0, j - k), min(ny, j + k + 1)):
            row = jj * nx
            for ii in range(max(0, i - k), min(nx, i + k + 1)):
                if reg[row + ii] in edge:
                    hit = True
                    break
            if hit:
                break
        memo[c] = hit
        return hit
    return near


def _spread_corridors(g, reg, nreg, outside, kinds, bridges, per_ft):
    """A corridor closed off by a bridge across a wide opening (a branch
    of the corridor, not a door) is still corridor: unlabelled narrow
    spaces joined to a corridor through an opening 4'-6" or wider take
    the label, a few branches deep."""
    nx = g.nx
    box = [[1 << 30, 1 << 30, -1, -1] for _ in range(nreg)]
    for k, r in enumerate(reg):
        if r < 0:
            continue
        i, j = k % nx, k // nx
        b = box[r]
        if i < b[0]:
            b[0] = i
        if j < b[1]:
            b[1] = j
        if i > b[2]:
            b[2] = i
        if j > b[3]:
            b[3] = j
    pairs = []
    for a, b, hw in bridges:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 4.5 * per_ft:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        off = hw + 1.75 * g.cell
        ra = g.open_near((m[0] - uy * off, m[1] + ux * off), reg, -uy, ux)
        rb = g.open_near((m[0] + uy * off, m[1] - ux * off), reg, uy, -ux)
        if ra is not None and rb is not None and ra != rb:
            pairs.append((ra, rb))

    def narrow(r):
        b = box[r]
        w = (b[2] - b[0] + 1) * g.cell
        h = (b[3] - b[1] + 1) * g.cell
        return min(w, h) <= 12 * per_ft and max(w, h) >= 2.0 * min(w, h)
    for _ in range(4):
        grew = False
        for ra, rb in pairs:
            for x, y in ((ra, rb), (rb, ra)):
                if "corridor" in kinds[x] and not kinds[y] and \
                        y not in outside and narrow(y):
                    kinds[y].add("corridor")
                    grew = True
        if not grew:
            break


# ---- the classification ------------------------------------------------------------
def classify(walls, labels, ppu, unit="ft", page_rect=None):
    """Split `walls` (autowalls.walls output) into role pieces.

    labels: labels_from_words() output. page_rect: (x0, y0, x1, y1) - walls
    hugging the sheet's edge (its border lines) are left out.
    Returns [{"p0", "p1", "length" (unit), "thickness" (in), "role",
    "wall" (index into walls)}]."""
    per_ft = ppu * FT_PER.get(unit, 1.0)
    if per_ft <= 0:
        raise ValueError("Set the scale for this page first.")
    ws = []
    for i, w in enumerate(walls):
        ww = _W(i, w, per_ft)
        if page_rect is not None:
            px0, py0, px1, py1 = page_rect
            edge = 54.0
            if all(min(abs(p[0] - px0), abs(p[0] - px1)) < edge or
                   min(abs(p[1] - py0), abs(p[1] - py1)) < edge
                   for p in (ww.a, ww.b)) and ww.L > 0.5 * min(
                       px1 - px0, py1 - py0):
                continue                         # the sheet border
        ws.append(ww)
    if not ws:
        return []
    margin = MARGIN_FT * per_ft
    xs = [p[0] for w in ws for p in (w.a, w.b)]
    ys = [p[1] for w in ws for p in (w.a, w.b)]
    x0, y0 = min(xs) - margin, min(ys) - margin
    x1, y1 = max(xs) + margin, max(ys) + margin
    cell = CELL_FT * per_ft
    while ((x1 - x0) / cell) * ((y1 - y0) / cell) > MAX_CELLS:
        cell *= 1.25
    g = Grid(x0, y0, cell, int((x1 - x0) / cell) + 1,
             int((y1 - y0) / cell) + 1)
    for w in ws:
        g.draw(w.a, w.b, w.hw, 1)
    bridges = _bridges(ws, DOOR_FT * per_ft)
    for a, b, hw in bridges:
        g.draw(a, b, hw, 2)
    reg, nreg, outside = g.label()
    # labels into spaces
    kinds = [set() for _ in range(nreg)]
    tenants = [set() for _ in range(nreg)]
    placed = []
    leaked = False
    outside = set(outside)
    for lab in labels:
        r = g.open_near(lab["pt"], reg)
        if r is None:
            # on a wall line or a bridge: try the cells around it
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                r = g.open_near(lab["pt"], reg, dx, dy, steps=4)
                if r is not None:
                    break
        if r is None:
            continue
        if lab["kind"] == "outside":
            outside.add(r)          # a porch or patio: outside the building
            continue
        if r in outside:
            leaked = True          # a named space open to the outside
            continue
        kinds[r].add(lab["kind"])
        if lab["tenant"]:
            tenants[r].add(lab["tenant"])
        placed.append((lab, r))
    _spread_corridors(g, reg, nreg, outside, kinds, bridges, per_ft)
    # the building's footprint (openings in the wall lines closed, porches
    # and patios left out): a face is outside when it is off the footprint
    fp = _footprint(g, ws, [lab["pt"] for lab in labels
                            if lab.get("kind") == "outside"], per_ft)
    if fp is not None and not _footprint_holds_walls(fp, ws):
        # no closed building outline (walls missing from the linework):
        # without a footprint nothing can be called freestanding - a wall
        # with outside on a face is exterior, as before the footprint
        fp = None
    # tenants reach the rooms joined to theirs through doors
    special = {r for r in range(nreg) if r in outside or
               kinds[r] & {"corridor", "shaft", "restroom"}}
    blocked = bytearray(len(reg))
    for k, r in enumerate(reg):
        if r in special:
            blocked[k] = 1
    sreg, nsuite, _ = g.label(blocked=blocked, walls_only=True)
    suite_t = [set() for _ in range(nsuite)]
    region_suite = {}
    for k, r in enumerate(reg):
        if r != -1 and r not in region_suite and sreg[k] != -1:
            region_suite[r] = sreg[k]
    for lab, r in placed:
        s = region_suite.get(r)
        if s is not None and lab["tenant"]:
            suite_t[s].add(lab["tenant"])

    def tenant(r):
        if r is None:
            return None
        if len(tenants[r]) == 1:
            return next(iter(tenants[r]))
        if tenants[r]:
            return None
        s = region_suite.get(r)
        if s is not None and len(suite_t[s]) == 1:
            return next(iter(suite_t[s]))
        return None

    # an opening wider than a door (a storefront) lets "outside" into the
    # rooms behind it: then outside also has to be outside the footprint
    # with openings up to 2 x LEAK_FT closed
    near_out = _footprint_test(ws, x0, y0, x1, y1, per_ft) \
        if leaked and fp is None else None

    def role(ra, rb, pa=None, pb=None):
        sides = []
        ext = 0
        for r, p in ((ra, pa), (rb, pb)):
            if r is None:
                continue
            if r in outside:
                if fp is not None and p is not None:
                    if not fp.inside(p):
                        ext += 1
                elif near_out is None or p is None or near_out(p):
                    ext += 1
                continue                      # leaked-into space: unknown
            sides.append(r)
        if ext == 2 and fp is not None:
            # outside on both faces of a building with a known footprint:
            # porch beams, screen walls, site walls - not the building's
            # exterior wall
            return "Freestanding"
        if ext:
            return "Exterior"
        if not sides:
            return None
        inner = sides
        k = set()
        for r in inner:
            k |= kinds[r]
        if "shaft" in k:
            return "Shaft"
        if "restroom" in k:
            return "Restroom"
        if "corridor" in k:
            return "Corridor"
        if len(inner) == 2:
            ta, tb = tenant(inner[0]), tenant(inner[1])
            if ta and tb and ta != tb:
                return "Demising"
        return "Interior"

    out = []
    step = SAMPLE_FT * per_ft
    min_run = MIN_RUN_FT * per_ft
    for w in ws:
        n = max(1, int(round(w.L / step)))
        ts = [w.L * (k + 0.5) / n for k in range(n)]
        sides = []

        def probe(t, w=w):
            c = w.at(t)
            off = w.hw + 1.75 * cell
            pa = (c[0] + w.nx * off, c[1] + w.ny * off)
            pb = (c[0] - w.nx * off, c[1] - w.ny * off)
            return (g.open_near(pa, reg, w.nx, w.ny),
                    g.open_near(pb, reg, -w.nx, -w.ny), pa, pb)
        for t in ts:
            sides.append(probe(t))
        roles = [role(*sd) for sd in sides]
        # fill unknown samples from their neighbours
        known = [r for r in roles if r]
        if not known:
            roles = ["Interior"] * n
        else:
            last = None
            for k in range(n):
                if roles[k]:
                    last = roles[k]
                elif last:
                    roles[k] = last
            first = next(r for r in roles if r)
            roles = [r or first for r in roles]
        # runs: [role, first sample, last sample]
        runs = []
        for k, r in enumerate(roles):
            if runs and runs[-1][0] == r:
                runs[-1][2] = k
            else:
                runs.append([r, k, k])
        runs = []
        for k, r in enumerate(roles):
            if runs and runs[-1][0] == r:
                runs[-1][2] = k
            else:
                runs.append([r, k, k])
        # smooth: short runs take the longer neighbour's role
        changed = True
        while changed and len(runs) > 1:
            changed = False
            for k, run in enumerate(runs):
                span = (run[2] - run[1] + 1) * w.L / n
                if span >= min_run:
                    continue
                nb = [runs[q] for q in (k - 1, k + 1) if 0 <= q < len(runs)]
                big = max(nb, key=lambda q: q[2] - q[1])
                run[0] = big[0]
                merged = []
                for r in runs:
                    if merged and merged[-1][0] == r[0]:
                        merged[-1][2] = r[2]
                    else:
                        merged.append(list(r))
                runs = merged
                changed = True
                break
        src = walls[w.i]
        # where one role ends and the next begins, to about a cell
        cuts = [0.0]
        for q in range(len(runs) - 1):
            lo, hi = ts[runs[q][2]], ts[runs[q + 1][1]]
            want_lo, want_hi = runs[q][0], runs[q + 1][0]
            while hi - lo > cell:
                mid = (lo + hi) / 2
                got = role(*probe(mid))
                if got == want_lo:
                    lo = mid
                elif got == want_hi:
                    hi = mid
                else:
                    break
            cuts.append((lo + hi) / 2)
        cuts.append(w.L)
        for q, (r, k0, k1) in enumerate(runs):
            t0, t1 = cuts[q], cuts[q + 1]
            out.append({"p0": w.at(t0), "p1": w.at(t1),
                        "length": (t1 - t0) / ppu,
                        "thickness": float(src.get("thickness", 0.0)),
                        "role": r, "wall": w.i})
    return out


EXT_GAP_FT = 24.0           # gaps in a wall line closed for the footprint
STUB_FT = 2.0               # footprint parts thinner than this: wall lines
MIN_BUILDING_SF = 100.0     # footprint pieces smaller than this: not one


def _inline_bridges(ws, max_gap):
    """Gaps along one wall line (windows, storefronts) up to max_gap:
    [(p, q, half width)] from each wall end straight on to the next wall
    on the same line."""
    out = []
    for w in ws:
        for E, dx, dy in ((w.a, -w.ux, -w.uy), (w.b, w.ux, w.uy)):
            best = None
            for o in ws:
                if o is w or abs(dx * o.uy - dy * o.ux) >= 0.03:
                    continue                          # not parallel
                ox, oy = o.a[0] - E[0], o.a[1] - E[1]
                if abs(ox * dy - oy * dx) > max(w.hw, o.hw) * 0.5 + 0.5:
                    continue                          # not on this line
                s0 = ox * dx + oy * dy
                s1 = (o.b[0] - E[0]) * dx + (o.b[1] - E[1]) * dy
                s = min(s0, s1)
                if 0.01 < s <= max_gap and (best is None or s < best):
                    best = s
            if best is not None:
                out.append((E, (E[0] + dx * best, E[1] + dy * best),
                            w.hw))
    return out


class _Footprint:
    """The building's footprint on the role grid: inside(p) for page
    points; `mask` (rows x cols, 1 = building) and the grid's origin and
    cell."""

    def __init__(self, mask, g):
        self.mask, self.g = mask, g

    def inside(self, p):
        c = self.g.cell_of(p)
        return c is not None and bool(self.mask[c[1], c[0]])


FP_MIN_SHARE = 0.6        # of the wall length on or in the footprint


def _footprint_holds_walls(fp, ws):
    """True when the footprint is the building: most of the walls (by
    length) are on or inside it. A footprint that closed around one part
    only (the rest of the outline missing from the linework) would make
    every other wall "freestanding"."""
    try:
        import numpy as np
        import cv2
    except ImportError:                          # pragma: no cover
        return True
    if not fp.mask.any():
        return False
    grown = cv2.dilate(fp.mask.astype(np.uint8), np.ones((5, 5), np.uint8))
    near = _Footprint(grown, fp.g)
    tot = on = 0.0
    for w in ws:
        mid = ((w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2)
        tot += w.L
        if near.inside(mid):
            on += w.L
    return tot <= 0 or on >= FP_MIN_SHARE * tot


def _footprint(g, ws, out_pts, per_ft):
    """The footprint (numpy and OpenCV; None without them): the walls,
    door bridges and bridges across wall-line gaps up to EXT_GAP_FT, and
    every space not open to the edge of the grid nor labelled as a porch /
    patio (`out_pts`: those labels' points); then parts thinner than
    STUB_FT (wall lines out on their own: porch beams, screen walls) and
    pieces under MIN_BUILDING_SF are taken off."""
    try:
        import numpy as np
        import cv2
    except ImportError:                          # pragma: no cover
        return None
    ny, nx = g.ny, g.nx
    solid = (np.frombuffer(bytes(g.v), np.uint8).reshape(ny, nx) != 0)
    extra = Grid(g.x0, g.y0, g.cell, nx, ny)
    for a, b, hw in _inline_bridges(ws, EXT_GAP_FT * per_ft):
        extra.draw(a, b, hw, 1)
    solid = solid | (np.frombuffer(bytes(extra.v), np.uint8)
                     .reshape(ny, nx) != 0)
    open_ = (~solid).astype(np.uint8)
    n, lab = cv2.connectedComponents(open_, connectivity=4)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    out_ids = set(np.unique(border[border > 0]).tolist())
    # porches and patios: the space each such label sits in (or next to,
    # when the label is printed on a line) is outside too
    for p in out_pts:
        c = g.cell_of(p)
        if c is None:
            continue
        i, j = c
        for rr in range(0, 6):
            win = lab[max(0, j - rr):j + rr + 1, max(0, i - rr):i + rr + 1]
            ids = win[win > 0]
            if len(ids):
                out_ids.add(int(np.bincount(ids).argmax()))
                break
    out = np.isin(lab, np.array(sorted(out_ids), np.int32))
    fp = (~out).astype(np.uint8)
    k = max(3, int(round(STUB_FT * per_ft / g.cell)) | 1)
    fp = cv2.morphologyEx(fp, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n2, lab2, st, _c = cv2.connectedComponentsWithStats(fp, connectivity=4)
    small = st[:, cv2.CC_STAT_AREA] * (g.cell / per_ft) ** 2 < \
        MIN_BUILDING_SF
    small[0] = True
    fp = (~small[lab2]).astype(np.uint8)
    return _Footprint(fp, g)


def _setup(walls, ppu, unit, page_rect):
    per_ft = ppu * FT_PER.get(unit, 1.0)
    if per_ft <= 0:
        raise ValueError("Set the scale for this page first.")
    ws = []
    for i, w in enumerate(walls):
        ww = _W(i, w, per_ft)
        if page_rect is not None:
            px0, py0, px1, py1 = page_rect
            edge = 54.0
            if all(min(abs(p[0] - px0), abs(p[0] - px1)) < edge or
                   min(abs(p[1] - py0), abs(p[1] - py1)) < edge
                   for p in (ww.a, ww.b)) and ww.L > 0.5 * min(
                       px1 - px0, py1 - py0):
                continue                         # the sheet border
        ws.append(ww)
    if not ws:
        return per_ft, ws, None
    margin = MARGIN_FT * per_ft
    xs = [p[0] for w in ws for p in (w.a, w.b)]
    ys = [p[1] for w in ws for p in (w.a, w.b)]
    x0, y0 = min(xs) - margin, min(ys) - margin
    x1, y1 = max(xs) + margin, max(ys) + margin
    cell = CELL_FT * per_ft
    while ((x1 - x0) / cell) * ((y1 - y0) / cell) > MAX_CELLS:
        cell *= 1.25
    g = Grid(x0, y0, cell, int((x1 - x0) / cell) + 1,
             int((y1 - y0) / cell) + 1)
    for w in ws:
        g.draw(w.a, w.b, w.hw, 1)
    for a, b, hw in _bridges(ws, DOOR_FT * per_ft):
        g.draw(a, b, hw, 2)
    return per_ft, ws, g


def exterior_outline(walls, ppu, unit="ft", labels=(), page_rect=None,
                     other_views=()):
    """The building's outer face loop - what the exterior wall is taken
    off as (it runs across windows and storefronts; porch, canopy and
    column linework is outside it).

    The footprint (see _footprint) is outlined and each side of the
    outline is moved onto the outer face of the walls along it, so the
    loop is exact to the drawn faces, not the grid. Returns {"outer_face_lf",
    "centerline_lf" (the same loop at the walls' centerlines),
    "openings_lf" (stretches of it with no wall drawn: windows, doors,
    storefronts), "gross_area" (the area inside the loop - the gross floor
    area, to the outside face of the exterior walls, square `unit`s), "unsnapped_lf" (sides no wall face was found for -
    measured on the grid), "loops" (number of buildings), "pts" [[(x, y)]]
    (page points), "flags"} - lengths in `unit`; None values when the
    footprint can't be made (no walls, or no numpy/OpenCV)."""
    res = {"outer_face_lf": None, "centerline_lf": None, "openings_lf": None,
           "unsnapped_lf": None, "loops": 0, "pts": [], "flags": [],
           "gross_area": None}
    per_ft, ws, g = _setup(walls, ppu, unit, page_rect)
    if g is None:
        res["flags"].append("no walls")
        return res
    try:
        import numpy as np
        import cv2
    except ImportError:                          # pragma: no cover
        res["flags"].append("needs numpy and OpenCV")
        return res
    fp = _footprint(g, ws, [lab["pt"] for lab in labels or ()
                            if lab.get("kind") == "outside"], per_ft)
    if fp is None:
        res["flags"].append("no closed building outline found")
        return res
    if fp.mask.any() and not _footprint_holds_walls(fp, ws):
        res["flags"].append("the building outline closes around part of the "
                            "walls only - exterior wall not taken off; check "
                            "the plan's outline")
        return res
    cnts, _h = cv2.findContours(fp.mask, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
    cnts = [c for c in cnts if cv2.contourArea(c) * (g.cell / per_ft) ** 2
            >= MIN_BUILDING_SF]
    if not cnts:
        res["flags"].append("no closed building outline found")
        return res
    if other_views and len(cnts) > 1:
        # an outline inside another drawing on the sheet (a mezzanine
        # plan, a detail) is not a building: its walls are inside the
        # building or not at this scale. The biggest outline always stays.
        big = max(cnts, key=cv2.contourArea)
        keep = []
        for c in cnts:
            m = cv2.moments(c)
            if c is not big and m["m00"]:
                cx = g.x0 + (m["m10"] / m["m00"] + 0.5) * g.cell
                cy = g.y0 + (m["m01"] / m["m00"] + 0.5) * g.cell
                hit = next((t for (x0, y0, x1, y1), t in other_views
                            if x0 <= cx <= x1 and y0 <= cy <= y1), None)
                if hit:
                    res["flags"].append(f"an outline inside '{hit}' left "
                                        "out of the exterior wall")
                    continue
            keep.append(c)
        cnts = keep
    hws = sorted(w.hw for w in ws)
    hw_typ = hws[len(hws) // 2]
    face = cl = opening = unsnapped = area = 0.0
    for c in cnts:
        poly = cv2.approxPolyDP(c, 1.5, True).reshape(-1, 2)
        pts = [(g.x0 + (x + 0.5) * g.cell, g.y0 + (y + 0.5) * g.cell)
               for x, y in poly]
        got = _snap_loop(pts, ws, g.cell, hw_typ)
        res["pts"].append(got["face"])
        f_ = got["face"]
        area += abs(sum(a[0] * b[1] - b[0] * a[1]
                        for a, b in zip(f_, list(f_[1:]) + list(f_[:1])))) / 2
        face += got["face_len"]
        cl += got["center_len"]
        opening += got["open_len"]
        unsnapped += got["unsnapped"]
    res["loops"] = len(cnts)
    res["outer_face_lf"] = face / ppu
    res["centerline_lf"] = cl / ppu
    res["openings_lf"] = float(opening) / ppu
    res["unsnapped_lf"] = unsnapped / ppu
    # gross floor area: inside the exterior walls' outer face (square units)
    res["gross_area"] = area / ppu ** 2
    if len(cnts) > 1:
        res["flags"].append(f"{len(cnts)} separate buildings outlined - "
                            "check they all belong")
    if unsnapped > 0.02 * max(face, 1e-9):
        res["flags"].append(f"{unsnapped / ppu:,.1f} {unit} of the outline "
                            "follows no wall face (measured on a 3\" grid) - "
                            "check")
    return res


def _poly_inside(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def _snap_loop(pts, ws, cell, hw_typ):
    """Move each side of the outline `pts` onto the outer face of the
    walls along it. Returns {"face": [points], "face_len", "center_len",
    "open_len", "unsnapped"} (page points)."""
    n = len(pts)
    sides = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-9:
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = uy, -ux
        mid = ((a[0] + b[0]) / 2 + nx * cell, (a[1] + b[1]) / 2 + ny * cell)
        if _poly_inside(mid, pts):
            nx, ny = -nx, -ny                     # outward
        cands = []
        for w in ws:
            if abs(ux * w.uy - uy * w.ux) > 0.087:   # 5 degrees
                continue
            d = (w.a[0] - a[0]) * nx + (w.a[1] - a[1]) * ny
            f = d + w.hw                              # its outer face
            if abs(f) > 3.5 * cell:
                continue
            s0 = (w.a[0] - a[0]) * ux + (w.a[1] - a[1]) * uy
            s1 = (w.b[0] - a[0]) * ux + (w.b[1] - a[1]) * uy
            s0, s1 = min(s0, s1), max(s0, s1)
            ov = min(s1, L) - max(s0, 0.0)
            if ov <= 0.25 * cell:
                continue
            cands.append((f, ov, w.hw, max(s0, 0.0), min(s1, L), w))
        if cands:
            cands.sort(key=lambda c: c[0])
            tot = sum(c[1] for c in cands)
            acc, pick = 0.0, cands[0]
            for c in cands:
                acc += c[1]
                if acc >= tot / 2:
                    pick = c
                    break
            f, hw, w = pick[0], pick[2], pick[5]
            # the side runs along that wall: its direction, through its
            # outer face (the grid outline is only good to a cell)
            wx, wy = (w.ux, w.uy) if w.ux * ux + w.uy * uy >= 0 \
                else (-w.ux, -w.uy)
            ux, uy = wx, wy
            sx, sy = (uy, -ux) if uy * nx - ux * ny >= 0 else (-uy, ux)
            nx, ny = sx, sy
            on = (w.a[0] - a[0]) * nx + (w.a[1] - a[1]) * ny + w.hw
            a = (a[0] + nx * on, a[1] + ny * on)
            f = 0.0
            iv = sorted((c[3], c[4]) for c in cands)
            cov, cur = 0.0, None
            for s0, s1 in iv:
                if cur is None or s0 > cur[1]:
                    if cur:
                        cov += cur[1] - cur[0]
                    cur = [s0, s1]
                else:
                    cur[1] = max(cur[1], s1)
            if cur:
                cov += cur[1] - cur[0]
            snapped = True
        else:
            f, hw, cov, snapped = 0.0, hw_typ, 0.0, False
        sides.append({"p": (a[0] + nx * f, a[1] + ny * f), "u": (ux, uy),
                      "n": (nx, ny), "hw": hw, "cov": cov, "L": L,
                      "snapped": snapped})

    def corners(off):
        out = []
        m = len(sides)
        for i in range(m):
            s, t = sides[i - 1], sides[i]
            p = (s["p"][0] - s["n"][0] * off(s), s["p"][1] - s["n"][1] * off(s))
            q = (t["p"][0] - t["n"][0] * off(t), t["p"][1] - t["n"][1] * off(t))
            den = s["u"][0] * t["u"][1] - s["u"][1] * t["u"][0]
            if abs(den) < 0.17:                       # about parallel
                out.append(q)
                continue
            k = ((q[0] - p[0]) * t["u"][1] - (q[1] - p[1]) * t["u"][0]) / den
            out.append((p[0] + k * s["u"][0], p[1] + k * s["u"][1]))
        return out

    def length(loop):
        return sum(math.hypot(loop[i][0] - loop[i - 1][0],
                              loop[i][1] - loop[i - 1][1])
                   for i in range(len(loop)))
    face = corners(lambda s: 0.0)
    center = corners(lambda s: s["hw"])
    m = len(sides)
    open_len = unsnapped = 0.0
    for i in range(m):
        seg = math.hypot(center[(i + 1) % m][0] - center[i][0],
                         center[(i + 1) % m][1] - center[i][1])
        if sides[i]["snapped"]:
            open_len += max(0.0, seg - sides[i]["cov"])
        else:
            unsnapped += math.hypot(face[(i + 1) % m][0] - face[i][0],
                                    face[(i + 1) % m][1] - face[i][1])
    return {"face": face, "face_len": length(face),
            "center_len": length(center), "open_len": open_len,
            "unsnapped": unsnapped}


def summary(pieces):
    """{role: total length} in ROLES order (roles with none left out)."""
    tot = {}
    for p in pieces:
        tot[p["role"]] = tot.get(p["role"], 0.0) + p["length"]
    return {r: tot[r] for r in ROLES if r in tot}


def marks(page_no, pieces, scale):
    """Viewer marks [(page, "add_line", payload)]: one line per piece, in
    the group of its role."""
    unit = scale.get("unit", "ft")
    out = []
    for p in pieces:
        role = p["role"]
        out.append((page_no, "add_line", {
            "pts": [list(p["p0"]), list(p["p1"])],
            "color": list(ROLE_COLORS.get(role, (0.3, 0.3, 0.3))),
            "width": 3, "opacity": 0.6,
            "measure": {"type": "length", "value": round(p["length"], 4),
                        "unit": unit, "group": group_name(role),
                        "method": "walls by role"}}))
    return out


def find(page, ppu, unit="ft"):
    """Walls of `page` by role: (pieces, labels). Uses autowalls for the
    walls (vector linework, else the scanned picture)."""
    from . import autowalls
    try:
        ws = autowalls.walls(page, ppu, unit)
    except autowalls.AutoWallsError:
        ws = []
    if len(ws) < 2 and len(autowalls.segments(page)) < 200:
        segs = autowalls.raster_segments(page, ppu, unit)
        ws = autowalls.walls(page, ppu, unit, segs=segs)
    labels = labels_from_words(page.get_text("words"))
    r = page.rect * page.derotation_matrix          # unrotated, like walls
    box = (min(r.x0, r.x1), min(r.y0, r.y1), max(r.x0, r.x1),
           max(r.y0, r.y1))
    return classify(ws, labels, ppu, unit, page_rect=box), labels


def _other_views(page):
    """[((x0, y0, x1, y1) page coordinates, name)] of the parts of a sheet
    that are not the building plan: the secondary drawings (mezzanine /
    enlarged plans, details, sections - their linework patch from
    schedules.view_regions, else the area just above the title) and the
    title block down the right edge."""
    from . import schedules
    try:
        info = schedules.sheet_info(page)
        vs = schedules.views(info["cells"], loose=True)
        if len(vs) >= 2:
            vs = schedules.view_regions(vs, info["segs"], info["w"],
                                        info["h"])
    except Exception:                                    # noqa: BLE001
        return []
    out = []
    for v in vs:
        if not v.get("secondary"):
            continue
        reg = v.get("region")
        if not reg:
            x0, y0, _x1, _y1 = v["rect"]
            reg = (x0 - 72, max(0.0, y0 - 10 * 72), x0 + 8 * 72, y0)
        out.append((schedules.to_page(page, reg), v["title"]))
    w, h = info["w"], info["h"]
    out.append((schedules.to_page(page, (0.86 * w, 0, w, h)),
                "the title block"))
    return out


LAYER_GAP_FT = (1.0, 2.0, 3.0, 4.0, 6.0)   # openings closed, tried in turn
LAYER_SPIKE_FT = 1.5        # tags / markers on a wall layer: trimmed off
LAYER_ENCLOSES = 3.0        # outline area at least this x the ink inside


def layer_outline(page, ppu, unit="ft", labels=()):
    """The building outline from the PDF's own wall layers (CAD 'WALL'
    layers, autotakeoff.wall_layers), or None when the sheet has none or
    they close no building. Only that ink is drawn on a grid; openings up
    to the smallest of LAYER_GAP_FT that makes the outer contour enclose
    the building are closed; spikes thinner than LAYER_SPIKE_FT (tags on
    the layer) are trimmed; spaces inside labelled as porches, decks,
    covered or unconditioned areas (labels of kind "outside") are taken
    out. Site, porch and furniture linework on other layers never enters
    it. Returns {"gross_area" (square `unit`s), "outer_face_lf", "pts"
    [[(x, y)]] (unrotated page points, like walls()), "loops", "flags"}.
    """
    try:
        import numpy as np
        import cv2
    except ImportError:                          # pragma: no cover
        return None
    from . import autotakeoff
    names = autotakeoff.wall_layers(page)
    if not names:
        return None
    per_ft = ppu * FT_PER.get(unit, 1.0)
    if per_ft <= 0:
        return None
    cell = max(0.5, per_ft / 12.0)                       # about 1 inch
    box = page.mediabox
    nx, ny = int(box.width / cell) + 2, int(box.height / cell) + 2
    ink = np.zeros((ny, nx), np.uint8)
    try:
        paths = page.get_drawings()
    except Exception:                                    # noqa: BLE001
        return None
    for d in paths:
        if (d.get("layer") or "") not in names:
            continue
        for it in d["items"]:
            if it[0] == "l":
                pts = [it[1], it[2]]
            elif it[0] == "re":
                r = it[1]
                pts = [r.tl, r.tr, r.br, r.bl, r.tl]
            elif it[0] == "qu":
                q = it[1]
                pts = [q.ul, q.ur, q.lr, q.ll, q.ul]
            elif it[0] == "c":
                pts = [it[1], it[2], it[3], it[4]]
            else:
                continue
            a = np.array([[(p.x - box.x0) / cell, (p.y - box.y0) / cell]
                          for p in pts], np.int32)
            cv2.polylines(ink, [a], False, 1, 1)
    if not ink.any():
        return None
    min_px = MIN_BUILDING_SF * (per_ft / cell) ** 2
    filled = None
    for gap in LAYER_GAP_FT:
        k = int(round(gap * per_ft / cell)) | 1
        closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                                  np.ones((k, k), np.uint8))
        cnts, _h = cv2.findContours(closed, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
        cnts = [c for c in cnts if cv2.contourArea(c) >= min_px]
        if not cnts:
            continue
        f = np.zeros_like(ink)
        cv2.drawContours(f, cnts, -1, 1, cv2.FILLED)
        if f.sum() >= LAYER_ENCLOSES * max(1, int((closed & f).sum())):
            filled, used_gap = f, gap
            break
    if filled is None:
        return None
    s = int(round(LAYER_SPIKE_FT * per_ft / cell)) | 1
    filled = cv2.morphologyEx(filled, cv2.MORPH_OPEN,
                              np.ones((s, s), np.uint8))
    flags = [f"building outline from the PDF's wall layers "
             f"({', '.join(sorted(names))[:80]}); openings up to "
             f"{used_gap:g} ft closed"]
    out_pts = [lab["pt"] for lab in labels or ()
               if lab.get("kind") == "outside"]
    if out_pts:
        space = (filled & (1 - closed)).astype(np.uint8)
        n, lab = cv2.connectedComponents(space, connectivity=4)
        for (px, py) in out_pts:
            i, j = int((px - box.x0) / cell), int((py - box.y0) / cell)
            if 0 <= j < ny and 0 <= i < nx and lab[j, i] > 0:
                filled[lab == lab[j, i]] = 0
                flags.append("a porch / covered / unconditioned space "
                             "inside the walls left out of the gross area")
    cnts, _h = cv2.findContours(filled, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
    cnts = [c for c in cnts if cv2.contourArea(c) >= min_px]
    if not cnts:
        return None
    area = lf = 0.0
    loops = []
    for c in cnts:
        poly = cv2.approxPolyDP(c, 1.0, True)
        area += cv2.contourArea(poly) * cell * cell
        lf += cv2.arcLength(poly, True) * cell
        loops.append([(box.x0 + (x + 0.5) * cell, box.y0 + (y + 0.5) * cell)
                      for x, y in poly.reshape(-1, 2)])
    return {"gross_area": area / ppu ** 2, "outer_face_lf": lf / ppu,
            "pts": loops, "loops": len(loops), "flags": flags}


def find_ex(page, ppu, unit="ft"):
    """Walls by role with the exterior checked against the building
    outline: {"pieces", "labels", "walls", "summary", "exterior",
    "flags"}. summary["Exterior"] is the outer face loop
    (exterior_outline) - windows and storefronts included, porch and
    column linework left out - and summary["Exterior (wall pieces)"] the
    exterior wall pieces' centerlines, for comparison."""
    from . import autowalls
    try:
        ws = autowalls.walls(page, ppu, unit)
    except autowalls.AutoWallsError:
        ws = []
    if len(ws) < 2 and len(autowalls.segments(page)) < 200:
        segs = autowalls.raster_segments(page, ppu, unit)
        ws = autowalls.walls(page, ppu, unit, segs=segs)
    labels = labels_from_words(page.get_text("words"))
    r = page.rect * page.derotation_matrix          # unrotated, like walls
    box = (min(r.x0, r.x1), min(r.y0, r.y1), max(r.x0, r.x1),
           max(r.y0, r.y1))
    pieces = classify(ws, labels, ppu, unit, page_rect=box)
    ext = exterior_outline(ws, ppu, unit, labels, page_rect=box,
                           other_views=_other_views(page))
    lo = layer_outline(page, ppu, unit, labels)
    if lo is not None:
        # the PDF's own wall layers draw the building; the outline traced
        # from all the linework can take in site and porch lines (Harbor
        # Springs A101: 3,764 SF against about 2,320 SF printed)
        ext = dict(ext, gross_area=lo["gross_area"],
                   outer_face_lf=lo["outer_face_lf"], pts=lo["pts"],
                   loops=lo["loops"],
                   flags=[f for f in ext.get("flags") or ()
                          if "follows no wall face" not in f
                          and "no closed building outline" not in f]
                   + lo["flags"])
    sm = summary(pieces)
    flags = list(ext["flags"])
    if ext["outer_face_lf"]:
        sm["Exterior (wall pieces)"] = sm.get("Exterior", 0.0)
        sm["Exterior"] = ext["outer_face_lf"]
        if sm.get("Freestanding"):
            flags.append(f"{sm['Freestanding']:,.1f} {unit} of wall outside "
                         "the building (porch, screen or site walls) - not "
                         "in Exterior")
    else:
        flags.append("no building outline - Exterior is the exterior wall "
                     "pieces only (openings not included)")
    return {"pieces": pieces, "labels": labels, "walls": ws, "summary": sm,
            "exterior": ext, "flags": flags}


def exterior_marks(page_no, ext, scale):
    """Viewer marks for exterior_outline(): one "add_line" per side of the
    outer face loop, grouped "Exterior Walls" (the same group the
    exterior pieces use, so the loop replaces them in the totals)."""
    unit = scale.get("unit", "ft")
    ppu = scale.get("ppu") or 1.0
    out = []
    for loop in ext.get("pts") or []:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            L = math.hypot(b[0] - a[0], b[1] - a[1]) / ppu
            if L <= 0:
                continue
            out.append((page_no, "add_line", {
                "pts": [[float(a[0]), float(a[1])],
                        [float(b[0]), float(b[1])]],
                "color": list(ROLE_COLORS["Exterior"]), "width": 3,
                "opacity": 0.6,
                "measure": {"type": "length", "value": round(L, 4),
                            "unit": unit, "group": group_name("Exterior"),
                            "method": "walls by role: outer face"}}))
    return out
