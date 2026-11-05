"""Code Library (0.12.27): code books you own, searchable on this PC.

Add a PDF of a code you have a copy of - the IECC, IBC, IRC, a state energy
code, a local amendment - and QuantiSheet splits it into sections ("R402.1.2
Insulation and fenestration criteria.", "C402.4 Fenestration.", "SECTION
R402", "TABLE R402.1.3") so you can look a requirement up by number or by
words, then jump to the page in the book.

Code books are copyrighted (ICC, ASHRAE...): the books and their indexes
stay in this person's own folder (%LOCALAPPDATA%\\QuantiSheet\\Code Library)
and are never put in an installer, a support bundle or a shared project.
"""
import json
import os
import re
import shutil
import threading

_SUB = re.compile(r"^((?:[A-Z]{1,3})?\d{2,4}(?:\.\d+){1,6})\s+"
                  r"([A-Z][^.\n]{1,140}?)\.(?:\s|$)")
_SECTION = re.compile(r"^SECTION\s+((?:[A-Z]{1,3})?\d{2,4})\s*(.*)$")
_TABLE = re.compile(r"^TABLE\s+((?:[A-Z]{1,3})?\d{2,4}(?:\.\d+)*(?:\([0-9A-Z]+\))?)"
                    r"\s*(.*)$")
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
_lock = threading.Lock()
_cache = {}


def folder():
    """%LOCALAPPDATA%\\QuantiSheet\\Code Library."""
    from . import brand_paths
    d = os.path.join(brand_paths.local_dir(), brand_paths.CODE_LIBRARY)
    os.makedirs(d, exist_ok=True)
    return d


def _index_path(book_pdf):
    return os.path.splitext(book_pdf)[0] + ".index.json"


def books():
    """[{"name", "pdf", "sections"}] in the library."""
    out = []
    for f in sorted(os.listdir(folder())):
        if f.lower().endswith(".pdf"):
            p = os.path.join(folder(), f)
            idx = _index_path(p)
            n = None
            try:
                with open(idx, encoding="utf-8") as fh:
                    n = len(json.load(fh)["sections"])
            except (OSError, ValueError, KeyError):
                pass
            out.append({"name": os.path.splitext(f)[0], "pdf": p,
                        "sections": n})
    return out


def index_pages(pages):
    """[page text] -> sections [{"id", "title", "page", "text"}]."""
    secs, cur = [], None

    def close():
        if cur:
            cur["text"] = re.sub(r"\s+", " ", " ".join(cur.pop("_t")))\
                .strip()[:6000]
            secs.append(cur)

    for pno, text in enumerate(pages):
        for raw in (text or "").splitlines():
            line = raw.replace("\xa0", " ").strip()
            if not line:
                continue
            m = _SECTION.match(line) or _TABLE.match(line)
            kind = None
            if m:
                kind = "SECTION" if line.startswith("SECTION") else "TABLE"
            else:
                m = _SUB.match(line)
            if m:
                close()
                sid = m.group(1)
                title = (m.group(2) or "").strip(" .")
                if kind == "TABLE":
                    sid = "TABLE " + sid
                cur = {"id": sid, "title": title.title() if
                       title.isupper() else title, "page": pno + 1,
                       "_t": [line[m.end():]] if kind is None else []}
                continue
            if cur is not None and not cur["title"] and not cur["_t"]:
                cur["title"] = line.title() if line.isupper() else line
                continue                 # "SECTION R402" / its name below
            if cur is not None and len(cur["_t"]) < 400:
                cur["_t"].append(line)
    close()
    return secs


def add_book(pdf_path, name=None, progress=None):
    """Copy a code PDF into the library and index it. Returns the book."""
    import fitz
    name = re.sub(r'[<>:"/\\|?*]', "_", name or os.path.splitext(
        os.path.basename(pdf_path))[0]).strip(" .") or "Code book"
    dest = os.path.join(folder(), name + ".pdf")
    if os.path.abspath(pdf_path) != os.path.abspath(dest):
        shutil.copyfile(pdf_path, dest)
    with fitz.open(dest) as d:
        if d.needs_pass:
            raise ValueError("The PDF is password-protected.")
        pages = []
        for i, pg in enumerate(d):
            pages.append(pg.get_text())
            if progress and i % 25 == 0:
                progress(i, d.page_count)
    secs = index_pages(pages)
    if not secs:
        raise ValueError("No numbered sections found - is it a scan? "
                         "(Run OCR on it first.)")
    with open(_index_path(dest), "w", encoding="utf-8") as f:
        json.dump({"name": name, "sections": secs}, f, ensure_ascii=False)
    with _lock:
        _cache.pop(dest, None)
    return {"name": name, "pdf": dest, "sections": len(secs)}


def remove_book(name):
    for b in books():
        if b["name"] == name:
            for p in (b["pdf"], _index_path(b["pdf"])):
                try:
                    os.remove(p)
                except OSError:
                    pass
            with _lock:
                _cache.pop(b["pdf"], None)
            return True
    return False


def _load(pdf):
    with _lock:
        if pdf not in _cache:
            with open(_index_path(pdf), encoding="utf-8") as f:
                secs = json.load(f)["sections"]
            for s in secs:
                hay = (s["id"] + " " + s["title"] + " " + s["text"]).lower()
                s["_hay"] = hay + " " + hay.replace("-", "")
            _cache[pdf] = secs
        return _cache[pdf]


def search(query, book=None, limit=100):
    """[(book name, pdf, section)] best first, across the library (or one
    book). A section number lists it and what's under it."""
    q = (query or "").strip()
    if not q:
        return []
    out = []
    for b in books():
        if book and b["name"] != book or not b["sections"]:
            continue
        secs = _load(b["pdf"])
        sid = q.upper().replace("SECTION ", "").strip()
        exact = [s for s in secs if s["id"].upper() == sid or
                 s["id"].upper().startswith(sid + ".") or
                 s["id"].upper() == "TABLE " + sid]
        if exact and re.match(r"^(TABLE\s+)?[A-Z]{0,3}\d", sid):
            out += [(-100, len(s["id"]), b["name"], b["pdf"], s)
                    for s in exact]
            continue
        words = _WORD.findall(q.lower())
        if not words:
            continue
        phrase = " ".join(words)
        for s in secs:
            hay = s["_hay"]
            if not all(w in hay for w in words):
                continue
            t = s["title"].lower()
            score = sum(3 for w in words if w in t) + \
                sum(min(hay.count(w), 5) for w in words)
            if phrase in hay:
                score += 6
            if s["id"].startswith("TABLE"):
                score += 2                    # requirements live in tables
            out.append((-score, len(s["id"]), b["name"], b["pdf"], s))
    out.sort(key=lambda t: t[:3])
    return [(n, p, s) for _a, _b, n, p, s in out[:limit]]
