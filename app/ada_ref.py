"""The 2010 ADA Standards for Accessible Design, searchable.

app/data/ada2010.json is built by tools/ada_index.py from the Justice
Department's PDF (public domain): the DOJ rules (28 CFR 35.151, 36.401-406)
and every section of chapters 1-10 with its advisory notes.

    find("404.2.3")            -> that section
    search("door maneuvering") -> best matches, section number first
    children("404.2")          -> 404.2.1, 404.2.2, ...
"""
import json
import os
import re
import threading

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                    "ada2010.json")
_data = None
_lock = threading.Lock()
_ID = re.compile(r"^\s*(?:§\s*|sec(?:tion)?\.?\s*)?(\d{3,4}(?:\.\d+)*)\s*$",
                 re.I)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")


def data():
    global _data
    with _lock:
        if _data is None:
            with open(FILE, encoding="utf-8") as f:
                d = json.load(f)
            d["by_id"] = {s["id"]: s for s in d["sections"]}
            for s in d["sections"]:
                hay = (s["title"] + " " + s["text"] + " " +
                       s.get("advisory", "")).lower()
                # "check-out" is found by "checkout" too
                s["_hay"] = hay + " " + hay.replace("-", "")
            _data = d
        return _data


def sections():
    return data()["sections"]


def find(sid):
    sid = (sid or "").strip()
    m = _ID.match(sid)
    return data()["by_id"].get(m.group(1) if m else sid)


def parent(sid):
    return find(sid.rsplit(".", 1)[0]) if "." in sid else None


def children(sid):
    pre = sid + "."
    return [s for s in sections() if s["id"].startswith(pre) and
            "." not in s["id"][len(pre):]]


def chapter_name(n):
    return data()["chapters"].get(str(n), "DOJ rules" if n == 0 else "")


def cite(sid):
    s = find(sid)
    return f"2010 ADA Standards {sid}" + (f" ({s['title']})" if s else "")


def search(query, limit=50):
    """Sections matching every word of the query, best first. A section
    number (or the start of one, "404.2") lists that section and the ones
    under it."""
    q = (query or "").strip()
    if not q:
        return []
    m = _ID.match(q)
    if m:
        sid = m.group(1)
        hits = [s for s in sections() if s["id"] == sid or
                s["id"].startswith(sid + ".")]
        if hits:
            return hits[:limit]
    words = _WORD.findall(q.lower())
    if not words:
        return []
    phrase = " ".join(words)
    scored = []
    for s in sections():
        hay = s["_hay"]
        if not all(w in hay for w in words):
            continue
        title = s["title"].lower()
        score = sum(3 for w in words if w in title)
        score += sum(min(hay.count(w), 5) for w in words)
        if phrase in hay:
            score += 6
        if phrase in title:
            score += 10
        if s["id"].startswith("DOJ"):
            score -= 2
        scored.append((-score, len(s["id"]), s["id"], s))
    scored.sort(key=lambda t: t[:3])
    return [t[3] for t in scored[:limit]]


def snippet(s, query, width=160):
    """A bit of the text around the first query word."""
    text = s["text"].replace("\n", " ")
    words = _WORD.findall((query or "").lower())
    low = text.lower()
    at = min([low.find(w) for w in words if low.find(w) >= 0] or [0])
    start = max(0, at - width // 3)
    out = text[start:start + width]
    return ("…" if start else "") + out + ("…" if start + width < len(text)
                                           else "")
