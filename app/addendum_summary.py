"""Addendum "what changed" summary from the drawings (v20).

What's already there: bid packages per trade (pm/bidui.make_packages) and
bid_addendum, which numbers an addendum, attaches it, tells bidders and asks
them to acknowledge it, but the "what changed?" text is typed by hand.

This drafts that text from the old and new drawings (overlay.compare):
* summarize(old, new): changed sheets (with % of the sheet changed and the
  takeoffs sitting on changed areas, by group), new sheets, removed sheets,
  and sheets with no change.
* text(summary, label): "Addendum 2 changes 1 sheet: A-101 (4% of the sheet;
  1 takeoff affected (Wall)). New sheet: A-103. Removed: E-101. ..."
* packages_affected(summary, packages): the packages the addendum matters
  to, by trade discipline (A- for drywall, E- for electrical, C-/U- for
  utilities; see bid_followup.TRADE_SHEETS) or by the sheets listed on the
  package, with the sheets that matter to each.
* draft(package, summary, label): the text for one package, covering only
  its sheets. bid_addendum can use it as the default answer.
"""
import re

from . import overlay
from .bid_followup import sheets_for_trade, _SHEET


def _num(doc, i):
    try:
        return overlay.sheet_number(doc[i]) or f"Page {i + 1}"
    except Exception:
        return f"Page {i + 1}"


def _key(s):
    m = _SHEET.match(s)
    return (m.group(1), int(m.group(2))) if m else (s, 0)


def summarize(old, new, results=None):
    res = results if results is not None else overlay.compare(old, new)
    changed, added, removed, same = [], [], [], []
    for r in res:
        i, j = r.get("old"), r.get("new")
        if i is None and j is not None:
            added.append(r.get("sheet") or _num(new, j))
        elif j is None and i is not None:
            removed.append(r.get("sheet") or _num(old, i))
        elif r.get("changes"):
            groups = {}
            try:
                for pno, _k, payload in overlay.flag_ops(old, [r], "old"):
                    for a in old[pno].annots() or []:
                        from . import annotate
                        if annotate.ref(a) == {k: v for k, v in
                                               payload.items()
                                               if k != "status"}:
                            g = (a.info or {}).get("subject", "").split(
                                ":")[-1] or "Takeoff"
                            groups[g] = groups.get(g, 0) + 1
            except Exception:
                pass
            changed.append({"sheet": r.get("sheet") or _num(old, i),
                            "pct": round(float(r.get("changed_pct") or 0), 1),
                            "areas": len(r["changes"]), "takeoffs": groups})
        else:
            same.append(r.get("sheet") or _num(old, i))
    changed.sort(key=lambda c: _key(c["sheet"]))
    # Nov 4 (Jon): every addendum review checks for a new bid form
    try:
        from . import bidform_xl
        bf = bidform_xl.addendum_check(new)
    except Exception:                                     # noqa: BLE001
        bf = {"has_form": False, "revised": False, "pages": []}
    return {"changed": changed, "added": sorted(added, key=_key),
            "removed": sorted(removed, key=_key),
            "unchanged": sorted(same, key=_key),
            "bid_form": {"has_form": bf.get("has_form", False),
                         "revised": bf.get("revised", False),
                         "pages": bf.get("pages", [])}}


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def text(s, label="This addendum", only=None):
    keep = (lambda x: x in only) if only is not None else (lambda x: True)
    ch = [c for c in s["changed"] if keep(c["sheet"])]
    add = [x for x in s["added"] if keep(x)]
    rem = [x for x in s["removed"] if keep(x)]
    parts = []
    if ch:
        bits = []
        for c in ch:
            t = f"{c['sheet']} ({c['pct']:g}% of the sheet"
            n = sum(c["takeoffs"].values())
            if n:
                t += (f"; {_plural(n, 'takeoff')} affected ("
                      + ", ".join(sorted(c["takeoffs"])) + ")")
            bits.append(t + ")")
        parts.append(f"{label} changes {_plural(len(ch), 'sheet')}: "
                     + ", ".join(bits) + ".")
    else:
        parts.append(f"{label} changes no existing sheets.")
    if add:
        parts.append(f"New sheet{'s' if len(add) > 1 else ''}: "
                     + ", ".join(add) + ".")
    if rem:
        parts.append("Removed: " + ", ".join(rem) + ".")
    if only is None and s["unchanged"]:
        parts.append("No change: " + ", ".join(s["unchanged"]) + ".")
    bf = s.get("bid_form") or {}
    if bf.get("has_form"):
        pg = ", ".join(str(p + 1) for p in bf.get("pages", [])[:6])
        parts.append(f"BID FORM: {label} includes a bid form (page {pg}) - update the bid form "
                     "workbook (Estimate > Bid Form Workbook > Check an "
                     "Addendum) before pricing.")
    return " ".join(parts)


def _listed(spec):
    """'C-101 to C-120, U-201' -> predicate on sheet numbers."""
    spans = []
    for part in re.split(r"[,;]", str(spec or "")):
        m = re.match(r"\s*([A-Z]{1,3})-?(\d+)\s*(?:to|-|–)\s*"
                     r"(?:[A-Z]{1,3}-?)?(\d+)\s*$", part.upper())
        if m:
            spans.append((m.group(1), int(m.group(2)), int(m.group(3))))
            continue
        m = re.match(r"\s*([A-Z]{1,3})-?(\d+)\s*$", part.upper())
        if m:
            spans.append((m.group(1), int(m.group(2)), int(m.group(2))))

    def hit(sheet):
        k = _key(sheet)
        return any(k[0] == p and lo <= k[1] <= hi for p, lo, hi in spans)
    return hit


def _touched(s):
    return [c["sheet"] for c in s["changed"]] + s["added"] + s["removed"]


def sheets_for_package(pkg, s):
    touched = _touched(s)
    mine = set(sheets_for_trade(f"{pkg.get('trades', '')} "
                                f"{pkg.get('title', '')}", touched))
    listed = _listed(pkg.get("sheets"))
    mine |= {x for x in touched if listed(x)}
    return sorted(mine, key=_key)


def packages_affected(s, packages):
    """[(package, [sheets that matter to it])] for packages it touches."""
    out = []
    for p in packages:
        sh = sheets_for_package(p, s)
        if sh:
            out.append((p, sh))
    return out


def draft(pkg, s, label="This addendum"):
    sh = sheets_for_package(pkg, s)
    if not sh:
        return f"{label} doesn't change the sheets for {pkg.get('title')}."
    return text(s, label, only=set(sh))
