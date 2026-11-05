"""Contract billing: schedule of values, pay applications, change orders
and lien waivers, saved inside the job PDF.

* Schedule of values (SOV): the contract broken into line items. It can be
  built from the estimate (by trade, assembly or CSI division, at the
  proposal's prices). Executed change orders become their own SOV lines.
* Change orders move PCO (potential) -> COR (request sent to the owner)
  -> CO (executed), or are rejected / voided. Each step is logged. A PCO
  can be priced from takeoff markups (the drawn change) plus overhead and
  profit.
* Pay applications follow the G702 / G703 layout: per line, work from
  previous applications, work this period, materials presently stored,
  total to date, % complete, balance to finish and retainage; the summary
  lines 1-9 and the change order summary. A certified application is
  frozen: its numbers are kept as certified.
* Lien waivers: conditional / unconditional, progress / final.

(The layout follows the G702 / G703 forms; it is not an AIA document.)
(Built on the Venice AI draft, rewritten: the draft counted executed
change orders twice and invented 10% progress when none was entered.)
"""
from . import safeio
import copy
import datetime as _dt
import json
import logging
import math
import re

import fitz

from . import settings
from . import embfiles

log = logging.getLogger(__name__)

FILE = "quantisheet_money.json"
STAGES = ("pco", "cor", "co", "rejected", "void")
STAGE_LABEL = {"pco": "Potential (PCO)", "cor": "Requested (COR)",
               "co": "Executed (CO)", "rejected": "Rejected",
               "void": "Void"}
WAIVER_KINDS = {
    "conditional_progress": "Conditional Waiver and Release on Progress "
                            "Payment",
    "unconditional_progress": "Unconditional Waiver and Release on "
                              "Progress Payment",
    "conditional_final": "Conditional Waiver and Release on Final Payment",
    "unconditional_final": "Unconditional Waiver and Release on Final "
                           "Payment",
}
INFO_FIELDS = ("project", "project_address", "owner", "contractor",
               "architect", "contract_no", "contract_date", "contract_for")


class BillingError(ValueError):
    pass


def _today():
    return _dt.date.today().isoformat()


def _now():
    return _dt.datetime.now().isoformat(timespec="minutes")


def _who():
    try:
        return settings.author() or ""
    except Exception:
        return ""


def _num(v):
    """Dollars from a number or text ("$1,234.50"; "(500)" is -500, the
    accounting negative dmoney.D also reads). Blank is 0 (nothing entered).
    Text that isn't a number (a typo like "12,5OO") is None - never a
    silent 0 - so the caller can refuse it or flag it."""
    s = str(v if v is not None else "").replace("$", "").replace(
        ",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s[1:-1].strip() if neg else s
    if neg and s.startswith(("-", "+")):
        return None                            # "(-500)": which sign?
    if not s:
        return 0.0
    try:
        f = float(s)
    except ValueError:
        return None
    if not math.isfinite(f):
        return None
    return -f if neg else f


def _amount(v, what):
    """_num for something a person typed: refuse unreadable text."""
    n = _num(v)
    if n is None:
        raise BillingError(f"{what}: can't read {str(v).strip()!r} as a "
                           f"dollar amount.")
    return n


# ---- storage ----------------------------------------------------------------

def blank():
    return {"info": {k: "" for k in INFO_FIELDS},
            "retainage_work": 10.0, "retainage_stored": 10.0,
            "sov": [], "changes": [], "payapps": [], "waivers": [],
            "counter": {"PCO": 0, "COR": 0, "CO": 0}}


def read(doc):
    data = blank()
    try:
        if FILE in embfiles.names(doc):
            saved = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k == "info":
                        data["info"].update(v or {})
                    elif k == "counter":
                        data["counter"].update(v or {})
                    else:
                        data[k] = v
    except Exception:
        log.warning("could not read billing data", exc_info=True)
    return data


def write(doc, data):
    raw = json.dumps(data, indent=1).encode("utf-8")
    embfiles.put(doc, FILE, raw, "QuantiSheet billing")


def set_info(doc, retainage_work=None, retainage_stored=None, **info):
    data = read(doc)
    for k, v in info.items():
        if k in INFO_FIELDS:
            data["info"][k] = str(v or "")
    if retainage_work is not None:
        data["retainage_work"] = float(retainage_work)
    if retainage_stored is not None:
        data["retainage_stored"] = float(retainage_stored)
    write(doc, data)
    return data


def _next(data, prefix):
    data["counter"][prefix] = int(data["counter"].get(prefix, 0)) + 1
    return f"{prefix}-{data['counter'][prefix]:03d}"


# ---- schedule of values ------------------------------------------------------------

def sov(doc):
    return read(doc)["sov"]


def _certified(data):
    return [a for a in data["payapps"] if a.get("status") == "certified"]


def set_sov(doc, lines):
    """Replace the contract lines (change order lines are kept). Each line:
    {item?, csi?, desc, scheduled}. Once an application is certified the
    billed lines can't be removed or re-valued (only new lines added),
    because the certified numbers depend on them."""
    from . import csi
    data = read(doc)
    old = {l["item"]: l for l in data["sov"] if not l.get("co")}
    certified = _certified(data)
    new, used = [], set(l["item"] for l in data["sov"] if l.get("co"))
    n = 0
    for ln in lines:
        desc = str(ln.get("desc") or "").strip()
        if not desc:
            continue
        n += 1
        item = str(ln.get("item") or n).strip()
        while item in used:
            n += 1
            item = str(n)
        used.add(item)
        code = str(ln.get("csi") or "").strip()
        new.append({"item": item, "csi": csi.parse_code(code) or code,
                    "desc": desc, "scheduled": round(_amount(
                        ln.get("scheduled"), f"Line {item}"), 2), "co": ""})
    if certified:
        keep = {l["item"]: l for l in new}
        for item, l in old.items():
            if item not in keep:
                raise BillingError(f"Line {item} is on a certified pay "
                                   f"application and can't be removed.")
            if abs(keep[item]["scheduled"] - l["scheduled"]) > 0.005:
                raise BillingError(f"Line {item} is on a certified pay "
                                   f"application; change its value with a "
                                   f"change order instead.")
    data["sov"] = new + [l for l in data["sov"] if l.get("co")]
    write(doc, data)
    return data["sov"]


def from_estimate(doc, by="trade", front_load=0.0, months=12):
    """SOV lines from the estimate at the proposal's prices (the whole bid
    build-up), so the SOV adds up to the bid. by: trade, assembly or csi.
    front_load: move that share of value from the last third of the
    schedule to the first third (see bidbuild.front_load); the total stays
    the same."""
    from . import assemblies, csi, proposal
    pdata = dict(proposal.read(doc), detail="assembly")
    priced = proposal.price(doc, pdata)
    rows = {r["name"]: r for r in assemblies.rollup(doc)[0]}
    groups = {}
    for ln in priced["lines"]:
        r = rows.get(ln["name"], {})
        code = r.get("csi", "")
        if by == "assembly":
            key, desc = ln["name"], ln["name"]
        elif by == "csi":
            div = code[:2] if code else ""
            key = div or "zz"
            desc = (f"Division {div} - {csi.division_title(code)}" if div
                    else "Unclassified")
            code = f"{div} 00 00" if div else ""
        else:
            key = desc = ln.get("trade") or "General"
            code = ""
        g = groups.setdefault(key, {"csi": code, "desc": desc,
                                    "scheduled": 0.0})
        g["scheduled"] += ln["price"]
    out = [groups[k] for k in sorted(groups)] if by == "csi" else \
        list(groups.values())
    for g in out:
        g["scheduled"] = round(g["scheduled"], 2)
    if front_load and out:
        from . import bidbuild
        fl = bidbuild.front_load([g["scheduled"] for g in out], front_load,
                                 months)
        for g, v in zip(out, fl["values"]):
            g["scheduled"] = v
    return out


def original_contract(data):
    return sum(l["scheduled"] for l in data["sov"] if not l.get("co"))


# ---- change orders --------------------------------------------------------------

def changes(doc, stage=None):
    return [c for c in read(doc)["changes"]
            if stage is None or c["stage"] == stage]


def _co_num(v):
    """The number in a CO/COR label: "CO-007", "7" and 7 are all 7."""
    m = re.search(r"(\d+)\s*$", str(v if v is not None else ""))
    return int(m.group(1)) if m else None


def _find(data, cid):
    for c in data["changes"]:
        if cid in (c["id"], c.get("cor_no"), c.get("co_no")):
            return c
    # "CO-7", "7" or 7 for "CO-007" (review 3 #10: number, not text)
    n = _co_num(cid)
    want = _prefix(cid)
    if n is not None:
        for key in ("co_no", "cor_no"):
            for c in data["changes"]:
                v = c.get(key)
                if v and _co_num(v) == n and want in ("", _prefix(v)):
                    return c
    raise KeyError(cid)


def _prefix(v):
    return str(v if v is not None else "").rstrip("0123456789").strip(
        " -#").upper()


def _log(c, action, note="", by=None):
    c.setdefault("history", []).append({"when": _now(),
                                        "who": by or _who(),
                                        "action": action, "note": note})


def price_markups(doc, refs, markup_pct=0.0):
    """(cost, price, problems) of the takeoff measurements `refs` through
    their assemblies; price adds overhead & profit `markup_pct`."""
    from . import assemblies
    rows, totals, problems = assemblies.rollup(doc, refs=list(refs))
    cost = round(totals["total"], 2)
    return cost, round(cost * (1 + float(markup_pct or 0) / 100), 2), \
        problems


def new_change(doc, title, amount=0.0, days=0, reason="", refs=(), rfi="",
               cost=None, markup_pct=None, by=None):
    """A potential change order (PCO-001...). Returns its id."""
    if not str(title).strip():
        raise BillingError("A change needs a title.")
    data = read(doc)
    cid = _next(data, "PCO")
    c = {"id": cid, "title": str(title).strip(), "stage": "pco",
         "amount": round(_amount(amount, "Amount"), 2),
         "days": int(days or 0),
         "reason": reason, "refs": [dict(r) for r in refs], "rfi": rfi,
         "cost": None if cost is None else round(_amount(cost, "Cost"), 2),
         "markup_pct": None if markup_pct is None else float(markup_pct),
         "raised": _today(), "cor_no": "", "co_no": "", "submitted": "",
         "executed": "", "approved_amount": 0.0, "approved_days": 0,
         "history": []}
    _log(c, "created", by=by)
    data["changes"].append(c)
    write(doc, data)
    return cid


def update_change(doc, cid, **fields):
    data = read(doc)
    c = _find(data, cid)
    if c["stage"] in ("co", "void"):
        raise BillingError(f"{c.get('co_no') or c['id']} is "
                           f"{STAGE_LABEL[c['stage']].lower()} and can't be "
                           f"edited.")
    for k in ("title", "reason", "rfi"):
        if k in fields:
            c[k] = str(fields[k] or "")
    if "amount" in fields:
        c["amount"] = round(_amount(fields["amount"], "Amount"), 2)
    if "days" in fields:
        c["days"] = int(fields["days"] or 0)
    if "cost" in fields:
        c["cost"] = None if fields["cost"] is None else \
            round(_amount(fields["cost"], "Cost"), 2)
    if "markup_pct" in fields:
        c["markup_pct"] = None if fields["markup_pct"] is None else \
            float(fields["markup_pct"])
    if "refs" in fields:
        c["refs"] = [dict(r) for r in fields["refs"]]
    _log(c, "edited")
    write(doc, data)
    return c


def submit(doc, cid, note="", by=None):
    """Send a PCO to the owner as a change order request (COR-001...)."""
    data = read(doc)
    c = _find(data, cid)
    if c["stage"] != "pco":
        raise BillingError(f"{c['id']} is {STAGE_LABEL[c['stage']]}; only a "
                           f"potential change can be submitted.")
    c["stage"] = "cor"
    c["cor_no"] = _next(data, "COR")
    c["submitted"] = _today()
    _log(c, f"submitted as {c['cor_no']}", note, by)
    write(doc, data)
    return c


def execute(doc, cid, amount=None, days=None, date=None, note="", by=None):
    """The owner signed it: CO-001..., added to the schedule of values."""
    data = read(doc)
    c = _find(data, cid)
    if c["stage"] not in ("pco", "cor"):
        raise BillingError(f"{c['id']} is {STAGE_LABEL[c['stage']]} and "
                           f"can't be executed.")
    c["approved_amount"] = round(_amount(c["amount"] if amount is None
                                         else amount, "Amount"), 2)
    c["approved_days"] = int(c["days"] if days is None else days)
    c["stage"] = "co"
    c["co_no"] = _next(data, "CO")
    c["executed"] = date or _today()
    data["sov"].append({"item": c["co_no"], "csi": "",
                        "desc": f"{c['co_no']} {c['title']}",
                        "scheduled": c["approved_amount"], "co": c["id"]})
    _log(c, f"executed as {c['co_no']} for ${c['approved_amount']:,.2f}",
         note, by)
    write(doc, data)
    return c


def reject(doc, cid, note="", void=False, by=None):
    data = read(doc)
    c = _find(data, cid)
    if c["stage"] == "co":
        raise BillingError(f"{c['co_no']} is executed; reverse it with a new "
                           f"(deduct) change order.")
    c["stage"] = "void" if void else "rejected"
    _log(c, c["stage"], note, by)
    write(doc, data)
    return c


def change_summary(data, before=None, through=None):
    """Executed COs as G702's change order summary: (prev add, prev deduct,
    this add, this deduct). `before` = the previous application's period
    end; `through` = this one's."""
    pa = pd = ta = td = 0.0
    for c in data["changes"]:
        if c["stage"] != "co":
            continue
        if through and c["executed"] > through:
            continue
        amt = c["approved_amount"]
        prev = bool(before) and c["executed"] <= before
        if amt >= 0:
            if prev:
                pa += amt
            else:
                ta += amt
        elif prev:
            pd += -amt
        else:
            td += -amt
    return pa, pd, ta, td


# ---- pay applications --------------------------------------------------------------

def pay_apps(doc):
    return read(doc)["payapps"]


def _app(data, no):
    for a in data["payapps"]:
        if int(a["no"]) == int(no):
            return a
    raise KeyError(no)


def new_pay_app(doc, period_to, app_date=None):
    """The next application (a draft). Materials stored on the last one
    carry over until they are billed as installed work."""
    data = read(doc)
    if any(a.get("status") != "certified" for a in data["payapps"]):
        raise BillingError("Certify (or delete) the draft application "
                           "before starting the next one.")
    if not data["sov"]:
        raise BillingError("Set up the schedule of values first.")
    prev = data["payapps"][-1] if data["payapps"] else None
    if prev and period_to <= prev["period_to"]:
        raise BillingError(f"The period must end after {prev['period_to']}.")
    no = len(data["payapps"]) + 1
    lines = {}
    if prev:
        for item, ln in prev["lines"].items():
            s = _num(ln.get("stored"))
            if s is None or s:             # unreadable stays, to be flagged
                lines[item] = {"work": 0.0, "stored": ln["stored"]
                               if s is None else s}
    data["payapps"].append({
        "no": no, "period_to": period_to, "date": app_date or _today(),
        "status": "draft", "lines": lines,
        "retainage_work": data["retainage_work"],
        "retainage_stored": data["retainage_stored"]})
    write(doc, data)
    return no


def delete_pay_app(doc, no):
    data = read(doc)
    a = _app(data, no)
    if a.get("status") == "certified":
        raise BillingError("A certified application can't be deleted.")
    data["payapps"].remove(a)
    write(doc, data)


def _draft(data, no):
    a = _app(data, no)
    if a.get("status") == "certified":
        raise BillingError(f"Application {no} is certified and can't be "
                           f"changed.")
    return a


def set_progress(doc, no, item, work=None, stored=None, percent=None):
    """This period's work on a line, as dollars (`work`) or as the line's
    total % complete to date (`percent`); `stored` = materials presently
    stored, not yet installed."""
    data = read(doc)
    a = _draft(data, no)
    line = next((l for l in data["sov"] if l["item"] == str(item)), None)
    if line is None:
        raise KeyError(item)
    ln = a["lines"].setdefault(str(item), {"work": 0.0, "stored": 0.0})
    if percent is not None:
        prev = _previous_work(data, a["no"]).get(str(item), 0.0)
        work = round(line["scheduled"] * float(percent) / 100 - prev, 2)
    if work is not None:
        ln["work"] = round(_amount(work, f"Line {item} work"), 2)
    if stored is not None:
        ln["stored"] = round(_amount(stored, f"Line {item} stored"), 2)
    write(doc, data)
    return ln


def set_retainage(doc, no, work=None, stored=None):
    """This application's retainage % (e.g. 5 after 50% complete, or 0 on
    the final application to release it)."""
    data = read(doc)
    a = _draft(data, no)
    if work is not None:
        a["retainage_work"] = float(work)
    if stored is not None:
        a["retainage_stored"] = float(stored)
    write(doc, data)


# Only certified (or paid) applications count as "previously billed"; a
# draft that was never certified is not (review 3 #11).
COUNTED = ("certified", "paid")


def _previous_work(data, no):
    out = {}
    for a in data["payapps"]:
        if int(a["no"]) >= int(no):
            break
        if str(a.get("status") or "draft").lower() not in COUNTED:
            continue
        for item, ln in a["lines"].items():
            out[item] = out.get(item, 0.0) + (_num(ln.get("work")) or 0.0)
    return out


def compute(doc, no, data=None):
    """Everything a G702 and G703 show for application `no`. A certified
    application returns the numbers it was certified with."""
    data = data or read(doc)
    a = _app(data, no)
    if a.get("status") in COUNTED and a.get("certified_values"):
        return copy.deepcopy(a["certified_values"])
    prev_work = _previous_work(data, no)
    skipped = [int(x["no"]) for x in data["payapps"]
               if int(x["no"]) < int(no) and
               str(x.get("status") or "draft").lower() not in COUNTED]
    rw = float(a.get("retainage_work", data["retainage_work"])) / 100
    rs = float(a.get("retainage_stored", data["retainage_stored"])) / 100
    rows, warnings = [], []
    if skipped:
        warnings.append("Application(s) " + ", ".join(map(str, skipped)) +
                        " aren't certified yet, so their work isn't counted "
                        "as previously billed.")
    for x in data["payapps"]:                  # never a silent $0
        if int(x["no"]) > int(no):
            continue
        for item, ln in x["lines"].items():
            for k in ("work", "stored"):
                if _num(ln.get(k)) is None:
                    warnings.append(f"Application {x['no']} line {item}: "
                                    f"{k} {ln.get(k)!r} can't be read, so "
                                    f"it isn't counted.")
    for l in data["sov"]:
        if l.get("co"):
            c = next((c for c in data["changes"] if c["id"] == l["co"]),
                     None)
            if c and c["executed"] > a["period_to"]:
                continue                 # executed after this period
        ln = a["lines"].get(l["item"], {})
        prev = prev_work.get(l["item"], 0.0)
        this = _num(ln.get("work")) or 0.0
        stored = _num(ln.get("stored")) or 0.0
        done = prev + this + stored
        row = {"item": l["item"], "csi": l.get("csi", ""), "desc": l["desc"],
               "scheduled": l["scheduled"], "previous": prev, "this": this,
               "stored": stored, "completed": done,
               "percent": done / l["scheduled"] * 100 if l["scheduled"]
               else 0.0, "balance": l["scheduled"] - done,
               "retainage": (prev + this) * rw + stored * rs}
        if l["scheduled"] >= 0 and done > l["scheduled"] + 0.005:
            warnings.append(f"Line {l['item']} is billed past 100% "
                            f"({row['percent']:.0f}%).")
        if done < -0.005 and l["scheduled"] >= 0:
            warnings.append(f"Line {l['item']} is below zero.")
        rows.append(row)
    tot = {k: round(sum(r[k] for r in rows), 2)
           for k in ("scheduled", "previous", "this", "stored", "completed",
                     "balance", "retainage")}
    work_done = tot["previous"] + tot["this"]
    ret_work = round(work_done * rw, 2)
    ret_stored = round(tot["stored"] * rs, 2)
    prev_app = None
    for x in data["payapps"]:
        if int(x["no"]) < int(no) and \
                str(x.get("status") or "draft").lower() in COUNTED:
            prev_app = x
    previous_cert = compute(doc, prev_app["no"], data)["g702"]["6"] \
        if prev_app else 0.0
    pa, pd, ta, td = change_summary(
        data, prev_app["period_to"] if prev_app else None, a["period_to"])
    orig = round(original_contract(data), 2)
    net = round(pa - pd + ta - td, 2)
    line3 = round(orig + net, 2)
    line4 = tot["completed"]
    line5 = round(ret_work + ret_stored, 2)
    line6 = round(line4 - line5, 2)
    g = {"1": orig, "2": net, "3": line3, "4": line4,
         "5a": ret_work, "5b": ret_stored, "5": line5, "6": line6,
         "7": round(previous_cert, 2), "8": round(line6 - previous_cert, 2),
         "9": round(line3 - line6, 2)}
    return {"no": int(no), "period_to": a["period_to"], "date": a["date"],
            "status": a.get("status", "draft"),
            "retainage_work": rw * 100, "retainage_stored": rs * 100,
            "rows": rows, "totals": tot, "g702": g,
            "changes": {"prev_add": pa, "prev_deduct": pd, "this_add": ta,
                        "this_deduct": td},
            "info": dict(data["info"]), "warnings": warnings}


G702_LINES = [
    ("1", "Original contract sum"),
    ("2", "Net change by change orders"),
    ("3", "Contract sum to date (line 1 + 2)"),
    ("4", "Total completed and stored to date (from the detail sheet)"),
    ("5a", "Retainage: % of completed work"),
    ("5b", "Retainage: % of stored material"),
    ("5", "Total retainage (lines 5a + 5b)"),
    ("6", "Total earned less retainage (line 4 - line 5)"),
    ("7", "Less previous certificates for payment (line 6 from prior "
          "certificate)"),
    ("8", "Current payment due"),
    ("9", "Balance to finish, including retainage (line 3 - line 6)"),
]


def certify(doc, no, by=None):
    """Freeze the application with the numbers as they stand."""
    data = read(doc)
    a = _draft(data, no)
    if any(int(x["no"]) < int(no) and x.get("status") != "certified"
           for x in data["payapps"]):
        raise BillingError("Certify the earlier applications first.")
    bad = sorted({i for i, ln in a["lines"].items() for k in ("work", "stored")
                  if _num(ln.get(k)) is None})
    if bad:
        raise BillingError(f"Line {', '.join(bad)} has an amount that can't "
                           f"be read; re-enter it before certifying.")
    vals = compute(doc, no, data)
    a["status"] = "certified"
    a["certified"] = _now()
    a["certified_by"] = by or _who()
    a["certified_values"] = vals
    a["certified_values"]["status"] = "certified"
    write(doc, data)
    return vals


# ---- documents ----------------------------------------------------------------

def _para(page, rect, text, fontsize=9, color=(0, 0, 0)):
    from .forms import write_box
    write_box(page, rect, text, fontsize, color=color)


def _m(v):
    return f"${v:,.2f}" if v >= 0 else f"(${-v:,.2f})"


class _Page:
    def __init__(self, out, w, h):
        self.p = out.new_page(width=w, height=h)
        self.w, self.h = w, h

    def text(self, x, y, s, size=9, bold=False, right=None, color=(0, 0, 0)):
        font = "hebo" if bold else "helv"
        s = str(s)
        if right is not None:
            x = right - fitz.get_text_length(s, fontname=font, fontsize=size)
        self.p.insert_text((x, y), s, fontsize=size, fontname=font,
                           color=color)

    def box(self, r, text, size=8, bold=False, align=0, fill=None):
        from .forms import write_box
        self.p.draw_rect(fitz.Rect(r), color=(0.4,) * 3, fill=fill,
                         width=0.4)
        write_box(self.p, (r[0] + 3, r[1] + 2.5, r[2] - 3, r[3]), text,
                  size, bold, align)

    def line(self, a, b, w=0.5):
        self.p.draw_line(a, b, color=(0, 0, 0), width=w)


def _g702(out, v):
    pg = _Page(out, 612, 792)
    info = v["info"]
    pg.text(36, 48, "APPLICATION FOR PAYMENT", 14, True)
    pg.text(36, 62, "Summary page. Prepared with QuantiSheet in its own "
            "wording.", 7.5, color=(0.4, 0.4, 0.4))
    left = [("To owner", info.get("owner")), ("From contractor",
                                              info.get("contractor")),
            ("Via architect", info.get("architect")),
            ("Contract for", info.get("contract_for"))]
    right = [("Project", info.get("project")),
             ("Application no.", v["no"]), ("Period to", v["period_to"]),
             ("Application date", v["date"]),
             ("Contract no.", info.get("contract_no")),
             ("Contract date", info.get("contract_date"))]
    y = 84
    for (k, val) in left:
        pg.text(36, y, k + ":", 8, True)
        pg.text(120, y, val or "", 9)
        y += 14
    y = 84
    for (k, val) in right:
        pg.text(330, y, k + ":", 8, True)
        pg.text(420, y, val or "", 9)
        y += 14
    y = 180
    pg.text(36, y, "CONTRACTOR'S APPLICATION FOR PAYMENT", 10, True)
    y += 8
    g = v["g702"]
    for key, label in G702_LINES:
        y += 17
        if key == "5a":
            label = f"     a. {v['retainage_work']:g}% of completed work"
        elif key == "5b":
            label = f"     b. {v['retainage_stored']:g}% of stored material"
        pg.text(36, y, f"{key if len(key) == 1 else ''}", 9, True)
        pg.text(52, y, label, 9, key in ("3", "6", "8"))
        pg.text(0, y, _m(g[key]), 9, key in ("3", "6", "8"), right=576)
        pg.line((420, y + 3), (576, y + 3), 0.3)
    y += 30
    cs = v["changes"]
    pg.text(36, y, "CHANGE ORDER SUMMARY", 9, True)
    pg.text(0, y, "Additions", 8, True, right=470)
    pg.text(0, y, "Deductions", 8, True, right=576)
    for label, a, d in (("Approved in previous months", cs["prev_add"],
                         cs["prev_deduct"]),
                        ("Approved this month", cs["this_add"],
                         cs["this_deduct"]),
                        ("Totals", cs["prev_add"] + cs["this_add"],
                         cs["prev_deduct"] + cs["this_deduct"])):
        y += 14
        pg.text(36, y, label, 9, label == "Totals")
        pg.text(0, y, _m(a), 9, right=470)
        pg.text(0, y, _m(d), 9, right=576)
    y += 14
    pg.text(36, y, "Net changes by change order", 9, True)
    pg.text(0, y, _m(g["2"]), 9, True, right=576)
    y += 32
    _para(pg.p, fitz.Rect(36, y, 300, y + 70),
                        "CONTRACTOR. We state that the work listed in this "
                        "application was done as the contract requires, that "
                        "we have paid our subcontractors and suppliers from "
                        "the payments we received before, and that the "
                        "amount shown is now owed to us.", fontsize=7.5)
    _para(pg.p, fitz.Rect(320, y, 576, y + 70),
                        "OWNER'S REPRESENTATIVE. Having looked at the work "
                        "on site and at this application, I agree the work "
                        "has reached the stage shown, and the amount I "
                        "approve below is to be paid.",
                        fontsize=7.5)
    y += 90
    for x, label in ((36, "Contractor"), (320, "Architect")):
        pg.line((x, y), (x + 170, y))
        pg.text(x, y + 10, f"{label} signature", 7.5)
        pg.line((x + 180, y), (x + 250, y))
        pg.text(x + 180, y + 10, "Date", 7.5)
    pg.text(320, y + 34, "Amount certified:", 9, True)
    pg.line((410, y + 37), (576, y + 37))
    y += 60
    pg.text(36, y, "State of: ______________   County of: ______________",
            8)
    pg.text(36, y + 14, "Subscribed and sworn before me on ____________   "
            "Notary public: ____________________   My commission expires: "
            "__________", 8)
    if v.get("status") != "certified":
        pg.text(36, 770, "DRAFT - not certified", 9, True, color=(0.75, 0,
                                                                  0))


def _g703(out, v):
    W, H = 1224, 792
    cols = [("A\nItem", 50, 0), ("B\nDescription of work", 300, 0),
            ("C\nScheduled value", 95, 2), ("D\nFrom previous\napplication",
                                             95, 2),
            ("E\nThis period", 90, 2), ("F\nMaterials\npresently stored",
                                        95, 2),
            ("G\nTotal completed\n& stored (D+E+F)", 105, 2),
            ("G/C\n%", 50, 2), ("H\nBalance to\nfinish (C-G)", 95, 2),
            ("I\nRetainage", 85, 2)]

    def head():
        pg = _Page(out, W, H)
        pg.text(36, 40, "CONTINUATION SHEET", 13, True)
        pg.text(36, 54, f"Detail of the application.  Application no. "
                f"{v['no']}   "
                f"Period to {v['period_to']}   Project: "
                f"{v['info'].get('project', '')}", 8.5)
        x = 36
        for name, w, _ in cols:
            pg.box((x, 64, x + w, 100), name, 7.5, True, 1,
                   fill=(0.88, 0.9, 0.95))
            x += w
        return pg, 100
    pg, y = head()

    def row(vals, bold=False):
        nonlocal pg, y
        if y + 15 > H - 40:
            pg, y = head()
        x = 36
        for (name, w, al), val in zip(cols, vals):
            pg.box((x, y, x + w, y + 15), val, 7.5, bold, al)
            x += w
        y += 15
    for r in v["rows"]:
        desc = (f"{r['csi']}  " if r["csi"] else "") + r["desc"]
        row([r["item"], desc[:70], _m(r["scheduled"]), _m(r["previous"]),
             _m(r["this"]), _m(r["stored"]), _m(r["completed"]),
             f"{r['percent']:.0f}%", _m(r["balance"]), _m(r["retainage"])])
    t = v["totals"]
    row(["", "GRAND TOTALS", _m(t["scheduled"]), _m(t["previous"]),
         _m(t["this"]), _m(t["stored"]), _m(t["completed"]),
         f"{t['completed'] / t['scheduled'] * 100:.0f}%"
         if t["scheduled"] else "", _m(t["balance"]), _m(t["retainage"])],
        True)


def pay_app_pdf(doc, no, path):
    """G702 summary page plus G703 continuation sheets."""
    v = compute(doc, no)
    out = fitz.open()
    _g702(out, v)
    _g703(out, v)
    out.set_metadata({"title": f"Pay Application {no} - "
                      f"{v['info'].get('project', '')}",
                      "creator": "QuantiSheet"})
    safeio.atomic_save(out, path)
    out.close()
    return path


def pay_app_xlsx(doc, no, path):
    from . import acrobat
    v = compute(doc, no)
    g = v["g702"]
    summary = [["Application", v["no"]], ["Period to", v["period_to"]],
               ["Status", v["status"]], []]
    for key, label in G702_LINES:
        summary.append([key, label, g[key]])
    detail = [["Item", "CSI", "Description", "Scheduled", "Previous",
               "This period", "Stored", "Completed & stored", "%",
               "Balance", "Retainage"]]
    for r in v["rows"]:
        detail.append([r["item"], r["csi"], r["desc"], r["scheduled"],
                       r["previous"], r["this"], r["stored"], r["completed"],
                       round(r["percent"], 1), r["balance"],
                       round(r["retainage"], 2)])
    t = v["totals"]
    detail.append(["", "", "Totals", t["scheduled"], t["previous"],
                   t["this"], t["stored"], t["completed"], "", t["balance"],
                   t["retainage"]])
    acrobat.write_xlsx(path, [("Summary", summary), ("Detail", detail)])
    return path


def change_log_xlsx(doc, path):
    from . import acrobat
    rows = [["PCO", "COR", "CO", "Title", "Stage", "Amount", "Approved",
             "Days", "Approved days", "Raised", "Submitted", "Executed",
             "RFI", "Reason"]]
    for c in changes(doc):
        rows.append([c["id"], c.get("cor_no", ""), c.get("co_no", ""),
                     c["title"], STAGE_LABEL[c["stage"]], c["amount"],
                     c.get("approved_amount", 0), c.get("days", 0),
                     c.get("approved_days", 0), c.get("raised", ""),
                     c.get("submitted", ""), c.get("executed", ""),
                     c.get("rfi", ""), c.get("reason", "")])
    acrobat.write_xlsx(path, [("Change Orders", rows)])
    return path


def change_pdf(doc, cid, path):
    """A change order request / change order to send for signature."""
    data = read(doc)
    c = _find(data, cid)
    info = data["info"]
    out = fitz.open()
    pg = _Page(out, 612, 792)
    title = "CHANGE ORDER" if c["stage"] == "co" else \
        "CHANGE ORDER REQUEST" if c["stage"] == "cor" else \
        "POTENTIAL CHANGE ORDER"
    no = c.get("co_no") or c.get("cor_no") or c["id"]
    pg.text(36, 50, f"{title}  {no}", 15, True)
    y = 80
    for k, val in (("Project", info.get("project")),
                   ("Owner", info.get("owner")),
                   ("Contractor", info.get("contractor")),
                   ("Contract no.", info.get("contract_no")),
                   ("Reference", " / ".join(x for x in (
                       c["id"], c.get("cor_no"), c.get("co_no"),
                       c.get("rfi")) if x)),
                   ("Date", c.get("executed") or c.get("submitted") or
                    c.get("raised"))):
        pg.text(36, y, k + ":", 9, True)
        pg.text(130, y, val or "", 9)
        y += 15
    y += 10
    pg.text(36, y, c["title"], 11, True)
    _para(pg.p, fitz.Rect(36, y + 8, 576, y + 160),
                        c.get("reason") or "", fontsize=9.5)
    y += 175
    amt = c["approved_amount"] if c["stage"] == "co" else c["amount"]
    days = c["approved_days"] if c["stage"] == "co" else c["days"]
    if c.get("cost") is not None:
        pg.text(36, y, "Cost", 9.5)
        pg.text(0, y, _m(c["cost"]), 9.5, right=576)
        y += 15
        pg.text(36, y, f"Overhead & profit ({c.get('markup_pct') or 0:g}%)",
                9.5)
        pg.text(0, y, _m(amt - c["cost"]), 9.5, right=576)
        y += 15
    pg.text(36, y, "Change in contract sum", 10.5, True)
    pg.text(0, y, _m(amt), 10.5, True, right=576)
    y += 16
    pg.text(36, y, "Change in contract time", 10.5, True)
    pg.text(0, y, f"{days:+d} days", 10.5, True, right=576)
    if c["stage"] == "co":
        orig = original_contract(data)
        prior = sum(x["approved_amount"] for x in data["changes"]
                    if x["stage"] == "co" and x["co_no"] < c["co_no"])
        y += 28
        for k, val in (("Original contract sum", orig),
                       ("Net change by previous change orders", prior),
                       ("Contract sum before this change order",
                        orig + prior),
                       ("Contract sum including this change order",
                        orig + prior + amt)):
            pg.text(36, y, k, 9.5)
            pg.text(0, y, _m(val), 9.5, right=576)
            y += 15
    y += 50
    for x, label in ((36, "Owner"), (226, "Architect"), (416, "Contractor")):
        pg.line((x, y), (x + 160, y))
        pg.text(x, y + 11, f"{label}  (signature, date)", 7.5)
    safeio.atomic_save(out, path)
    out.close()
    return path


# ---- lien waivers ----------------------------------------------------------------

_WAIVER_BODY = {
    "conditional_progress":
        "Upon receipt by the claimant of a payment of {amount} from {payer}, "
        "this document waives and releases any lien, stop payment notice or "
        "payment bond right the claimant has on the job above for labor, "
        "services, equipment or materials furnished through {through}. It "
        "does not cover retention, extras not yet paid, or items furnished "
        "after that date. This waiver is effective only when the claimant "
        "has been paid.",
    "unconditional_progress":
        "The claimant has been paid {amount} and waives and releases any "
        "lien, stop payment notice or payment bond right on the job above "
        "for labor, services, equipment or materials furnished through "
        "{through}, except retention, extras not yet paid, and items "
        "furnished after that date. This waiver is effective now, whether "
        "or not the claimant has actually received the money.",
    "conditional_final":
        "Upon receipt by the claimant of a final payment of {amount} from "
        "{payer}, this document waives and releases any lien, stop payment "
        "notice or payment bond right the claimant has on the job above, "
        "except disputed claims of {disputed}. This waiver is effective "
        "only when the claimant has been paid.",
    "unconditional_final":
        "The claimant has been paid in full ({amount}) and waives and "
        "releases any lien, stop payment notice or payment bond right on "
        "the job above, except disputed claims of {disputed}. This waiver "
        "is effective now, whether or not the claimant has actually "
        "received the money.",
}
WAIVER_WARNING = ("Several states (including California, Texas, Florida, "
                  "Georgia, Arizona, Nevada, Utah, Michigan, Mississippi, "
                  "Missouri, Wyoming and Massachusetts) require their own "
                  "statutory waiver wording. Use the state's form where "
                  "required, and have counsel review.")


def waiver(doc, kind, through, amount, claimant="", payer="", disputed=0.0,
           app_no=None):
    if kind not in WAIVER_KINDS:
        raise BillingError(f"Waiver kind must be one of: "
                           f"{', '.join(WAIVER_KINDS)}")
    data = read(doc)
    rec = {"kind": kind, "through": through,
           "amount": round(_amount(amount, "Waiver amount"), 2),
           "claimant": claimant or data["info"].get("contractor", ""),
           "payer": payer or data["info"].get("owner", ""),
           "disputed": round(_amount(disputed, "Disputed amount"), 2),
           "app_no": app_no,
           "issued": _today()}
    data["waivers"].append(rec)
    write(doc, data)
    return rec


def waiver_pdf(doc, rec, path):
    data = read(doc)
    info = data["info"]
    out = fitz.open()
    pg = _Page(out, 612, 792)
    pg.text(36, 52, WAIVER_KINDS[rec["kind"]].upper(), 12.5, True)
    _para(pg.p, fitz.Rect(36, 62, 576, 100), WAIVER_WARNING,
                        fontsize=7.5, color=(0.6, 0, 0))
    y = 112
    for k, val in (("Name of claimant", rec["claimant"]),
                   ("Name of customer", rec["payer"]),
                   ("Job location", info.get("project_address") or
                    info.get("project")),
                   ("Owner", info.get("owner")),
                   ("Through date", rec["through"]),
                   ("Pay application", rec.get("app_no") or "")):
        pg.text(36, y, k + ":", 9, True)
        pg.text(160, y, val or "", 9)
        y += 16
    body = _WAIVER_BODY[rec["kind"]].format(
        amount=_m(rec["amount"]), payer=rec["payer"] or "the customer",
        through=rec["through"], disputed=_m(rec.get("disputed") or 0))
    _para(pg.p, fitz.Rect(36, y + 10, 576, y + 170), body,
                        fontsize=10)
    y += 200
    for label in ("Claimant's signature", "Claimant's title", "Date"):
        pg.line((36, y), (300, y))
        pg.text(36, y + 11, label, 7.5)
        y += 34
    safeio.atomic_save(out, path)
    out.close()
    return path
