"""Pay item vocabulary in the price database: one canonical name per item
(with its unit), and the many ways owners and bidders write it (aliases).
Bid tabs group by it, so "4\\" CONC SIDEWALK W/ REINF" from one owner and
"Concrete sidewalk, 4 in" from another count as the same item.

Matching and normalising come from your vocab tool (vocab_core)."""
import re

from . import pricedb
from . import vocab_core as core
from .dmoney import c2 as _c2

normalize = core.normalize


def items(search=""):
    words = str(search or "").lower().split()
    with pricedb.connect() as con:
        out = []
        for r in con.execute("SELECT * FROM vocab_items ORDER BY "
                             "trade, canonical COLLATE NOCASE"):
            if words and not all(w in r["canonical"].lower() for w in words):
                continue
            n = con.execute("SELECT COUNT(*) FROM vocab_aliases WHERE item=?",
                            (r["id"],)).fetchone()[0]
            out.append(dict(r, aliases=n))
    return out


def aliases(item_id):
    with pricedb.connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM vocab_aliases WHERE item=? ORDER BY text",
            (item_id,))]


def add_item(canonical, unit, trade="", code="", aliases=()):
    """Add (or find) an item; returns its id."""
    unit = str(unit or "EA").upper()
    with pricedb.connect(write=True) as con:
        r = con.execute("SELECT id FROM vocab_items WHERE canonical=? AND "
                        "unit=?", (canonical, unit)).fetchone()
        if r:
            iid = r[0]
        else:
            iid = con.execute(
                "INSERT INTO vocab_items (canonical, unit, trade, code, "
                "created, created_by) VALUES (?,?,?,?,?,?)",
                (canonical, unit, trade, code, pricedb.now(),
                 pricedb.user())).lastrowid
        for t in aliases:
            _alias(con, iid, t, "")
    return iid


def _alias(con, item_id, text, source):
    norm = normalize(text)
    if not norm:
        return False
    if con.execute("SELECT 1 FROM vocab_aliases WHERE item=? AND norm=?",
                   (item_id, norm)).fetchone():
        return False
    con.execute("INSERT INTO vocab_aliases (item, text, norm, source, hits) "
                "VALUES (?,?,?,?,0)", (item_id, text, norm, source))
    return True


def add_alias(item_id, text, source=""):
    with pricedb.connect(write=True) as con:
        return _alias(con, item_id, text, source)


def remove_item(item_id):
    with pricedb.connect(write=True) as con:
        con.execute("DELETE FROM vocab_aliases WHERE item=?", (item_id,))
        con.execute("DELETE FROM vocab_items WHERE id=?", (item_id,))


def matcher(threshold=0.82):
    with pricedb.connect() as con:
        its = [(r["id"], r["canonical"], r["unit"]) for r in con.execute(
            "SELECT id, canonical, unit FROM vocab_items")]
        als = [(r["item"], r["norm"]) for r in con.execute(
            "SELECT item, norm FROM vocab_aliases")]
    return core.Matcher(threshold=threshold, items=its, aliases=als)


def seed_from_catalog():
    """Every assembly in the shipped catalog becomes a vocabulary item
    (its name and unit). Returns how many were added."""
    from . import assembly_csv
    n = 0
    have = {(i["canonical"], i["unit"]) for i in items()}
    with pricedb.connect(write=True) as con:
        for a in assembly_csv.catalog().values():
            if a.get("source") != "catalog":
                continue
            key = (a["name"], str(a.get("unit") or "EA").upper())
            if key in have:
                continue
            con.execute("INSERT INTO vocab_items (canonical, unit, trade, "
                        "code, created, created_by) VALUES (?,?,?,?,?,?)",
                        (key[0], key[1], a.get("trade", ""), a.get("id", ""),
                         pricedb.now(), "catalog"))
            have.add(key)
            n += 1
    return n


def bid_descriptions():
    """[(description, unit, how many bid lines, trade)] in the bid tabs."""
    with pricedb.connect() as con:
        return [(r[0], r[1], r[2], r[3]) for r in con.execute(
            "SELECT desc, unit, COUNT(*), MIN(trade) FROM bid_rows "
            "GROUP BY lower(desc), unit ORDER BY COUNT(*) DESC")]


def review(threshold=0.82):
    """Every bid tab description with its match: [{input, unit, lines,
    trade, match, item_id, score, method, best}]."""
    m = matcher(threshold)
    out = []
    for desc, unit, lines, trade in bid_descriptions():
        r = m.match(desc, unit)
        r.update(unit=unit, lines=lines, trade=trade)
        out.append(r)
    return out


def learn(min_score=0.92, threshold=0.82):
    """Fuzzy matches at or above `min_score` become aliases. Returns how
    many were added."""
    n = 0
    rows = [r for r in review(threshold)
            if r["method"] == "fuzzy" and r["score"] >= min_score]
    with pricedb.connect(write=True) as con:
        for r in rows:
            if _alias(con, r["item_id"], r["input"], "learned"):
                n += 1
    return n


def suggest(threshold=0.82, top=25):
    """Unmatched bid descriptions grouped roughly (the vocab tool's
    clustering): [(how many, unit, [normalised texts])]."""
    clusters = {}
    for r in review(threshold):
        if r["item_id"]:
            continue
        norm = normalize(r["input"])
        key = (" ".join(sorted(set(norm.split()))[:3]), r["unit"] or "")
        clusters.setdefault(key, []).append(norm)
    ranked = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    return [(len(v), k[1], v) for k, v in ranked[:top]]


def canonical_map(threshold=0.82):
    """{(normalised description, unit): (item id, canonical)} for every bid
    description the vocabulary matches (minus pairings a reviewer
    rejected)."""
    out = {}
    try:
        no = rejected()
    except Exception:
        no = {}
    for r in review(threshold):
        key = (normalize(r["input"]), r["unit"])
        if r["item_id"] and no.get(key) != r["item_id"]:
            out[key] = (r["item_id"], r["match"])
    return out


def trade_of(canonical_trade, fallback):
    return canonical_trade or fallback


# ---- routing an import (your import_cost tool) -----------------------------------

AMBIGUITY_GAP = 0.03


def classify(desc, unit, m, auto=0.92, review=0.75, check_units=True):
    """auto / review / new for one bid line, with the reason - the
    routing of import_cost.py (sizes must agree, see Matcher)."""
    tops = m.candidates(desc, unit or None, 2, check_units=False)
    if not tops:
        return {"status": "new", "item_id": None, "match": None,
                "score": 0.0, "reason": "no vocabulary match"}
    score, item_id, canonical, item_unit = tops[0]
    base = {"item_id": item_id, "match": canonical, "score": round(score, 3)}
    if score < review:
        return dict(base, status="new", item_id=None,
                    reason=f"below review floor ({_c2(score):.2f})")
    if score < auto:
        return dict(base, status="review",
                    reason=f"low confidence ({_c2(score):.2f})")
    if len(tops) > 1 and (score - tops[1][0]) < AMBIGUITY_GAP:
        return dict(base, status="review",
                    reason=f"ambiguous vs '{tops[1][2]}'")
    if check_units and unit and item_unit and unit.upper() != \
            item_unit.upper():
        return dict(base, status="review",
                    reason=f"unit {unit} vs {item_unit}")
    return dict(base, status="auto", reason="")


def route(rows, auto=0.92, review=0.75, check_units=True):
    """Decisions for parsed bid rows (BidRow or dicts with desc/unit)."""
    m = matcher(min(review, 0.6))
    out = []
    for r in rows:
        desc = getattr(r, "desc", None) or r["desc"]
        unit = getattr(r, "unit", None) if not isinstance(r, dict) else \
            r.get("unit")
        d = classify(desc, unit, m, auto, review, check_units)
        d.update(desc=desc, unit=unit)
        out.append(d)
    return out


def apply_routing(decisions, project=None, source="", create_new_min=0,
                  trade_of_desc=None):
    """Record an import's routing: auto lines become aliases (so they
    match exactly from now on), review lines go to the review queue, and
    wordings seen at least `create_new_min` times become new items.
    Returns {auto, review, new, created}."""
    seen = set()
    counts = {"auto": 0, "review": 0, "new": 0, "created": 0}
    new_groups = {}
    with pricedb.connect(write=True) as con:
        for d in decisions:
            key = (normalize(d["desc"]), d["unit"])
            counts[d["status"]] += 1
            if key in seen:
                continue
            seen.add(key)
            if d["status"] == "auto":
                _alias(con, d["item_id"], d["desc"], source)
            elif d["status"] == "review":
                if not con.execute(
                        "SELECT 1 FROM vocab_review WHERE desc=? AND unit=? "
                        "AND status='open'", (d["desc"], d["unit"])
                        ).fetchone():
                    con.execute(
                        "INSERT INTO vocab_review (project, desc, unit, item, "
                        "score, reason, created) VALUES (?,?,?,?,?,?,?)",
                        (project, d["desc"], d["unit"], d["item_id"],
                         d["score"], d["reason"], pricedb.now()))
        for d in decisions:
            if d["status"] == "new":
                new_groups.setdefault((normalize(d["desc"]), d["unit"]),
                                      []).append(d["desc"])
        if create_new_min:
            for (norm, unit), texts in new_groups.items():
                if len(texts) < create_new_min:
                    continue
                canon = texts[0].strip().rstrip(".")[:120]
                trade = trade_of_desc(canon) if trade_of_desc else ""
                r = con.execute("SELECT id FROM vocab_items WHERE canonical=? "
                                "AND unit=?", (canon, unit or "EA")).fetchone()
                iid = r[0] if r else con.execute(
                    "INSERT INTO vocab_items (canonical, unit, trade, code, "
                    "created, created_by) VALUES (?,?,?,?,?,?)",
                    (canon, (unit or "EA").upper(), trade, "", pricedb.now(),
                     pricedb.user())).lastrowid
                for t in set(texts):
                    _alias(con, iid, t, source)
                counts["created"] += 1
    return counts


def review_queue(status="open"):
    with pricedb.connect() as con:
        return [dict(r, match=(con.execute(
            "SELECT canonical FROM vocab_items WHERE id=?",
            (r["item"],)).fetchone() or [None])[0])
            for r in con.execute(
                "SELECT * FROM vocab_review WHERE status=? ORDER BY id",
                (status,))]


def decide(review_id, approve, item_id=None):
    """Approve (the wording becomes an alias of the item) or reject (it
    never groups with that item) a queued line."""
    with pricedb.connect(write=True) as con:
        r = con.execute("SELECT * FROM vocab_review WHERE id=?",
                        (review_id,)).fetchone()
        if r is None:
            return False
        if approve:
            _alias(con, item_id or r["item"], r["desc"], "reviewed")
        con.execute("UPDATE vocab_review SET status=?, decided_by=? WHERE "
                    "id=?", ("approved" if approve else "rejected",
                             pricedb.user(), review_id))
    return True


def rejected():
    """{(normalised wording, unit): item id} the reviewers turned down."""
    with pricedb.connect() as con:
        return {(normalize(r["desc"]), r["unit"]): r["item"]
                for r in con.execute("SELECT desc, unit, item FROM "
                                     "vocab_review WHERE status='rejected'")}


__all__ = ["normalize", "items", "add_item", "add_alias", "matcher",
           "review", "learn", "suggest", "seed_from_catalog", "re"]
