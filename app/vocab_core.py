"""
vocab.py (your pay item vocabulary tool, used by QuantiSheet's Bid Tabs
vocabulary; the command-line version is tools/vocab.py and works on the
costdb.py database)
========
Normalise messy pay item text and fold it into a controlled vocabulary.

Pipeline: expand abbreviations, strip noise, normalise units, then match
exact -> alias -> fuzzy. Reports the method and a confidence so you can set
a threshold and only review the tail.

Usage
-----
    python vocab.py --db cost.db normalize "4 in conc sidewalk w/ reinf"
    python vocab.py --db cost.db batch items.txt
    python vocab.py --db cost.db batch items.csv --column description --out matched.csv
    python vocab.py --db cost.db suggest items.txt --threshold 0.70
    python vocab.py --db cost.db learn items.csv --min-score 0.92
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

try:                                  # spreadsheet formula guard (CSV)
    from . import safecell
except ImportError:                   # run as a script
    from app import safecell

ABBREV = {
    r"\bconc\b": "concrete", r"\bconc\.\b": "concrete", r"\bcnc\b": "concrete",
    r"\breinf\b": "reinforcing", r"\breinf\.\b": "reinforcing", r"\breinf'g\b": "reinforcing",
    r"\brebar\b": "reinforcing steel", r"\brbr\b": "reinforcing steel",
    r"\bsidewalk\b": "sidewalk", r"\bsw\b": "sidewalk",
    r"\bdia\b": "diameter", r"\bdiam\b": "diameter",
    r"\btyp\b": "typical", r"\btyp\.\b": "typical",
    r"\bo\.c\.\b": "on center", r"\boc\b": "on center",
    r"\be\.w\.\b": "each way", r"\bew\b": "each way",
    r"\bcl\b": "centerline", r"\bcl\.\b": "centerline",
    r"\bcmu\b": "concrete masonry unit", r"\bblk\b": "block",
    r"\bgalv\b": "galvanized", r"\bgalv\.\b": "galvanized",
    r"\bstl\b": "steel", r"\bss\b": "stainless steel",
    r"\bhm\b": "hollow metal", r"\bhdw\b": "hardware",
    r"\bgyp\b": "gypsum", r"\bgyp\.\b": "gypsum", r"\bdw\b": "drywall",
    r"\binsul\b": "insulation", r"\binsul\.\b": "insulation",
    r"\bmemb\b": "membrane", r"\bwaterproofing\b": "waterproofing",
    r"\bmisc\b": "miscellaneous", r"\bmisc\.\b": "miscellaneous",
    r"\beqpt\b": "equipment", r"\bequip\b": "equipment",
    r"\bvert\b": "vertical", r"\bhoriz\b": "horizontal",
    r"\bthk\b": "thick", r"\bthick\.\b": "thick",
    r"\bmax\b": "maximum", r"\bmin\b": "minimum",
    r"\bnom\b": "nominal", r"\bapprox\b": "approximate",
    r"\bexcav\b": "excavation", r"\bexcav\.\b": "excavation",
    r"\bbackfill\b": "backfill", r"\bbf\b": "backfill",
    r"\bcomp\b": "compacted", r"\bcomp\.\b": "compacted",
    r"\btransformer\b": "transformer", r"\bxmfr\b": "transformer",
    r"\brecept\b": "receptacle", r"\brecept\.\b": "receptacle",
    r"\bemt\b": "electrical metallic tubing", r"\brgs\b": "rigid galvanized steel",
    r"\bhvac\b": "heating ventilating air conditioning",
    r"\brtu\b": "rooftop unit", r"\bvav\b": "variable air volume",
    r"\bfcu\b": "fan coil unit", r"\bahu\b": "air handling unit",
    r"\bw\.c\.\b": "water closet", r"\bwc\b": "water closet",
    r"\blav\b": "lavatory", r"\bwh\b": "water heater",
    r"\bstorm\b": "storm", r"\bsan\b": "sanitary", r"\bsan\.\b": "sanitary",
    r"\brcp\b": "reinforced concrete pipe", r"\bpvc\b": "pvc",
    r"\bmanh\b": "manhole", r"\bcb\b": "catch basin",
    r"\basph\b": "asphalt", r"\basph\.\b": "asphalt",
    r"\bpvmt\b": "pavement", r"\bpavt\b": "pavement",
    r"\btopsoil\b": "topsoil", r"\blandscape\b": "landscaping",
    r"\bwt\b": "weight", r"\blbs\b": "lb", r"\blf\b": "lf", r"\bsf\b": "sf",
    r"\bsy\b": "sy", r"\bcy\b": "cy", r"\bea\b": "ea", r"\bls\b": "ls",
}

NOISE = {
    "furnish", "furnished", "furnishing", "install", "installed", "installation",
    "provide", "provided", "including", "include", "incl", "complete", "completed",
    "all", "any", "as", "per", "the", "a", "an", "of", "to", "for", "and", "or",
    "with", "w", "without", "at", "in", "on", "by", "no", "nos", "spec", "specs",
    "specification", "per", "each", "item", "work", "system", "new", "existing",
    "field", "shop", "typical", "various", "sizes", "size", "type", "types",
}

UNIT_TOKENS = {
    "sf": "SF", "sqft": "SF", "squarefoot": "SF", "sq ft": "SF",
    "sy": "SY", "sqyd": "SY", "sq yd": "SY",
    "lf": "LF", "linft": "LF", "linearfoot": "LF",
    "cy": "CY", "cuyd": "CY", "cubic yard": "CY",
    "ea": "EA", "each": "EA", "ls": "LS", "lumpsum": "LS",
    "ton": "TON", "tons": "TON", "gal": "GAL", "gallon": "GAL",
    "lb": "LB", "lbs": "LB", "hr": "HR", "hour": "HR", "day": "DAY",
    "mbh": "MBH", "kw": "KW", "bf": "BF", "cf": "CF",
}

FRACTIONS = {
    "1/2": "0.5", "1/4": "0.25", "3/4": "0.75", "1/8": "0.125",
    "3/8": "0.375", "5/8": "0.625", "7/8": "0.875", "1/3": "0.333",
    "2/3": "0.667", "1 1/2": "1.5", "2 1/2": "2.5", "1 1/4": "1.25",
}


def _dec(x: float) -> str:
    return f"{x:.3f}".rstrip("0").rstrip(".")


def normalize(text: str) -> str:
    """Fold a messy pay item string into a stable lookup key."""
    s = " " + str(text).lower().strip() + " "

    # mixed numbers first ("1 1/2" -> 1.5, also "1-1/2"), then plain
    # fractions; replacing "1/2" first turned "1 1/2" into "1 0.5"
    s = re.sub(r"(?<![\d./])(\d+)[\s-]+(\d+)/(\d+)(?![\d/])",
               lambda m: _dec(int(m.group(1)) + int(m.group(2)) /
                              max(1, int(m.group(3)))), s)
    s = re.sub(r"(?<![\d./])(\d+)/(\d+)(?![\d/])",
               lambda m: _dec(int(m.group(1)) / max(1, int(m.group(2)))), s)

    # inch / foot marks
    s = re.sub(r"(\d)\s*\"", r"\1 in ", s)
    s = re.sub(r"(\d)\s*'", r"\1 ft ", s)

    for pattern, replacement in ABBREV.items():
        s = re.sub(pattern, replacement, s)

    # strip punctuation except decimal points and slashes inside numbers;
    # a period anywhere else goes too ("Conc. sidewalk 4 in." kept
    # "concrete." and "in." as words, so it never matched)
    s = re.sub(r"[^\w\s./]", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    s = re.sub(r"(?<!\d)/(?!\d)", " ", s)

    tokens = []
    for token in s.split():
        if token in NOISE:
            continue
        tokens.append(token)

    return " ".join(tokens)


def extract_unit(text: str) -> str | None:
    lowered = " " + str(text).lower() + " "
    for token, unit in UNIT_TOKENS.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            return unit
    return None


def tokenset(text: str) -> str:
    """Order-insensitive key for fuzzy comparison."""
    return " ".join(sorted(set(normalize(text).split())))


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, tokenset(a), tokenset(b)).ratio()


def numbers(norm: str) -> set[str]:
    """Sizes in a normalised string ("concrete sidewalk 4" -> {"4"})."""
    return {_dec(float(t)) for t in re.findall(r"\d+(?:\.\d+)?", norm)}


def same_unit(a: str | None, b: str | None) -> bool:
    return not a or not b or a.upper() == b.upper()


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

class Matcher:
    """Exact -> alias -> fuzzy matching against a vocabulary.

    Fuzzy matches must agree on sizes ("4 in" never matches "6 in" - the
    words are 95% alike, the price isn't) and on the unit when the line
    has one (a SF price must not land on a CY item); learned aliases take
    part in fuzzy matching too."""

    def __init__(self, conn: sqlite3.Connection | None = None,
                 threshold: float = 0.82, items=None, aliases=None):
        self.threshold = threshold
        self.exact: dict[str, tuple[int, str, str]] = {}
        self.aliases: dict[str, tuple[int, str, str]] = {}
        if conn is not None:
            items = [(r["id"], r["canonical"], r["unit"]) for r in conn.execute(
                "SELECT id, canonical, unit FROM item WHERE active = 1")]
            aliases = [(r["item_id"], r["norm"]) for r in conn.execute(
                "SELECT item_id, norm FROM alias")]
        by_id = {}
        for item_id, canonical, unit in items or []:
            by_id[item_id] = (item_id, canonical, unit)
            self.exact[normalize(canonical)] = by_id[item_id]
        for item_id, norm in aliases or []:
            if item_id in by_id:
                self.aliases[norm] = by_id[item_id]
        self._pool = list(self.exact.items()) + list(self.aliases.items())
        self._tok = {k: tokenset(k) for k, _ in self._pool}

    def match(self, text: str, unit: str | None = None) -> dict:
        norm = normalize(text)
        unit = unit or extract_unit(text)

        for table, method in ((self.exact, "exact"), (self.aliases, "alias")):
            hit = table.get(norm)
            if hit and same_unit(unit, hit[2]):
                item_id, canonical, item_unit = hit
                return {"input": text, "match": canonical, "item_id": item_id,
                        "unit": unit or item_unit, "score": 1.0,
                        "method": method}

        nums = numbers(norm)
        mine = tokenset(norm)
        best_score, best = 0.0, None
        for key, (item_id, canonical, item_unit) in self._pool:
            if not same_unit(unit, item_unit) or numbers(key) != nums:
                continue
            score = difflib.SequenceMatcher(None, mine, self._tok[key]).ratio()
            if score > best_score:
                best_score, best = score, (item_id, canonical, item_unit)

        if best and best_score >= self.threshold:
            item_id, canonical, item_unit = best
            return {"input": text, "match": canonical, "item_id": item_id,
                    "unit": unit or item_unit, "score": round(best_score, 3), "method": "fuzzy"}

        return {"input": text, "match": None, "item_id": None, "unit": unit,
                "score": round(best_score, 3), "method": "unmatched",
                "best": best[1] if best else None}

    def candidates(self, text: str, unit: str | None = None, n: int = 2,
                   check_units: bool = True) -> list[tuple]:
        """The best `n` items as (score, item_id, canonical, unit), best
        first. Sizes must agree; with check_units=False items in another
        unit are kept (so an import can queue them as a unit mismatch)."""
        norm = normalize(text)
        unit = unit or extract_unit(text)
        for table in (self.exact, self.aliases):
            hit = table.get(norm)
            if hit and (not check_units or same_unit(unit, hit[2])):
                return [(1.0, *hit)]
        nums, mine = numbers(norm), tokenset(norm)
        best: dict[int, tuple] = {}
        for key, (item_id, canonical, item_unit) in self._pool:
            if numbers(key) != nums:
                continue
            if check_units and not same_unit(unit, item_unit):
                continue
            score = difflib.SequenceMatcher(None, mine, self._tok[key]).ratio()
            if score > best.get(item_id, (0,))[0]:
                best[item_id] = (score, item_id, canonical, item_unit)
        return sorted(best.values(), key=lambda t: -t[0])[:n]


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def load_lines(path: Path, column: str | None) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
        if column:
            return [r.get(column, "") for r in reader if r.get(column)]
        first = reader.fieldnames or []
        target = next((f for f in first if re.search(r"desc|item|work|scope", f, re.I)), first[0])
        return [r.get(target, "") for r in reader if r.get(target)]
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def cmd_normalize(conn, args) -> int:
    matcher = Matcher(conn, args.threshold)
    result = matcher.match(args.text)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"input      {result['input']}")
        print(f"normalised {normalize(result['input'])}")
        print(f"method     {result['method']}  ({result['score']:.3f})")
        print(f"match      {result['match'] or 'NO MATCH - candidate for a new item'}")
        if result["unit"]:
            print(f"unit       {result['unit']}")
    return 0


def cmd_batch(conn, args) -> int:
    matcher = Matcher(conn, args.threshold)
    lines = load_lines(args.path, args.column)
    results = [matcher.match(line) for line in lines]

    matched = sum(1 for r in results if r["item_id"])
    print(f"{matched}/{len(results)} matched  ({matched / max(1, len(results)) * 100:.0f}%)",
          file=sys.stderr)

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as fh:
            writer = safecell.writer(fh)
            writer.writerow(["input", "match", "item_id", "unit", "score", "method"])
            for r in results:
                writer.writerow([r["input"], r["match"] or "", r["item_id"] or "",
                                 r["unit"] or "", r["score"], r["method"]])
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        for r in results:
            flag = " " if r["item_id"] else "!"
            print(f"{flag} {r['score']:.2f} {r['method']:<9} {r['input'][:48]:<50} -> {r['match'] or ''}")
    return 0


def cmd_suggest(conn, args) -> int:
    matcher = Matcher(conn, args.threshold)
    unmatched = []
    for line in load_lines(args.path, args.column):
        result = matcher.match(line)
        if not result["item_id"]:
            unmatched.append((normalize(line), result["unit"]))

    clusters: dict[str, list[str]] = {}
    for norm, _ in unmatched:
        key = " ".join(sorted(set(norm.split()))[:3])
        clusters.setdefault(key, []).append(norm)

    ranked = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    print(f"{len(unmatched)} unmatched lines in {len(clusters)} rough clusters\n")
    for key, members in ranked[:args.top]:
        unit = next((u for n, u in unmatched if n in members and u), None) or "?"
        print(f"[{len(members):>3}] unit~{unit:<4} {members[0][:70]}")
        for extra in members[1:3]:
            print(f"      {'':<10} {extra[:70]}")
        print()
    return 0


def cmd_learn(conn, args) -> int:
    matcher = Matcher(conn, args.threshold)
    added = 0
    for line in load_lines(args.path, args.column):
        result = matcher.match(line)
        if result["item_id"] and result["method"] == "fuzzy" and result["score"] >= args.min_score:
            norm = normalize(result["input"])
            if conn.execute("SELECT 1 FROM alias WHERE item_id=? AND norm=?",
                            (result["item_id"], norm)).fetchone():
                continue                       # already learned
            conn.execute(
                "INSERT INTO alias (item_id, text, norm, hits) VALUES (?,?,?,1)",
                (result["item_id"], result["input"], norm),
            )
            matcher.aliases[norm] = (result["item_id"], result["match"], result["unit"])
            added += 1
    conn.commit()
    print(f"learned {added} new aliases")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Normalise pay item text into a controlled vocabulary.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db", type=Path, default=Path("cost.db"))
    p.add_argument("--threshold", type=float, default=0.82, help="fuzzy match floor (default 0.82)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("normalize")
    s.add_argument("text"); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_normalize)

    s = sub.add_parser("batch")
    s.add_argument("path", type=Path); s.add_argument("--column"); s.add_argument("--out", type=Path)
    s.set_defaults(func=cmd_batch)

    s = sub.add_parser("suggest")
    s.add_argument("path", type=Path); s.add_argument("--column"); s.add_argument("--top", type=int, default=25)
    s.set_defaults(func=cmd_suggest)

    s = sub.add_parser("learn")
    s.add_argument("path", type=Path); s.add_argument("--column")
    s.add_argument("--min-score", type=float, default=0.92)
    s.set_defaults(func=cmd_learn)

    args = p.parse_args(argv)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        return args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())