"""A synthetic sanitary sewer plan set (50 sheets) and project manual with
known planted problems, for measuring the RFI finder's precision/recall.
Every planted problem has a key (kind, subject); everything else in the set
is consistent and must NOT produce a finding."""
import fitz

W, H = 1224, 792

PLANTED = [
    ("pipe_conflict", "MH-5/MH-6"),        # 8" on plan, 10" on profile
    ("pipe_conflict", "MH-23/MH-24"),      # PVC on plan, DIP on profile
    ("elev_conflict", "MH-12"),            # rim differs plan vs profile
    ("elev_conflict", "MH-31"),            # invert out differs
    ("slope_math", "MH-17/MH-18"),         # label 0.60%, inverts give less
    ("min_slope", "MH-40/MH-41"),          # 8" at 0.25% (< 0.40% min)
    ("missing_sheet", "C-599"),            # SEE 4/C-599
    ("missing_detail", "7/C-501"),         # C-501 has details 1-5 only
    ("missing_spec", "33 05 13"),          # cited, not in the manual
    ("spec_class", "MH-44/MH-45"),         # SDR-26, spec says SDR 35
    ("missing_invert", "MH-52"),           # rim given, no inverts
    ("undefined_structure", "MH-99"),      # pipe runs to MH-99, never shown
    ("open_scope", "SERVICE LATERALS BY OTHERS"),
    ("open_scope", "BYPASS PUMPING PLAN TBD"),
    ("unscheduled_equip", "P-3"),          # pump P-3 on plan, not scheduled
]


def _sheet(doc, number, title, lines):
    p = doc.new_page(width=W, height=H)
    y = 60
    for ln in lines:
        p.insert_text((50, y), ln, fontsize=9)
        y += 14
    p.insert_text((1090, 740), title, fontsize=8)
    p.insert_text((1090, 768), number, fontsize=18)
    return p


def _network():
    """Structures MH-1..MH-61 in a chain; consistent data."""
    st, seg = {}, []
    inv = 520.00
    for i in range(1, 62):
        rim = round(inv + 9.5 + (i % 3) * 0.7, 2)
        st[i] = {"rim": rim, "in": round(inv, 2), "out": round(inv - 0.10, 2)}
        if i < 61:
            length = 200 + (i * 37) % 200
            slope = 0.40 + (i % 4) * 0.10
            seg.append({"a": i, "b": i + 1, "len": length, "slope": slope,
                        "size": 8, "mat": "PVC", "cls": "SDR-35"})
            inv = round(st[i]["out"] - length * slope / 100, 2)
    return st, seg


STYLE = {"alt": False}


def _st_line(i, s, rim=None, out=None, inverts=True):
    if STYLE["alt"]:
        rim = s["rim"] if rim is None else rim
        out = s["out"] if out is None else out
        if not inverts:
            return f"MH {i} (48\" DIA) RIM EL. {rim:.2f}"
        return f"MH {i} (48\" DIA) RIM EL. {rim:.2f}, IE IN (W) " \
               f"{s['in']:.2f}, IE OUT (E) {out:.2f}"
    rim = s["rim"] if rim is None else rim
    out = s["out"] if out is None else out
    if not inverts:
        return f"SAN MH-{i}  RIM={rim:.2f}"
    return f"SAN MH-{i}  RIM={rim:.2f}  INV IN={s['in']:.2f}  " \
           f"INV OUT={out:.2f}"


def _seg_line(g, size=None, mat=None, cls=None, slope=None, b=None):
    size = g["size"] if size is None else size
    mat = g["mat"] if mat is None else mat
    cls = g["cls"] if cls is None else cls
    slope = g["slope"] if slope is None else slope
    b = g["b"] if b is None else b
    if STYLE["alt"]:
        return (f"MH {g['a']} - MH {b}: {g['len']} LF OF {size}-IN {mat} "
                f"{cls.replace('-', ' ')} S={slope / 100:.4f}".replace(
                    f"S={slope / 100:.4f}", f"S = {slope:.2f}%"))
    return (f"MH-{g['a']} TO MH-{b}  {g['len']} LF {size}\" {mat} {cls} "
            f"@ {slope:.2f}%")


def make_set(plans_path, specs_path, alt=False):
    STYLE["alt"] = alt
    st, seg = _network()
    # planted changes
    st[17]["out"] = st[17]["out"]               # real inverts kept...
    seg[16]["slope_label"] = 0.60               # ...but labelled 0.60%
    seg[39]["slope"] = 0.25                     # MH-40 to MH-41 too flat
    st[41]["in"] = round(st[40]["out"] - seg[39]["len"] * 0.25 / 100, 2)
    # recompute downstream inverts after 41 so the chain stays consistent
    for i in range(41, 62):
        g = seg[i - 2]
        st[i]["in"] = round(st[i - 1]["out"] - g["len"] * g["slope"] / 100,
                            2) if i > 41 else st[i]["in"]
        st[i]["out"] = round(st[i]["in"] - 0.10, 2)
        st[i]["rim"] = round(st[i]["in"] + 9.5, 2)
    seg[43]["cls"] = "SDR-26"                   # MH-44 to MH-45
    d = fitz.open()
    _sheet(d, "C-001", "COVER SHEET", [
        "SANITARY SEWER IMPROVEMENTS", "SHEET INDEX: C-001 TO C-504"])
    _sheet(d, "C-002", "GENERAL NOTES", [
        "1. ALL GRAVITY SEWER PIPE PER SECTION 33 31 00.",
        "2. MANHOLES PER SECTION 33 39 13.",
        "3. TRENCHING AND BACKFILL PER SECTION 31 23 33.",
        "4. PIPE BEDDING PER SECTION 33 05 13.",
        "5. CONTRACTOR SHALL VERIFY IN FIELD ALL EXISTING UTILITIES.",
        "6. SERVICE LATERALS BY OTHERS.",
        "7. BYPASS PUMPING PLAN TBD.",
        "8. SEE DETAIL 1/C-501 FOR STANDARD MANHOLE.",
        "9. SEE DETAIL 3/C-502 FOR TRENCH SECTION."])
    for n, title in (("C-003", "EXISTING CONDITIONS"),
                     ("C-004", "SURVEY CONTROL"), ("C-005", "DEMOLITION PLAN")):
        _sheet(d, n, title, [f"{title} - SEE SHEET C-002 FOR NOTES",
                             "EXISTING 8\" VCP SEWER TO BE ABANDONED"])
    # 20 plan sheets + 20 profile sheets, 3 runs each
    for k in range(20):
        runs = seg[k * 3:(k + 1) * 3]
        for kind in ("PLAN", "PROFILE"):
            num = f"C-{101 + k}" if kind == "PLAN" else f"C-{121 + k}"
            lines = [f"SANITARY SEWER {kind} STA {k * 10}+00 TO "
                     f"{k * 10 + 10}+00"]
            for g in runs:
                a = g["a"]
                kw = {}
                if kind == "PROFILE" and a == 5:
                    kw["size"] = 10
                if kind == "PROFILE" and a == 23:
                    kw["mat"] = "DIP"
                if "slope_label" in g:
                    kw["slope"] = g["slope_label"]
                lines.append(_seg_line(g, **kw))
                for i in (a, a + 1):
                    if i == 52:
                        lines.append(_st_line(i, st[i], inverts=False))
                        continue
                    rim = st[i]["rim"] + (1.0 if kind == "PROFILE" and
                                          i == 12 else 0)
                    out = st[i]["out"] - (0.5 if kind == "PROFILE" and
                                          i == 31 else 0)
                    lines.append(_st_line(i, st[i], rim, out))
            if kind == "PLAN" and k == 2:
                lines.append("SEE 4/C-599 FOR CONNECTION TO EXISTING")
                lines.append("SEE 2/C-501 FOR DROP MANHOLE")
            if kind == "PLAN" and k == 5:
                lines.append("SEE 7/C-501 FOR OUTSIDE DROP")
                lines.append(_seg_line({"a": 20, "b": 99, "len": 120,
                                        "size": 8, "mat": "PVC",
                                        "cls": "SDR-35", "slope": 0.50}))
            if kind == "PLAN" and k == 8:
                lines.append("LIFT STATION PUMPS P-1 AND P-2, STANDBY P-3")
            _sheet(d, num, f"SANITARY {kind} {k + 1}", lines)
    for n, title, dets in ((501, "MANHOLE DETAILS", range(1, 6)),
                           (502, "TRENCH DETAILS", range(1, 5)),
                           (503, "PAVEMENT REPAIR", range(1, 3))):
        _sheet(d, f"C-{n}", title,
               [f"DETAIL {i} - {title[:-8]} TYPE {i}" for i in dets])
    _sheet(d, "C-504", "LIFT STATION SCHEDULE", [
        "PUMP SCHEDULE", "P-1  SUBMERSIBLE  250 GPM  15 HP",
        "P-2  SUBMERSIBLE  250 GPM  15 HP"])
    _sheet(d, "C-505", "EROSION CONTROL", [
        "SILT FENCE PER SECTION 31 25 00", "SEE DETAIL 2/C-503"])
    d.save(plans_path)
    s = fitz.open()
    for sec, title, body in (
            ("33 31 00", "SANITARY UTILITY SEWERAGE PIPING",
             ["2.1 GRAVITY SEWER PIPE", "A. PVC, ASTM D3034, SDR 35.",
              "B. DUCTILE IRON PIPE, AWWA C151, WHERE SHOWN."]),
            ("33 39 13", "SANITARY SEWER MANHOLES",
             ["2.1 PRECAST MANHOLES, ASTM C478."]),
            ("31 23 33", "TRENCHING AND BACKFILLING",
             ["3.1 BACKFILL IN 8 INCH LIFTS."]),
            ("31 25 00", "EROSION AND SEDIMENTATION CONTROLS",
             ["2.1 SILT FENCE."])):
        p = s.new_page()
        y = 72
        for ln in [f"SECTION {sec} - {title}", "PART 1 - GENERAL"] + body:
            p.insert_text((72, y), ln, fontsize=10)
            y += 18
    s.save(specs_path)
    return d.page_count
