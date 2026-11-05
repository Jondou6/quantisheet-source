"""CSV, XLSX and PDF export (brief 3.10). All three come from one
ExportModel built from settle_claim, so they always agree with the
Settlement tab. Plain reports only: no carrier logos or forms, built-in
Helvetica in the PDF (no font files to license).

No ESX import or export (Jon, Oct 20, 2026). Do not read or write
Xactimate files.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from . import categories, settings
from .cents import apply_bp, bp_text, fmt, money_text, qty_text
from .settle import Settlement, settle_claim

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_text(v: str) -> str:
    """Stop a name from running as a spreadsheet formula."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA_START) else s


@dataclass(frozen=True)
class ExportLine:
    structure: str
    group: str
    room: str
    item_code: str
    description: str
    category: str
    qty_q4: int
    unit: str
    unit_cost: int
    rc: int
    dep_bp: int
    dep: int
    acv: int
    # (material, labor, equipment, other) of the unit cost - 0.2.2
    split: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass(frozen=True)
class ExportModel:
    header: tuple[tuple[str, str], ...]
    lines: tuple[ExportLine, ...]
    settlement: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]
    supplements: tuple[tuple[str, str, int, str], ...]
    claim_number: str
    paid_now: int
    # (file path, caption, taken, where) - PM review NW-16
    photos: tuple[tuple[str, str, str, str], ...] = ()
    # (name, size, floor SF, walls SF, ceiling SF, perimeter LF) - 0.2
    rooms: tuple[tuple[str, str, str, str, str, str], ...] = ()
    # (date, kind, amount cents, reference) and still open - 0.2 (r47 #8)
    payments: tuple[tuple[str, str, int, str], ...] = ()
    still_open: int = 0
    # (description, room, qty, unit RC, RCV, dep bp, dep, ACV, age) - 0.2.2
    contents: tuple[tuple, ...] = ()
    contents_label: str = "Contents"


def build_model(claim, revision=None, settlement: Optional[Settlement] = None,
                printed: str = "", author: str = "",
                photo_folder: Optional[str] = None) -> ExportModel:
    s = settlement or settle_claim(claim)
    names = {st.id: st.name for st in claim.structures}
    groups = {n.id: n.name for n in claim.wbs}
    rooms = {r.id: r.name for r in claim.rooms}
    ctype = claim.claim_type.title()
    header = (
        ("Claim number", claim.claim_number), ("Insured", claim.insured),
        ("Carrier", claim.carrier), ("Loss address", claim.loss_address),
        ("Loss date", claim.loss_date), ("Peril", claim.peril),
        ("Claim type", ctype),
        ("Revision", str(revision.number) if revision else "0"),
        ("Status", revision.status if revision else claim.status),
        ("Printed", printed or datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Author", author or settings.author()),
    )
    order = {st.id: i for i, st in enumerate(claim.structures)}
    rows = []
    for ln in sorted(claim.lines, key=lambda ln: (
            order.get(ln.structure_id, 0), groups.get(ln.group_id, ""),
            rooms.get(ln.room_id, ""), ln.ordinal)):
        rc = ln.rc
        dep = apply_bp(rc, ln.dep_bp)
        rows.append(ExportLine(
            names.get(ln.structure_id, ""), groups.get(ln.group_id, ""),
            rooms.get(ln.room_id, ""), ln.item_code, ln.description,
            categories.label(ln.category), ln.qty_q4, ln.unit,
            ln.unit_cost.total, rc, ln.dep_bp, dep, rc - dep,
            (ln.unit_cost.material, ln.unit_cost.labor,
             ln.unit_cost.equipment, ln.unit_cost.other)))
    st = []
    multi = len(s.structures) > 1
    for r in s.structures:
        p = f"{r.name}: " if multi else ""
        st += [(p + "Replacement cost (RC)", r.rc), (p + "Overhead", r.overhead),
               (p + "Profit", r.profit)]
        if r.ol:
            st.append((p + "Ordinance or law", r.ol))
        st += [(p + "RCV", r.rcv), (p + "Depreciation", r.dep),
               (p + "ACV", r.acv)]
        if claim.claim_type == "commercial" and claim.limits.mode != "blanket":
            st.append((p + "After coinsurance", r.after_coinsurance))
        if not (claim.claim_type == "commercial" and claim.limits.mode == "blanket"):
            st += [(p + "Deductible", r.deductible), (p + "Paid now", r.paid_now)] \
                if multi else [("Deductible", r.deductible)]
    if multi:
        st += [("Total RCV", s.rcv), ("Total depreciation", s.dep),
               ("Total ACV", s.acv)]
    if claim.claim_type == "commercial" and claim.limits.mode == "blanket":
        st += [("After coinsurance (blanket)", s.after_coinsurance),
               ("Deductible", s.deductible)]
    st.append(("Paid now", s.net))
    st.append(("Recoverable depreciation (paid later)", s.recoverable_holdback))
    if claim.claim_type == "residential" and claim.ale is not None:
        st.append(("ALE", s.ale))
    if claim.claim_type == "commercial" and claim.bi_ee is not None:
        st += [("Business income", s.bi), ("Extra expense", s.ee),
               ("BI + EE paid", s.bi_ee)]
    if claim.contents:                       # 0.2.2
        from . import contents as ct
        lab = ct.label(claim)
        st += [(f"{lab} RCV", s.contents_rcv),
               (f"{lab} depreciation", s.contents_dep),
               (f"{lab} ACV", s.contents_acv)]
        if s.contents_deductible:
            st.append((f"{lab} deductible", s.contents_deductible))
        st += [(f"{lab} paid now", s.contents_now),
               (f"{lab} paid later", s.contents_holdback)]
    st.append(("Total indemnity now", s.total_indemnity))
    sup = ()
    if revision is not None:
        sup = tuple((c.kind, c.description, c.rc_delta, c.reason or "NEEDS A REASON")
                    for c in revision.changes if c.included)
    pics = ()
    if claim.photos:
        from . import photos
        pics = photos.for_export(claim, photo_folder)
    from . import rooms as roomcalc
    rms = []
    for r in claim.rooms:
        ms = roomcalc.measure(r)
        if not ms.floor:
            continue
        rms.append((r.name, roomcalc.size_text(r), str(ms.floor), str(ms.walls),
                    str(ms.ceiling), str(ms.perimeter)))
    return ExportModel(header, tuple(rows), tuple(st),
                       tuple(w.plain() for w in s.warnings), sup,
                       claim.claim_number, s.net, pics, tuple(rms),
                       tuple((p.on, p.kind, p.amount_cents, p.reference)
                             for p in claim.payments),
                       s.total_indemnity + s.holdback_total
                       - claim.paid_cents(), _contents_rows(claim, rooms),
                       _contents_label(claim))


def _contents_label(claim) -> str:
    from . import contents as ct
    return ct.label(claim)


def _contents_rows(claim, room_names) -> tuple:
    from . import contents as ct
    return tuple((i.description, room_names.get(i.room_id, ""), i.qty,
                  i.unit_rc_cents, ct.item_rcv(i), i.dep_bp, ct.item_dep(i),
                  ct.item_acv(i), i.age) for i in claim.contents)


LINE_HEAD = ("Structure", "Group", "Room", "Item code", "Description", "Category",
             "Qty", "Unit", "Unit cost", "RC", "Dep %", "Dep", "ACV")
# 0.2.2 (r47 #13): the unit cost's split, after the columns above
SPLIT_HEAD = ("Material", "Labor", "Equipment", "Other")


ROOM_HEAD = ("Room", "Size (L x W x H)", "Floor SF", "Walls SF", "Ceiling SF",
             "Perimeter LF")
PAY_HEAD = ("Payment date", "Kind", "Amount", "Reference")
CONTENTS_HEAD = ("Item", "Room", "Qty", "Each (RC)", "RCV", "Dep %", "Dep",
                 "ACV", "Age")


def _num(v: str):
    """A room measurement as a number for Excel (text kept if it isn't)."""
    try:
        return Decimal(str(v))
    except Exception:
        return safe_text(str(v))


# ------------------------------------------------------------------ CSV

def to_csv(model: ExportModel, path: str) -> str:
    settings.check_safe(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, lineterminator="\r\n")
        for k, v in model.header:
            w.writerow([k, safe_text(v)])
        w.writerow([])
        w.writerow(LINE_HEAD + SPLIT_HEAD)
        for ln in model.lines:
            w.writerow([safe_text(ln.structure), safe_text(ln.group),
                        safe_text(ln.room), safe_text(ln.item_code),
                        safe_text(ln.description), safe_text(ln.category),
                        qty_text(ln.qty_q4), ln.unit, money_text(ln.unit_cost),
                        money_text(ln.rc), bp_text(ln.dep_bp),
                        money_text(ln.dep), money_text(ln.acv)] +
                       [money_text(v) for v in ln.split])
        w.writerow([])
        w.writerow(["Settlement", "Amount"])
        for k, v in model.settlement:
            w.writerow([k, money_text(v)])
        for msg in model.warnings:
            w.writerow(["Warning", safe_text(msg)])
        if model.supplements:
            w.writerow([])
            w.writerow(["Change", "Description", "RC change", "Reason"])
            for kind, desc, d, reason in model.supplements:
                w.writerow([kind, safe_text(desc), money_text(d), safe_text(reason)])
        if model.rooms:                 # 0.2.2: as in the PDF
            w.writerow([])
            w.writerow(ROOM_HEAD)
            for row in model.rooms:
                w.writerow([safe_text(str(v)) for v in row])
        if model.payments:
            w.writerow([])
            w.writerow(PAY_HEAD)
            for on, kind, cents, ref in model.payments:
                w.writerow([safe_text(str(on)), safe_text(str(kind)),
                            money_text(cents), safe_text(ref or "")])
            w.writerow(["Still open", "", money_text(model.still_open), ""])
        if model.contents:              # 0.2.2
            w.writerow([])
            w.writerow([model.contents_label])
            w.writerow(CONTENTS_HEAD)
            for d, rm, q, u, rcv, bp, dep, acv, age in model.contents:
                w.writerow([safe_text(d), safe_text(rm), q, money_text(u),
                            money_text(rcv), bp_text(bp), money_text(dep),
                            money_text(acv), safe_text(age)])
    return path


# ------------------------------------------------------------------ XLSX

def _dec(cents: int) -> Decimal:
    return Decimal(cents) / 100


def to_xlsx(model: ExportModel, path: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    settings.check_safe(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb = Workbook()
    bold = Font(bold=True)
    ws = wb.active
    ws.title = "Summary"
    for k, v in model.header:
        ws.append([k, safe_text(v)])
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 48

    li = wb.create_sheet("Line Items")
    li.append(list(LINE_HEAD + SPLIT_HEAD))
    for c in li[1]:
        c.font = bold
    for ln in model.lines:
        li.append([safe_text(ln.structure), safe_text(ln.group), safe_text(ln.room),
                   safe_text(ln.item_code), safe_text(ln.description),
                   safe_text(ln.category), Decimal(ln.qty_q4) / 10_000, ln.unit,
                   _dec(ln.unit_cost), _dec(ln.rc), Decimal(ln.dep_bp) / 100,
                   _dec(ln.dep), _dec(ln.acv)] + [_dec(v) for v in ln.split])
        r = li.max_row
        li.cell(r, 7).number_format = "0.0000"
        for col in (9, 10, 12, 13, 14, 15, 16, 17):
            li.cell(r, col).number_format = "#,##0.00"
        li.cell(r, 11).number_format = "0.00"
    li.freeze_panes = "A2"
    for col, wdt in zip("ABCDEFGHIJKLMNOPQ", (16, 16, 14, 14, 40, 16, 12, 6, 12,
                                             14, 8, 12, 14, 11, 11, 11, 11)):
        li.column_dimensions[col].width = wdt

    se = wb.create_sheet("Settlement")
    se.append(["Step", "Amount"])
    for c in se[1]:
        c.font = bold
    for k, v in model.settlement:
        se.append([k, _dec(v)])
        se.cell(se.max_row, 2).number_format = "#,##0.00"
    for msg in model.warnings:
        se.append(["Warning", safe_text(msg)])
    se.freeze_panes = "A2"
    se.column_dimensions["A"].width = 40
    se.column_dimensions["B"].width = 18

    su = wb.create_sheet("Supplements")
    su.append(["Change", "Description", "RC change", "Reason"])
    for c in su[1]:
        c.font = bold
    for kind, desc, d, reason in model.supplements:
        su.append([kind, safe_text(desc), _dec(d), safe_text(reason)])
        su.cell(su.max_row, 3).number_format = "#,##0.00"
    su.freeze_panes = "A2"
    su.column_dimensions["B"].width = 40
    su.column_dimensions["D"].width = 30

    if model.rooms:                     # 0.2.2: as in the PDF
        rm = wb.create_sheet("Rooms")
        rm.append(list(ROOM_HEAD))
        for c in rm[1]:
            c.font = bold
        for row in model.rooms:
            rm.append([safe_text(str(row[0])), safe_text(str(row[1]))] +
                      [_num(v) for v in row[2:]])
            for col in range(3, 7):
                rm.cell(rm.max_row, col).number_format = "#,##0.00"
        rm.freeze_panes = "A2"
        for col, wdt in zip("ABCDEF", (24, 20, 12, 12, 12, 14)):
            rm.column_dimensions[col].width = wdt
    if model.payments:
        pa = wb.create_sheet("Payments")
        pa.append(list(PAY_HEAD))
        for c in pa[1]:
            c.font = bold
        for on, kind, cents, ref in model.payments:
            pa.append([safe_text(str(on)), safe_text(str(kind)), _dec(cents),
                       safe_text(ref or "")])
            pa.cell(pa.max_row, 3).number_format = "#,##0.00"
        pa.append(["Still open", "", _dec(model.still_open), ""])
        pa.cell(pa.max_row, 3).number_format = "#,##0.00"
        pa.freeze_panes = "A2"
        pa.column_dimensions["A"].width = 14
        pa.column_dimensions["D"].width = 30
    if model.contents:                  # 0.2.2
        co = wb.create_sheet("Contents")
        co.append(list(CONTENTS_HEAD))
        for c in co[1]:
            c.font = bold
        for d, rm, q, u, rcv, bp, dep, acv, age in model.contents:
            co.append([safe_text(d), safe_text(rm), q, _dec(u), _dec(rcv),
                       Decimal(bp) / 100, _dec(dep), _dec(acv),
                       safe_text(age)])
            r = co.max_row
            for col in (4, 5, 7, 8):
                co.cell(r, col).number_format = "#,##0.00"
            co.cell(r, 6).number_format = "0.00"
        co.freeze_panes = "A2"
        for col, wdt in zip("ABCDEFGHI", (36, 16, 6, 12, 12, 8, 12, 12, 10)):
            co.column_dimensions[col].width = wdt
    wb.save(path)
    return path


# ------------------------------------------------------------------ PDF

W, H = 612, 792                  # Letter
M = 40
FONT, BOLD = "helv", "hebo"


def _fit(text: str, width: float, size: float, font=FONT) -> str:
    import pymupdf as fitz
    t = str(text)
    if fitz.get_text_length(t, fontname=font, fontsize=size) <= width:
        return t
    while t and fitz.get_text_length(t + "...", fontname=font,
                                     fontsize=size) > width:
        t = t[:-1]
    return t + "..."


def _wrap(text: str, width: float, size: float, font=FONT,
          max_lines: int = 3) -> list[str]:
    """Text broken into lines that fit `width` (0.2.2: long room names were
    cut off). Words longer than a line are split; past `max_lines` the
    last line ends in '...'."""
    import pymupdf as fitz

    def w(t):
        return fitz.get_text_length(t, fontname=font, fontsize=size)

    lines, cur = [], ""
    for word in str(text).split():
        while w(word) > width:                       # one very long word
            k = len(word)
            while k > 1 and w(word[:k]) > width:
                k -= 1
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:k])
            word = word[k:]
        t = (cur + " " + word) if cur else word
        if w(t) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur or not lines:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [
            _fit(" ".join(lines[max_lines - 1:]), width, size, font)]
    return lines


# columns: (title, x, width, right-aligned)
_COLS = (("Item", M, 62, False), ("Description", M + 64, 168, False),
         ("Qty", M + 234, 52, True), ("Unit", M + 290, 26, False),
         ("Unit cost", M + 318, 50, True), ("RC", M + 370, 56, True),
         ("Dep", M + 428, 50, True), ("ACV", M + 480, 52, True))


def to_pdf(model: ExportModel, path: str) -> str:
    import pymupdf as fitz
    settings.check_safe(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc = fitz.open()
    state = {"page": None, "y": 0}

    def new_page():
        pg = doc.new_page(width=W, height=H)
        pg.insert_text((M, M), "ClaimIT - Claim " + model.claim_number,
                       fontname=BOLD, fontsize=11)
        hd = dict(model.header)
        pg.insert_text((M, M + 14), _fit(
            f"{hd.get('Insured', '')}  |  {hd.get('Loss address', '')}  |  "
            f"{hd.get('Claim type', '')}  |  Rev {hd.get('Revision', '0')} "
            f"({hd.get('Status', '')})", W - 2 * M, 8), fontname=FONT, fontsize=8)
        pg.draw_line((M, M + 20), (W - M, M + 20), width=0.5)
        state["page"], state["y"] = pg, M + 36
        return pg

    def need(h, table_head=False):
        if state["y"] + h > H - M - 20:
            new_page()
            if table_head:
                head_row()

    def text(x, s, size=9, font=FONT, right=False, width=None):
        pg, y = state["page"], state["y"]
        if width:
            s = _fit(s, width, size, font)
        if right and width:
            x = x + width - fitz.get_text_length(s, fontname=font, fontsize=size)
        pg.insert_text((x, y), s, fontname=font, fontsize=size)

    def head_row():
        for title, x, wd, right in _COLS:
            text(x, title, 8, BOLD, right, wd)
        state["page"].draw_line((M, state["y"] + 3), (W - M, state["y"] + 3),
                                width=0.3)
        state["y"] += 13

    new_page()
    # page 1: claim header + settlement summary box
    for k, v in model.header:
        text(M, k, 9, BOLD)
        text(M + 90, v, 9, width=W - 2 * M - 90)
        state["y"] += 12
    state["y"] += 8
    box = [("Paid now", model.paid_now)] + [
        (k, v) for k, v in model.settlement
        if k in ("RCV", "Total RCV", "Depreciation", "Total depreciation", "ACV",
                 "Total ACV", "Deductible", "Recoverable depreciation (paid later)",
                 "Total indemnity now")]
    top = state["y"]
    hbox = 16 + 12 * len(box)
    state["page"].draw_rect(fitz.Rect(M, top - 10, M + 300, top - 10 + hbox),
                            width=0.8)
    text(M + 8, "Settlement summary", 10, BOLD)
    state["y"] += 14
    for k, v in box:
        text(M + 8, k, 9)
        text(M + 180, fmt(v), 9, BOLD if k == "Paid now" else FONT, True, 110)
        state["y"] += 12
    state["y"] = top - 10 + hbox + 20

    text(M, "Line items", 11, BOLD)
    state["y"] += 16
    head_row()
    cur = None
    for ln in model.lines:
        key = " / ".join(x for x in (ln.structure, ln.group, ln.room) if x)
        if key != cur:
            heads = _wrap(key or "(no group)", W - 2 * M, 8, BOLD)
            need(15 + 11 * len(heads), True)
            cur = key
            for h in heads:
                text(M, h, 8, BOLD)
                state["y"] += 11
        desc = _wrap(ln.description, _COLS[1][2], 8)
        need(11 * len(desc) + 1, True)
        vals = (ln.item_code, desc[0], qty_text(ln.qty_q4), ln.unit,
                fmt(ln.unit_cost), fmt(ln.rc),
                f"{fmt(ln.dep)}", fmt(ln.acv))
        for (title, x, wd, right), v in zip(_COLS, vals):
            text(x, v, 8, FONT, right, wd)
        for more in desc[1:]:
            state["y"] += 10
            text(_COLS[1][1], more, 8)
        state["y"] += 11

    if model.rooms:                     # 0.2: how the quantities were measured
        state["y"] += 10
        need(30)
        text(M, "Room measurements", 11, BOLD)
        state["y"] += 16
        cols = ((M, "Room", 130), (M + 132, "Size (L x W x H)", 120),
                (M + 254, "Floor SF", 60), (M + 316, "Walls SF", 60),
                (M + 378, "Ceiling SF", 64), (M + 444, "Perimeter LF", 70))
        for x, title, wd in cols:
            text(x, title, 8, BOLD, width=wd)
        state["y"] += 11
        for row in model.rooms:
            name = _wrap(row[0], cols[0][2], 8)
            size = _wrap(row[1], cols[1][2], 8)
            n = max(len(name), len(size))
            need(10 * n + 2)
            y0 = state["y"]
            for (x, _t, wd), v in zip(cols[2:], row[2:]):
                text(x, v, 8, width=wd)
            for col, parts in ((cols[0], name), (cols[1], size)):
                state["y"] = y0
                for t in parts:
                    text(col[0], t, 8)
                    state["y"] += 10
            state["y"] = y0 + 10 * n + 1

    state["y"] += 10
    need(30)
    text(M, "Settlement", 11, BOLD)
    state["y"] += 16
    for k, v in model.settlement:
        need(12)
        text(M, k, 9, BOLD if k == "Paid now" else FONT, width=300)
        text(M + 320, fmt(v), 9, BOLD if k == "Paid now" else FONT, True, 110)
        state["y"] += 12
    for msg in model.warnings:
        need(12)
        text(M, "Warning: " + msg, 9, width=W - 2 * M)
        state["y"] += 12
    if model.contents:                  # 0.2.2: the contents list
        state["y"] += 10
        need(30)
        text(M, model.contents_label, 11, BOLD)
        state["y"] += 16
        cc = ((M, "Item", 170, False), (M + 172, "Room", 70, False),
              (M + 244, "Qty", 26, True), (M + 272, "Each", 56, True),
              (M + 330, "RCV", 62, True), (M + 394, "Dep %", 36, True),
              (M + 432, "ACV", 62, True))
        for x, title, wd, right in cc:
            text(x, title, 8, BOLD, right, wd)
        state["y"] += 11
        for d, rm, q, u, rcv, bp, dep, acv, age in model.contents:
            desc = _wrap(d + (f" ({age})" if age else ""), cc[0][2], 8)
            need(10 * len(desc) + 2)
            y0 = state["y"]
            for (x, _t, wd, right), v in zip(
                    cc[1:], (rm, str(q), fmt(u), fmt(rcv), bp_text(bp),
                             fmt(acv))):
                text(x, v, 8, FONT, right, wd)
            for t in desc:
                text(M, t, 8)
                state["y"] += 10
            state["y"] = y0 + 10 * len(desc) + 1
        tot = (sum(r[4] for r in model.contents),
               sum(r[7] for r in model.contents))
        need(12)
        text(M, "Total", 8, BOLD)
        text(cc[4][0], fmt(tot[0]), 8, BOLD, True, cc[4][2])
        text(cc[6][0], fmt(tot[1]), 8, BOLD, True, cc[6][2])
        state["y"] += 12
    if model.payments:                  # 0.2: what the carrier has paid
        state["y"] += 10
        need(30)
        text(M, "Payments received", 11, BOLD)
        state["y"] += 16
        for on, kind, cents, ref in model.payments:
            need(12)
            text(M, on, 9, width=80)
            text(M + 82, kind, 9, width=90)
            text(M + 174, ref, 9, width=140)
            text(M + 320, fmt(cents), 9, FONT, True, 110)
            state["y"] += 12
        need(12)
        text(M, "Still open (now and recoverable later)", 9, BOLD, width=300)
        text(M + 320, fmt(model.still_open), 9, BOLD, True, 110)
        state["y"] += 12
    if model.supplements:
        state["y"] += 10
        need(30)
        text(M, "Supplement changes", 11, BOLD)
        state["y"] += 16
        for kind, desc, d, reason in model.supplements:
            need(12)
            text(M, kind, 8, width=60)
            text(M + 62, desc, 8, width=200)
            text(M + 264, fmt(d), 8, FONT, True, 70)
            text(M + 340, reason, 8, width=190)
            state["y"] += 11

    # photo pages, two to a page, with caption, date and what they show
    for k, (pic, caption, taken, where_) in enumerate(model.photos):
        if k % 2 == 0:
            new_page()
            text(M, "Photos", 11, BOLD)
            state["y"] += 10
        top = state["y"]
        box = fitz.Rect(M, top, W - M, top + (H - 2 * M - 120) / 2)
        try:
            state["page"].insert_image(box, filename=pic,
                                       keep_proportion=True)
        except Exception:                                 # noqa: BLE001
            state["page"].draw_rect(box, width=0.5)
        state["y"] = box.y1 + 12
        text(M, f"Photo {k + 1}: {caption}", 9, BOLD, width=W - 2 * M)
        state["y"] += 11
        text(M, f"Taken {taken or 'date unknown'}  |  {where_}", 8,
             width=W - 2 * M)
        state["y"] += 18

    n = doc.page_count
    for i, pg in enumerate(doc, 1):
        s = f"Page {i} of {n}"
        pg.insert_text((W - M - fitz.get_text_length(s, fontname=FONT, fontsize=8),
                        H - M + 10), s, fontname=FONT, fontsize=8)
    doc.set_metadata({"title": f"Claim {model.claim_number}",
                      "creator": "ClaimIT"})
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def default_export_path(claim, ext: str) -> str:
    from .store import _safe_name
    return os.path.join(settings.exports_folder(),
                        f"{_safe_name(claim.claim_number)}.{ext}")
