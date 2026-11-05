"""Build app/data/ada2010.json - the 2010 ADA Standards split into sections -
from the page text tools/fetch_ada.py pulled out of the DOJ PDF.

    python tools/ada_index.py [data/ada/pages.json]

Each section: {"id": "404.2.3", "title": "...", "chapter": 4, "page": n,
"text": "...", "advisory": "..."}. Pages 1-36 (the DOJ rules, 28 CFR
35.151 and 36.401-406) go in as their own entries ("DOJ 35.151" ...)."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "data", "ada", "pages.json")
OUT = os.path.join(HERE, "app", "data", "ada2010.json")
ADAAG_FROM = 40          # page index of "101 Purpose"

CHAPTERS = {
    1: "Application and Administration", 2: "Scoping Requirements",
    3: "Building Blocks", 4: "Accessible Routes",
    5: "General Site and Building Elements", 6: "Plumbing Elements and "
    "Facilities", 7: "Communication Elements and Features",
    8: "Special Rooms, Spaces, and Elements", 9: "Built-In Elements",
    10: "Recreation Facilities"}

_JUNK = re.compile(
    r"^(AMERICANS WITH DISABILITIES ACT:.*|ADA CHAPTER \d+:.*|"
    r"Titles II and III - 2010 Standards - \d+|"
    r"2010 Standards: Titles II and III - \d+|Department of Justice|"
    r"Title I[I]* - 2010 Standards.*|.*2010 Standards - \d+|"
    r"\d+ - 2010 Standards: Titles? III?( and III)?|"
    r"Section 3[56]\.\d+ of 28 CFR [Pp]art 3[56]|"
    r"2010 Standards: Titles? II(I| and III)? - \d+|"
    r"Subpart [A-Z] of 28 CFR Part 3[56]|"
    r"(ADA )?CHAPTER \d+:.*(SCOPING|TECHNICAL)|"
    r"(ADA )?CHAPTER \d+:[A-Z ,\-]+|(\d+ )?(TECHNICAL|SCOPING)( \d+)?)\s*$")
# "404.2.3 Clear Width.  text"  or  "404 Doors, Doorways, and Gates"
_SUB = re.compile(r"^(\d{3,4}(?:\.\d+)+)\s+([A-Z0-9][^.]{0,150}?)\.(\s+|$)")
_TOP = re.compile(r"^(\d{3,4})\s+([A-Z][A-Za-z ,\-&/']{2,80}?)\s*$")
_ADV = re.compile(r"^Advisory\s+(\d{3,4}(?:\.\d+)*)\b")
_DOJ = re.compile(r"^§\s*(3[56]\.\d+)\s+(.{3,120})$")


def _key(sid):
    return tuple(int(x) for x in sid.split("."))


def _chapter(sid):
    n = int(sid.split(".")[0])
    return n // 100 if n < 1000 else 10


def _lines(pages, start, stop):
    for i in range(start, stop):
        raw = [ln.strip() for ln in pages[i].splitlines()]
        raw = [s for s in raw if s]
        for n, s in enumerate(raw):
            if _JUNK.match(s):
                continue
            nxt = raw[n + 1] if n + 1 < len(raw) else ""
            prev = raw[n - 1] if n else ""
            row = re.search(r"\d+ to \d+$|and over$|or less$|"
                            r"or more$", prev)
            if re.fullmatch(r"\d{1,3}", s) and (
                    n < 4 or ("2010 Standards -" in nxt and not row)):
                continue                        # the page number
            yield i, s


def _join(parts):
    text = " ".join(parts)            # table rows start with "\n"
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r" ?\n ?", "\n", text).strip()


def adaag(pages):
    out, cur, last, mode = [], None, (0,), "text"

    def close():
        if cur:
            cur["text"] = _join(cur.pop("_t"))
            cur["advisory"] = _join(cur.pop("_a"))
            out.append(cur)

    stop = next((i for i, t in enumerate(pages)
                 if "INDEX TO THE 2010 STANDARDS" in t), len(pages))
    lines = list(_lines(pages, ADAAG_FROM, stop))
    for n in range(len(lines) - 1):        # a heading that wraps a line
        page, s = lines[n]
        if re.match(r"\d{3,4}(\.\d+)+\s+[A-Z]", s) and not _SUB.match(s) \
                and _SUB.match(s + " " + lines[n + 1][1]):
            lines[n] = (page, s + " " + lines[n + 1][1])
            lines[n + 1] = (page, "")
    for page, s in lines:
        if not s:
            continue
        m = _SUB.match(s) or _TOP.match(s)
        if m:
            sid = m.group(1)
            k = _key(sid)
            # accept only numbers that move forward and stay plausible
            # (table rows such as "101 to 150" must not start sections)
            if k > last and (len(k) > 1 or k[0] in _TOP_IDS) and \
                    1 <= _chapter(sid) <= 10 and \
                    (len(k) == 1 or k[0] == last[0] or k[0] in _TOP_IDS):
                close()
                last = k
                rest = s[m.end():] if len(k) > 1 else ""
                cur = {"id": sid, "title": m.group(2).strip(),
                       "chapter": _chapter(sid), "page": page + 1,
                       "_t": [rest] if rest else [], "_a": []}
                mode = "text"
                continue
        if cur is None:
            continue
        if _ADV.match(s) or "(Continued)" in s[:80]:
            mode = "adv"
        elif re.match(r"Table \d+(\.\d+)*\s+[A-Z]", s):
            mode = "table"
            s = "\n" + s
        elif s.startswith("Figure ") and mode == "adv":
            mode = "text"
        elif mode == "table":
            if s.startswith(("EXCEPTION", "Figure ")) or len(s) > 90:
                mode = "text"
                s = "\n" + s
            else:
                s = "\n" + s
        (cur["_a"] if mode == "adv" else cur["_t"]).append(s)
    close()
    return out


_TOP_IDS = set()


def doj(pages):
    out, cur = [], None
    for page, s in _lines(pages, 2, ADAAG_FROM - 4):
        m = _DOJ.match(s)
        if m:
            if cur:
                cur["text"] = _join(cur.pop("_t"))
                out.append(cur)
            cur = {"id": "DOJ " + m.group(1), "title": m.group(2).strip(" ."),
                   "chapter": 0, "page": page + 1, "_t": [], "advisory": ""}
            continue
        if cur:
            cur["_t"].append(s)
    if cur:
        cur["text"] = _join(cur.pop("_t"))
        out.append(cur)
    return out


def tops(pages):
    """The chapter-level section names, from the table of contents."""
    ids = set()
    for i in range(ADAAG_FROM - 4, ADAAG_FROM):
        for ln in pages[i].splitlines():
            m = _TOP.match(ln.strip())
            if m:
                ids.add(int(m.group(1)))
    return ids


def build(src=SRC, out=OUT):
    with open(src, encoding="utf-8") as f:
        pages = json.load(f)
    _TOP_IDS.clear()
    _TOP_IDS.update(tops(pages))
    secs = doj(pages) + adaag(pages)
    seen = {}
    for x in secs:                      # the DOJ rules print some twice
        n = seen[x["id"]] = seen.get(x["id"], 0) + 1
        if n > 1:
            x["id"] += f" ({n})"
    data = {"title": "2010 ADA Standards for Accessible Design",
            "source": "U.S. Department of Justice, September 15, 2010 "
                      "(www.ada.gov) - public domain",
            "chapters": CHAPTERS, "sections": secs}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)
    return data


if __name__ == "__main__":
    d = build(*(sys.argv[1:2] or [SRC]))
    print(len(d["sections"]), "sections;",
          len(_TOP_IDS), "chapter-level names")
