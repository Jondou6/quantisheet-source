"""Exclusions side by side: who excludes what (Nov 11).

A low bid isn't good news until you know what it leaves out. Each bidder's
exclusions (from the quote PDF, the bid form, or typed on the Scope Sheet)
are put in one table: a row per exclusion, a column per bidder, each cell
"excluded", "included" or "not stated".

Similar wordings share a row ("permits", "permit fees", "all permits by
others"). The grouping is by the words themselves, no AI, and it will be
wrong both ways now and then, so the user can split a wording off into its
own row or merge two rows; those choices (`moves`) are kept by whoever
owns the bids. No wording is rewritten or dropped: every cell keeps the
bidder's own text.

Pure Python, no Qt.
"""
import re

EXCLUDED, INCLUDED, NOT_STATED = "excluded", "included", "not stated"

_STOP = {
    "a", "all", "an", "and", "any", "are", "as", "associated", "be", "by",
    "cost", "costs", "excluded", "excludes", "exclude", "exclusion", "fee",
    "fees", "for", "from", "in", "included", "includes", "include", "is",
    "it", "no", "not", "of", "on", "or", "other", "others", "our", "owner",
    "per", "required", "the", "this", "to", "we", "with", "work", "gc",
    "provided", "furnished", "if", "that", "will", "unless", "noted",
}


def norm(text):
    """One wording, for comparing: lower case, single spaces."""
    return re.sub(r"\s+", " ", str(text or "").lower()).strip(" .;:-•*")


def _stem(w):
    for end in ("ings", "ing", "es", "s"):
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[:-len(end)]
    return w


def stems(text):
    """The words that say what the exclusion is about."""
    out = []
    for w in re.findall(r"[a-z][a-z0-9]+", norm(text)):
        if w in _STOP:
            continue
        s = _stem(w)
        if s not in _STOP and s not in out:
            out.append(s)
    return out


def _entries(bids):
    """[(bidder, kind, text)] in order, blanks dropped."""
    out = []
    for b in bids:
        for kind in ("exclusions", "inclusions"):
            for t in b.get(kind) or []:
                if norm(t):
                    out.append((b["bidder"], kind, str(t).strip()))
    return out


def matrix(bids, moves=None):
    """The table. `bids`: [{"bidder", "exclusions": [text], "inclusions":
    [text]}]. `moves`: {norm(wording): row label} - the user's split and
    merge choices. Returns rows, most-excluded first:
        {"id", "label", "cells": {bidder: {"state", "texts": [..]}},
         "only": bidder or "", "wordings": [text, ...]}
    "only": the one bidder who excludes it while two or more bid."""
    moves = moves or {}
    bidders = []
    for b in bids:
        if b["bidder"] not in bidders:
            bidders.append(b["bidder"])
    ex = [(who, t) for who, kind, t in _entries(bids) if kind == "exclusions"]
    # shortest wordings first: they name the subject ("permits") and the
    # longer ones ("all permits by others") join them
    order = sorted(range(len(ex)), key=lambda i: (len(stems(ex[i][1])), i))
    groups = []                    # {"core": set, "label", "items": [i]}
    by_label = {}
    for i in order:
        who, t = ex[i]
        forced = moves.get(norm(t))
        if forced is not None:
            g = by_label.get(("u", forced))
            if g is None:
                g = {"core": None, "label": forced, "items": []}
                by_label[("u", forced)] = g
                groups.append(g)
            g["items"].append(i)
            continue
        st = set(stems(t))
        g = next((g for g in groups if g["core"] is not None and st and
                  g["core"] <= st), None)
        if g is None:
            g = {"core": st or {norm(t)}, "label": t, "items": []}
            groups.append(g)
        g["items"].append(i)
    inc = [(who, t, set(stems(t))) for who, kind, t in _entries(bids)
           if kind == "inclusions"]
    rows = []
    for g in groups:
        items = sorted(g["items"])
        cells = {b: {"state": NOT_STATED, "texts": []} for b in bidders}
        for i in items:
            who, t = ex[i]
            cells[who]["state"] = EXCLUDED
            if t not in cells[who]["texts"]:
                cells[who]["texts"].append(t)
        core = g["core"]
        if core is None:           # a row the user made: its wordings' words
            sets = [set(stems(ex[i][1])) for i in items]
            core = set.intersection(*sets) if sets else set()
        for who, t, st in inc:
            if core and core <= st and cells[who]["state"] == NOT_STATED:
                cells[who] = {"state": INCLUDED, "texts": [t]}
        who_ex = [b for b in bidders if cells[b]["state"] == EXCLUDED]
        wordings = []
        for i in items:
            if ex[i][1] not in wordings:
                wordings.append(ex[i][1])
        rows.append({"id": norm(g["label"]), "label": g["label"],
                     "cells": cells, "wordings": wordings,
                     "only": who_ex[0] if len(who_ex) == 1 and
                     len(bidders) >= 2 else ""})
    rows.sort(key=lambda r: (-sum(c["state"] == EXCLUDED
                                  for c in r["cells"].values()),
                             r["label"].lower()))
    return rows


def split(moves, wording):
    """`wording` gets a row of its own."""
    out = dict(moves or {})
    out[norm(wording)] = str(wording).strip()
    return out


def merge(moves, row, into):
    """Every wording of `row` joins the row `into` (rows from matrix())."""
    out = dict(moves or {})
    for t in list(into["wordings"]) + list(row["wordings"]):
        out[norm(t)] = into["label"]
    return out


def unmove(moves, wording):
    """Back to the automatic grouping for `wording`."""
    out = dict(moves or {})
    out.pop(norm(wording), None)
    return out


def cell_text(cell):
    if cell["state"] == EXCLUDED:
        return "Excluded: " + "; ".join(cell["texts"])
    if cell["state"] == INCLUDED:
        return "Included: " + "; ".join(cell["texts"])
    return "Not stated"


def table(bids, moves=None, rows=None):
    """Rows for a report: a header, then one line per exclusion with each
    bidder's own wording."""
    rows = matrix(bids, moves) if rows is None else rows
    bidders = []
    for b in bids:
        if b["bidder"] not in bidders:
            bidders.append(b["bidder"])
    out = [["Exclusion"] + bidders + ["Only one bidder excludes it"]]
    for r in rows:
        out.append([r["label"]] + [cell_text(r["cells"][b]) for b in bidders]
                   + [r["only"]])
    return out


def from_proposals(proposals):
    """`bids` for matrix() from proposal_level.parse() results."""
    return [{"bidder": p["bidder"],
             "exclusions": list(p.get("exclusions") or []),
             "inclusions": list(p.get("inclusions") or [])}
            for p in proposals]
